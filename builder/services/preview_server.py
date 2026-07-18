"""Run Node SSR preview servers (Nitro / TanStack Start / similar) for live preview."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

_lock = threading.Lock()
_servers: dict[str, "PreviewServerHandle"] = {}


def _boot_timeout_seconds() -> float:
    try:
        from django.conf import settings

        return float(getattr(settings, "SSR_PREVIEW_BOOT_SECONDS", 25))
    except Exception:
        return float(os.environ.get("SSR_PREVIEW_BOOT_SECONDS", "25"))


@dataclass
class SsrPreviewInfo:
    package_dir: Path
    package_dir_rel: str
    server_script: Path
    command: list[str]
    kind: str


@dataclass
class PreviewServerHandle:
    project_id: str
    port: int
    process: subprocess.Popen
    package_dir: Path
    kind: str


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def detect_ssr_preview(package_dir: Path, source_root: Path) -> SsrPreviewInfo | None:
    """Detect Nitro / node-server builds that need a running Node process."""
    nitro_path = package_dir / "dist" / "nitro.json"
    server_candidates = [
        package_dir / "dist" / "server" / "index.mjs",
        package_dir / "dist" / "server" / "index.js",
        package_dir / ".output" / "server" / "index.mjs",
        package_dir / ".output" / "server" / "index.js",
    ]
    server_script = next((path for path in server_candidates if path.is_file()), None)

    kind = ""
    if nitro_path.is_file():
        kind = "nitro"
        try:
            data = json.loads(nitro_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        entry = (data.get("serverEntry") or "").strip()
        if entry:
            candidate = (package_dir / "dist" / entry).resolve()
            if candidate.is_file():
                server_script = candidate
        commands = data.get("commands") if isinstance(data.get("commands"), dict) else {}
        preview_cmd = str(commands.get("preview") or "").strip()
        if preview_cmd.startswith("node ") and server_script is None:
            rel = preview_cmd.split(None, 1)[1].lstrip("./")
            candidate = (package_dir / "dist" / rel).resolve()
            if not candidate.is_file():
                candidate = (package_dir / rel).resolve()
            if candidate.is_file():
                server_script = candidate
    elif server_script is not None:
        kind = "node-server"

    if server_script is None or not server_script.is_file():
        return None

    try:
        package_dir_rel = package_dir.relative_to(source_root).as_posix() if package_dir != source_root else "."
    except ValueError:
        package_dir_rel = "."

    return SsrPreviewInfo(
        package_dir=package_dir,
        package_dir_rel=package_dir_rel,
        server_script=server_script,
        command=["node", str(server_script)],
        kind=kind or "node-server",
    )


def get_running_preview(project_id: str) -> PreviewServerHandle | None:
    with _lock:
        handle = _servers.get(str(project_id))
        if handle is None:
            return None
        if handle.process.poll() is not None:
            _servers.pop(str(project_id), None)
            return None
        return handle


def stop_preview_server(project_id: str) -> None:
    with _lock:
        handle = _servers.pop(str(project_id), None)
    if handle is None:
        return
    proc = handle.process
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass


def _wait_for_http(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/"
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1.5) as response:
                if 200 <= getattr(response, "status", 200) < 500:
                    return True
        except (URLError, OSError, TimeoutError):
            time.sleep(0.25)
    return False


def start_preview_server(project_id: str, info: SsrPreviewInfo) -> PreviewServerHandle:
    """Start (or reuse) a Node SSR preview server for this project."""
    existing = get_running_preview(project_id)
    if existing is not None:
        return existing

    stop_preview_server(project_id)
    port = _pick_free_port()
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["HOST"] = "127.0.0.1"
    env["NITRO_PORT"] = str(port)
    env["NITRO_HOST"] = "127.0.0.1"
    env["NODE_ENV"] = "production"

    proc = subprocess.Popen(
        info.command,
        cwd=str(info.package_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    handle = PreviewServerHandle(
        project_id=str(project_id),
        port=port,
        process=proc,
        package_dir=info.package_dir,
        kind=info.kind,
    )

    if not _wait_for_http(port, timeout=_boot_timeout_seconds()):
        stop_preview_server(project_id)
        if proc.poll() is None:
            proc.kill()
        raise RuntimeError(f"SSR preview server failed to become ready on port {port}.")

    with _lock:
        # Another thread may have started one; keep the healthy one we just verified.
        previous = _servers.get(str(project_id))
        if previous is not None and previous is not handle and previous.process.poll() is None:
            proc.terminate()
            return previous
        _servers[str(project_id)] = handle
    return handle


def server_entry_rel(info: SsrPreviewInfo, source_root: Path) -> str:
    try:
        return info.server_script.relative_to(source_root).as_posix()
    except ValueError:
        return str(info.server_script)


def proxy_upstream_url(project_id: str, asset_path: str = "") -> str | None:
    handle = get_running_preview(project_id)
    if handle is None:
        return None
    path = "/" + (asset_path or "").lstrip("/")
    if path == "/":
        return f"http://127.0.0.1:{handle.port}/"
    return f"http://127.0.0.1:{handle.port}{path}"


def restart_ssr_from_status(project_id: str, source_root: Path, status: dict[str, Any]) -> PreviewServerHandle | None:
    """Restart an SSR preview using paths stored in build-status.json."""
    if status.get("previewMode") != "ssr":
        return None
    rel = status.get("packageDir") or "."
    package_dir = source_root if rel in {".", ""} else source_root / str(rel)
    info = detect_ssr_preview(package_dir, source_root)
    if info is None:
        return None
    return start_preview_server(project_id, info)
