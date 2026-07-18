"""Multi-page helpers for HTML projects."""

from __future__ import annotations

import re
import shutil
from pathlib import Path, PurePosixPath

from django.core.exceptions import ValidationError
from django.utils.text import get_valid_filename

from .archive import is_html_path, safe_project_path

NAV_HREF_RE = re.compile(
    r"""<a\b[^>]*\bhref\s*=\s*([\"'])(?P<href>[^\"']+)\1[^>]*>(?P<label>.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
)
HEADER_RE = re.compile(r"(?is)<header\b[^>]*>.*?</header>")
FOOTER_RE = re.compile(r"(?is)<footer\b[^>]*>.*?</footer>")
HEAD_RE = re.compile(r"(?is)<head\b[^>]*>(.*?)</head>")


def _find_section_by_id(html_text: str, section_id: str) -> str | None:
    pattern = re.compile(
        rf"""(?is)<(?P<tag>section|div|article)\b[^>]*\bid\s*=\s*[\"']{re.escape(section_id)}[\"'][^>]*>.*?</(?P=tag)>"""
    )
    match = pattern.search(html_text or "")
    return match.group(0) if match else None

BLANK_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
</head>
<body>
  <main>
    <h1>{title}</h1>
    <p>Start editing this page.</p>
  </main>
</body>
</html>
"""


def list_html_pages(source_root: Path) -> list[str]:
    pages = [
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*")
        if path.is_file() and is_html_path(path)
        and "__MACOSX" not in path.parts
        and not any(part.startswith(".") for part in path.relative_to(source_root).parts)
    ]
    return sorted(pages, key=lambda item: (item.count("/"), item.lower()))


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def extract_nav_links(html_text: str) -> list[dict[str, str]]:
    """Return ordered nav-like links from header/nav (label + href)."""
    scope_match = re.search(r"(?is)<(?:header|nav)\b[^>]*>.*?</(?:header|nav)>", html_text or "")
    scope = scope_match.group(0) if scope_match else (html_text or "")
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in NAV_HREF_RE.finditer(scope):
        href = (match.group("href") or "").strip()
        label = _strip_tags(match.group("label") or "")
        if not href or not label:
            continue
        lowered = href.lower()
        if lowered.startswith(("mailto:", "tel:", "javascript:", "http://", "https://", "//")):
            continue
        key = href.split("#", 1)[0] or href
        if key in seen:
            continue
        seen.add(key)
        links.append({"href": href, "label": label[:80]})
    return links


def _slug_to_page_name(slug: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "-", (slug or "page").strip("#/")).strip(".-_") or "page"
    return _safe_page_name(cleaned)


def expand_hash_navigation_to_pages(source_root: Path, entry_file: str) -> list[str]:
    """Turn single-page #section menu links into real HTML pages (idempotent)."""
    entry_rel = (entry_file or "").replace("\\", "/").lstrip("/")
    if not entry_rel or not is_html_path(entry_rel):
        return list_html_pages(source_root)
    entry_path = source_root / entry_rel
    if not entry_path.is_file():
        return list_html_pages(source_root)

    html_text = entry_path.read_text(encoding="utf-8", errors="replace")
    nav_links = extract_nav_links(html_text)
    skip_ids = {"top", "home", "main", "content", "root", "app", "header", "footer", "nav"}
    hash_targets = []
    for link in nav_links:
        href = link["href"]
        if href.startswith("#") and len(href) > 1:
            section_id = href[1:].strip()
            if not section_id or section_id.lower() in skip_ids:
                continue
            hash_targets.append((section_id, link["label"]))

    # Only expand when this looks like a one-page site with in-page menu targets.
    existing = [p for p in list_html_pages(source_root) if not p.startswith("captured/")]
    if len(existing) > 1 or not hash_targets:
        return list_html_pages(source_root)

    head_match = HEAD_RE.search(html_text)
    head_inner = head_match.group(1) if head_match else "<meta charset=\"utf-8\">"
    header_html = HEADER_RE.search(html_text)
    footer_html = FOOTER_RE.search(html_text)
    header = header_html.group(0) if header_html else ""
    footer = footer_html.group(0) if footer_html else ""

    created: list[str] = []
    replacements: list[tuple[str, str]] = []
    for section_id, label in hash_targets:
        page_name = _slug_to_page_name(section_id)
        if page_name == Path(entry_rel).name:
            continue
        section_body = _find_section_by_id(html_text, section_id)
        if not section_body:
            section_body = (
                f'<section id="{section_id}">'
                f'<div class="wrap"><h1>{label}</h1>'
                f"<p>Edit this page in Safe Edit.</p></div></section>"
            )

        page_html = (
            "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
            f"{head_inner}\n"
            f"<title>{label}</title>\n"
            "</head>\n<body>\n"
            f"{header}\n<main>\n{section_body}\n</main>\n{footer}\n"
            "</body>\n</html>\n"
        )
        destination = source_root / page_name
        if not destination.exists():
            destination.write_text(page_html, encoding="utf-8")
            created.append(page_name)
        replacements.append((f"#{section_id}", page_name))

    if not replacements and not created:
        return list_html_pages(source_root)

    def rewrite_nav(text: str) -> str:
        updated = text
        # Brand / home links that pointed at #top
        updated = re.sub(
            r"""(href\s*=\s*["'])#top(["'])""",
            rf"\1{Path(entry_rel).name}\2",
            updated,
            flags=re.IGNORECASE,
        )
        for old, new in replacements:
            updated = re.sub(
                rf"""(href\s*=\s*["']){re.escape(old)}(["'])""",
                rf"\1{new}\2",
                updated,
                flags=re.IGNORECASE,
            )
        return updated

    # Rewrite nav across entry + newly related pages in the entry directory.
    entry_dir = entry_path.parent
    for path in entry_dir.glob("*.html"):
        current = path.read_text(encoding="utf-8", errors="replace")
        rewritten = rewrite_nav(current)
        if rewritten != current:
            path.write_text(rewritten, encoding="utf-8")

    return list_html_pages(source_root)


def describe_site_pages(source_root: Path, entry_file: str) -> list[dict]:
    """Pages list ordered by menu-bar navigation, with human labels."""
    entry_rel = (entry_file or "").replace("\\", "/").lstrip("/")
    expand_hash_navigation_to_pages(source_root, entry_rel)
    pages = list_html_pages(source_root)

    label_by_path: dict[str, str] = {}
    nav_order: list[str] = []
    if entry_rel and (source_root / entry_rel).is_file():
        html_text = (source_root / entry_rel).read_text(encoding="utf-8", errors="replace")
        for link in extract_nav_links(html_text):
            href = link["href"].split("#", 1)[0].strip()
            if not href or href in {".", "./"}:
                href = entry_rel
            # Resolve relative to entry directory.
            resolved = (PurePosixPath(entry_rel).parent / href).as_posix()
            if resolved.startswith("./"):
                resolved = resolved[2:]
            if resolved == ".":
                resolved = entry_rel
            if not is_html_path(resolved):
                continue
            if resolved not in nav_order:
                nav_order.append(resolved)
            label_by_path.setdefault(resolved, link["label"])

    # Homepage label should stay "Home" unless the menu literally says Home.
    if entry_rel:
        if label_by_path.get(entry_rel, "").strip().lower() not in {"home", "homepage"}:
            label_by_path[entry_rel] = "Home"

    ordered: list[str] = []
    if entry_rel in pages:
        ordered.append(entry_rel)
    for path in nav_order:
        if path in pages and path not in ordered:
            ordered.append(path)
    for path in pages:
        # Hide accidental scroll-target pages and capture drafts from the manager.
        stem = Path(path).stem.lower()
        if stem in {"top", "home", "main", "content", "root", "app"} and path != entry_rel:
            continue
        if path.startswith("captured/") and path != entry_rel:
            continue
        if path not in ordered:
            ordered.append(path)

    result = []
    for path in ordered:
        stem = Path(path).stem.replace("-", " ").replace("_", " ").title()
        result.append(
            {
                "path": path,
                "label": label_by_path.get(path) or stem,
                "inNav": path in nav_order or path == entry_rel,
                "isHome": path == entry_rel,
            }
        )
    return result


def _safe_page_name(name: str, default: str = "page") -> str:
    raw = (name or default).strip()
    if not raw.lower().endswith((".html", ".htm")):
        raw = f"{raw}.html"
    stem = Path(raw).stem
    cleaned = get_valid_filename(stem) or default
    cleaned = re.sub(r"[^\w.\-]+", "-", cleaned).strip(".-_") or default
    suffix = Path(raw).suffix.lower() if Path(raw).suffix.lower() in {".html", ".htm"} else ".html"
    return f"{cleaned}{suffix}"


def _unique_path(source_root: Path, relative: str) -> str:
    candidate = PurePosixPath(relative)
    target = source_root / candidate
    if not target.exists():
        return candidate.as_posix()
    stem = candidate.stem
    suffix = candidate.suffix
    parent = candidate.parent
    counter = 2
    while True:
        next_name = f"{stem}-{counter}{suffix}"
        next_rel = (parent / next_name).as_posix() if str(parent) != "." else next_name
        if not (source_root / next_rel).exists():
            return next_rel
        counter += 1


def add_blank_page(source_root: Path, name: str = "page.html", title: str | None = None) -> str:
    relative = _unique_path(source_root, _safe_page_name(name))
    target = source_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    page_title = title or Path(relative).stem.replace("-", " ").replace("_", " ").title()
    target.write_text(BLANK_PAGE.format(title=page_title), encoding="utf-8")
    return relative


def duplicate_page(source_root: Path, source_path: str) -> str:
    try:
        source = safe_project_path(source_root, source_path)
    except FileNotFoundError as exc:
        raise ValidationError("That page does not exist.") from exc
    if not source.is_file() or not is_html_path(source):
        raise ValidationError("Only HTML pages can be duplicated.")

    relative_source = PurePosixPath(source_path.replace("\\", "/").lstrip("/")).as_posix()
    stem = Path(relative_source).stem
    suffix = Path(relative_source).suffix
    parent = PurePosixPath(relative_source).parent
    base = f"{stem}-copy{suffix}"
    relative = _unique_path(source_root, (parent / base).as_posix() if str(parent) != "." else base)
    destination = source_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return relative


def rename_page(source_root: Path, source_path: str, new_name: str) -> str:
    try:
        source = safe_project_path(source_root, source_path)
    except FileNotFoundError as exc:
        raise ValidationError("That page does not exist.") from exc
    if not source.is_file() or not is_html_path(source):
        raise ValidationError("Only HTML pages can be renamed.")

    parent = PurePosixPath(source_path.replace("\\", "/").lstrip("/")).parent
    filename = _safe_page_name(new_name, default=Path(source_path).stem)
    relative = (parent / filename).as_posix() if str(parent) != "." else filename
    if ".." in PurePosixPath(relative).parts:
        raise ValidationError("Invalid page name.")
    destination = source_root / relative
    if destination.resolve() == source.resolve():
        return relative
    if destination.exists():
        raise ValidationError("A page with that name already exists.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.rename(destination)
    return relative
