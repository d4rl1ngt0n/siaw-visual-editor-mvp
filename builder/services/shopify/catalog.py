from __future__ import annotations

import logging
import re
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.contrib.auth.models import AbstractBaseUser
from django.core.files.base import ContentFile

from builder.models import AIWebsiteAsset, AIWebsiteBrief, ShopifyShop

from .api import ShopifyAPIError, fetch_products, fetch_shop_logo, fetch_shop_profile
from .tokens import decrypt_token

logger = logging.getLogger(__name__)


def _access_token(shop: ShopifyShop) -> str:
    return decrypt_token(shop.access_token_encrypted)


def refresh_shop_profile(shop: ShopifyShop) -> ShopifyShop:
    profile = fetch_shop_profile(shop.shop_domain, _access_token(shop))
    shop.shop_name = profile.get("name") or shop.shop_name
    shop.shop_email = profile.get("email") or shop.shop_email
    shop.primary_domain = profile.get("primary_domain") or shop.primary_domain
    shop.currency = profile.get("currency") or shop.currency
    shop.plan_name = profile.get("plan_name") or shop.plan_name
    meta = dict(shop.metadata_json or {})
    if profile.get("description"):
        meta["description"] = profile["description"]
    shop.metadata_json = meta
    shop.save(
        update_fields=[
            "shop_name",
            "shop_email",
            "primary_domain",
            "currency",
            "plan_name",
            "metadata_json",
            "updated_at",
        ]
    )
    return shop


def catalog_snapshot(shop: ShopifyShop, *, limit: int = 24) -> dict[str, Any]:
    token = _access_token(shop)
    try:
        profile = fetch_shop_profile(shop.shop_domain, token)
        products = fetch_products(shop.shop_domain, token, limit=limit)
        logo = fetch_shop_logo(shop.shop_domain, token)
    except ShopifyAPIError:
        raise
    return {
        "shop": {
            "domain": shop.shop_domain,
            "name": profile.get("name") or shop.shop_name,
            "email": profile.get("email") or shop.shop_email,
            "primary_domain": profile.get("primary_domain") or shop.primary_domain,
            "currency": profile.get("currency") or shop.currency,
            "plan_name": profile.get("plan_name") or shop.plan_name,
            "description": profile.get("description") or (shop.metadata_json or {}).get("description", ""),
            "logo_url": (logo or {}).get("url") or "",
            "logo_alt": (logo or {}).get("alt") or "",
        },
        "products": products,
        "product_count": len(products),
    }


def _guess_logo_name(url: str) -> str:
    path = PurePosixPath(urlparse(url).path)
    name = path.name or "shop-logo.png"
    if "." not in name:
        name = f"{name}.png"
    return name[:180]


def _download_image_bytes(url: str) -> tuple[bytes, str] | None:
    try:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://cdn.shopify.com/",
            },
        )
        with urlopen(request, timeout=25) as response:
            raw = response.read()
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        logger.info("Could not download Shopify image %s: %s", url[:160], exc)
        return None
    if not raw or len(raw) > 10 * 1024 * 1024:
        return None
    return raw, content_type


def _normalize_image_name(url: str, content_type: str, fallback: str = "image") -> str:
    name = _guess_logo_name(url)
    if fallback and name.startswith("shop-logo"):
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", fallback).strip(".-") or "image"
        name = f"{stem}{Path(name).suffix or '.png'}"
    if content_type == "image/jpeg" and not name.lower().endswith((".jpg", ".jpeg")):
        name = f"{PurePosixPath(name).stem}.jpg"
    elif content_type == "image/png" and not name.lower().endswith(".png"):
        name = f"{PurePosixPath(name).stem}.png"
    elif content_type == "image/webp" and not name.lower().endswith(".webp"):
        name = f"{PurePosixPath(name).stem}.webp"
    elif content_type == "image/svg+xml" and not name.lower().endswith(".svg"):
        name = f"{PurePosixPath(name).stem}.svg"
    return name[:180]


def attach_shop_logo(brief: AIWebsiteBrief, logo: dict[str, str]) -> AIWebsiteAsset | None:
    url = (logo.get("url") or "").strip()
    if not url:
        return None
    downloaded = _download_image_bytes(url)
    if not downloaded:
        return None
    raw, content_type = downloaded
    name = _normalize_image_name(url, content_type, fallback="shop-logo")

    brief.assets.filter(asset_type="logo").update(asset_type="reference")
    asset = AIWebsiteAsset(
        brief=brief,
        asset_type="logo",
        original_name=name,
        metadata_json={
            "source": "shopify",
            "source_url": url,
            "alt": (logo.get("alt") or "").strip(),
        },
    )
    asset.file.save(name, ContentFile(raw), save=True)
    return asset


def attach_product_image(brief: AIWebsiteBrief, image: dict[str, str]) -> AIWebsiteAsset | None:
    url = (image.get("url") or "").strip()
    if not url:
        return None
    downloaded = _download_image_bytes(url)
    if not downloaded:
        return None
    raw, content_type = downloaded
    name = _normalize_image_name(url, content_type, fallback=image.get("name") or "product")
    asset = AIWebsiteAsset(
        brief=brief,
        asset_type="image",
        original_name=name,
        metadata_json={
            "source": "shopify",
            "source_url": url,
            "alt": (image.get("alt") or "").strip(),
        },
    )
    asset.file.save(name, ContentFile(raw), save=True)
    return asset


def seed_brief_from_shop(owner: AbstractBaseUser, shop: ShopifyShop) -> AIWebsiteBrief:
    snapshot = catalog_snapshot(shop, limit=16)
    shop_info = snapshot["shop"]
    products = snapshot["products"]
    active = [p for p in products if (p.get("status") or "").upper() == "ACTIVE"] or products

    services = []
    for product in active[:8]:
        price = ""
        if product.get("price_amount"):
            currency = product.get("price_currency") or shop_info.get("currency") or ""
            price = f"{product['price_amount']} {currency}".strip()
        services.append(
            {
                "name": product.get("title") or "Product",
                "summary": (product.get("description") or "")[:280],
                "price": price,
                "image": product.get("image_url") or "",
                "url": product.get("online_store_url") or "",
            }
        )

    store_url = ""
    if shop_info.get("primary_domain"):
        host = shop_info["primary_domain"]
        store_url = host if host.startswith("http") else f"https://{host}"
    else:
        store_url = f"https://{shop.shop_domain}"

    description_bits = [
        f"{shop_info.get('name') or shop.shop_domain} is a Shopify store.",
        (shop_info.get("description") or "").strip(),
    ]
    if active:
        titles = ", ".join(p.get("title") for p in active[:5] if p.get("title"))
        if titles:
            description_bits.append(f"Featured products include {titles}.")
    description = " ".join(bit for bit in description_bits if bit).strip()

    logo_url = (shop_info.get("logo_url") or "").strip()
    brief = AIWebsiteBrief.objects.create(
        owner=owner,
        status="draft",
        current_step=1,
        starting_point="shopify",
        business_name=(shop_info.get("name") or shop.shop_name or shop.shop_domain)[:160],
        industry="Ecommerce and retail",
        description=description[:4000],
        language="English",
        primary_goal="sell",
        primary_cta={
            "label": "Shop now",
            "destination": store_url,
        },
        audience={"who": "Online shoppers discovering and buying products"},
        value_proposition=f"Shop {shop_info.get('name') or 'the collection'} with a brand site built for conversion.",
        tone="confident",
        visual_style="editorial retail",
        existing_website_url=store_url[:500],
        services_json=services,
        trust_json={"proof_points": [f"Live on Shopify ({shop.shop_domain})"]},
        contact_json={"email": shop_info.get("email") or shop.shop_email or ""},
        brand_json={
            "source": "shopify",
            "shop_domain": shop.shop_domain,
            "currency": shop_info.get("currency") or shop.currency,
            "logo_url": logo_url,
        },
        generation_brief_json={
            "source": "shopify",
            "shop_id": str(shop.id),
            "catalog": {
                "product_count": snapshot["product_count"],
                "logo_url": logo_url,
                "products": [
                    {
                        "title": p.get("title"),
                        "handle": p.get("handle"),
                        "price": p.get("price_amount"),
                        "currency": p.get("price_currency"),
                        "image": p.get("image_url"),
                        "url": p.get("online_store_url"),
                    }
                    for p in active[:12]
                ],
            },
        },
    )
    if logo_url:
        attach_shop_logo(
            brief,
            {"url": logo_url, "alt": shop_info.get("logo_alt") or shop_info.get("name") or ""},
        )
    for index, product in enumerate(active[:8]):
        image_url = (product.get("image_url") or "").strip()
        if not image_url:
            continue
        attach_product_image(
            brief,
            {
                "url": image_url,
                "alt": product.get("title") or f"Product {index + 1}",
                "name": f"product-{index + 1}",
            },
        )
    shop.last_synced_at = brief.created_at
    shop.save(update_fields=["last_synced_at", "updated_at"])
    return brief
