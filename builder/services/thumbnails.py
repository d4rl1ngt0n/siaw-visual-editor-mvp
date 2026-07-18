"""Dashboard project thumbnails from entry HTML hero imagery."""

from __future__ import annotations

import html
import re
from pathlib import PurePosixPath
from urllib.parse import unquote

from django.urls import reverse

from builder.models import WebsiteProject

IMG_SRC_RE = re.compile(
    r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE | re.DOTALL,
)
OG_IMAGE_RE = re.compile(
    r"""<meta\b[^>]*?(?:property|name)\s*=\s*["']og:image["'][^>]*?\bcontent\s*=\s*["']([^"']+)["']"""
    r"""|<meta\b[^>]*?\bcontent\s*=\s*["']([^"']+)["'][^>]*?(?:property|name)\s*=\s*["']og:image["']""",
    re.IGNORECASE | re.DOTALL,
)
CSS_URL_RE = re.compile(
    r"""background(?:-image)?\s*:\s*[^;]*url\(\s*["']?([^"')]+)["']?\s*\)""",
    re.IGNORECASE,
)


def _is_usable_image_url(src: str) -> bool:
    value = html.unescape((src or "").strip())
    if not value or value.startswith("#") or value.lower().startswith("javascript:"):
        return False
    lowered = value.lower()
    if lowered.startswith("data:image/"):
        return True
    if lowered.startswith(("http://", "https://", "//")):
        return True
    # Skip tiny icons / favicons when possible.
    if any(token in lowered for token in ("favicon", "logo-mark", "icon-16", "icon-32", ".svg#")):
        return False
    return True


def _resolve_local_image(project: WebsiteProject, src: str) -> str | None:
    raw = unquote(html.unescape((src or "").strip()))
    if raw.startswith("//"):
        return f"https:{raw}"
    if raw.startswith(("http://", "https://", "data:")):
        return raw

    entry_parent = PurePosixPath(project.entry_file or "index.html").parent
    relative = entry_parent / raw.lstrip("/")

    # Normalize .. segments safely.
    parts: list[str] = []
    for part in relative.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    rel = "/".join(parts)
    if not rel:
        return None
    candidate = project.source_dir / rel
    if not candidate.is_file():
        return None
    return reverse("builder:source_file", args=[project.id, rel])


def extract_thumbnail_src(html_text: str, project: WebsiteProject) -> str | None:
    text = html_text or ""
    og = OG_IMAGE_RE.search(text)
    if og:
        candidate = og.group(1) or og.group(2) or ""
        if _is_usable_image_url(candidate):
            resolved = _resolve_local_image(project, candidate)
            if resolved:
                return resolved

    for match in IMG_SRC_RE.finditer(text):
        candidate = match.group(1)
        if not _is_usable_image_url(candidate):
            continue
        resolved = _resolve_local_image(project, candidate)
        if resolved:
            return resolved

    for match in CSS_URL_RE.finditer(text):
        candidate = match.group(1)
        if not _is_usable_image_url(candidate):
            continue
        # Prefer raster-looking background images.
        if any(ext in candidate.lower() for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", "unsplash", "images")):
            resolved = _resolve_local_image(project, candidate)
            if resolved:
                return resolved
    return None


def project_thumbnail(project: WebsiteProject) -> dict:
    """Return {kind: image|iframe|placeholder, src?: str} for dashboard cards."""
    entry = project.entry_path
    if entry.is_file() and entry.suffix.lower() in {".html", ".htm"}:
        try:
            html_text = entry.read_text(encoding="utf-8", errors="replace")
        except OSError:
            html_text = ""
        image = extract_thumbnail_src(html_text, project)
        if image:
            return {"kind": "image", "src": image}
        # Live scaled preview of the site itself (not the preview chrome page).
        return {
            "kind": "iframe",
            "src": reverse("builder:runtime_site", args=[project.id]),
        }
    return {"kind": "placeholder"}


def attach_project_thumbnails(projects) -> list[dict]:
    rows = []
    for project in projects:
        rows.append({"project": project, "thumbnail": project_thumbnail(project)})
    return rows
