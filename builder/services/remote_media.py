"""Download and localize remote storefront images into a project."""

from __future__ import annotations

import hashlib
import logging
import re
from html import unescape
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .editor_assets import recover_shopify_media_urls

logger = logging.getLogger(__name__)

SHOPIFY_CDN_URL_RE = re.compile(
    r"""https://cdn\.shopify\.com/s/files/[^\s\"'<>]+""",
    re.IGNORECASE,
)


def _safe_filename(url: str) -> str:
    path = PurePosixPath(urlparse(unescape(url)).path)
    name = path.name or "image.png"
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-") or "image.png"
    if "." not in name:
        name = f"{name}.png"
    if len(name) > 120:
        stem, suffix = Path(name).stem[:80], Path(name).suffix
        name = f"{stem}{suffix}"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"{Path(name).stem}-{digest}{Path(name).suffix.lower()}"


def download_remote_image(url: str, *, timeout: int = 25) -> bytes | None:
    clean = unescape((url or "").strip())
    if not clean.startswith(("http://", "https://")):
        return None
    try:
        request = Request(
            clean,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://cdn.shopify.com/",
            },
        )
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        logger.info("Could not download remote image %s: %s", clean[:160], exc)
        return None
    if not raw or len(raw) > 12 * 1024 * 1024:
        return None
    if content_type and not content_type.startswith("image/") and "octet-stream" not in content_type:
        return None
    return raw


def localize_shopify_media_in_text(text: str, source_root: Path) -> tuple[str, int]:
    """Recover Shopify CDN URLs, download them, rewrite HTML to local paths."""
    updated = recover_shopify_media_urls(text or "")
    urls = {unescape(match.group(0)) for match in SHOPIFY_CDN_URL_RE.finditer(updated)}
    if not urls:
        return updated, 0

    dest_dir = source_root / "images" / "shopify"
    dest_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    for url in sorted(urls):
        filename = _safe_filename(url)
        target = dest_dir / filename
        if not target.is_file():
            raw = download_remote_image(url)
            if not raw:
                continue
            target.write_bytes(raw)
        if target.is_file():
            relative = f"images/shopify/{filename}"
            mapping[url] = relative
            # Also map HTML-escaped ampersand variants used in attributes.
            mapping[url.replace("&", "&amp;")] = relative

    if not mapping:
        return updated, 0

    for remote, local in mapping.items():
        updated = updated.replace(remote, local)
    return updated, len(mapping)


def _text_needs_shopify_repair(sample: str) -> bool:
    lowered = (sample or "").lower()
    if "ngrok" in lowered:
        return True
    if re.search(r"""["']/s/files/\d+/""", sample or ""):
        return True
    if "cdn.shopify.com/s/files/" in (sample or ""):
        return True
    return False


def repair_project_shopify_images(
    source_root: Path,
    *,
    editor_data_path: Path | None = None,
) -> dict[str, int]:
    """Rewrite HTML (and optional GrapesJS JSON) to use local Shopify image copies."""
    root = Path(source_root)
    if not root.is_dir():
        return {"files": 0, "images": 0}
    files_changed = 0
    images = 0
    for html_path in sorted(root.rglob("*.html")):
        original = html_path.read_text(encoding="utf-8", errors="replace")
        if not _text_needs_shopify_repair(original):
            continue
        updated, count = localize_shopify_media_in_text(original, root)
        if updated != original:
            html_path.write_text(updated, encoding="utf-8")
            files_changed += 1
            images = max(images, count)

    if editor_data_path and Path(editor_data_path).is_file():
        original = Path(editor_data_path).read_text(encoding="utf-8", errors="replace")
        if _text_needs_shopify_repair(original):
            updated, count = localize_shopify_media_in_text(original, root)
            if updated != original:
                Path(editor_data_path).write_text(updated, encoding="utf-8")
                files_changed += 1
                images = max(images, count)

    return {"files": files_changed, "images": images}


def project_needs_shopify_image_repair(
    source_root: Path,
    *,
    editor_data_path: Path | None = None,
) -> bool:
    root = Path(source_root)
    if root.is_dir():
        for html_path in root.rglob("*.html"):
            try:
                sample = html_path.read_text(encoding="utf-8", errors="replace")[:200_000]
            except OSError:
                continue
            if _text_needs_shopify_repair(sample):
                return True
    if editor_data_path and Path(editor_data_path).is_file():
        try:
            sample = Path(editor_data_path).read_text(encoding="utf-8", errors="replace")[:400_000]
        except OSError:
            return False
        return _text_needs_shopify_repair(sample)
    return False
