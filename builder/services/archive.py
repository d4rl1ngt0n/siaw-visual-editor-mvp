from __future__ import annotations

import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from django.core.exceptions import ValidationError

MAX_FILES = 2500
MAX_UNCOMPRESSED_BYTES = 120 * 1024 * 1024

ALLOWED_SUFFIXES = {
    ".html", ".htm", ".css", ".js", ".json", ".xml", ".txt", ".md",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif",
    ".mp4", ".webm", ".ogg", ".mp3", ".wav",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".pdf", ".webmanifest", ".map",
}

BLOCKED_FILENAMES = {".htaccess", "web.config", "nginx.conf", "apache.conf"}

BLOCKED_SUFFIXES = {
    ".php", ".py", ".pyc", ".exe", ".dll", ".so", ".dylib", ".bat",
    ".cmd", ".ps1", ".sh", ".com", ".msi", ".jar", ".war", ".asp",
    ".aspx", ".jsp", ".cgi", ".pl", ".rb", ".go", ".rs",
}


class StylesheetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stylesheets: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() != "link":
            return
        data = {str(k).lower(): v for k, v in attrs if k}
        rel = (data.get("rel") or "").lower()
        href = data.get("href")
        if href and "stylesheet" in rel:
            self.stylesheets.append(href)


@dataclass(frozen=True)
class ImportedWebsite:
    entry_file: str
    stylesheet_files: list[str]


def _validate_member(info: zipfile.ZipInfo) -> PurePosixPath:
    raw = info.filename.replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValidationError(f"Unsafe path found in ZIP: {info.filename}")
    if not path.parts:
        raise ValidationError("The ZIP contains an invalid empty path.")

    unix_mode = (info.external_attr >> 16) & 0o170000
    if unix_mode == stat.S_IFLNK:
        raise ValidationError(f"Symbolic links are not allowed: {info.filename}")

    if not info.is_dir():
        if path.name.lower() in BLOCKED_FILENAMES:
            raise ValidationError(f"Server configuration file is not allowed: {info.filename}")
        suffix = Path(path.name).suffix.lower()
        if suffix in BLOCKED_SUFFIXES:
            raise ValidationError(f"Server-side or executable file is not allowed: {info.filename}")
        if suffix and suffix not in ALLOWED_SUFFIXES:
            raise ValidationError(f"Unsupported file type in ZIP: {info.filename}")
    return path


def _find_project_root(extracted_dir: Path) -> tuple[Path, Path]:
    index_candidates = [
        p for p in extracted_dir.rglob("*")
        if p.is_file() and p.name.lower() in {"index.html", "index.htm"}
    ]
    if not index_candidates:
        raise ValidationError("No index.html or index.htm file was found in the ZIP.")

    index_candidates.sort(key=lambda p: (len(p.relative_to(extracted_dir).parts), str(p)))
    entry_path = index_candidates[0]
    root = entry_path.parent
    return root, entry_path


def _local_stylesheets(html_text: str, entry_dir: Path, source_root: Path) -> list[str]:
    parser = StylesheetParser()
    parser.feed(html_text)
    result: list[str] = []
    for href in parser.stylesheets:
        lowered = href.lower()
        if lowered.startswith(("http://", "https://", "//", "data:")):
            result.append(href)
            continue
        clean = href.split("?", 1)[0].split("#", 1)[0]
        candidate = (entry_dir / clean).resolve()
        try:
            relative = candidate.relative_to(source_root.resolve()).as_posix()
        except ValueError:
            continue
        if candidate.is_file():
            result.append(relative)
    return result


def _write_uploaded_bytes(uploaded_file, destination: Path) -> None:
    with destination.open("wb") as target:
        for chunk in uploaded_file.chunks():
            target.write(chunk)


def _import_single_html(uploaded_file, destination_project_dir: Path) -> ImportedWebsite:
    """Accept a lone .html upload by packaging it as a one-file website ZIP."""
    destination_project_dir.mkdir(parents=True, exist_ok=True)
    source_dir = destination_project_dir / "source"
    editor_dir = destination_project_dir / "editor"
    editor_dir.mkdir(parents=True, exist_ok=True)
    if source_dir.exists():
        shutil.rmtree(source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)

    entry_name = "index.html"
    html_path = source_dir / entry_name
    _write_uploaded_bytes(uploaded_file, html_path)

    temp_zip = destination_project_dir / "original.zip"
    with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(html_path, entry_name)

    html_text = html_path.read_text(encoding="utf-8", errors="replace")
    stylesheets = _local_stylesheets(html_text, html_path.parent, source_dir)
    return ImportedWebsite(entry_file=entry_name, stylesheet_files=stylesheets)


def import_website_zip(uploaded_file, destination_project_dir: Path) -> ImportedWebsite:
    uploaded_name = (getattr(uploaded_file, "name", "") or "").lower()
    if uploaded_name.endswith((".html", ".htm")):
        return _import_single_html(uploaded_file, destination_project_dir)

    destination_project_dir.mkdir(parents=True, exist_ok=True)
    source_dir = destination_project_dir / "source"
    editor_dir = destination_project_dir / "editor"
    editor_dir.mkdir(parents=True, exist_ok=True)

    temp_zip = destination_project_dir / "original.zip"
    _write_uploaded_bytes(uploaded_file, temp_zip)

    with tempfile.TemporaryDirectory(prefix="siaw-editor-") as tmp:
        extracted = Path(tmp) / "extracted"
        extracted.mkdir(parents=True, exist_ok=True)

        try:
            archive = zipfile.ZipFile(temp_zip)
        except zipfile.BadZipFile as exc:
            raise ValidationError("The uploaded file is not a valid ZIP archive.") from exc

        with archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES:
                raise ValidationError(f"The ZIP contains too many files. Maximum: {MAX_FILES}.")
            total_size = sum(info.file_size for info in infos)
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise ValidationError("The extracted website is too large for this MVP.")

            validated: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
            for info in infos:
                validated.append((info, _validate_member(info)))

            for info, safe_path in validated:
                output = extracted.joinpath(*safe_path.parts)
                if info.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, output.open("wb") as target:
                    shutil.copyfileobj(source, target)

        project_root, entry_path = _find_project_root(extracted)
        if source_dir.exists():
            shutil.rmtree(source_dir)
        shutil.copytree(project_root, source_dir)

    relative_entry = entry_path.relative_to(project_root).as_posix()
    html_path = source_dir / relative_entry
    html_text = html_path.read_text(encoding="utf-8", errors="replace")
    stylesheets = _local_stylesheets(html_text, html_path.parent, source_dir)
    return ImportedWebsite(entry_file=relative_entry, stylesheet_files=stylesheets)


def safe_project_path(source_root: Path, requested_path: str) -> Path:
    requested = requested_path.replace("\\", "/").lstrip("/")
    relative = PurePosixPath(requested)
    if ".." in relative.parts:
        raise FileNotFoundError(requested_path)
    target = source_root.joinpath(*relative.parts).resolve()
    try:
        target.relative_to(source_root.resolve())
    except ValueError as exc:
        raise FileNotFoundError(requested_path) from exc
    return target
