from __future__ import annotations

from django.conf import settings


DEFAULT_SCOPES = (
    "read_products",
    "read_product_listings",
    "read_files",
    "read_themes",
)


def shopify_api_key() -> str:
    return (getattr(settings, "SHOPIFY_API_KEY", "") or "").strip()


def shopify_api_secret() -> str:
    return (getattr(settings, "SHOPIFY_API_SECRET", "") or "").strip()


def shopify_api_version() -> str:
    return (getattr(settings, "SHOPIFY_API_VERSION", "") or "2025-10").strip()


def shopify_scopes() -> str:
    raw = (getattr(settings, "SHOPIFY_SCOPES", "") or "").strip()
    if raw:
        parts = [part.strip() for part in raw.replace(" ", ",").split(",") if part.strip()]
        return ",".join(parts)
    return ",".join(DEFAULT_SCOPES)


def shopify_configured() -> bool:
    return bool(shopify_api_key() and shopify_api_secret())


def shopify_app_url() -> str:
    return (getattr(settings, "SHOPIFY_APP_URL", "") or "").strip().rstrip("/")
