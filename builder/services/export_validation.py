"""Pre-export validation for missing assets and broken relative links."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .archive import is_html_path

HREF_ATTRS = {"href", "src", "poster", "data"}
SRCSET_ATTRS = {"srcset", "data-srcset"}
EXTERNAL_SCHEMES = {"http", "https", "mailto", "tel", "sms", "data", "blob", "javascript", "whatsapp"}


class ResourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        data = {str(k).lower(): "" if v is None else str(v) for k, v in attrs if k}
        for attr in HREF_ATTRS:
            if attr not in data:
                continue
            self.refs.append((tag, attr, data.get(attr) or ""))
        for attr in SRCSET_ATTRS:
            if attr not in data:
                continue
            value = data.get(attr) or ""
            if not value.strip():
                self.refs.append((tag, attr, ""))
                continue
            for part in value.split(","):
                url = part.strip().split(" ")[0].strip()
                if url:
                    self.refs.append((tag, attr, url))


def _is_external(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned or cleaned.startswith("#") or cleaned.startswith("?"):
        return True
    lowered = cleaned.lower()
    if lowered.startswith("//"):
        return True
    scheme = urlsplit(cleaned).scheme.lower()
    return bool(scheme) and scheme in EXTERNAL_SCHEMES


def _resolve_local(source_root: Path, page_path: str, ref: str) -> Path | None:
    cleaned = unquote(ref.split("?", 1)[0].split("#", 1)[0]).strip()
    if not cleaned or _is_external(cleaned):
        return None
    page_dir = (source_root / page_path).parent
    candidate = (page_dir / cleaned).resolve()
    try:
        candidate.relative_to(source_root.resolve())
    except ValueError:
        return None
    return candidate


def validate_export(source_root: Path, entry_file: str) -> dict:
    pages = [
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*")
        if path.is_file() and is_html_path(path)
    ]
    if entry_file not in pages and (source_root / entry_file).is_file():
        pages.insert(0, entry_file)

    missing: list[dict[str, str]] = []
    empty_links: list[dict[str, str]] = []
    checked_pages = 0

    for page in pages:
        target = source_root / page
        if not target.is_file():
            continue
        checked_pages += 1
        html_text = target.read_text(encoding="utf-8", errors="replace")
        parser = ResourceParser()
        try:
            parser.feed(html_text)
        except Exception:
            continue
        for tag, attr, value in parser.refs:
            if not value.strip():
                empty_links.append({"page": page, "tag": tag, "attribute": attr, "value": ""})
                continue
            if _is_external(value):
                continue
            resolved = _resolve_local(source_root, page, value)
            if resolved is None:
                continue
            if not resolved.is_file():
                try:
                    resolved_rel = resolved.relative_to(source_root.resolve()).as_posix()
                except ValueError:
                    resolved_rel = value
                missing.append(
                    {
                        "page": page,
                        "tag": tag,
                        "attribute": attr,
                        "value": value,
                        "resolved": resolved_rel,
                    }
                )

    # Deduplicate missing by page+value
    seen = set()
    unique_missing = []
    for item in missing:
        key = (item["page"], item["value"])
        if key in seen:
            continue
        seen.add(key)
        unique_missing.append(item)

    warning_count = len(unique_missing) + len(empty_links)
    return {
        "ok": warning_count == 0,
        "checkedPages": checked_pages,
        "entryFile": entry_file,
        "warningCount": warning_count,
        "missingResources": unique_missing[:80],
        "emptyLinks": empty_links[:40],
        "summary": (
            "Export looks clean."
            if warning_count == 0
            else f"Found {warning_count} warning(s) before export."
        ),
    }
