from __future__ import annotations

import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from django.core.exceptions import ValidationError

MAX_FILES = 5000
MAX_UNCOMPRESSED_BYTES = 150 * 1024 * 1024

# Broad web/source allowlist. True binaries and installers stay blocked.
ALLOWED_SUFFIXES = {
    ".html", ".htm", ".xhtml", ".shtml",
    ".css", ".scss", ".sass", ".less", ".styl",
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts",
    ".vue", ".svelte", ".astro",
    ".json", ".jsonc", ".json5", ".webmanifest", ".map",
    ".xml", ".xsl", ".xslt", ".svg",
    ".txt", ".md", ".mdx", ".markdown", ".rst", ".csv", ".tsv",
    ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".env",
    ".py", ".pyi", ".pyw",
    ".rb", ".php", ".phtml",
    ".go", ".rs", ".java", ".kt", ".kts", ".cs",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".m", ".mm", ".swift",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".sql", ".graphql", ".gql", ".proto",
    ".wasm",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".avif", ".bmp", ".tif", ".tiff",
    ".mp4", ".webm", ".ogg", ".mp3", ".wav", ".m4a", ".flac",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".pdf", ".zip",
    ".lock", ".npmrc", ".editorconfig", ".gitignore", ".gitattributes", ".dockerignore",
    ".htaccess",
}

# Extensionless filenames common in JS/Python/tooling projects.
ALLOWED_BASENAMES = {
    "dockerfile", "makefile", "procfile", "gemfile", "rakefile",
    "license", "licence", "readme", "changelog", "authors", "contributing",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "composer.json", "cargo.toml", "go.mod", "go.sum", "pyproject.toml",
    "requirements.txt", "pipfile", "poetry.lock", "setup.cfg", "setup.py",
    "manage.py", "wsgi.py", "asgi.py", "settings.py", "urls.py",
    "tsconfig.json", "jsconfig.json", "vite.config.js", "vite.config.ts",
    "vite.config.mjs", "next.config.js", "next.config.mjs", "nuxt.config.js",
    "nuxt.config.ts", "svelte.config.js", "astro.config.mjs", "webpack.config.js",
    "rollup.config.js", "babel.config.js", "postcss.config.js", "tailwind.config.js",
    "tailwind.config.ts", "eslint.config.js", "eslint.config.mjs", ".eslintrc",
    ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".prettierrc",
    ".prettierrc.json", ".prettierrc.js", ".babelrc", ".nvmrc", ".node-version",
    ".python-version", "runtime.txt", "gunicorn.conf.py",
}

BLOCKED_SUFFIXES = {
    ".exe", ".dll", ".so", ".dylib", ".bin", ".com", ".msi", ".app",
    ".dmg", ".iso", ".img", ".class", ".jar", ".war", ".ear",
    ".pyc", ".pyo", ".pyd", ".o", ".a", ".lib", ".obj",
    ".db", ".sqlite", ".sqlite3",
}

SKIP_DIR_NAMES = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next", ".nuxt",
    ".svelte-kit", ".turbo", ".parcel-cache", ".cache", "coverage",
    ".idea", ".vscode", ".cursor", ".svn", ".hg", "vendor/bundle",
}

PREFERRED_ENTRY_NAMES = {
    "index.html": 0,
    "index.htm": 1,
    "default.html": 2,
    "default.htm": 3,
    "home.html": 4,
    "home.htm": 5,
    "main.html": 6,
    "app.html": 7,
    "index.xhtml": 8,
}

PREFERRED_SOURCE_NAMES = {
    "main.tsx": 20,
    "main.jsx": 21,
    "main.ts": 22,
    "main.js": 23,
    "app.tsx": 24,
    "app.jsx": 25,
    "app.ts": 26,
    "app.js": 27,
    "app.vue": 28,
    "app.svelte": 29,
    "page.tsx": 30,
    "page.jsx": 31,
    "manage.py": 40,
    "settings.py": 41,
    "urls.py": 42,
    "wsgi.py": 43,
    "package.json": 50,
    "readme.md": 60,
    "readme.txt": 61,
}

TEXT_SUFFIXES = {
    ".html", ".htm", ".xhtml", ".shtml",
    ".css", ".scss", ".sass", ".less", ".styl",
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts",
    ".vue", ".svelte", ".astro",
    ".json", ".jsonc", ".json5", ".webmanifest", ".map",
    ".xml", ".xsl", ".xslt", ".svg",
    ".txt", ".md", ".mdx", ".markdown", ".rst", ".csv", ".tsv",
    ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".env",
    ".py", ".pyi", ".pyw",
    ".rb", ".php", ".phtml",
    ".go", ".rs", ".java", ".kt", ".kts", ".cs",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".m", ".mm", ".swift",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".sql", ".graphql", ".gql", ".proto",
    ".lock", ".npmrc", ".editorconfig", ".gitignore", ".gitattributes",
    ".dockerignore", ".htaccess",
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


def is_html_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in {".html", ".htm", ".xhtml", ".shtml"}


def is_text_path(path: str | Path) -> bool:
    name = Path(path).name.lower()
    suffix = Path(path).suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return True
    return name in ALLOWED_BASENAMES or name.startswith(".env")


def _is_ignored_extract_name(name: str) -> bool:
    lowered = name.lower()
    return lowered in {"__macosx", ".ds_store"} or lowered.startswith("._")


def _should_skip_path(parts: tuple[str, ...]) -> bool:
    for part in parts:
        lowered = part.lower()
        if lowered in SKIP_DIR_NAMES or _is_ignored_extract_name(part):
            return True
    return False


def _is_allowed_file(path: PurePosixPath) -> bool:
    name = path.name.lower()
    suffix = Path(path.name).suffix.lower()
    if suffix in BLOCKED_SUFFIXES:
        return False
    if name.startswith(".env"):
        return True
    if name in ALLOWED_BASENAMES:
        return True
    if not suffix:
        return name in {"license", "licence", "readme", "makefile", "dockerfile", "procfile", "gemfile"}
    return suffix in ALLOWED_SUFFIXES


def _validate_member(info: zipfile.ZipInfo) -> PurePosixPath | None:
    raw = info.filename.replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValidationError(f"Unsafe path found in ZIP: {info.filename}")
    if not path.parts:
        raise ValidationError("The ZIP contains an invalid empty path.")
    if _should_skip_path(path.parts):
        return None

    unix_mode = (info.external_attr >> 16) & 0o170000
    if unix_mode == stat.S_IFLNK:
        raise ValidationError(f"Symbolic links are not allowed: {info.filename}")

    if not info.is_dir():
        if not _is_allowed_file(path):
            raise ValidationError(f"Unsupported file type in archive: {info.filename}")
    return path


def _detect_archive_root(extracted_dir: Path) -> Path:
    """Use a single top-level folder as the site root when ZIP authors wrap the site."""
    children = [
        path for path in extracted_dir.iterdir()
        if not _is_ignored_extract_name(path.name) and path.name.lower() not in SKIP_DIR_NAMES
    ]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extracted_dir


def _entry_sort_key(path: Path, root: Path) -> tuple:
    relative = path.relative_to(root)
    name = path.name.lower()
    if name in PREFERRED_ENTRY_NAMES:
        preferred = PREFERRED_ENTRY_NAMES[name]
    elif name in PREFERRED_SOURCE_NAMES:
        preferred = PREFERRED_SOURCE_NAMES[name]
    elif is_html_path(path):
        preferred = 15
    elif is_text_path(path):
        preferred = 80
    else:
        preferred = 200
    return (preferred, len(relative.parts), relative.as_posix().lower())


def _iter_candidate_files(root: Path) -> list[Path]:
    candidates = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if _should_skip_path(relative_parts):
            continue
        candidates.append(path)
    return candidates


def _find_project_root(extracted_dir: Path, preferred_entry: str | None = None) -> tuple[Path, Path]:
    root = _detect_archive_root(extracted_dir)
    candidates = _iter_candidate_files(root)
    if not candidates:
        raise ValidationError("No usable project files were found in the upload.")

    if preferred_entry:
        preferred = PurePosixPath(preferred_entry.replace("\\", "/").lstrip("/"))
        if ".." not in preferred.parts:
            preferred_path = root.joinpath(*preferred.parts)
            if preferred_path.is_file():
                return root, preferred_path

    html_candidates = [path for path in candidates if is_html_path(path)]
    if html_candidates:
        html_candidates.sort(key=lambda path: _entry_sort_key(path, root))
        return root, html_candidates[0]

    text_candidates = [path for path in candidates if is_text_path(path)]
    if not text_candidates:
        raise ValidationError("No editable text or HTML files were found in the upload.")
    text_candidates.sort(key=lambda path: _entry_sort_key(path, root))
    return root, text_candidates[0]


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


def _uploaded_is_zip(uploaded_file) -> bool:
    """Detect ZIP content even when the filename ends in .html (common macOS download)."""
    if not hasattr(uploaded_file, "seek") or not hasattr(uploaded_file, "read"):
        return False
    try:
        position = uploaded_file.tell()
    except Exception:
        position = 0
    try:
        return bool(zipfile.is_zipfile(uploaded_file))
    finally:
        try:
            uploaded_file.seek(position)
        except Exception:
            try:
                uploaded_file.seek(0)
            except Exception:
                pass


def _safe_filename(uploaded_name: str, fallback: str = "page.html") -> str:
    raw = Path(uploaded_name or fallback).name
    stem = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in Path(raw).stem).strip(".-_")
    suffix = Path(raw).suffix.lower()
    if suffix and suffix not in BLOCKED_SUFFIXES:
        return f"{stem or 'file'}{suffix}"
    return f"{stem or 'file'}{Path(fallback).suffix}"


def _import_single_file(uploaded_file, destination_project_dir: Path) -> ImportedWebsite:
    """Accept a lone source/HTML upload by packaging it as a one-file project ZIP."""
    destination_project_dir.mkdir(parents=True, exist_ok=True)
    source_dir = destination_project_dir / "source"
    editor_dir = destination_project_dir / "editor"
    editor_dir.mkdir(parents=True, exist_ok=True)
    if source_dir.exists():
        shutil.rmtree(source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)

    entry_name = _safe_filename(getattr(uploaded_file, "name", "") or "page.html")
    if not _is_allowed_file(PurePosixPath(entry_name)):
        raise ValidationError("That file type is not supported for import yet.")
    file_path = source_dir / entry_name
    _write_uploaded_bytes(uploaded_file, file_path)

    temp_zip = destination_project_dir / "original.zip"
    with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(file_path, entry_name)

    stylesheets: list[str] = []
    if is_html_path(entry_name):
        html_text = file_path.read_text(encoding="utf-8", errors="replace")
        stylesheets = _local_stylesheets(html_text, file_path.parent, source_dir)
    return ImportedWebsite(entry_file=entry_name, stylesheet_files=stylesheets)


def _import_zip_archive(
    uploaded_file,
    destination_project_dir: Path,
    preferred_entry: str | None = None,
) -> ImportedWebsite:
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
                raise ValidationError(f"The archive contains too many files. Maximum: {MAX_FILES}.")
            total_size = sum(info.file_size for info in infos)
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise ValidationError("The extracted project is too large for this MVP.")

            validated: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
            for info in infos:
                safe_path = _validate_member(info)
                if safe_path is None:
                    continue
                validated.append((info, safe_path))

            if not validated:
                raise ValidationError("No usable project files were found after skipping tooling folders.")

            for info, safe_path in validated:
                output = extracted.joinpath(*safe_path.parts)
                if info.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, output.open("wb") as target:
                    shutil.copyfileobj(source, target)

        project_root, entry_path = _find_project_root(extracted, preferred_entry=preferred_entry)
        if source_dir.exists():
            shutil.rmtree(source_dir)
        shutil.copytree(
            project_root,
            source_dir,
            ignore=shutil.ignore_patterns(*SKIP_DIR_NAMES, "__MACOSX", ".DS_Store"),
        )

    relative_entry = entry_path.relative_to(project_root).as_posix()
    # Re-resolve after copytree/ignore in case preferred path was under a skipped tree.
    if not (source_dir / relative_entry).is_file():
        _, fallback_entry = _find_project_root(source_dir)
        relative_entry = fallback_entry.relative_to(source_dir).as_posix()

    stylesheets: list[str] = []
    if is_html_path(relative_entry):
        html_path = source_dir / relative_entry
        html_text = html_path.read_text(encoding="utf-8", errors="replace")
        stylesheets = _local_stylesheets(html_text, html_path.parent, source_dir)
    return ImportedWebsite(entry_file=relative_entry, stylesheet_files=stylesheets)


def import_website_zip(
    uploaded_file,
    destination_project_dir: Path,
    preferred_entry: str | None = None,
) -> ImportedWebsite:
    uploaded_name = (getattr(uploaded_file, "name", "") or "").lower()
    single_suffixes = {
        ".html", ".htm", ".css", ".js", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
        ".py", ".json", ".md", ".txt", ".php", ".rb",
    }
    if any(uploaded_name.endswith(suffix) for suffix in single_suffixes) and not _uploaded_is_zip(uploaded_file):
        return _import_single_file(uploaded_file, destination_project_dir)
    return _import_zip_archive(uploaded_file, destination_project_dir, preferred_entry=preferred_entry)


def list_source_files(source_root: Path, limit: int = 400) -> list[str]:
    files: list[str] = []
    if not source_root.is_dir():
        return files
    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source_root)
        if _should_skip_path(relative.parts):
            continue
        files.append(relative.as_posix())
        if len(files) >= limit:
            break
    return files


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
