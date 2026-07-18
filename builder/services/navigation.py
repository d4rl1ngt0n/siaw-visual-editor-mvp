from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

SCRIPT_BLOCK_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.I | re.S)
SCRIPT_SRC_RE = re.compile(r"\bsrc\s*=\s*(['\"])(.*?)\1", re.I | re.S)
TAG_RE = re.compile(r"</?([A-Za-z][\w:-]*)\b[^>]*>", re.S)
CLICKABLE_RE = re.compile(r"<(a|button)\b([^>]*)>([\s\S]*?)</\1\s*>", re.I)
ATTR_RE = re.compile(r"([:\w-]+)\s*=\s*(['\"])(.*?)\2", re.S)
NAV_ASSIGNMENT_RE = re.compile(r"\b(?:const|let|var)\s+(NAV|navItems|navigationItems|menuItems)\s*=\s*\[", re.I)
SAFE_ROUTE_RE = re.compile(r"^[A-Za-z0-9_:/#?&.=-]{1,240}$")


def _strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _attrs(text: str) -> dict[str, str]:
    return {name.lower(): html.unescape(value) for name, _quote, value in ATTR_RE.findall(text)}


def _balanced_end(text: str, opening: int, open_char: str, close_char: str) -> int | None:
    depth = 0
    quote = ""
    escaped = False
    line_comment = False
    block_comment = False
    template_expr_depth = 0
    index = opening
    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and nxt == "/":
                block_comment = False
                index += 2
                continue
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif quote == "`" and char == "$" and nxt == "{":
                template_expr_depth += 1
                index += 2
                continue
            elif quote == "`" and template_expr_depth and char == "}":
                template_expr_depth -= 1
            elif char == quote and template_expr_depth == 0:
                quote = ""
            index += 1
            continue
        if char == "/" and nxt == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and nxt == "*":
            block_comment = True
            index += 2
            continue
        if char in "'\"`":
            quote = char
            index += 1
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _split_top_level_objects(array_text: str) -> list[str]:
    result: list[str] = []
    index = 0
    while index < len(array_text):
        if array_text[index] == "{":
            end = _balanced_end(array_text, index, "{", "}")
            if end is None:
                break
            result.append(array_text[index : end + 1])
            index = end + 1
        else:
            index += 1
    return result


def _js_string(raw: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*:\s*(['\"])(.*?)\1", raw, re.S)
    if not match:
        return ""
    value = match.group(2)
    try:
        return bytes(value, "utf-8").decode("unicode_escape") if "\\" in value else value
    except UnicodeDecodeError:
        return value


def _js_bool(raw: str, name: str) -> bool:
    match = re.search(rf"\b{re.escape(name)}\s*:\s*(true|false)", raw, re.I)
    return bool(match and match.group(1).lower() == "true")


def _replace_js_string(raw: str, name: str, value: str) -> str:
    encoded = json.dumps(value, ensure_ascii=False)
    pattern = re.compile(rf"(\b{re.escape(name)}\s*:\s*)(['\"])(.*?)\2", re.S)
    if pattern.search(raw):
        return pattern.sub(lambda match: match.group(1) + encoded, raw, count=1)
    return raw[:-1].rstrip() + f", {name}: {encoded}" + "}"


def _replace_js_bool(raw: str, name: str, value: bool) -> str:
    pattern = re.compile(rf"(\b{re.escape(name)}\s*:\s*)(true|false)", re.I)
    if pattern.search(raw):
        return pattern.sub(lambda match: match.group(1) + ("true" if value else "false"), raw, count=1)
    if value:
        return raw[:-1].rstrip() + f", {name}: true" + "}"
    return raw


def _local_script_texts(source_root: Path, entry_file: str, html_text: str) -> list[tuple[str, str, str]]:
    """Return (source kind, relative path, text); inline path is an ordinal string."""
    result: list[tuple[str, str, str]] = []
    inline_index = 0
    for attrs_text, body in SCRIPT_BLOCK_RE.findall(html_text):
        source_match = SCRIPT_SRC_RE.search(attrs_text)
        if not source_match:
            result.append(("inline", str(inline_index), body))
            inline_index += 1
            continue
        src = source_match.group(2).strip()
        parsed = urlsplit(src)
        if parsed.scheme or parsed.netloc or src.startswith("//"):
            continue
        relative = PurePosixPath(entry_file).parent / PurePosixPath(parsed.path.lstrip("/"))
        target = (source_root / Path(*relative.parts)).resolve()
        try:
            target.relative_to(source_root.resolve())
        except ValueError:
            continue
        if target.is_file():
            relative_path = target.resolve().relative_to(source_root.resolve()).as_posix()
            result.append(("external", relative_path, target.read_text(encoding="utf-8", errors="replace")))
    return result


def _load_js_navigation(source_root: Path, entry_file: str, html_text: str) -> dict[str, Any] | None:
    for source_kind, source_file, script_text in _local_script_texts(source_root, entry_file, html_text):
        match = NAV_ASSIGNMENT_RE.search(script_text)
        if not match:
            continue
        opening = match.end() - 1
        closing = _balanced_end(script_text, opening, "[", "]")
        if closing is None:
            continue
        raw_objects = _split_top_level_objects(script_text[opening + 1 : closing])
        items: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_objects):
            item_id = _js_string(raw, "id")
            label = _js_string(raw, "label") or _js_string(raw, "title")
            if not item_id or not label:
                continue
            items.append({
                "key": item_id,
                "label": label,
                "destination": item_id,
                "type": _js_string(raw, "type") or "page",
                "cta": _js_bool(raw, "cta"),
                "visible": True,
                "index": index,
            })
        if items:
            return {
                "available": True,
                "mode": "javascript-array",
                "title": "JavaScript navigation",
                "description": "This menu is generated from a JavaScript data array. Labels, order and visibility can be changed safely.",
                "sourceKind": source_kind,
                "sourceFile": source_file,
                "variableName": match.group(1),
                "supportsStructure": True,
                "supportsAdd": False,
                "items": items,
            }
    return None


def _element_by_id(html_text: str, element_id: str) -> tuple[int, int, str] | None:
    open_match = re.search(
        rf"<([A-Za-z][\w:-]*)\b(?=[^>]*\bid\s*=\s*(['\"]){re.escape(element_id)}\2)[^>]*>",
        html_text,
        re.I | re.S,
    )
    if not open_match:
        return None
    tag = open_match.group(1).lower()
    depth = 0
    for token in TAG_RE.finditer(html_text, open_match.start()):
        token_text = token.group(0)
        token_tag = token.group(1).lower()
        if token_tag != tag:
            continue
        if token_text.startswith("</"):
            depth -= 1
            if depth == 0:
                return open_match.start(), token.end(), html_text[open_match.start() : token.end()]
        elif not token_text.rstrip().endswith("/>"):
            depth += 1
    return None


def _nav_blocks(html_text: str) -> list[tuple[int, int, str]]:
    blocks: list[tuple[int, int, str]] = []
    for match in re.finditer(r"<nav\b[^>]*>", html_text, re.I | re.S):
        depth = 0
        for token in TAG_RE.finditer(html_text, match.start()):
            token_text = token.group(0)
            if token.group(1).lower() != "nav":
                continue
            if token_text.startswith("</"):
                depth -= 1
                if depth == 0:
                    blocks.append((match.start(), token.end(), html_text[match.start() : token.end()]))
                    break
            elif not token_text.rstrip().endswith("/>"):
                depth += 1
    return blocks


def _item_label(inner: str) -> str:
    span_matches = re.findall(r"<span\b[^>]*>([\s\S]*?)</span\s*>", inner, re.I)
    if span_matches:
        candidate = _strip_tags(span_matches[-1])
        if candidate:
            return candidate
    return _strip_tags(inner)


def _static_items(block: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, match in enumerate(CLICKABLE_RE.finditer(block)):
        tag = match.group(1).lower()
        attrs = _attrs(match.group(2))
        classes = attrs.get("class", "").split()
        label = _item_label(match.group(3))
        if not label:
            continue
        if "brand" in classes or "logo" in classes or attrs.get("aria-label", "").lower().endswith("home") and "img" in match.group(3).lower():
            continue
        destination_attr = "href" if tag == "a" else next(
            (name for name in ("data-view", "data-goto", "data-go", "data-page", "data-scroll-to", "data-target") if name in attrs),
            "",
        )
        destination = attrs.get(destination_attr, "") if destination_attr else ""
        items.append({
            "key": attrs.get("id") or f"item-{index + 1}",
            "label": label,
            "destination": destination,
            "destinationAttribute": destination_attr,
            "tag": tag,
            "target": attrs.get("target", ""),
            "visible": "display:none" not in attrs.get("style", "").replace(" ", "").lower(),
            "classes": attrs.get("class", ""),
            "index": index,
        })
    return items


def _load_static_navigation(html_text: str) -> dict[str, Any] | None:
    candidates: list[tuple[int, str, str, int]] = []
    nav_links = _element_by_id(html_text, "navLinks")
    if nav_links:
        items = _static_items(nav_links[2])
        if items:
            candidates.append((100 + len(items), "#navLinks", nav_links[2], 0))

    for block_index, (_start, _end, block) in enumerate(_nav_blocks(html_text)):
        items = _static_items(block)
        if not items:
            continue
        open_tag = block.split(">", 1)[0] + ">"
        attrs = _attrs(open_tag)
        descriptor = " ".join((attrs.get("id", ""), attrs.get("class", ""), attrs.get("aria-label", ""))).lower()
        score = len(items) * 3
        if any(word in descriptor for word in ("main", "haupt", "primary", "desktop", "navigation", "navbar")):
            score += 30
        if any(word in descriptor for word in ("footer", "quick", "dock", "social")):
            score -= 20
        selector = f"#{attrs['id']}" if attrs.get("id") else "nav"
        candidates.append((score, selector, block, block_index))

    if not candidates:
        return None
    _score, selector, block, selector_index = max(candidates, key=lambda item: item[0])
    items = _static_items(block)
    complex_menu = len(items) > 15 or any(token in block.lower() for token in ("dropdown", "submenu", "mega-menu", "<details", "aria-haspopup"))
    if selector == "nav" and block.lower().count("<ul") > 1:
        complex_menu = True
    return {
        "available": True,
        "mode": "static-html",
        "title": "Website navigation",
        "description": "This menu exists directly in the HTML and can be changed visually.",
        "containerSelector": selector,
        "containerIndex": selector_index,
        "supportsStructure": not complex_menu,
        "supportsAdd": not complex_menu,
        "complex": complex_menu,
        "items": items,
    }


def load_smart_navigation(source_root: Path, entry_file: str, html_text: str) -> dict[str, Any]:
    # A generated empty primary navigation should be handled from its JS array.
    js_navigation = _load_js_navigation(source_root, entry_file, html_text)
    static_navigation = _load_static_navigation(html_text)
    if js_navigation and (not static_navigation or len(static_navigation.get("items", [])) <= 1):
        return js_navigation
    if static_navigation:
        return static_navigation
    if js_navigation:
        return js_navigation
    return {"available": False, "mode": "none", "items": []}


def _clean_navigation_payload(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or value.get("mode") != "javascript-array":
        return []
    raw_items = value.get("items")
    if not isinstance(raw_items, list):
        return []
    result: list[dict[str, Any]] = []
    used: set[str] = set()
    for raw in raw_items[:40]:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key", "")).strip()
        label = str(raw.get("label", "")).strip()[:160]
        destination = str(raw.get("destination", key)).strip()[:240]
        if not key or key in used or not label or not SAFE_ROUTE_RE.fullmatch(destination or key):
            continue
        used.add(key)
        result.append({
            "key": key,
            "label": label,
            "destination": destination or key,
            "type": str(raw.get("type", "page")).strip()[:40] or "page",
            "cta": bool(raw.get("cta")),
            "visible": raw.get("visible") is not False,
            "isNew": bool(raw.get("isNew")),
        })
    return result


def _rewrite_nav_array(script_text: str, variable_name: str, payload: dict[str, Any]) -> tuple[str, int]:
    pattern = re.compile(rf"\b(?:const|let|var)\s+{re.escape(variable_name)}\s*=\s*\[", re.I)
    match = pattern.search(script_text)
    if not match:
        return script_text, 0
    opening = match.end() - 1
    closing = _balanced_end(script_text, opening, "[", "]")
    if closing is None:
        return script_text, 0
    raw_objects = _split_top_level_objects(script_text[opening + 1 : closing])
    originals = {_js_string(raw, "id"): raw for raw in raw_objects if _js_string(raw, "id")}
    items = _clean_navigation_payload(payload)
    rendered: list[str] = []
    for item in items:
        if not item["visible"]:
            continue
        raw = originals.get(item["key"])
        if raw:
            raw = _replace_js_string(raw, "label", item["label"])
            raw = _replace_js_bool(raw, "cta", item["cta"])
            rendered.append(raw)
        else:
            rendered.append(
                "{" +
                f"id:{json.dumps(item['destination'], ensure_ascii=False)}," +
                f"label:{json.dumps(item['label'], ensure_ascii=False)}," +
                f"type:{json.dumps(item['type'], ensure_ascii=False)}," +
                ("cta:true," if item["cta"] else "") +
                "items:[]}" 
            )
    replacement = "[\n  " + ",\n  ".join(rendered) + "\n]"
    return script_text[:opening] + replacement + script_text[closing + 1 :], len(rendered)


def apply_javascript_navigation(
    source_root: Path,
    html_text: str,
    payload: Any,
    *,
    source_overrides: dict[Path, str] | None = None,
) -> tuple[str, dict[Path, str], list[str]]:
    if not isinstance(payload, dict) or payload.get("mode") != "javascript-array":
        return html_text, {}, []
    variable = str(payload.get("variableName", "NAV")).strip() or "NAV"
    source_kind = str(payload.get("sourceKind", "inline"))
    source_file = str(payload.get("sourceFile", ""))
    if source_kind == "external" and source_file:
        target = (source_root / Path(*PurePosixPath(source_file).parts)).resolve()
        try:
            target.relative_to(source_root.resolve())
        except ValueError:
            return html_text, {}, []
        if not target.is_file():
            return html_text, {}, []
        original = (source_overrides or {}).get(target)
        if original is None:
            original = target.read_text(encoding="utf-8", errors="replace")
        updated, count = _rewrite_nav_array(original, variable, payload)
        if count and updated != original:
            return html_text, {target: updated}, [f"Navigation manager ({count} items)"]
        return html_text, {}, []

    inline_ordinal = int(source_file) if source_file.isdigit() else 0
    current = 0
    synced_count = 0

    def replace_script(match: re.Match[str]) -> str:
        nonlocal current, synced_count
        attrs_text, body = match.group(1), match.group(2)
        if SCRIPT_SRC_RE.search(attrs_text):
            return match.group(0)
        if current != inline_ordinal:
            current += 1
            return match.group(0)
        current += 1
        updated, count = _rewrite_nav_array(body, variable, payload)
        synced_count = count
        return f"<script{attrs_text}>{updated}</script>"

    updated_html = SCRIPT_BLOCK_RE.sub(replace_script, html_text)
    synced = [f"Navigation manager ({synced_count} items)"] if synced_count and updated_html != html_text else []
    return updated_html, {}, synced
