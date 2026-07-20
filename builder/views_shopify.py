from __future__ import annotations

import json
import logging

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import ShopifyConnectForm
from .models import AIWebsiteBrief, ShopifyShop
from .services.shopify.api import ShopifyAPIError
from .services.shopify.catalog import catalog_snapshot, seed_brief_from_shop
from .services.shopify.config import shopify_api_key, shopify_app_url, shopify_configured
from .services.shopify.install import (
    ensure_merchant_user,
    link_shop_to_user,
    load_wizard_handoff,
    make_wizard_handoff,
    mark_shop_uninstalled,
    upsert_installed_shop,
)
from .services.shopify.oauth import (
    build_authorize_url,
    exchange_code_for_token,
    load_oauth_state,
    make_oauth_state,
    normalize_shop_domain,
    verify_oauth_hmac,
    verify_webhook_hmac,
)
from .services.shopify.session import (
    SessionTokenError,
    bearer_token_from_request,
    exchange_session_token,
    verify_session_token,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def _redirect_uri(request) -> str:
    configured = shopify_app_url()
    if configured:
        return f"{configured}{reverse('builder:shopify_callback')}"
    return request.build_absolute_uri(reverse("builder:shopify_callback"))


def _app_home_url(*, shop: str = "", host: str = "") -> str:
    base = reverse("builder:shopify_app")
    params = []
    if shop:
        params.append(f"shop={shop}")
    if host:
        params.append(f"host={host}")
    return f"{base}?{'&'.join(params)}" if params else base


def _public_absolute(request, path: str) -> str:
    """Prefer SHOPIFY_APP_URL so wizard links stay on https://ngrok instead of http://."""
    origin = shopify_app_url()
    if origin:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{origin}{path}"
    return request.build_absolute_uri(path)


def _owned_shop(request, shop_id) -> ShopifyShop:
    return get_object_or_404(ShopifyShop, id=shop_id, owner=request.user, is_active=True)


def _active_shop(shop_domain: str) -> ShopifyShop | None:
    return ShopifyShop.objects.filter(shop_domain=shop_domain, is_active=True).first()


def _begin_install(request, shop: str, *, host: str = ""):
    state = make_oauth_state(
        user_id=request.user.id if request.user.is_authenticated else None,
        next_url=_app_home_url(shop=shop, host=host),
        mode="install",
        shop=shop,
    )
    return redirect(build_authorize_url(shop=shop, redirect_uri=_redirect_uri(request), state=state))


@xframe_options_exempt
@require_GET
def shopify_app(request):
    """
    Merchant App Home. Shopify Admin loads this after Add app / open app.
    Merchants install the app on their store; this is not a private admin tool.
    """
    if not shopify_configured():
        return render(
            request,
            "builder/shopify_app.html",
            {
                "shopify_ready": False,
                "error": "Siaw Shopify app credentials are not configured on this server.",
            },
            status=503,
        )

    shop_param = (request.GET.get("shop") or "").strip()
    host = (request.GET.get("host") or "").strip()
    hmac_ok = verify_oauth_hmac(request.GET) if request.GET.get("hmac") else False

    shop_domain = ""
    if shop_param:
        try:
            shop_domain = normalize_shop_domain(shop_param)
        except ValueError:
            return render(
                request,
                "builder/shopify_app.html",
                {"shopify_ready": False, "error": "Invalid shop domain."},
                status=400,
            )

    # Fresh Admin entry with HMAC and no install yet: run authorization code grant.
    if shop_domain and hmac_ok and not _active_shop(shop_domain):
        return _begin_install(request, shop_domain, host=host)

    # Direct open without install: ask for shop or start OAuth when shop is present.
    if shop_domain and not _active_shop(shop_domain) and not request.GET.get("id_token"):
        if hmac_ok or request.GET.get("embedded") == "1":
            return _begin_install(request, shop_domain, host=host)

    shop = _active_shop(shop_domain) if shop_domain else None
    return render(
        request,
        "builder/shopify_app.html",
        {
            "shopify_ready": True,
            "api_key": shopify_api_key(),
            "shop_domain": shop_domain,
            "host": host,
            "shop": shop,
            "session_url": reverse("builder:shopify_session"),
            "build_url": reverse("builder:shopify_app_build"),
            "products_url": reverse("builder:shopify_app_products"),
            "web_workspace_url": request.build_absolute_uri(reverse("builder:workspace")),
        },
    )


@require_GET
def shopify_auth(request):
    """Entry used by Partners / CLI: /shopify/auth?shop=store.myshopify.com"""
    if not shopify_configured():
        return HttpResponse("Shopify app is not configured.", status=503)
    try:
        shop = normalize_shop_domain(request.GET.get("shop") or "")
    except ValueError as exc:
        return HttpResponse(str(exc), status=400)
    host = (request.GET.get("host") or "").strip()
    return _begin_install(request, shop, host=host)


@login_required
@require_http_methods(["GET", "POST"])
def shopify_connect(request):
    if not shopify_configured():
        messages.error(
            request,
            "Shopify is not configured yet. Add SHOPIFY_API_KEY and SHOPIFY_API_SECRET to the environment.",
        )
        return redirect(f"{reverse('builder:account')}#shopify")

    form = ShopifyConnectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        shop = form.cleaned_data["shop"]
        state = make_oauth_state(
            user_id=request.user.id,
            next_url=reverse("builder:account") + "#shopify",
            mode="connect",
            shop=shop,
        )
        url = build_authorize_url(shop=shop, redirect_uri=_redirect_uri(request), state=state)
        return redirect(url)

    if request.method == "POST":
        for error in form.errors.get("shop", []):
            messages.error(request, error)
        return redirect(f"{reverse('builder:account')}#shopify")

    return redirect(f"{reverse('builder:account')}#shopify")


@require_GET
def shopify_callback(request):
    if not shopify_configured():
        messages.error(request, "Shopify is not configured on this server.")
        return redirect("builder:dashboard")

    params = request.GET
    if not verify_oauth_hmac(params):
        messages.error(request, "Shopify callback failed HMAC verification.")
        return redirect("builder:dashboard")

    state_raw = (params.get("state") or "").strip()
    state: dict = {}
    if state_raw:
        try:
            state = load_oauth_state(state_raw)
        except Exception:
            messages.error(request, "Shopify install session expired. Open the app from Shopify Admin again.")
            return redirect("builder:dashboard")

    mode = (state.get("mode") or "install").strip()
    try:
        shop_domain = normalize_shop_domain(params.get("shop") or state.get("shop") or "")
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("builder:dashboard")

    code = (params.get("code") or "").strip()
    if not code:
        messages.error(request, "Shopify did not return an authorization code.")
        return redirect("builder:dashboard")

    try:
        token_payload = exchange_code_for_token(shop=shop_domain, code=code)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("builder:dashboard")

    owner = None
    if mode == "connect":
        uid = state.get("uid")
        if not uid:
            messages.error(request, "Missing Siaw account for Shopify connect.")
            return redirect("builder:login")
        owner = get_object_or_404(User, pk=uid)
        if not request.user.is_authenticated or request.user.pk != owner.pk:
            messages.error(request, "Log in with the same Siaw account you used to start Shopify connect.")
            return redirect(f"{reverse('builder:login')}?next={reverse('builder:account')}")

    shop = upsert_installed_shop(
        shop_domain=shop_domain,
        access_token=token_payload["access_token"],
        scopes=token_payload.get("scope") or "",
        owner=owner,
    )

    if mode == "connect" and owner is not None:
        link_shop_to_user(shop, owner)
        messages.success(request, f"Connected {shop.shop_name or shop.shop_domain}.")
        next_url = (state.get("next") or "").strip() or f"{reverse('builder:account')}#shopify"
        if next_url.startswith("/"):
            return redirect(next_url)
        return redirect(f"{reverse('builder:account')}#shopify")

    # Merchant install from Shopify Admin: land back in App Home (embedded).
    next_url = (state.get("next") or "").strip()
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect(_app_home_url(shop=shop_domain))


@csrf_exempt
@require_POST
def shopify_session(request):
    """Exchange App Bridge session token for offline Admin API token and persist install."""
    if not shopify_configured():
        return JsonResponse({"ok": False, "error": "Shopify is not configured."}, status=503)
    token = bearer_token_from_request(request)
    if not token:
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {}
        token = (body.get("session_token") or "").strip()
    if not token:
        return JsonResponse({"ok": False, "error": "Missing session token."}, status=401)
    try:
        claims = verify_session_token(token)
        shop_domain = claims["shop"]
        exchanged = exchange_session_token(shop=shop_domain, session_token=token, offline=True)
        shop = upsert_installed_shop(
            shop_domain=shop_domain,
            access_token=exchanged["access_token"],
            scopes=exchanged.get("scope") or "",
            owner=request.user if request.user.is_authenticated else None,
        )
    except SessionTokenError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=401)
    except Exception as exc:
        logger.exception("Shopify session exchange failed")
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)

    return JsonResponse(
        {
            "ok": True,
            "shop": {
                "id": str(shop.id),
                "domain": shop.shop_domain,
                "name": shop.shop_name or shop.shop_domain,
                "currency": shop.currency,
                "linked": bool(shop.owner_id),
            },
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def shopify_app_products(request):
    token = bearer_token_from_request(request)
    if not token:
        return JsonResponse({"ok": False, "error": "Missing session token."}, status=401)
    try:
        claims = verify_session_token(token)
        shop = _active_shop(claims["shop"])
        if shop is None or not shop.access_token_encrypted:
            exchanged = exchange_session_token(shop=claims["shop"], session_token=token, offline=True)
            shop = upsert_installed_shop(
                shop_domain=claims["shop"],
                access_token=exchanged["access_token"],
                scopes=exchanged.get("scope") or "",
            )
        snapshot = catalog_snapshot(shop, limit=int(request.GET.get("limit") or 12))
    except (SessionTokenError, ShopifyAPIError, ValueError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
    return JsonResponse({"ok": True, **snapshot})


@csrf_exempt
@require_POST
def shopify_app_build(request):
    """Create an AI brief from the merchant's catalog (called from App Home)."""
    token = bearer_token_from_request(request)
    if not token:
        return JsonResponse({"ok": False, "error": "Missing session token."}, status=401)
    try:
        claims = verify_session_token(token)
        shop = _active_shop(claims["shop"])
        if shop is None or not shop.access_token_encrypted:
            exchanged = exchange_session_token(shop=claims["shop"], session_token=token, offline=True)
            shop = upsert_installed_shop(
                shop_domain=claims["shop"],
                access_token=exchanged["access_token"],
                scopes=exchanged.get("scope") or "",
            )
        user = ensure_merchant_user(shop)
        brief = seed_brief_from_shop(user, shop)
    except (SessionTokenError, ShopifyAPIError, ValueError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)

    handoff = make_wizard_handoff(
        user_id=user.pk,
        brief_id=str(brief.id),
        shop_domain=shop.shop_domain,
    )
    continue_path = f"{reverse('builder:shopify_continue')}?token={handoff}"
    absolute = _public_absolute(request, continue_path)
    return JsonResponse(
        {
            "ok": True,
            "brief_id": str(brief.id),
            "wizard_url": absolute,
            "shop": shop.shop_name or shop.shop_domain,
        }
    )


@require_GET
def shopify_continue(request):
    """
    One-time handoff from embedded App Home into the Siaw wizard.
    Logs in the shop's Siaw user so ownership checks succeed.
    """
    raw = (request.GET.get("token") or "").strip()
    if not raw:
        messages.error(request, "Missing Shopify continue token. Build again from the app.")
        return redirect("builder:dashboard")
    try:
        payload = load_wizard_handoff(raw)
    except signing.BadSignature:
        messages.error(request, "That Shopify continue link expired. Open the app and build again.")
        return redirect("builder:dashboard")

    user = get_object_or_404(User, pk=payload.get("uid"))
    brief = get_object_or_404(AIWebsiteBrief, id=payload.get("brief_id"), owner=user)
    auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.set_expiry(60 * 60 * 24 * 14)
    request.session.save()
    messages.success(
        request,
        f"Continuing from {(payload.get('shop') or 'your Shopify store')}.",
    )
    # Force https wizard URL when behind ngrok so the session cookie stays on one host.
    wizard_path = reverse("builder:ai_wizard", kwargs={"brief_id": brief.id})
    return redirect(_public_absolute(request, wizard_path))


@login_required
@require_POST
def shopify_disconnect(request, shop_id):
    shop = _owned_shop(request, shop_id)
    shop.is_active = False
    shop.uninstalled_at = timezone.now()
    shop.access_token_encrypted = ""
    shop.save(update_fields=["is_active", "uninstalled_at", "access_token_encrypted", "updated_at"])
    messages.success(request, f"Disconnected {shop.shop_name or shop.shop_domain}.")
    return redirect(f"{reverse('builder:account')}#shopify")


@login_required
@require_GET
def shopify_products(request, shop_id):
    shop = _owned_shop(request, shop_id)
    try:
        snapshot = catalog_snapshot(shop, limit=int(request.GET.get("limit") or 24))
    except (ShopifyAPIError, ValueError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
    return JsonResponse({"ok": True, **snapshot})


@login_required
@require_POST
def shopify_build_site(request, shop_id):
    shop = _owned_shop(request, shop_id)
    try:
        brief = seed_brief_from_shop(request.user, shop)
    except (ShopifyAPIError, ValueError) as exc:
        messages.error(request, f"Could not load catalog from Shopify: {exc}")
        return redirect(f"{reverse('builder:account')}#shopify")
    messages.success(request, "AI brief started from your Shopify catalog.")
    return redirect("builder:ai_wizard", brief_id=brief.id)


@login_required
@require_POST
def shopify_link_account(request, shop_id):
    shop = get_object_or_404(ShopifyShop, id=shop_id, is_active=True)
    if shop.owner_id and shop.owner_id != request.user.id:
        messages.error(request, "That store is already linked to another Siaw account.")
        return redirect(f"{reverse('builder:account')}#shopify")
    link_shop_to_user(shop, request.user)
    messages.success(request, f"Linked {shop.shop_name or shop.shop_domain} to your Siaw account.")
    return redirect(f"{reverse('builder:account')}#shopify")


@csrf_exempt
@require_POST
def shopify_webhook(request):
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")
    if not verify_webhook_hmac(request.body, hmac_header):
        return HttpResponse(status=401)

    topic = (request.headers.get("X-Shopify-Topic") or "").strip()
    shop_domain = (request.headers.get("X-Shopify-Shop-Domain") or "").strip().lower()
    if topic == "app/uninstalled" and shop_domain:
        mark_shop_uninstalled(shop_domain)
    # Mandatory compliance topics: acknowledge. Expand with data export/redaction later.
    elif topic in {
        "customers/data_request",
        "customers/redact",
        "shop/redact",
    }:
        logger.info("Shopify compliance webhook %s for %s", topic, shop_domain)
    try:
        json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        pass
    return HttpResponse(status=200)
