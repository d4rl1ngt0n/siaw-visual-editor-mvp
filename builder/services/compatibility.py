from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import unquote, urlsplit

from .support_profile import support_profile_payload

STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.IGNORECASE | re.DOTALL)
SCRIPT_BLOCK_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)
GET_ID_RE = re.compile(r"getElementById\(\s*['\"]([^'\"]+)['\"]\s*\)")
QUERY_ID_RE = re.compile(r"querySelector(?:All)?\(\s*['\"]#([A-Za-z][\w:.-]*)['\"]\s*\)")
QUERY_CLASS_RE = re.compile(r"querySelector(?:All)?\(\s*['\"]\.([A-Za-z_][\w-]*)['\"]\s*\)")
DYNAMIC_OPERATION_RE = re.compile(
    r"\b(?:innerHTML|outerHTML|insertAdjacentHTML|appendChild|prepend|replaceChildren|createElement|cloneNode)\b"
)
LOCAL_STORAGE_RE = re.compile(r"\b(?:localStorage|sessionStorage)\b")
ARRAY_DATA_RE = re.compile(r"\b(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*\[")
HASH_ROUTE_RE = re.compile(r"""['"]#/[^'"]+['"]|location\.hash|hashchange""")
MODULE_SCRIPT_RE = re.compile(r"""<script\b[^>]*\btype\s*=\s*['"]module['"]""", re.I)
SPA_MOUNT_IDS = {"main", "app", "root", "app-root", "__next", "outlet", "siaw-root"}
BUILD_OUTPUT_DIRS = {"dist", "build", "out", "output"}
REVEAL_NAME_RE = re.compile(r"(?:reveal|animate|animation|fade|slide|scroll|appear|inview|in-view|aos)", re.I)
HIDDEN_DECL_RE = re.compile(
    r"(?:opacity\s*:\s*0(?:\D|$)|visibility\s*:\s*hidden|transform\s*:\s*(?:translate|scale))",
    re.I,
)

MEDIA_TAGS = {"img", "source", "video", "audio", "iframe", "object", "embed"}
RESOURCE_ATTRIBUTES = {"src", "href", "poster", "data", "srcset", "data-src", "data-srcset", "data-original", "data-lazy-src", "data-poster"}
EXTERNAL_SCHEMES = {"http", "https", "mailto", "tel", "data", "blob", "javascript"}
RUNTIME_CONTAINER_TAGS = {"div", "section", "main", "aside", "article", "nav", "header", "footer", "ul", "ol", "tbody", "table", "span"}


@dataclass
class ElementInfo:
    tag: str
    attrs: dict[str, str]
    element_id: str
    classes: list[str]
    child_tags: int = 0
    has_text: bool = False

    @property
    def empty(self) -> bool:
        return self.child_tags == 0 and not self.has_text


class CompatibilityHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: dict[str, int] = {}
        self.resources: list[tuple[str, str, str]] = []
        self.lazy_media = 0
        self.srcset = 0
        self.inline_svg = 0
        self.forms = 0
        self.elements_by_id: dict[str, ElementInfo] = {}
        self.elements_by_class: dict[str, list[ElementInfo]] = {}
        self._stack: list[ElementInfo] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        self.tags[tag] = self.tags.get(tag, 0) + 1
        data = {str(key).lower(): "" if value is None else str(value) for key, value in attrs if key}
        if tag == "svg":
            self.inline_svg += 1
        if tag == "form":
            self.forms += 1
        if any(name in data for name in ("data-src", "data-srcset", "data-original", "data-lazy-src", "loading")):
            if any(name in data for name in ("data-src", "data-srcset", "data-original", "data-lazy-src")):
                self.lazy_media += 1
        if "srcset" in data or "data-srcset" in data:
            self.srcset += 1
        for attribute in RESOURCE_ATTRIBUTES:
            value = data.get(attribute)
            if value:
                self.resources.append((tag, attribute, value))

        element = ElementInfo(
            tag=tag,
            attrs=data,
            element_id=data.get("id", ""),
            classes=[item for item in data.get("class", "").split() if item],
        )
        if self._stack:
            self._stack[-1].child_tags += 1
        self._stack.append(element)
        if element.element_id:
            self.elements_by_id[element.element_id] = element
        for class_name in element.classes:
            self.elements_by_class.setdefault(class_name, []).append(element)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        # HTML can be imperfect. Pop until the matching tag is found.
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == tag.lower():
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if data.strip() and self._stack:
            self._stack[-1].has_text = True


def _clean_reference(value: str) -> list[str]:
    result: list[str] = []
    for candidate in value.split(",") if "," in value else [value]:
        candidate = candidate.strip()
        if not candidate:
            continue
        # srcset entries end with density/width descriptors.
        candidate = candidate.split()[0]
        if candidate:
            result.append(candidate)
    return result


def _is_local_reference(value: str) -> bool:
    value = value.strip()
    if not value or value.startswith(("#", "//")):
        return False
    parsed = urlsplit(value)
    return parsed.scheme.lower() not in EXTERNAL_SCHEMES and not parsed.netloc


def _resolve_reference(source_root: Path, entry_file: str, value: str) -> Path | None:
    value = unquote(value.split("?", 1)[0].split("#", 1)[0]).strip()
    if not value or not _is_local_reference(value):
        return None
    if value.startswith("/"):
        relative = PurePosixPath(value.lstrip("/"))
    else:
        relative = PurePosixPath(entry_file).parent / PurePosixPath(value)
    if ".." in relative.parts:
        # Resolve safely and then confirm it stays under source_root.
        target = (source_root / Path(*relative.parts)).resolve()
    else:
        target = (source_root / Path(*relative.parts)).resolve()
    try:
        target.relative_to(source_root.resolve())
    except ValueError:
        return None
    return target


def _script_sources(html_text: str) -> list[str]:
    result: list[str] = []
    for attrs, _body in SCRIPT_BLOCK_RE.findall(html_text):
        match = re.search(r"\bsrc\s*=\s*['\"]([^'\"]+)['\"]", attrs, re.I)
        if match:
            result.append(match.group(1))
    return result


def _stylesheet_sources(html_text: str) -> list[str]:
    result: list[str] = []
    for tag in re.findall(r"<link\b[^>]*>", html_text, re.I | re.S):
        if not re.search(r"\brel\s*=\s*['\"][^'\"]*stylesheet", tag, re.I):
            continue
        match = re.search(r"\bhref\s*=\s*['\"]([^'\"]+)['\"]", tag, re.I)
        if match:
            result.append(match.group(1))
    return result


def _read_local_text(source_root: Path, entry_file: str, references: Iterable[str]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for reference in references:
        target = _resolve_reference(source_root, entry_file, reference)
        if target and target.is_file():
            try:
                result.append(
                    (
                        target.resolve().relative_to(source_root.resolve()).as_posix(),
                        target.read_text(encoding="utf-8", errors="replace"),
                    )
                )
            except OSError:
                continue
    return result


def _css_background_count(css_texts: Iterable[str]) -> int:
    return sum(len(CSS_URL_RE.findall(text)) for text in css_texts)


def _animation_selectors(css_texts: Iterable[str]) -> list[str]:
    selectors: list[str] = []
    for text in css_texts:
        for selector_text, declarations in CSS_RULE_RE.findall(text):
            if not HIDDEN_DECL_RE.search(declarations):
                continue
            for selector in selector_text.split(","):
                selector = selector.strip()
                if selector and REVEAL_NAME_RE.search(selector):
                    selectors.append(selector)
    # Keep the report compact and JSON-safe.
    deduped: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        if selector not in seen:
            seen.add(selector)
            deduped.append(selector)
    return deduped[:80]


def _missing_resources(
    source_root: Path,
    entry_file: str,
    parser: CompatibilityHTMLParser,
    css_texts: Iterable[str],
) -> list[str]:
    references: list[str] = []
    for _tag, attribute, value in parser.resources:
        if attribute in {"srcset", "data-srcset"}:
            references.extend(_clean_reference(value))
        else:
            references.append(value.strip())
    for css_text in css_texts:
        references.extend(match[1] for match in CSS_URL_RE.findall(css_text))

    missing: list[str] = []
    seen: set[str] = set()
    for reference in references:
        if reference in seen or not _is_local_reference(reference):
            continue
        seen.add(reference)
        target = _resolve_reference(source_root, entry_file, reference)
        if target is not None:
            try:
                exists = target.is_file()
            except OSError:
                # Extremely long or malformed references are treated as non-local
                # rather than allowing the report itself to fail.
                continue
            if not exists:
                missing.append(reference)
    return missing[:100]


def detect_spa_shell(
    parser: CompatibilityHTMLParser,
    all_script_text: str,
    inline_script_chars: int,
    *,
    html_text: str = "",
    linked_script_count: int = 0,
    entry_file: str = "",
) -> dict:
    """Detect JS apps where the visible page is rendered into empty mount points."""
    empty_mounts = []
    for element_id, element in parser.elements_by_id.items():
        if element_id.lower() in SPA_MOUNT_IDS and element.empty:
            empty_mounts.append(f"#{element_id}")

    hash_routes = bool(HASH_ROUTE_RE.search(all_script_text))
    dynamic_ops = len(DYNAMIC_OPERATION_RE.findall(all_script_text))
    large_inline_script = inline_script_chars >= 40_000
    module_scripts = bool(MODULE_SCRIPT_RE.search(html_text or ""))
    entry_parts = {part.lower() for part in PurePosixPath(entry_file or "").parts}
    built_output_entry = bool(entry_parts & BUILD_OUTPUT_DIRS)

    # Vite/React/etc. dist shells often only have <div id="root"> + <script type="module">.
    # Do not require scanning huge bundled JS for DOM APIs.
    client_app_signals = (
        hash_routes
        or dynamic_ops >= 8
        or large_inline_script
        or module_scripts
        or (bool(empty_mounts) and linked_script_count >= 1)
        or (bool(empty_mounts) and built_output_entry)
    )
    is_spa = bool(empty_mounts) and client_app_signals

    reasons = []
    if empty_mounts:
        reasons.append("Empty mount point(s): " + ", ".join(empty_mounts[:4]))
    if hash_routes:
        reasons.append("Hash-based client routing detected")
    if dynamic_ops >= 8:
        reasons.append("Heavy DOM generation via JavaScript")
    if large_inline_script:
        reasons.append("Large inline application script")
    if module_scripts:
        reasons.append("ES module app bootstrap detected")
    if built_output_entry and empty_mounts:
        reasons.append("Built output folder entry (dist/build/out) with empty mount")

    return {
        "isSpaShell": is_spa,
        "emptyMounts": empty_mounts[:8],
        "hashRouting": hash_routes,
        "reasons": reasons,
        "guidance": (
            "This site is a JS app shell. Use Live Preview or Interactive mode to see the real UI. "
            "Capture this page when you want a static HTML snapshot for Safe Edit."
            if is_spa
            else ""
        ),
    }


def _has_editable_static_content(parser: CompatibilityHTMLParser, spa: dict, direct_editable: int) -> bool:
    if spa.get("isSpaShell"):
        return False
    content_tags = sum(
        parser.tags.get(tag, 0)
        for tag in ("h1", "h2", "h3", "h4", "h5", "p", "a", "button", "img", "li", "section", "article")
    )
    return content_tags >= 6 or direct_editable >= 8


def analyze_website(source_root: Path, entry_file: str, html_text: str) -> dict:
    parser = CompatibilityHTMLParser()
    parser.feed(html_text)

    inline_styles = [item for item in STYLE_RE.findall(html_text) if item.strip()]
    stylesheet_sources = _stylesheet_sources(html_text)
    external_css = _read_local_text(source_root, entry_file, stylesheet_sources)
    css_texts = inline_styles + [text for _path, text in external_css]

    script_blocks = SCRIPT_BLOCK_RE.findall(html_text)
    inline_scripts = [body for attrs, body in script_blocks if not re.search(r"\bsrc\s*=", attrs, re.I)]
    script_sources = _script_sources(html_text)
    external_scripts = _read_local_text(source_root, entry_file, script_sources)
    all_script_text = "\n".join(inline_scripts + [text for _path, text in external_scripts])
    inline_script_chars = sum(len(body) for body in inline_scripts)
    spa = detect_spa_shell(
        parser,
        all_script_text,
        inline_script_chars,
        html_text=html_text,
        linked_script_count=len(script_sources),
        entry_file=entry_file,
    )

    dynamic_target_ids = set(GET_ID_RE.findall(all_script_text)) | set(QUERY_ID_RE.findall(all_script_text))
    dynamic_target_classes = set(QUERY_CLASS_RE.findall(all_script_text))
    runtime_regions = []
    for element_id in sorted(dynamic_target_ids):
        element = parser.elements_by_id.get(element_id)
        if element and element.empty and element.tag in RUNTIME_CONTAINER_TAGS:
            runtime_regions.append({
                "selector": f"#{element_id}",
                "id": element_id,
                "tag": element.tag,
                "reason": "Referenced by JavaScript and empty in the original HTML",
            })
    for class_name in sorted(dynamic_target_classes):
        elements = parser.elements_by_class.get(class_name, [])
        containers = [element for element in elements if element.tag in RUNTIME_CONTAINER_TAGS]
        if containers and all(element.empty for element in containers):
            runtime_regions.append({
                "selector": f".{class_name}",
                "id": "",
                "tag": containers[0].tag,
                "reason": "Selected by JavaScript and empty in the original HTML",
            })

    html_pages = sorted(
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".html", ".htm"}
    )
    image_files = sum(
        1 for path in source_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif"}
    )
    media_files = sum(
        1 for path in source_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".mp4", ".webm", ".ogg", ".mp3", ".wav"}
    )

    dynamic_operations = len(DYNAMIC_OPERATION_RE.findall(all_script_text))
    storage_usage = len(LOCAL_STORAGE_RE.findall(all_script_text))
    data_arrays = len(ARRAY_DATA_RE.findall(all_script_text))
    animation_selectors = _animation_selectors(css_texts)
    missing = _missing_resources(source_root, entry_file, parser, css_texts)

    if spa["isSpaShell"]:
        website_type = "JavaScript app / SPA shell"
    elif storage_usage and (parser.forms or dynamic_operations >= 3):
        website_type = "Interactive web application"
    elif script_blocks or external_scripts:
        website_type = "Static HTML with JavaScript"
    else:
        website_type = "Static HTML website"

    direct_editable = sum(parser.tags.get(tag, 0) for tag in ("h1", "h2", "h3", "h4", "p", "a", "button", "img"))
    if spa["isSpaShell"]:
        # Mount points and chrome may inflate editable estimates; the real content is runtime-only.
        direct_editable = min(direct_editable, 12)
    has_editable_static = _has_editable_static_content(parser, spa, direct_editable)
    entry_parts = {part.lower() for part in PurePosixPath(entry_file).parts}
    built_output_entry = bool(entry_parts & BUILD_OUTPUT_DIRS)
    prefer_live_preview = bool(spa["isSpaShell"] or (built_output_entry and not has_editable_static))

    protected_regions = len(runtime_regions)
    score = 100
    score -= min(35, protected_regions * 4)
    score -= min(25, len(missing) * 5)
    score -= 10 if dynamic_operations >= 10 else 0
    score -= 8 if storage_usage else 0
    if spa["isSpaShell"]:
        score = min(score, 45)
    score = max(20, score)

    recommendations: list[str] = []
    if spa["isSpaShell"] or prefer_live_preview:
        recommendations.append(
            spa["guidance"]
            or "Open Live Preview to see the built website. Use Capture this page before Safe Edit."
        )
    if parser.lazy_media:
        recommendations.append("Lazy-loaded media is hydrated automatically in Safe Edit mode.")
    if animation_selectors:
        recommendations.append("Animation-hidden content is temporarily revealed in Safe Edit mode.")
    if runtime_regions and not spa["isSpaShell"]:
        recommendations.append("Use Interactive mode to view JavaScript-generated regions before editing nearby content.")
    if storage_usage:
        recommendations.append("Live Preview uses an isolated project origin so localStorage and application state can run.")
    if missing:
        recommendations.append("Review the missing local resources listed below before export.")
    if not recommendations:
        recommendations.append("This website should be highly compatible with direct visual editing.")

    return {
        "websiteType": website_type,
        "compatibilityScore": score,
        "supportProfile": support_profile_payload(),
        "htmlPageCount": len(html_pages),
        "pages": html_pages[:40],
        "inlineStyleCount": len(inline_styles),
        "linkedStyleCount": len(stylesheet_sources),
        "inlineScriptCount": len(inline_scripts),
        "linkedScriptCount": len(script_sources),
        "imageTagCount": parser.tags.get("img", 0),
        "imageFileCount": image_files,
        "inlineSvgCount": parser.inline_svg,
        "videoTagCount": parser.tags.get("video", 0),
        "mediaFileCount": media_files,
        "iframeCount": parser.tags.get("iframe", 0),
        "formCount": parser.forms,
        "lazyMediaCount": parser.lazy_media,
        "srcsetCount": parser.srcset,
        "cssBackgroundCount": _css_background_count(css_texts),
        "animationSelectorCount": len(animation_selectors),
        "animationSelectors": animation_selectors,
        "dynamicOperationCount": dynamic_operations,
        "dataArrayCount": data_arrays,
        "storageUsageCount": storage_usage,
        "runtimeRegionCount": len(runtime_regions),
        "runtimeRegions": runtime_regions[:60],
        "directEditableEstimate": direct_editable,
        "hasEditableStaticContent": has_editable_static,
        "preferLivePreview": prefer_live_preview,
        "canSafeEdit": has_editable_static and not spa["isSpaShell"],
        "missingResourceCount": len(missing),
        "missingResources": missing,
        "recommendations": recommendations,
        "spaShell": spa,
    }
