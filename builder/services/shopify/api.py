from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import shopify_api_version

logger = logging.getLogger(__name__)


class ShopifyAPIError(RuntimeError):
    pass


def _graphql_request(url: str, query: str, *, headers: dict[str, str], variables: dict | None = None) -> dict[str, Any]:
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **headers,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise ShopifyAPIError(f"Shopify GraphQL error ({exc.code}): {detail[:400]}") from exc
    except URLError as exc:
        raise ShopifyAPIError(f"Could not reach Shopify GraphQL: {exc.reason}") from exc

    data = json.loads(body)
    if data.get("errors"):
        raise ShopifyAPIError(f"Shopify GraphQL errors: {data['errors']!r}"[:500])
    return data.get("data") or {}


def admin_graphql(shop_domain: str, access_token: str, query: str, variables: dict | None = None) -> dict[str, Any]:
    version = shopify_api_version()
    return _graphql_request(
        f"https://{shop_domain}/admin/api/{version}/graphql.json",
        query,
        headers={"X-Shopify-Access-Token": access_token},
        variables=variables,
    )


SHOP_QUERY = """
query SiawShopProfile {
  shop {
    name
    email
    myshopifyDomain
    primaryDomain { url host }
    currencyCode
    plan { displayName }
    description
  }
}
"""

PRODUCTS_QUERY = """
query SiawProducts($first: Int!) {
  products(first: $first, sortKey: UPDATED_AT, reverse: true) {
    edges {
      node {
        id
        title
        handle
        status
        description
        productType
        vendor
        tags
        featuredImage { url altText }
        priceRangeV2 {
          minVariantPrice { amount currencyCode }
          maxVariantPrice { amount currencyCode }
        }
        onlineStoreUrl
      }
    }
  }
}
"""


def fetch_shop_profile(shop_domain: str, access_token: str) -> dict[str, Any]:
    data = admin_graphql(shop_domain, access_token, SHOP_QUERY)
    shop = data.get("shop") or {}
    primary = shop.get("primaryDomain") or {}
    plan = shop.get("plan") or {}
    return {
        "name": (shop.get("name") or "").strip(),
        "email": (shop.get("email") or "").strip(),
        "myshopify_domain": (shop.get("myshopifyDomain") or shop_domain).strip(),
        "primary_domain": (primary.get("host") or primary.get("url") or "").strip(),
        "currency": (shop.get("currencyCode") or "").strip(),
        "plan_name": (plan.get("displayName") or "").strip(),
        "description": (shop.get("description") or "").strip(),
    }


STOREFRONT_BRAND_QUERY = """
query SiawStorefrontBrand {
  shop {
    brand {
      logo { image { url altText } }
      squareLogo { image { url altText } }
    }
  }
}
"""

FILES_LOGO_QUERY = """
query SiawLogoFiles {
  files(first: 10, query: "filename:logo*", sortKey: CREATED_AT, reverse: true) {
    edges {
      node {
        ... on MediaImage {
          image { url altText }
        }
      }
    }
  }
}
"""


def fetch_shop_logo(shop_domain: str, access_token: str) -> dict[str, str]:
    """Return {url, alt} for the merchant logo when available."""
    version = shopify_api_version()
    # Storefront brand API often exposes the Settings → Brand logo without extra scopes.
    try:
        data = _graphql_request(
            f"https://{shop_domain}/api/{version}/graphql.json",
            STOREFRONT_BRAND_QUERY,
            headers={},
        )
        brand = ((data.get("shop") or {}).get("brand")) or {}
        for key in ("logo", "squareLogo"):
            image = ((brand.get(key) or {}).get("image")) or {}
            url = (image.get("url") or "").strip()
            if url:
                return {"url": url, "alt": (image.get("altText") or "").strip()}
    except ShopifyAPIError as exc:
        logger.info("Storefront brand logo unavailable for %s: %s", shop_domain, exc)

    try:
        data = admin_graphql(shop_domain, access_token, FILES_LOGO_QUERY)
        edges = ((data.get("files") or {}).get("edges")) or []
        for edge in edges:
            image = ((edge or {}).get("node") or {}).get("image") or {}
            url = (image.get("url") or "").strip()
            if url:
                return {"url": url, "alt": (image.get("altText") or "").strip()}
    except ShopifyAPIError as exc:
        logger.info("Admin files logo search failed for %s: %s", shop_domain, exc)

    return {}


def fetch_products(shop_domain: str, access_token: str, *, limit: int = 24) -> list[dict[str, Any]]:
    first = max(1, min(int(limit), 50))
    data = admin_graphql(shop_domain, access_token, PRODUCTS_QUERY, {"first": first})
    edges = ((data.get("products") or {}).get("edges")) or []
    products = []
    for edge in edges:
        node = (edge or {}).get("node") or {}
        image = node.get("featuredImage") or {}
        price = ((node.get("priceRangeV2") or {}).get("minVariantPrice")) or {}
        products.append(
            {
                "id": node.get("id") or "",
                "title": (node.get("title") or "").strip(),
                "handle": (node.get("handle") or "").strip(),
                "status": (node.get("status") or "").strip(),
                "description": (node.get("description") or "").strip(),
                "product_type": (node.get("productType") or "").strip(),
                "vendor": (node.get("vendor") or "").strip(),
                "tags": node.get("tags") or [],
                "image_url": (image.get("url") or "").strip(),
                "image_alt": (image.get("altText") or "").strip(),
                "price_amount": (price.get("amount") or "").strip(),
                "price_currency": (price.get("currencyCode") or "").strip(),
                "online_store_url": (node.get("onlineStoreUrl") or "").strip(),
            }
        )
    return products
