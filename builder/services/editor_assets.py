"""Materialize local assets for GrapesJS Safe Edit (all projects, not site-specific).

GrapesJS canvas frames often use about:blank/blob documents, so relative paths like
../assets/hero.jpg fail even when a <base> tag is present. Absolute project-file
URLs and inlined local CSS make captured and imported pages render reliably.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .route_capture import (
    ATTR_URL_RE,
    CSS_URL_RE,
    RUNTIME_HOST_RE,
    SRCSET_RE,
    _normalize_capture_ref,
    _split_suffix,
    collect_stylesheet_refs,
)
from .runtime_site import should_rewrite_root_path

PROJECT_FILE_URL_RE = re.compile(
    r"""/projects/[0-9a-f-]{36}/files/(?P<path>[^?\s#'"]+)""",
    re.IGNORECASE,
)
# Dead ngrok / storefront proxies that wrap Shopify CDN paths.
PROXY_SHOPIFY_FILES_RE = re.compile(
    r"""https?://(?!cdn\.shopify\.com)[^/\"'\s]+(/s/files/\d+/[^\s\"'<>]+)""",
    re.IGNORECASE,
)
RELATIVE_SHOPIFY_FILES_RE = re.compile(
    r"""(?<=["'(])(/s/files/\d+/[^\s\"'<>)]+)""",
    re.IGNORECASE,
)
CSS_IMPORT_RE = re.compile(
    r"""@import\s+(?:url\(\s*)?(?P<quote>['"]?)(?P<value>[^'")\s]+)(?P=quote)\s*\)?\s*;""",
    re.IGNORECASE,
)


def recover_shopify_media_urls(value: str) -> str:
    """Map broken Shopify file proxies back to the public CDN host.

    Codex / storefront imports often embed ngrok or relative `/s/files/...`
    URLs. The editor previously rewrote any path containing `/files/` onto
    localhost, which 404s. Prefer the real Shopify CDN.
    """
    text = value or ""
    if not text:
        return text
    text = PROXY_SHOPIFY_FILES_RE.sub(r"https://cdn.shopify.com\1", text)
    text = RELATIVE_SHOPIFY_FILES_RE.sub(r"https://cdn.shopify.com\1", text)
    return text


def _is_external(value: str) -> bool:
    raw = (value or "").strip().lower()
    if not raw or raw.startswith(("#", "data:", "blob:", "mailto:", "tel:", "javascript:", "whatsapp:")):
        return True
    if raw.startswith("//"):
        return True
    parsed = urlsplit(raw)
    return bool(parsed.scheme and parsed.scheme not in {"", "file"})


def resolve_source_relative(
    value: str,
    *,
    source_root: Path,
    entry_file: str,
    project_file_prefix: str = "",
) -> str | None:
    """Map any local URL form to a source-root-relative path if the file exists."""
    raw = (value or "").strip()
    if not raw:
        return None

    path_only, _suffix = _split_suffix(raw)
    source_root_resolved = source_root.resolve()
    entry_dir = (source_root / entry_file).parent

    # Runtime host absolute URL.
    runtime = RUNTIME_HOST_RE.match(path_only)
    if runtime:
        candidate_rel = runtime.group("path").lstrip("/")
        candidate = (source_root / candidate_rel).resolve()
        if candidate.is_file():
            try:
                return candidate.relative_to(source_root_resolved).as_posix()
            except ValueError:
                return None
        return None

    # Already a project files URL.
    match = PROJECT_FILE_URL_RE.search(path_only)
    if match:
        candidate_rel = unquote(match.group("path"))
        candidate = (source_root / candidate_rel).resolve()
        if candidate.is_file():
            try:
                return candidate.relative_to(source_root_resolved).as_posix()
            except ValueError:
                return None
        return None

    # External non-local URL.
    if _is_external(path_only):
        return None

    # Root-absolute /assets/...
    root_asset = _normalize_capture_ref(path_only)
    if root_asset:
        candidate = (source_root / root_asset).resolve()
        if candidate.is_file():
            return root_asset
        return None

    # Relative to entry (../assets/x, ./img.png, assets/x)
    cleaned = path_only
    if cleaned.startswith("/"):
        if should_rewrite_root_path(cleaned):
            candidate = (source_root / cleaned.lstrip("/")).resolve()
            if candidate.is_file():
                try:
                    return candidate.relative_to(source_root_resolved).as_posix()
                except ValueError:
                    return None
        return None

    candidate = (entry_dir / cleaned).resolve()
    try:
        relative = candidate.relative_to(source_root_resolved).as_posix()
    except ValueError:
        return None
    if candidate.is_file():
        return relative
    return None


def absolutize_html_assets(
    html_text: str,
    *,
    source_root: Path,
    entry_file: str,
    project_file_prefix: str,
    origin: str = "",
) -> str:
    """Rewrite local asset URLs in HTML to absolute project-file URLs for Safe Edit."""
    prefix = project_file_prefix if project_file_prefix.endswith("/") else project_file_prefix + "/"
    if origin and prefix.startswith("/"):
        base = origin.rstrip("/") + prefix
    else:
        base = prefix

    def to_abs(value: str) -> str:
        path_only, suffix = _split_suffix(value)
        relative = resolve_source_relative(
            path_only,
            source_root=source_root,
            entry_file=entry_file,
            project_file_prefix=project_file_prefix,
        )
        if not relative:
            return value
        return f"{base}{relative}{suffix}"

    def repl_attr(match: re.Match[str]) -> str:
        # Keep in-page anchors and non-asset page routes as-is.
        value = match.group("value")
        attr = match.group("prefix").lower()
        if "href" in attr:
            lowered = value.strip().lower()
            if lowered.startswith("#") or lowered.startswith(("mailto:", "tel:", "whatsapp:", "javascript:")):
                return match.group(0)
            # Don't rewrite plain site routes like /product/soft into missing files.
            relative = resolve_source_relative(
                value,
                source_root=source_root,
                entry_file=entry_file,
                project_file_prefix=project_file_prefix,
            )
            if not relative:
                return match.group(0)
        return f'{match.group("prefix")}{match.group("quote")}{to_abs(value)}{match.group("quote")}'

    def repl_srcset(match: re.Match[str]) -> str:
        parts = []
        for chunk in match.group("value").split(","):
            piece = chunk.strip()
            if not piece:
                continue
            bits = piece.split()
            bits[0] = to_abs(bits[0])
            parts.append(" ".join(bits))
        return f'{match.group("prefix")}{match.group("quote")}{", ".join(parts)}{match.group("quote")}'

    def repl_css_url(match: re.Match[str]) -> str:
        quote = match.group("quote") or ""
        return f'{match.group("prefix")}{quote}{to_abs(match.group("value"))}{quote})'

    html_text = ATTR_URL_RE.sub(repl_attr, html_text)
    html_text = SRCSET_RE.sub(repl_srcset, html_text)
    return CSS_URL_RE.sub(repl_css_url, html_text)


def rewrite_css_urls(
    css_text: str,
    *,
    css_relative_path: str,
    source_root: Path,
    project_file_prefix: str,
    origin: str = "",
) -> str:
    prefix = project_file_prefix if project_file_prefix.endswith("/") else project_file_prefix + "/"
    base = (origin.rstrip("/") + prefix) if origin and prefix.startswith("/") else prefix
    css_entry = css_relative_path

    def to_abs(value: str) -> str:
        path_only, suffix = _split_suffix(value)
        relative = resolve_source_relative(
            path_only,
            source_root=source_root,
            entry_file=css_entry,
            project_file_prefix=project_file_prefix,
        )
        if not relative:
            return value
        return f"{base}{relative}{suffix}"

    def repl(match: re.Match[str]) -> str:
        quote = match.group("quote") or ""
        return f'{match.group("prefix")}{quote}{to_abs(match.group("value"))}{quote})'

    return CSS_URL_RE.sub(repl, css_text)


def inline_local_stylesheets(
    stylesheet_refs: list[str],
    *,
    source_root: Path,
    project_file_prefix: str,
    origin: str = "",
) -> tuple[list[str], list[str]]:
    """Return (inline_css_texts, remaining_remote_stylesheet_urls)."""
    inline: list[str] = []
    remote: list[str] = []
    for ref in stylesheet_refs:
        raw = (ref or "").strip()
        if not raw or "siaw-editor-overrides" in raw:
            continue
        if raw.lower().startswith(("http://", "https://", "//")):
            remote.append(raw)
            continue
        path = source_root / raw
        if not path.is_file():
            continue
        try:
            css_text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        css_text = rewrite_css_urls(
            css_text,
            css_relative_path=raw,
            source_root=source_root,
            project_file_prefix=project_file_prefix,
            origin=origin,
        )
        # Promote @import to <link> URLs. @import inside injected <style> tags
        # is unreliable and can delay or break the rest of the stylesheet.
        for match in CSS_IMPORT_RE.finditer(css_text):
            imported = (match.group("value") or "").strip()
            if imported and imported not in remote:
                remote.append(imported)
        css_text = CSS_IMPORT_RE.sub("", css_text).lstrip()
        if css_text:
            inline.append(css_text)
    return inline, remote


_IMAGE_EXT_RE = re.compile(
    r"""\.(?:png|jpe?g|gif|webp|svg|ico|avif|bmp)(?:\?|#|$)""",
    re.IGNORECASE,
)


def _looks_like_asset_path(value: str) -> bool:
    raw = (value or "").strip()
    if not raw:
        return False
    if any(
        token in raw
        for token in (
            "/assets/",
            "../assets/",
            "assets/",
            "siaw-hydrated/",
            ".runtime.localhost",
            "/files/",
        )
    ):
        return True
    if raw.startswith(("./", "../")) or "/" in raw:
        return True
    return bool(_IMAGE_EXT_RE.search(raw))


def absolutize_data_urls(
    value,
    *,
    source_root: Path,
    entry_file: str,
    project_file_prefix: str,
    origin: str,
):
    """Recursively rewrite local asset URL strings inside GrapesJS project JSON."""
    if isinstance(value, str):
        if not value or value.startswith(("#", "data:", "blob:")):
            return value
        # GrapesJS saves assets as entry-relative paths (e.g. siaw-hydrated/hero-1.jpg).
        # Those break in the parent-page Asset Manager, which has no canvas <base> tag.
        if _looks_like_asset_path(value):
            path_only, suffix = _split_suffix(value)
            relative = resolve_source_relative(
                path_only,
                source_root=source_root,
                entry_file=entry_file,
                project_file_prefix=project_file_prefix,
            )
            if relative:
                prefix = project_file_prefix if project_file_prefix.endswith("/") else project_file_prefix + "/"
                base = (origin.rstrip("/") + prefix) if origin and prefix.startswith("/") else prefix
                return f"{base}{relative}{suffix}"
        return value
    if isinstance(value, list):
        return [
            absolutize_data_urls(
                item,
                source_root=source_root,
                entry_file=entry_file,
                project_file_prefix=project_file_prefix,
                origin=origin,
            )
            for item in value
        ]
    if isinstance(value, dict):
        skipped_keys = {"relativePath", "name", "type", "tagName", "unitDim", "status"}
        return {
            key: (
                item
                if key in skipped_keys
                else absolutize_data_urls(
                    item,
                    source_root=source_root,
                    entry_file=entry_file,
                    project_file_prefix=project_file_prefix,
                    origin=origin,
                )
            )
            for key, item in value.items()
        }
    return value


def materialize_entry_for_visual_editor(
    html_text: str,
    *,
    source_root: Path,
    entry_file: str,
    project_file_prefix: str,
    origin: str,
    stylesheet_files: list[str] | None = None,
    project_data: dict | None = None,
) -> dict:
    """Prepare HTML + CSS payloads so Safe Edit renders like the live page."""
    html_text = recover_shopify_media_urls(html_text or "")
    discovered = collect_stylesheet_refs(
        html_text,
        relative_html_path=entry_file,
        source_root=source_root,
    )
    sheets: list[str] = []
    for item in list(stylesheet_files or []) + discovered:
        if item and item not in sheets:
            sheets.append(item)

    absolute_html = absolutize_html_assets(
        html_text,
        source_root=source_root,
        entry_file=entry_file,
        project_file_prefix=project_file_prefix,
        origin=origin,
    )
    inline_css, remote_sheets = inline_local_stylesheets(
        sheets,
        source_root=source_root,
        project_file_prefix=project_file_prefix,
        origin=origin,
    )
    absolute_project_data = None
    if isinstance(project_data, dict):
        recovered_data = absolutize_data_urls(
            project_data,
            source_root=source_root,
            entry_file=entry_file,
            project_file_prefix=project_file_prefix,
            origin=origin,
        )

        def _recover_tree(value):
            if isinstance(value, str):
                return recover_shopify_media_urls(value)
            if isinstance(value, list):
                return [_recover_tree(item) for item in value]
            if isinstance(value, dict):
                return {key: _recover_tree(item) for key, item in value.items()}
            return value

        absolute_project_data = _recover_tree(recovered_data)

    return {
        "html": absolute_html,
        "inlineStyles": inline_css,
        "remoteStylesheets": remote_sheets,
        "stylesheetFiles": sheets,
        "projectData": absolute_project_data,
    }
