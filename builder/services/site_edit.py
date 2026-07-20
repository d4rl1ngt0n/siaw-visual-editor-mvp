"""Localhost-only marketing site edits that write back into template files."""

from __future__ import annotations

import html
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest

LOCAL_HOSTS = {"127.0.0.1", "localhost", "testserver"}
TEMPLATE_ROOT = Path(settings.BASE_DIR) / "templates" / "builder"
STATIC_SITE_EDITS = Path(settings.BASE_DIR) / "static" / "builder" / "site-edits"
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,80}$", re.I)
GROUP_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,40}$", re.I)
ITEM_VALUE_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,100}$", re.I)
ALLOWED_REORDER_ATTRS = {"data-site-edit", "data-site-block"}
IMAGE_EXTS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}
MAX_IMAGE_BYTES = 4 * 1024 * 1024


# App screens where marketing site-edit must never inject UI chrome.
SITE_EDIT_BLOCKED_PREFIXES = (
    "/login",
    "/signup",
    "/logout",
    "/account",
    "/workspace",
    "/projects/",
    "/admin",
    "/site-edit/",
)


def site_edit_allowed(request: HttpRequest | None) -> bool:
    """True only for local DEBUG marketing pages. Never on deployed hosts or app screens."""
    if not request or not getattr(settings, "DEBUG", False):
        return False
    if getattr(settings, "SIAW_SITE_EDIT", True) is False:
        return False
    raw_host = request.META.get("HTTP_HOST") or request.META.get("SERVER_NAME") or ""
    host = str(raw_host).split(":", 1)[0].lower()
    if not (host in LOCAL_HOSTS or host.endswith(".localhost")):
        return False
    path = (getattr(request, "path", "") or "/").split("?", 1)[0].lower()
    for prefix in SITE_EDIT_BLOCKED_PREFIXES:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return False
    return True


def _iter_template_files() -> list[Path]:
    if not TEMPLATE_ROOT.is_dir():
        return []
    return sorted(
        path for path in TEMPLATE_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in {".html", ".htm"}
    )


def _replace_element_inner(content: str, key: str, value: str) -> tuple[str, bool]:
    """Replace inner HTML/text of the first data-site-edit=key element."""
    pattern = re.compile(
        rf'(data-site-edit="{re.escape(key)}"(?P<attrs>[^>]*)>)(?P<body>.*?)(</(?P<tag>[a-zA-Z0-9]+)\s*>)',
        re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        return content, False
    safe = html.escape(value, quote=False)
    replaced = content[: match.start("body")] + safe + content[match.end("body") :]
    return replaced, True


def _replace_img_src(content: str, key: str, value: str) -> tuple[str, bool]:
    safe_src = value.strip().replace("&", "&amp;").replace('"', "&quot;")
    # data-site-edit before src
    pattern_a = re.compile(
        rf'(data-site-edit="{re.escape(key)}"[^>]*?\bsrc=")([^"]*)(")',
        re.IGNORECASE,
    )
    match = pattern_a.search(content)
    if match:
        replaced = content[: match.start(2)] + safe_src + content[match.end(2) :]
        return replaced, True
    # src before data-site-edit
    pattern_b = re.compile(
        rf'(<img\b[^>]*?\bsrc=")([^"]*)("[^>]*?\bdata-site-edit="{re.escape(key)}")',
        re.IGNORECASE,
    )
    match = pattern_b.search(content)
    if not match:
        return content, False
    replaced = content[: match.start(2)] + safe_src + content[match.end(2) :]
    return replaced, True


def _find_tag_start(content: str, attr_match_start: int) -> tuple[int, str] | None:
    lt = content.rfind("<", 0, attr_match_start)
    if lt < 0:
        return None
    tag_match = re.match(r"<([a-zA-Z][a-zA-Z0-9]*)\b", content[lt:])
    if not tag_match:
        return None
    return lt, tag_match.group(1).lower()


def _extract_element_span(content: str, start: int, tag: str) -> tuple[int, int] | None:
    """Return [start, end) covering a full element starting at start."""
    tag_l = tag.lower()
    void = tag_l in {"img", "br", "hr", "input", "meta", "link", "source"}
    open_re = re.compile(rf"<{re.escape(tag_l)}\b([^>]*)>", re.IGNORECASE)
    close_re = re.compile(rf"</{re.escape(tag_l)}\s*>", re.IGNORECASE)
    open_match = open_re.match(content, start)
    if not open_match:
        return None
    attrs = open_match.group(1) or ""
    if void or attrs.rstrip().endswith("/"):
        return start, open_match.end()

    depth = 1
    pos = open_match.end()
    while pos < len(content) and depth > 0:
        next_open = open_re.search(content, pos)
        next_close = close_re.search(content, pos)
        if not next_close:
            return None
        if next_open and next_open.start() < next_close.start():
            inner_attrs = next_open.group(1) or ""
            if not (void or inner_attrs.rstrip().endswith("/")):
                depth += 1
            pos = next_open.end()
            continue
        depth -= 1
        pos = next_close.end()
        if depth == 0:
            return start, pos
    return None


def _extract_by_attr(content: str, attr: str, value: str) -> tuple[int, int, str] | None:
    needle = f'{attr}="{value}"'
    attr_at = content.find(needle)
    if attr_at < 0:
        needle = f"{attr}='{value}'"
        attr_at = content.find(needle)
    if attr_at < 0:
        return None
    found = _find_tag_start(content, attr_at)
    if not found:
        return None
    start, tag = found
    span = _extract_element_span(content, start, tag)
    if not span:
        return None
    a, b = span
    return a, b, content[a:b]


def _extract_block(content: str, group: str, key: str) -> tuple[int, int, str] | None:
    return _extract_by_attr(content, "data-site-block", f"{group}:{key}")


def _reorder_items(content: str, items: list[tuple[str, str]]) -> tuple[str, bool]:
    """Reorder elements identified by (attr, value) pairs within one contiguous region."""
    blocks: list[tuple[int, int, str, str]] = []
    for attr, value in items:
        extracted = _extract_by_attr(content, attr, value)
        if not extracted:
            return content, False
        start, end, html_block = extracted
        blocks.append((start, end, f"{attr}={value}", html_block))

    blocks_sorted = sorted(blocks, key=lambda item: item[0])
    for i in range(1, len(blocks_sorted)):
        if blocks_sorted[i][0] < blocks_sorted[i - 1][1]:
            return content, False

    region_start = blocks_sorted[0][0]
    region_end = blocks_sorted[-1][1]
    separators: list[str] = []
    for i in range(len(blocks_sorted) - 1):
        separators.append(content[blocks_sorted[i][1]: blocks_sorted[i + 1][0]])

    by_id = {item_id: html_block for _, _, item_id, html_block in blocks}
    order_ids = [f"{attr}={value}" for attr, value in items]
    pieces = [by_id[order_ids[0]]]
    for idx, item_id in enumerate(order_ids[1:], start=0):
        sep = separators[idx] if idx < len(separators) else "\n"
        pieces.append(sep)
        pieces.append(by_id[item_id])
    rebuilt = "".join(pieces)
    if content[region_start:region_end] == rebuilt:
        return content, False
    return content[:region_start] + rebuilt + content[region_end:], True


def _reorder_blocks(content: str, group: str, order: list[str]) -> tuple[str, bool]:
    items = [("data-site-block", f"{group}:{key}") for key in order]
    return _reorder_items(content, items)


def save_site_edit_image(upload) -> dict:
    """Persist an uploaded image under static/builder/site-edits/."""
    content_type = (getattr(upload, "content_type", None) or "").split(";")[0].strip().lower()
    ext = IMAGE_EXTS.get(content_type)
    name = str(getattr(upload, "name", "") or "")
    if not ext:
        suffix = Path(name).suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}:
            ext = ".jpg" if suffix == ".jpeg" else suffix
    if not ext:
        raise ValueError("Upload a JPG, PNG, WebP, GIF, or SVG image.")

    data = upload.read(MAX_IMAGE_BYTES + 1)
    if not data:
        raise ValueError("Empty image upload.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image is too large (max 4 MB).")

    STATIC_SITE_EDITS.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    path = STATIC_SITE_EDITS / filename
    path.write_bytes(data)
    return {
        "ok": True,
        "url": f"/static/builder/site-edits/{filename}",
        "path": f"static/builder/site-edits/{filename}",
    }


def apply_site_edits(edits: list[dict]) -> dict:
    """
    Apply edits shaped like:
      {"key": "hero.headline", "value": "...", "kind": "text"|"src"}
      {"kind": "reorder", "group": "services", "order": ["1", "2", ...]}
      {"kind": "reorder_items", "items": [{"attr": "data-site-edit", "key": "hero.lead"}, ...]}
    Writes into templates under templates/builder/.
    """
    if not isinstance(edits, list) or not edits:
        raise ValueError("No edits provided.")

    files = _iter_template_files()
    if not files:
        raise ValueError("No editable template files found.")

    pending_text: list[tuple[str, str, str]] = []
    pending_reorder: list[tuple[str, list[str]]] = []
    pending_reorder_items: list[list[tuple[str, str]]] = []

    for item in edits:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "text").strip().lower()
        if kind == "reorder_items":
            raw_items = item.get("items")
            if not isinstance(raw_items, list) or len(raw_items) < 2:
                raise ValueError("reorder_items needs at least two items.")
            cleaned_items: list[tuple[str, str]] = []
            seen: set[str] = set()
            for raw in raw_items:
                if not isinstance(raw, dict):
                    continue
                attr = str(raw.get("attr") or "").strip()
                value = str(raw.get("key") or raw.get("value") or "").strip()
                if attr not in ALLOWED_REORDER_ATTRS:
                    raise ValueError(f"Unsupported reorder attr: {attr!r}")
                if not ITEM_VALUE_RE.match(value):
                    raise ValueError(f"Invalid reorder item key: {value!r}")
                token = f"{attr}={value}"
                if token in seen:
                    raise ValueError(f"Duplicate reorder item: {value}")
                seen.add(token)
                cleaned_items.append((attr, value))
            if len(cleaned_items) < 2:
                raise ValueError("reorder_items needs at least two valid items.")
            pending_reorder_items.append(cleaned_items)
            continue
        if kind == "reorder":
            group = str(item.get("group") or "").strip()
            order = item.get("order")
            if not GROUP_RE.match(group):
                raise ValueError(f"Invalid reorder group: {group!r}")
            if not isinstance(order, list) or len(order) < 2:
                raise ValueError(f"Reorder group {group} needs at least two keys.")
            cleaned: list[str] = []
            for raw in order:
                key = str(raw or "").strip()
                if not KEY_RE.match(key):
                    raise ValueError(f"Invalid reorder key: {key!r}")
                cleaned.append(key)
            if len(set(cleaned)) != len(cleaned):
                raise ValueError(f"Reorder group {group} has duplicate keys.")
            pending_reorder.append((group, cleaned))
            continue

        key = str(item.get("key") or "").strip()
        value = item.get("value")
        if not KEY_RE.match(key):
            raise ValueError(f"Invalid edit key: {key!r}")
        if not isinstance(value, str):
            raise ValueError(f"Edit value for {key} must be a string.")
        limit = 12000 if kind == "src" else 4000
        if len(value) > limit:
            raise ValueError(f"Edit value for {key} is too long.")
        if kind not in {"text", "src"}:
            raise ValueError(f"Unsupported edit kind for {key}.")
        if kind == "src":
            lowered = value.strip().lower()
            if not (
                lowered.startswith("https://")
                or lowered.startswith("http://")
                or lowered.startswith("/")
                or lowered.startswith("data:image/")
            ):
                raise ValueError(f"Image URL for {key} must be http(s), site-relative, or data:image.")
        pending_text.append((key, value, kind))

    if not pending_text and not pending_reorder and not pending_reorder_items:
        raise ValueError("No valid edits provided.")

    originals = {path: path.read_text(encoding="utf-8") for path in files}
    working = dict(originals)
    applied: list[dict] = []
    missing: list[str] = []

    for items in pending_reorder_items:
        found = False
        needle = f'{items[0][0]}="{items[0][1]}"'
        for path, content in working.items():
            if needle not in content and f"{items[0][0]}='{items[0][1]}'" not in content:
                continue
            next_content, ok = _reorder_items(content, items)
            if ok:
                working[path] = next_content
                applied.append({
                    "kind": "reorder_items",
                    "count": len(items),
                    "file": path.relative_to(TEMPLATE_ROOT).as_posix(),
                })
                found = True
                break
            if all(_extract_by_attr(content, attr, value) for attr, value in items):
                applied.append({
                    "kind": "reorder_items",
                    "count": len(items),
                    "file": path.relative_to(TEMPLATE_ROOT).as_posix(),
                    "unchanged": True,
                })
                found = True
                break
        if not found:
            missing.append("reorder_items:" + ",".join(value for _, value in items[:3]))

    for group, order in pending_reorder:
        found = False
        for path, content in working.items():
            marker = f'data-site-block="{group}:'
            if marker not in content and f"data-site-block='{group}:" not in content:
                continue
            next_content, ok = _reorder_blocks(content, group, order)
            if ok:
                working[path] = next_content
                applied.append({
                    "kind": "reorder",
                    "group": group,
                    "order": order,
                    "file": path.relative_to(TEMPLATE_ROOT).as_posix(),
                })
                found = True
                break
            # order already matches: treat as applied no-op success
            if all(_extract_block(content, group, key) for key in order):
                applied.append({
                    "kind": "reorder",
                    "group": group,
                    "order": order,
                    "file": path.relative_to(TEMPLATE_ROOT).as_posix(),
                    "unchanged": True,
                })
                found = True
                break
        if not found:
            missing.append(f"reorder:{group}")

    for key, value, kind in pending_text:
        found = False
        for path, content in working.items():
            if f'data-site-edit="{key}"' not in content and f"data-site-edit='{key}'" not in content:
                continue
            if kind == "src":
                next_content, ok = _replace_img_src(content, key, value)
            else:
                next_content, ok = _replace_element_inner(content, key, value)
            if ok:
                working[path] = next_content
                applied.append({
                    "key": key,
                    "kind": kind,
                    "file": path.relative_to(TEMPLATE_ROOT).as_posix(),
                })
                found = True
                break
        if not found:
            missing.append(key)

    if missing:
        raise ValueError("Could not find editable regions: " + ", ".join(missing))

    for path, content in working.items():
        if content != originals[path]:
            path.write_text(content, encoding="utf-8")

    changed = sum(1 for item in applied if not item.get("unchanged"))
    return {"ok": True, "applied": applied, "count": changed}
