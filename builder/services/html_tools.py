from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any

BODY_RE = re.compile(r"(<body\b[^>]*>)(.*?)(</body\s*>)", re.IGNORECASE | re.DOTALL)
SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.IGNORECASE | re.DOTALL)
OVERRIDE_LINK_RE = re.compile(
    r"<link\b[^>]*data-siaw-editor=[\"']true[\"'][^>]*>",
    re.IGNORECASE,
)
HEAD_CLOSE_RE = re.compile(r"</head\s*>", re.IGNORECASE)
HTML_OPEN_RE = re.compile(r"<html\b([^>]*)>", re.IGNORECASE | re.DOTALL)
BODY_OPEN_RE = re.compile(r"<body\b([^>]*)>", re.IGNORECASE | re.DOTALL)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif"}
SERVICE_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

LAZY_MEDIA_TAG_RE = re.compile(r"<(img|source|video)\b[^>]*>", re.IGNORECASE | re.DOTALL)
ATTRIBUTE_RE = re.compile(r"([:\w-]+)\s*=\s*([\"\'])(.*?)\2", re.DOTALL)


def hydrate_lazy_media(html_fragment: str) -> tuple[str, int]:
    """Make common lazy-loaded media visible in the script-free editor.

    The original data-* attributes are preserved so the exported website can still
    use its own lazy-loading JavaScript. Only missing or placeholder presentation
    attributes are supplemented.
    """
    hydrated = 0

    def replace_tag(match: re.Match[str]) -> str:
        nonlocal hydrated
        tag = match.group(0)
        attrs = {name.lower(): value for name, _quote, value in ATTRIBUTE_RE.findall(tag)}
        changes: list[tuple[str, str]] = []

        source = next((attrs.get(name) for name in ("data-src", "data-lazy-src", "data-original", "data-image") if attrs.get(name)), None)
        current_src = attrs.get("src", "").strip()
        placeholder = (
            not current_src
            or current_src in {"#", "about:blank"}
            or current_src.startswith("data:image/gif;base64,R0lGOD")
            or current_src.startswith("data:image/svg+xml,%3Csvg") and "width%3D%271%27" in current_src
        )
        if source and placeholder:
            changes.append(("src", source))

        data_srcset = attrs.get("data-srcset")
        if data_srcset and not attrs.get("srcset"):
            changes.append(("srcset", data_srcset))

        data_poster = attrs.get("data-poster")
        if data_poster and not attrs.get("poster"):
            changes.append(("poster", data_poster))

        if not changes:
            return tag

        updated = tag
        for name, value in changes:
            existing = re.compile(rf"\b{re.escape(name)}\s*=\s*([\"\']).*?\1", re.IGNORECASE | re.DOTALL)
            escaped_value = html.escape(value, quote=True)
            if existing.search(updated):
                updated = existing.sub(f'{name}="{escaped_value}"', updated, count=1)
            else:
                updated = updated[:-1] + f' {name}="{escaped_value}">'
        hydrated += 1
        return updated

    return LAZY_MEDIA_TAG_RE.sub(replace_tag, html_fragment), hydrated


class _AttributeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.attributes: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs):
        if self.attributes:
            return
        for key, value in attrs:
            if key:
                self.attributes[str(key)] = "" if value is None else str(value)


@dataclass(frozen=True)
class DocumentContext:
    inline_styles: list[str]
    html_attributes: dict[str, str]
    body_attributes: dict[str, str]


@dataclass(frozen=True)
class ServiceCardData:
    key: str
    title: str
    card_description: str
    button_text: str
    image: str
    detail_summary: str
    detail_section_one_heading: str
    detail_section_one_text: str
    detail_section_two_heading: str
    detail_section_two_bullets: list[str]
    detail_section_three_heading: str
    detail_section_three_text: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "cardDescription": self.card_description,
            "buttonText": self.button_text,
            "image": self.image,
            "detailSummary": self.detail_summary,
            "detailSectionOneHeading": self.detail_section_one_heading,
            "detailSectionOneText": self.detail_section_one_text,
            "detailSectionTwoHeading": self.detail_section_two_heading,
            "detailSectionTwoBullets": self.detail_section_two_bullets,
            "detailSectionThreeHeading": self.detail_section_three_heading,
            "detailSectionThreeText": self.detail_section_three_text,
        }


def _parse_tag_attributes(tag_name: str, attributes_text: str) -> dict[str, str]:
    parser = _AttributeParser()
    parser.feed(f"<{tag_name}{attributes_text}>")
    return parser.attributes


def extract_document_context(html_text: str) -> DocumentContext:
    html_match = HTML_OPEN_RE.search(html_text)
    body_match = BODY_OPEN_RE.search(html_text)
    return DocumentContext(
        inline_styles=[style.strip() for style in STYLE_RE.findall(html_text) if style.strip()],
        html_attributes=_parse_tag_attributes("html", html_match.group(1)) if html_match else {},
        body_attributes=_parse_tag_attributes("body", body_match.group(1)) if body_match else {},
    )


def extract_editable_body(html_text: str) -> tuple[str, list[str]]:
    match = BODY_RE.search(html_text)
    if not match:
        body = html_text
    else:
        body = match.group(2)
    scripts = SCRIPT_RE.findall(body)
    editable = SCRIPT_RE.sub("", body)
    return editable.strip(), scripts


def strip_script_tags(html_fragment: str) -> str:
    return SCRIPT_RE.sub("", html_fragment)


def ensure_override_link(html_text: str, href: str) -> str:
    link = f'<link rel="stylesheet" href="{href}" data-siaw-editor="true">'
    if OVERRIDE_LINK_RE.search(html_text):
        return OVERRIDE_LINK_RE.sub(link, html_text, count=1)
    match = HEAD_CLOSE_RE.search(html_text)
    if match:
        return html_text[: match.start()] + f"  {link}\n" + html_text[match.start() :]
    return link + "\n" + html_text


def merge_editor_body(current_html: str, edited_body: str, override_href: str) -> str:
    edited_body = strip_script_tags(edited_body).strip()
    match = BODY_RE.search(current_html)
    if not match:
        merged = edited_body
    else:
        current_inner = match.group(2)
        scripts = SCRIPT_RE.findall(current_inner)
        scripts_html = "\n".join(scripts)
        replacement = edited_body
        if scripts_html:
            replacement += "\n\n" + scripts_html
        merged = current_html[: match.start(2)] + "\n" + replacement + "\n" + current_html[match.end(2) :]
    return ensure_override_link(merged, override_href)


def editor_override_path(entry_file: str) -> tuple[Path, str]:
    entry = PurePosixPath(entry_file)
    relative_href = "siaw-editor-overrides.css"
    target = Path(*entry.parent.parts) / relative_href if entry.parent.parts else Path(relative_href)
    return target, relative_href


def list_image_assets(source_root: Path) -> list[str]:
    assets: list[str] = []
    for path in source_root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            assets.append(path.relative_to(source_root).as_posix())
    return sorted(assets)


def _normalize_string(value: str, project_file_prefix: str, origin: str, entry_dir: str) -> str:
    prefixes = [project_file_prefix]
    if origin:
        prefixes.insert(0, origin.rstrip("/") + project_file_prefix)

    result = value
    for prefix in prefixes:
        if prefix and prefix in result:
            def replace_url(match):
                file_path = match.group(1)
                base = PurePosixPath(entry_dir or ".")
                target = PurePosixPath(file_path)
                import posixpath

                return posixpath.relpath(target.as_posix(), base.as_posix())

            escaped = re.escape(prefix)
            result = re.sub(escaped + r"([^\s\"'\)<>]+)", replace_url, result)
    return result


def normalize_project_urls(
    value: Any,
    *,
    project_file_prefix: str,
    origin: str,
    entry_dir: str,
) -> Any:
    if isinstance(value, str):
        return _normalize_string(value, project_file_prefix, origin, entry_dir)
    if isinstance(value, list):
        return [
            normalize_project_urls(
                item,
                project_file_prefix=project_file_prefix,
                origin=origin,
                entry_dir=entry_dir,
            )
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: normalize_project_urls(
                item,
                project_file_prefix=project_file_prefix,
                origin=origin,
                entry_dir=entry_dir,
            )
            for key, item in value.items()
        }
    return value


def _tag_attribute_for_id(html_fragment: str, element_id: str, attribute: str) -> str | None:
    tag_pattern = re.compile(
        rf"<[^>]+(?=[^>]*\bid\s*=\s*[\"']{re.escape(element_id)}[\"'])[^>]*>",
        re.IGNORECASE | re.DOTALL,
    )
    tag_match = tag_pattern.search(html_fragment)
    if not tag_match:
        return None
    attribute_pattern = re.compile(
        rf"\b{re.escape(attribute)}\s*=\s*[\"']([^\"']+)[\"']",
        re.IGNORECASE,
    )
    attribute_match = attribute_pattern.search(tag_match.group(0))
    return attribute_match.group(1).strip() if attribute_match else None


def _replace_js_property_after_anchor(
    script_text: str,
    *,
    anchor_pattern: str,
    property_name: str,
    value: str,
) -> tuple[str, bool]:
    pattern = re.compile(
        rf"({anchor_pattern}[\s\S]*?\b{re.escape(property_name)}\s*:\s*[\"'])([^\"']*)([\"'])",
        re.MULTILINE,
    )
    safe_value = json.dumps(value, ensure_ascii=False)[1:-1]
    updated, count = pattern.subn(rf"\g<1>{safe_value}\g<3>", script_text, count=1)
    return updated, bool(count)


def _find_balanced_brace(text: str, opening_index: int) -> int | None:
    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = opening_index

    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if line_comment:
            if char == "\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and next_char == "/":
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
            elif char == quote:
                quote = None
            index += 1
            continue

        if char == "/" and next_char == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            block_comment = True
            index += 2
            continue
        if char in {'"', "'", "`"}:
            quote = char
            index += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _service_object_bounds(script_text: str) -> tuple[int, int] | None:
    match = re.search(r"\bconst\s+serviceExpandedContent\s*=\s*\{", script_text)
    if not match:
        return None
    opening = script_text.find("{", match.start())
    closing = _find_balanced_brace(script_text, opening)
    if closing is None:
        return None
    return opening, closing


def _decode_js_string(raw: str) -> str:
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw.replace(r"\'", "'").replace(r'\"', '"').replace(r"\\", "\\")


def _js_property(object_text: str, name: str) -> str:
    string_match = re.search(
        rf"\b{re.escape(name)}\s*:\s*([\"'])(.*?)(?<!\\)\1",
        object_text,
        re.DOTALL,
    )
    if string_match:
        return _decode_js_string(string_match.group(2))
    template_match = re.search(
        rf"\b{re.escape(name)}\s*:\s*`([\s\S]*?)(?<!\\)`",
        object_text,
    )
    return template_match.group(1) if template_match else ""


def _parse_service_objects(script_text: str) -> dict[str, dict[str, str]]:
    bounds = _service_object_bounds(script_text)
    if not bounds:
        return {}
    opening, closing = bounds
    content = script_text[opening + 1 : closing]
    result: dict[str, dict[str, str]] = {}
    index = 0
    depth = 0
    quote: str | None = None
    escaped = False

    while index < len(content):
        char = content[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'", "`"}:
            quote = char
            index += 1
            continue
        if char == "{":
            depth += 1
            index += 1
            continue
        if char == "}":
            depth = max(0, depth - 1)
            index += 1
            continue
        if depth == 0:
            match = re.match(r"\s*([A-Za-z_$][\w$-]*)\s*:\s*\{", content[index:])
            if match:
                key = match.group(1)
                object_open = index + match.end() - 1
                object_close = _find_balanced_brace(content, object_open)
                if object_close is None:
                    break
                object_text = content[object_open + 1 : object_close]
                result[key] = {
                    "title": _js_property(object_text, "title"),
                    "image": _js_property(object_text, "image"),
                    "summary": _js_property(object_text, "summary"),
                    "details": _js_property(object_text, "details"),
                }
                index = object_close + 1
                continue
        index += 1
    return result


def _strip_tags(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).strip()


def _details_sections(details_html: str) -> list[dict[str, Any]]:
    sections = re.findall(
        r"<div\b[^>]*class=[\"'][^\"']*modal-detail-section[^\"']*[\"'][^>]*>([\s\S]*?)</div>",
        details_html,
        re.IGNORECASE,
    )
    parsed: list[dict[str, Any]] = []
    for section in sections:
        heading_match = re.search(r"<h4\b[^>]*>([\s\S]*?)</h4>", section, re.IGNORECASE)
        bullets = [
            _strip_tags(item)
            for item in re.findall(r"<li\b[^>]*>([\s\S]*?)</li>", section, re.IGNORECASE)
            if _strip_tags(item)
        ]
        paragraph_match = re.search(r"<p\b[^>]*>([\s\S]*?)</p>", section, re.IGNORECASE)
        parsed.append(
            {
                "heading": _strip_tags(heading_match.group(1)) if heading_match else "",
                "text": _strip_tags(paragraph_match.group(1)) if paragraph_match else "",
                "bullets": bullets,
            }
        )
    return parsed


def _attribute(tag_text: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*([\"'])(.*?)\1", tag_text, re.IGNORECASE | re.DOTALL)
    return html.unescape(match.group(2)).strip() if match else ""


def _service_cards_from_html(html_text: str) -> list[dict[str, str]]:
    cards = re.findall(
        r"(<article\b(?=[^>]*\bclass\s*=\s*[\"'][^\"']*\bservice-card\b[^\"']*[\"'])"
        r"(?=[^>]*\bdata-service\s*=\s*[\"'][^\"']+[\"'])[^>]*>[\s\S]*?</article\s*>)",
        html_text,
        re.IGNORECASE,
    )
    result: list[dict[str, str]] = []
    for card in cards:
        open_tag = card.split(">", 1)[0] + ">"
        key = _attribute(open_tag, "data-service")
        image_tag_match = re.search(r"<img\b[^>]*>", card, re.IGNORECASE)
        title_match = re.search(r"<h3\b[^>]*>([\s\S]*?)</h3>", card, re.IGNORECASE)
        paragraph_match = re.search(r"<p\b[^>]*>([\s\S]*?)</p>", card, re.IGNORECASE)
        link_match = re.search(
            r"<[^>]+\bclass\s*=\s*[\"'][^\"']*\bservice-detail-link\b[^\"']*[\"'][^>]*>([\s\S]*?)</[^>]+>",
            card,
            re.IGNORECASE,
        )
        result.append(
            {
                "key": key,
                "title": _strip_tags(title_match.group(1)) if title_match else "",
                "cardDescription": _strip_tags(paragraph_match.group(1)) if paragraph_match else "",
                "buttonText": _strip_tags(link_match.group(1)) if link_match else "View service details →",
                "image": _attribute(image_tag_match.group(0), "src") if image_tag_match else "",
            }
        )
    return result


def load_smart_services(source_root: Path, html_text: str) -> dict[str, Any]:
    cards = _service_cards_from_html(html_text)
    script_path = source_root / "script.js"
    if not cards or not script_path.is_file():
        return {"available": False, "services": []}

    script_text = script_path.read_text(encoding="utf-8", errors="replace")
    expanded = _parse_service_objects(script_text)
    services: list[dict[str, Any]] = []
    for card in cards:
        detail = expanded.get(card["key"], {})
        sections = _details_sections(detail.get("details", ""))
        while len(sections) < 3:
            sections.append({"heading": "", "text": "", "bullets": []})
        services.append(
            ServiceCardData(
                key=card["key"],
                title=card["title"] or detail.get("title", ""),
                card_description=card["cardDescription"],
                button_text=card["buttonText"],
                image=card["image"] or detail.get("image", ""),
                detail_summary=detail.get("summary", ""),
                detail_section_one_heading=sections[0]["heading"],
                detail_section_one_text=sections[0]["text"],
                detail_section_two_heading=sections[1]["heading"],
                detail_section_two_bullets=sections[1]["bullets"],
                detail_section_three_heading=sections[2]["heading"],
                detail_section_three_text=sections[2]["text"],
            ).as_dict()
        )
    return {"available": True, "services": services}


def _clean_service_payload(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    used: set[str] = set()
    for raw in value[:50]:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key", "")).strip().lower()
        if not SERVICE_KEY_RE.fullmatch(key) or key in used:
            continue
        used.add(key)
        bullets_raw = raw.get("detailSectionTwoBullets", [])
        if isinstance(bullets_raw, str):
            bullets = [line.strip() for line in bullets_raw.splitlines() if line.strip()]
        elif isinstance(bullets_raw, list):
            bullets = [str(line).strip() for line in bullets_raw if str(line).strip()]
        else:
            bullets = []
        result.append(
            {
                "key": key,
                "title": str(raw.get("title", "")).strip()[:200],
                "cardDescription": str(raw.get("cardDescription", "")).strip()[:1000],
                "buttonText": str(raw.get("buttonText", "View service details →")).strip()[:120],
                "image": str(raw.get("image", "")).strip()[:1000],
                "detailSummary": str(raw.get("detailSummary", "")).strip()[:2000],
                "detailSectionOneHeading": str(raw.get("detailSectionOneHeading", "What we help with")).strip()[:200],
                "detailSectionOneText": str(raw.get("detailSectionOneText", "")).strip()[:5000],
                "detailSectionTwoHeading": str(raw.get("detailSectionTwoHeading", "Examples of support")).strip()[:200],
                "detailSectionTwoBullets": bullets[:30],
                "detailSectionThreeHeading": str(raw.get("detailSectionThreeHeading", "What you get")).strip()[:200],
                "detailSectionThreeText": str(raw.get("detailSectionThreeText", "")).strip()[:5000],
            }
        )
    return result


def _escape_template_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def _service_details_html(service: dict[str, Any]) -> str:
    bullets = "\n".join(f"            <li>{html.escape(item)}</li>" for item in service["detailSectionTwoBullets"])
    return f"""
      <div class=\"modal-detail-grid\">
        <div class=\"modal-detail-section\">
          <h4>{html.escape(service['detailSectionOneHeading'])}</h4>
          <p>{html.escape(service['detailSectionOneText'])}</p>
        </div>

        <div class=\"modal-detail-section\">
          <h4>{html.escape(service['detailSectionTwoHeading'])}</h4>
          <ul>
{bullets}
          </ul>
        </div>

        <div class=\"modal-detail-section\">
          <h4>{html.escape(service['detailSectionThreeHeading'])}</h4>
          <p>{html.escape(service['detailSectionThreeText'])}</p>
        </div>
      </div>
    """.rstrip()


def _render_service_object(services: list[dict[str, Any]]) -> str:
    objects: list[str] = []
    for service in services:
        title = json.dumps(service["title"], ensure_ascii=False)
        image_value = json.dumps(service["image"], ensure_ascii=False)
        summary = json.dumps(service["detailSummary"], ensure_ascii=False)
        details = _escape_template_literal(_service_details_html(service))
        objects.append(
            f"  {service['key']}: {{\n"
            f"    title: {title},\n"
            f"    image: {image_value},\n"
            f"    summary: {summary},\n"
            f"    details: `\n{details}\n    `\n"
            f"  }}"
        )
    return "{\n" + ",\n\n".join(objects) + "\n}"


def _replace_service_object(script_text: str, services_payload: Any) -> tuple[str, int]:
    services = _clean_service_payload(services_payload)
    if not services:
        return script_text, 0
    bounds = _service_object_bounds(script_text)
    if not bounds:
        return script_text, 0
    opening, closing = bounds
    rendered = _render_service_object(services)
    return script_text[:opening] + rendered + script_text[closing + 1 :], len(services)


def build_dynamic_script_updates(
    source_root: Path,
    edited_html: str,
    smart_services: Any = None,
) -> tuple[dict[Path, str], list[str]]:
    """Synchronise supported JavaScript-driven fields with visual edits."""
    script_path = source_root / "script.js"
    if not script_path.is_file():
        return {}, []

    script_text = script_path.read_text(encoding="utf-8", errors="replace")
    updated_text = script_text
    synced: list[str] = []

    updated_text, service_count = _replace_service_object(updated_text, smart_services)
    if service_count:
        synced.append(f"Services manager ({service_count} services)")

    detail_image = _tag_attribute_for_id(edited_html, "detailImage", "src")
    if detail_image:
        updated_text, changed = _replace_js_property_after_anchor(
            updated_text,
            anchor_pattern=r"\bid\s*:\s*[\"']agrisense-probe[\"']\s*,",
            property_name="image",
            value=detail_image,
        )
        if changed:
            synced.append("AgriSense product image")

    spotlight_image = _tag_attribute_for_id(edited_html, "spotlightImage", "src")
    if spotlight_image:
        updated_text, changed = _replace_js_property_after_anchor(
            updated_text,
            anchor_pattern=r"\bagrisense\s*:\s*\{",
            property_name="image",
            value=spotlight_image,
        )
        if changed:
            synced.append("AgriSense project spotlight image")

    if updated_text == script_text:
        return {}, synced
    return {script_path: updated_text}, synced


def load_project_data(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
