from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from django.core.exceptions import ValidationError
from django.utils.text import get_valid_filename

from .archive import StylesheetParser, is_html_path, safe_project_path
from .html_tools import SCRIPT_RE
from .runtime_site import should_rewrite_root_path

MAX_CAPTURED_HTML_BYTES = 2 * 1024 * 1024
CAPTURE_DIR = "captured"

ATTR_URL_RE = re.compile(
    r"""(?P<prefix>\b(?:src|href|poster|data)\s*=\s*)(?P<quote>['"])(?P<value>[^'"]+)(?P=quote)""",
    re.IGNORECASE,
)
SRCSET_RE = re.compile(
    r"""(?P<prefix>\bsrcset\s*=\s*)(?P<quote>['"])(?P<value>[^'"]+)(?P=quote)""",
    re.IGNORECASE,
)
CSS_URL_RE = re.compile(
    r"""(?P<prefix>\burl\(\s*)(?P<quote>['"]?)(?P<value>[^'")]+)(?P=quote)\s*\)""",
    re.IGNORECASE,
)
RUNTIME_HOST_RE = re.compile(
    r"""^https?://[0-9a-f-]{36}\.runtime\.localhost(?::\d+)?(?P<path>/[^?\s#]*)""",
    re.IGNORECASE,
)


def route_slug_from_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return "page"
    parsed = urlsplit(raw)
    fragment = unquote(parsed.fragment or "")
    path = fragment if fragment.startswith("/") else (parsed.path or "")
    path = path.split("?", 1)[0].strip("/")
    if path.startswith("/"):
        path = path[1:]
    if not path or path in {"#", "/"}:
        return "home"
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", path).strip("-_.")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or "page")[:80]


# Browser extensions and AI sidebars that often pollute document.documentElement.outerHTML.
EXTENSION_NODE_RE = re.compile(
    r"""<(?:chatgpt-sidebar|grammarly-desktop-integration|grammarly-extension|"""
    r"""hubspot-messages-iframe-container|crx-|moz-extension)[^>]*>.*?</(?:chatgpt-sidebar|"""
    r"""grammarly-desktop-integration|grammarly-extension|hubspot-messages-iframe-container|"""
    r"""crx-|moz-extension)>|"""
    r"""<(?:chatgpt-sidebar|grammarly-desktop-integration|grammarly-extension)\b[^>]*/?>""",
    re.IGNORECASE | re.DOTALL,
)


def sanitise_captured_html(html_text: str) -> str:
    text = (html_text or "").strip()
    if not text:
        raise ValidationError("Captured page HTML was empty.")
    if len(text.encode("utf-8")) > MAX_CAPTURED_HTML_BYTES:
        raise ValidationError("Captured page is too large to save.")
    # Drop executable scripts; keep styles and rendered markup.
    text = SCRIPT_RE.sub("", text)
    text = re.sub(r"\son\w+\s*=\s*([\"']).*?\1", "", text, flags=re.IGNORECASE | re.DOTALL)
    # Drop modulepreload / script prefetch leftovers that cannot run in Safe Edit.
    text = re.sub(
        r"<link\b[^>]*\brel\s*=\s*[\"'][^\"']*(?:modulepreload|preload)[^\"']*[\"'][^>]*>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = EXTENSION_NODE_RE.sub("", text)
    # Collapse accidental duplicate closing body/html tags from polluted captures.
    text = re.sub(r"(</body>\s*){2,}", "</body>\n", text, flags=re.IGNORECASE)
    text = re.sub(r"(</html>\s*){2,}", "</html>\n", text, flags=re.IGNORECASE)
    if "<html" not in text.lower():
        text = (
            "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>Captured page</title>\n</head>\n<body>\n{text}\n</body>\n</html>\n"
        )
    if "<!DOCTYPE" not in text[:200].upper():
        text = "<!DOCTYPE html>\n" + text
    return text


def _split_suffix(value: str) -> tuple[str, str]:
    match = re.match(r"^([^?#]*)([?#].*)?$", (value or "").strip())
    if not match:
        return (value or "").strip(), ""
    return match.group(1), match.group(2) or ""


def _normalize_capture_ref(value: str) -> str | None:
    """Return a root-relative project path (no leading slash) for local assets."""
    raw = (value or "").strip()
    if not raw or raw.startswith(("#", "data:", "blob:", "mailto:", "tel:", "javascript:")):
        return None

    runtime = RUNTIME_HOST_RE.match(raw)
    if runtime:
        raw = runtime.group("path")

    parsed = urlsplit(raw)
    if parsed.scheme in {"http", "https"} or raw.startswith("//"):
        # External CDN / fonts stay untouched unless rewritten above as runtime host.
        if not runtime:
            return None

    path = unquote(parsed.path or raw)
    path, _suffix = _split_suffix(path)
    if not path.startswith("/"):
        return None
    if not should_rewrite_root_path(path):
        return None
    return path.lstrip("/")


def _relative_from_html(relative_html_path: str, asset_path: str) -> str:
    html_parent = PurePosixPath(relative_html_path).parent
    if str(html_parent) == ".":
        return asset_path
    ups = "/".join(".." for _ in html_parent.parts)
    return f"{ups}/{asset_path}"


def rewrite_captured_asset_urls(html_text: str, *, relative_html_path: str) -> str:
    """Rewrite root-absolute and runtime-host asset URLs for a file under captured/."""

    def rewrite_one(value: str) -> str:
        path_only, suffix = _split_suffix(value)
        asset = _normalize_capture_ref(path_only)
        if not asset:
            return value
        return _relative_from_html(relative_html_path, asset) + suffix

    def repl_attr(match: re.Match[str]) -> str:
        return f'{match.group("prefix")}{match.group("quote")}{rewrite_one(match.group("value"))}{match.group("quote")}'

    def repl_srcset(match: re.Match[str]) -> str:
        parts = []
        for chunk in match.group("value").split(","):
            piece = chunk.strip()
            if not piece:
                continue
            bits = piece.split()
            bits[0] = rewrite_one(bits[0])
            parts.append(" ".join(bits))
        return f'{match.group("prefix")}{match.group("quote")}{", ".join(parts)}{match.group("quote")}'

    def repl_css_url(match: re.Match[str]) -> str:
        quote = match.group("quote") or ""
        return f'{match.group("prefix")}{quote}{rewrite_one(match.group("value"))}{quote})'

    html_text = ATTR_URL_RE.sub(repl_attr, html_text)
    html_text = SRCSET_RE.sub(repl_srcset, html_text)
    return CSS_URL_RE.sub(repl_css_url, html_text)


def collect_stylesheet_refs(html_text: str, *, relative_html_path: str, source_root: Path) -> list[str]:
    """Return stylesheet hrefs usable by the editor (remote URLs or source-relative local paths)."""
    parser = StylesheetParser()
    parser.feed(html_text)
    html_dir = (source_root / relative_html_path).parent
    source_root_resolved = source_root.resolve()
    collected: list[str] = []
    seen: set[str] = set()

    for href in parser.stylesheets:
        raw = (href or "").strip()
        if not raw or "siaw-editor-overrides" in raw:
            continue
        lowered = raw.lower()
        if lowered.startswith(("http://", "https://", "//")):
            if raw not in seen:
                seen.add(raw)
                collected.append(raw)
            continue

        root_asset = _normalize_capture_ref(raw)
        if root_asset:
            candidate = (source_root / root_asset).resolve()
            relative = root_asset
        else:
            candidate = (html_dir / raw).resolve()
            try:
                relative = candidate.relative_to(source_root_resolved).as_posix()
            except ValueError:
                continue

        if not candidate.is_file():
            continue
        if relative not in seen:
            seen.add(relative)
            collected.append(relative)
    return collected


def prepare_captured_html(
    html_text: str,
    *,
    relative_html_path: str,
    source_root: Path,
) -> tuple[str, list[str]]:
    clean = sanitise_captured_html(html_text)
    rewritten = rewrite_captured_asset_urls(clean, relative_html_path=relative_html_path)
    stylesheets = collect_stylesheet_refs(
        rewritten,
        relative_html_path=relative_html_path,
        source_root=source_root,
    )
    return rewritten, stylesheets


def save_captured_route(
    source_root: Path,
    *,
    html_text: str,
    route_url: str = "",
    title: str = "",
) -> tuple[str, list[str]]:
    slug = route_slug_from_url(route_url)
    if title:
        title_slug = get_valid_filename(title).replace(" ", "-").strip("-_.")[:40]
        if title_slug:
            slug = f"{slug}-{title_slug}" if slug != "home" else title_slug
    slug = re.sub(r"-{2,}", "-", slug).strip("-_.") or "page"

    target_dir = source_root / CAPTURE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{slug}.html"
    relative = f"{CAPTURE_DIR}/{filename}"
    destination = safe_project_path(source_root, relative)
    # Avoid overwriting: append counter.
    counter = 2
    while destination.exists():
        relative = f"{CAPTURE_DIR}/{slug}-{counter}.html"
        destination = safe_project_path(source_root, relative)
        counter += 1
        if counter > 50:
            raise ValidationError("Too many captured pages with this name.")

    if not is_html_path(destination):
        raise ValidationError("Captured pages must be saved as HTML.")

    clean_html, stylesheets = prepare_captured_html(
        html_text,
        relative_html_path=relative,
        source_root=source_root,
    )

    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(clean_html, encoding="utf-8")
    temporary.replace(destination)
    return relative, stylesheets


def rewrite_html_for_editor_entry(html_text: str, *, relative_html_path: str) -> str:
    """Repair root-absolute asset URLs when loading an existing captured page."""
    text = EXTENSION_NODE_RE.sub("", html_text or "")
    text = re.sub(r"(</body>\s*){2,}", "</body>\n", text, flags=re.IGNORECASE)
    text = re.sub(r"(</html>\s*){2,}", "</html>\n", text, flags=re.IGNORECASE)
    if f"{CAPTURE_DIR}/" not in relative_html_path.replace("\\", "/"):
        # Still rewrite runtime-host absolute URLs and /assets for Vite pages.
        if "/assets/" not in text and ".runtime.localhost" not in text:
            return text
    return rewrite_captured_asset_urls(text, relative_html_path=relative_html_path)
