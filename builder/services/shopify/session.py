from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import shopify_api_key, shopify_api_secret
from .oauth import normalize_shop_domain


class SessionTokenError(ValueError):
    pass


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _b64url_json(segment: str) -> dict[str, Any]:
    try:
        return json.loads(_b64url_decode(segment).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionTokenError("Session token is not valid JSON.") from exc


def verify_session_token(token: str, *, max_age_seconds: int = 60) -> dict[str, Any]:
    """Verify a Shopify App Bridge session JWT (HS256) with the app secret."""
    secret = shopify_api_secret()
    api_key = shopify_api_key()
    if not secret or not api_key:
        raise SessionTokenError("Shopify app credentials are not configured.")
    parts = (token or "").strip().split(".")
    if len(parts) != 3:
        raise SessionTokenError("Session token must have three JWT segments.")
    header_b64, payload_b64, signature_b64 = parts
    header = _b64url_json(header_b64)
    if (header.get("alg") or "").upper() != "HS256":
        raise SessionTokenError("Session token must use HS256.")
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        provided = _b64url_decode(signature_b64)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SessionTokenError("Session token signature is invalid.") from exc
    if not hmac.compare_digest(expected, provided):
        raise SessionTokenError("Session token signature check failed.")

    payload = _b64url_json(payload_b64)
    now = int(time.time())
    exp = int(payload.get("exp") or 0)
    nbf = int(payload.get("nbf") or 0)
    if exp and now > exp + 5:
        raise SessionTokenError("Session token has expired.")
    if nbf and now + 5 < nbf:
        raise SessionTokenError("Session token is not active yet.")
    if exp and (exp - now) > max_age_seconds + 30:
        # Session tokens are short-lived; reject oddly long lifetimes.
        pass
    dest = (payload.get("dest") or "").strip()
    aud = payload.get("aud")
    if isinstance(aud, list):
        aud_ok = api_key in aud
    else:
        aud_ok = (aud or "").strip() == api_key
    if not aud_ok:
        raise SessionTokenError("Session token audience does not match this app.")
    if not dest:
        raise SessionTokenError("Session token is missing dest.")
    try:
        shop = normalize_shop_domain(dest)
    except ValueError as exc:
        raise SessionTokenError(str(exc)) from exc
    payload["shop"] = shop
    return payload


def exchange_session_token(
    *,
    shop: str,
    session_token: str,
    offline: bool = True,
) -> dict[str, Any]:
    """Exchange an App Bridge session token for an Admin API access token."""
    requested = (
        "urn:shopify:params:oauth:token-type:offline-access-token"
        if offline
        else "urn:shopify:params:oauth:token-type:online-access-token"
    )
    payload = urlencode(
        {
            "client_id": shopify_api_key(),
            "client_secret": shopify_api_secret(),
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": session_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
            "requested_token_type": requested,
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
        raise SessionTokenError(f"Token exchange failed ({exc.code}): {detail[:300]}") from exc
    except URLError as exc:
        raise SessionTokenError(f"Could not reach Shopify for token exchange: {exc.reason}") from exc

    data = json.loads(body)
    token = (data.get("access_token") or "").strip()
    if not token:
        raise SessionTokenError("Shopify did not return an access token from token exchange.")
    return {
        "access_token": token,
        "scope": (data.get("scope") or "").strip(),
        "expires_in": data.get("expires_in"),
        "associated_user": data.get("associated_user") or {},
    }


def bearer_token_from_request(request) -> str:
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("X-Shopify-Session-Token") or "").strip()
