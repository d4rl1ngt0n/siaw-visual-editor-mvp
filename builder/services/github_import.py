from __future__ import annotations

import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from .archive import import_website_zip

GITHUB_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?(?:/)?(?:tree/(?P<ref>[^/]+)(?:/(?P<subpath>.*))?)?$"
)


def github_import_enabled() -> bool:
    return str(getattr(settings, "ENABLE_GITHUB_IMPORT", True)).lower() in {"1", "true", "yes"}


def parse_github_url(url: str) -> dict[str, str]:
    cleaned = (url or "").strip()
    match = GITHUB_URL_RE.match(cleaned)
    if not match:
        raise ValidationError("Use a public GitHub URL like https://github.com/owner/repo")
    owner = match.group("owner")
    repo = match.group("repo")
    ref = match.group("ref") or ""
    subpath = (match.group("subpath") or "").strip("/")
    return {
        "owner": owner,
        "repo": repo,
        "ref": ref,
        "subpath": subpath,
        "clone_url": f"https://github.com/{owner}/{repo}.git",
    }


def _run_git(command: list[str], cwd: Path | None = None) -> None:
    timeout = int(getattr(settings, "GITHUB_CLONE_TIMEOUT_SECONDS", 120))
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValidationError("git is not available on this server.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValidationError("GitHub clone timed out.") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "git failed").strip()
        raise ValidationError(f"Could not clone repository. {detail[:300]}")


def import_github_repository(url: str, destination_project_dir: Path, preferred_entry: str | None = None):
    if not github_import_enabled():
        raise ValidationError("GitHub import is disabled on this server.")
    parsed = parse_github_url(url)

    with tempfile.TemporaryDirectory(prefix="siaw-gh-") as tmp:
        tmp_path = Path(tmp)
        clone_dir = tmp_path / "repo"
        command = ["git", "clone", "--depth", "1"]
        if parsed["ref"]:
            command.extend(["--branch", parsed["ref"]])
        command.extend([parsed["clone_url"], str(clone_dir)])
        _run_git(command)

        source_root = clone_dir
        if parsed["subpath"]:
            source_root = clone_dir.joinpath(*parsed["subpath"].split("/"))
            if not source_root.exists():
                raise ValidationError("That GitHub subfolder was not found in the repository.")

        # Package as zip so the existing importer validates/skips tooling folders.
        archive_path = tmp_path / "repo.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in source_root.rglob("*"):
                if not path.is_file():
                    continue
                relative = path.relative_to(source_root)
                if any(part in {".git", "node_modules", ".venv", "venv", "__pycache__"} for part in relative.parts):
                    continue
                archive.write(path, relative.as_posix())

        uploaded = SimpleUploadedFile(
            f"{parsed['repo']}.zip",
            archive_path.read_bytes(),
            content_type="application/zip",
        )
        return import_website_zip(uploaded, destination_project_dir, preferred_entry=preferred_entry)
