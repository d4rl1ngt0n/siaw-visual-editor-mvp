"""Localhost-only marketing site edits that write back into template files."""

from __future__ import annotations

import html
import re
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest

LOCAL_HOSTS = {"127.0.0.1", "localhost", "testserver"}
TEMPLATE_ROOT = Path(settings.BASE_DIR) / "templates" / "builder"
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,80}$", re.I)


def site_edit_allowed(request: HttpRequest | None) -> bool:
    """True only for local DEBUG servers. Never on deployed hosts."""
    if not request or not getattr(settings, "DEBUG", False):
        return False
    if getattr(settings, "SIAW_SITE_EDIT", True) is False:
        return False
    host = (request.get_host() or "").split(":", 1)[0].lower()
    return host in LOCAL_HOSTS or host.endswith(".localhost")


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
    # Preserve intentional simple markup from the editor: only plain text is accepted.
    if "<" in value or ">" in value:
        safe = html.escape(value, quote=False)
    replaced = content[: match.start("body")] + safe + content[match.end("body") :]
    return replaced, True


def _replace_img_src(content: str, key: str, value: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf'(data-site-edit="{re.escape(key)}"[^>]*?\bsrc=")([^"]*)(")',
        re.IGNORECASE,
    )
    match = pattern.search(content)
    if not match:
        return content, False
    safe_src = value.strip().replace("&", "&amp;").replace('"', "&quot;")
    replaced = content[: match.start(2)] + safe_src + content[match.end(2) :]
    return replaced, True


def apply_site_edits(edits: list[dict]) -> dict:
    """
    Apply edits shaped like:
      {"key": "hero.headline", "value": "...", "kind": "text"|"src"}
    Writes into templates under templates/builder/.
    """
    if not isinstance(edits, list) or not edits:
        raise ValueError("No edits provided.")

    files = _iter_template_files()
    if not files:
        raise ValueError("No editable template files found.")

    pending: list[tuple[str, str, str]] = []
    for item in edits:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        value = item.get("value")
        kind = str(item.get("kind") or "text").strip().lower()
        if not KEY_RE.match(key):
            raise ValueError(f"Invalid edit key: {key!r}")
        if not isinstance(value, str):
            raise ValueError(f"Edit value for {key} must be a string.")
        if len(value) > 4000:
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
        pending.append((key, value, kind))

    if not pending:
        raise ValueError("No valid edits provided.")

    originals = {path: path.read_text(encoding="utf-8") for path in files}
    working = dict(originals)
    applied: list[dict] = []
    missing: list[str] = []

    for key, value, kind in pending:
        found = False
        for path, content in working.items():
            if f'data-site-edit="{key}"' not in content:
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

    return {"ok": True, "applied": applied, "count": len(applied)}
