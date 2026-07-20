"""Ownership checks and short-lived runtime access tokens."""

from __future__ import annotations

from pathlib import Path

from django.core import signing
from django.http import HttpRequest

from builder.models import WebsiteProject

RUNTIME_TOKEN_SALT = "siaw-runtime-access"
RUNTIME_TOKEN_MAX_AGE = 60 * 60 * 12  # 12 hours
RUNTIME_COOKIE_PREFIX = "siaw_rt_"

# Subresources loaded by the preview iframe after the HTML document.
# Cross-site iframes (127.0.0.1 editor -> *.runtime.localhost) often block the
# access cookie, so CSS/JS/images 404 unless these stay readable without it.
ANONYMOUS_RUNTIME_ASSET_SUFFIXES = {
    ".js",
    ".mjs",
    ".cjs",
    ".css",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".avif",
    ".bmp",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".mp4",
    ".webm",
    ".ogg",
    ".mp3",
    ".wav",
    ".json",
    ".wasm",
    ".txt",
}


def allows_anonymous_runtime_asset(asset_path: str) -> bool:
    """True for non-document assets that preview iframes load without cookies."""
    cleaned = (asset_path or "").replace("\\", "/").lstrip("/")
    if not cleaned or cleaned.endswith("/"):
        return False
    suffix = Path(cleaned).suffix.lower()
    return suffix in ANONYMOUS_RUNTIME_ASSET_SUFFIXES


def user_can_access_project(user, project: WebsiteProject) -> bool:
    if project.deleted_at is not None:
        return False
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False):
        return True
    return project.owner_id == getattr(user, "id", None)


def issue_runtime_access_token(project: WebsiteProject, user) -> str:
    signer = signing.TimestampSigner(salt=RUNTIME_TOKEN_SALT)
    return signer.sign(f"{project.id}:{user.id}")


def verify_runtime_access_token(token: str, project: WebsiteProject) -> bool:
    if not token:
        return False
    signer = signing.TimestampSigner(salt=RUNTIME_TOKEN_SALT)
    try:
        value = signer.unsign(token, max_age=RUNTIME_TOKEN_MAX_AGE)
    except signing.BadSignature:
        return False
    try:
        project_id, _user_id = value.split(":", 1)
    except ValueError:
        return False
    return str(project.id) == project_id


def runtime_cookie_name(project: WebsiteProject) -> str:
    return f"{RUNTIME_COOKIE_PREFIX}{project.id}"


def request_has_runtime_access(request: HttpRequest, project: WebsiteProject) -> bool:
    user = getattr(request, "user", None)
    if user_can_access_project(user, project):
        return True
    token = request.GET.get("access") or request.COOKIES.get(runtime_cookie_name(project)) or ""
    return verify_runtime_access_token(token, project)


def request_can_serve_runtime_path(
    request: HttpRequest,
    project: WebsiteProject,
    asset_path: str = "",
) -> bool:
    if request_has_runtime_access(request, project):
        return True
    return allows_anonymous_runtime_asset(asset_path)


def attach_runtime_access_cookie(response, request: HttpRequest, project: WebsiteProject):
    token = request.GET.get("access") or ""
    if not verify_runtime_access_token(token, project):
        return response
    response.set_cookie(
        runtime_cookie_name(project),
        token,
        max_age=RUNTIME_TOKEN_MAX_AGE,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return response
