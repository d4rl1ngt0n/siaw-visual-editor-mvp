"""Named project restore points (source + editor state)."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from django.core.exceptions import ValidationError

MAX_SNAPSHOTS = 10


def snapshots_dir(project_dir: Path) -> Path:
    return project_dir / "snapshots"


def list_snapshots(project_dir: Path) -> list[dict]:
    root = snapshots_dir(project_dir)
    if not root.is_dir():
        return []
    items = []
    for path in sorted(root.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        meta_path = path / "meta.json"
        meta = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
        items.append(
            {
                "id": path.name,
                "label": meta.get("label") or path.name,
                "createdAt": meta.get("createdAt") or "",
                "entryFile": meta.get("entryFile") or "",
            }
        )
    return items


def _safe_label(label: str) -> str:
    cleaned = re.sub(r"[^\w\s.\-]+", "", (label or "Restore point").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip() or "Restore point"
    return cleaned[:80]


def create_snapshot(
    project_dir: Path,
    source_dir: Path,
    editor_dir: Path,
    entry_file: str,
    label: str = "Restore point",
) -> dict:
    if not source_dir.is_dir():
        raise ValidationError("Project source is missing.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^\w\-]+", "-", _safe_label(label).lower()).strip("-")[:40] or "point"
    snapshot_id = f"{stamp}-{slug}"
    root = snapshots_dir(project_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / snapshot_id
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    shutil.copytree(source_dir, target / "source")
    if editor_dir.is_dir():
        shutil.copytree(editor_dir, target / "editor")
    else:
        (target / "editor").mkdir(parents=True, exist_ok=True)

    meta = {
        "id": snapshot_id,
        "label": _safe_label(label),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "entryFile": entry_file,
    }
    (target / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    existing = sorted([path for path in root.iterdir() if path.is_dir()], reverse=True)
    for stale in existing[MAX_SNAPSHOTS:]:
        shutil.rmtree(stale, ignore_errors=True)

    return meta


def restore_snapshot(
    project_dir: Path,
    source_dir: Path,
    editor_dir: Path,
    snapshot_id: str,
) -> dict:
    root = snapshots_dir(project_dir)
    target = root / snapshot_id
    if not target.is_dir() or ".." in Path(snapshot_id).parts:
        raise ValidationError("That restore point was not found.")

    source_snapshot = target / "source"
    if not source_snapshot.is_dir():
        raise ValidationError("Restore point is incomplete.")

    meta_path = target / "meta.json"
    meta = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}

    if source_dir.exists():
        shutil.rmtree(source_dir)
    shutil.copytree(source_snapshot, source_dir)

    editor_snapshot = target / "editor"
    if editor_dir.exists():
        shutil.rmtree(editor_dir)
    if editor_snapshot.is_dir():
        shutil.copytree(editor_snapshot, editor_dir)
    else:
        editor_dir.mkdir(parents=True, exist_ok=True)

    return {
        "id": snapshot_id,
        "label": meta.get("label") or snapshot_id,
        "entryFile": meta.get("entryFile") or "index.html",
        "createdAt": meta.get("createdAt") or "",
    }
