from __future__ import annotations

import logging
import secrets
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.core import signing
from django.db import transaction
from django.utils import timezone

from builder.models import ShopifyShop

from .api import ShopifyAPIError
from .catalog import refresh_shop_profile
from .tokens import encrypt_token

logger = logging.getLogger(__name__)
User = get_user_model()
HANDOFF_SALT = "siaw-shopify-wizard-handoff-v1"
HANDOFF_MAX_AGE = 60 * 30


def upsert_installed_shop(
    *,
    shop_domain: str,
    access_token: str,
    scopes: str = "",
    owner: AbstractBaseUser | None = None,
) -> ShopifyShop:
    """Create or reactivate a merchant install. One active row per shop domain."""
    with transaction.atomic():
        shop = (
            ShopifyShop.objects.select_for_update()
            .filter(shop_domain=shop_domain)
            .order_by("-updated_at")
            .first()
        )
        if shop is None:
            shop = ShopifyShop(
                shop_domain=shop_domain,
                owner=owner,
            )
        shop.access_token_encrypted = encrypt_token(access_token)
        shop.scopes = scopes or shop.scopes
        shop.is_active = True
        shop.uninstalled_at = None
        if owner is not None:
            shop.owner = owner
        elif shop.owner_id is None:
            shop.owner = None
        shop.save()
    try:
        refresh_shop_profile(shop)
    except ShopifyAPIError as exc:
        logger.warning("Shopify profile refresh failed for %s: %s", shop_domain, exc)
    return shop


def link_shop_to_user(shop: ShopifyShop, user: AbstractBaseUser) -> ShopifyShop:
    shop.owner = user
    shop.save(update_fields=["owner", "updated_at"])
    return shop


def mark_shop_uninstalled(shop_domain: str) -> int:
    now = timezone.now()
    return ShopifyShop.objects.filter(shop_domain=shop_domain, is_active=True).update(
        is_active=False,
        uninstalled_at=now,
        access_token_encrypted="",
        updated_at=now,
    )


def make_wizard_handoff(*, user_id: int, brief_id: str, shop_domain: str) -> str:
    return signing.dumps(
        {
            "uid": user_id,
            "brief_id": str(brief_id),
            "shop": shop_domain,
            "nonce": secrets.token_urlsafe(12),
        },
        salt=HANDOFF_SALT,
    )


def load_wizard_handoff(token: str) -> dict[str, Any]:
    return signing.loads(token, salt=HANDOFF_SALT, max_age=HANDOFF_MAX_AGE)


def ensure_merchant_user(shop: ShopifyShop) -> AbstractBaseUser:
    """Ensure an install has a Siaw user so AI briefs can be owned."""
    if shop.owner_id:
        return shop.owner
    email = (shop.shop_email or "").strip().lower()
    username_base = shop.shop_domain.replace(".myshopify.com", "")[:40] or "shop"
    username = f"shop_{username_base}"
    user = None
    if email:
        user = User.objects.filter(email__iexact=email).first()
    if user is None:
        user = User.objects.filter(username=username).first()
    if user is None:
        # Unique username if taken.
        candidate = username
        n = 1
        while User.objects.filter(username=candidate).exists():
            n += 1
            candidate = f"{username}_{n}"
        user = User.objects.create_user(
            username=candidate,
            email=email or f"{candidate}@shopify.siaw.local",
            password=secrets.token_urlsafe(32),
        )
    shop.owner = user
    shop.save(update_fields=["owner", "updated_at"])
    return user
