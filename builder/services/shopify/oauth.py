from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core import signing

from .config import shopify_api_key, shopify_api_secret, shopify_scopes

SHOP_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*\.myshopify\.com$")
STATE_SALT = "siaw-shopify-oauth-v1"
STATE_MAX_AGE = 60 * 15


def normalize_shop_domain(value: str) -> str:
    raw = (value or "").strip().lower()
    raw = raw.replace("https://", "").replace("http://", "")
    raw = raw.split("/")[0].split("?")[0].strip(".")
    if not raw:
        raise ValueError("Enter your store domain, for example your-store.myshopify.com.")
    if "." not in raw:
        raw = f"{raw}.myshopify.com"
    if not SHOP_DOMAIN_RE.match(raw):
        raise ValueError("Use a valid myshopify.com domain, for example your-store.myshopify.com.")
    return raw


def make_oauth_state(
    *,
    user_id: int | None = None,
    next_url: str = "",
    mode: str = "connect",
    shop: str = "",
) -> str:
    """mode: connect (Siaw account link) | install (merchant Add app from Shopify)."""
    return signing.dumps(
        {
            "uid": user_id,
            "nonce": secrets.token_urlsafe(16),
            "next": (next_url or "")[:500],
            "mode": mode,
            "shop": shop,
        },
        salt=STATE_SALT,
    )


def load_oauth_state(state: str) -> dict[str, Any]:
    return signing.loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE)


def verify_oauth_hmac(query_dict) -> bool:
    """Verify Shopify OAuth/query HMAC (hex digest of sorted query without hmac)."""
    secret = shopify_api_secret()
    if not secret:
        return False
    provided = (query_dict.get("hmac") or "").strip()
    if not provided:
        return False
    items = []
    for key in sorted(query_dict.keys()):
        if key == "hmac":
            continue
        value = query_dict.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        items.append(f"{key}={value}")
    message = "&".join(items).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, provided)


def verify_webhook_hmac(raw_body: bytes, hmac_header: str) -> bool:
    secret = shopify_api_secret()
    if not secret or not hmac_header:
        return False
    digest = base64_hmac_sha256(secret.encode("utf-8"), raw_body)
    return hmac.compare_digest(digest, hmac_header.strip())


def base64_hmac_sha256(key: bytes, message: bytes) -> str:
    digest = hmac.new(key, message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def build_authorize_url(*, shop: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": shopify_api_key(),
        "scope": shopify_scopes(),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"https://{shop}/admin/oauth/authorize?{urlencode(params)}"


def exchange_code_for_token(*, shop: str, code: str) -> dict[str, Any]:
    payload = urlencode(
        {
            "client_id": shopify_api_key(),
            "client_secret": shopify_api_secret(),
            "code": code,
        }
    ).encode("utf-8")
    request = Request(
        f"https://{shop}/admin/oauth/access_token",
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise ValueError(f"Shopify token exchange failed ({exc.code}): {detail[:300]}") from exc
    except URLError as exc:
        raise ValueError(f"Could not reach Shopify: {exc.reason}") from exc

    data = json.loads(body)
    token = (data.get("access_token") or "").strip()
    if not token:
        raise ValueError("Shopify did not return an access token.")
    return {
        "access_token": token,
        "scope": (data.get("scope") or "").strip(),
    }
