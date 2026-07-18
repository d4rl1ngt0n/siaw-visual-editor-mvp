from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from django.conf import settings

from .archive import is_html_path

OUTPUT_DIR_NAMES = (
    "dist",
    "dist/client",
    "dist/public",
    "build",
    "out",
    "output",
    "public/build",
    ".output/public",
)
PACKAGE_MARKERS = ("package.json",)
LOCK_NAMES = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb")
SKIP_DIR_NAMES = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", ".next", ".nuxt",
    ".svelte-kit", ".turbo", ".cache", "coverage", ".idea", ".vscode",
}

_build_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@dataclass
class JsProjectInfo:
    package_dir: Path  # absolute
    package_dir_rel: str  # relative to source root
    package_json: dict[str, Any]
    package_manager: str
    framework: str
    build_script: str | None
    existing_output_entry: str | None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_status_path(project_dir: Path) -> Path:
    return project_dir / "editor" / "build-status.json"


def read_build_status(project_dir: Path) -> dict[str, Any]:
    path = build_status_path(project_dir)
    if not path.is_file():
        return {"status": "idle", "message": "", "updatedAt": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"status": "idle", "message": "Build status unreadable.", "updatedAt": None}


def write_build_status(project_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = build_status_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {**payload, "updatedAt": _now_iso()}
    if "progress" in data and data["progress"] is not None:
        try:
            data["progress"] = max(0, min(100, int(data["progress"])))
        except (TypeError, ValueError):
            data.pop("progress", None)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)
    return data


def _clamp_progress(value: float, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _progress_from_output(line: str, phase_low: int, phase_high: int) -> int | None:
    """Best-effort percent from npm/vite/webpack log lines."""
    text = line.strip()
    if not text:
        return None
    # npm: ".........] | reify:axios: timing reifyNode:..." or "45%"
    match = re.search(r"(?<!\d)(\d{1,3})%(?!\d)", text)
    if match:
        pct = int(match.group(1))
        if 0 <= pct <= 100:
            span = phase_high - phase_low
            return _clamp_progress(phase_low + (span * pct / 100), phase_low, phase_high)
    lowered = text.lower()
    if "added" in lowered and "package" in lowered:
        return _clamp_progress(phase_low + (phase_high - phase_low) * 0.85, phase_low, phase_high)
    if "built in" in lowered or "build complete" in lowered:
        return phase_high
    if "transforming" in lowered or "rendering chunks" in lowered:
        return _clamp_progress(phase_low + (phase_high - phase_low) * 0.55, phase_low, phase_high)
    return None


def js_build_enabled() -> bool:
    return str(getattr(settings, "ENABLE_JS_BUILD", True)).lower() in {"1", "true", "yes"}


def _load_package_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _detect_package_manager(package_dir: Path) -> str:
    if (package_dir / "pnpm-lock.yaml").is_file() and shutil.which("pnpm"):
        return "pnpm"
    if (package_dir / "yarn.lock").is_file() and shutil.which("yarn"):
        return "yarn"
    if (package_dir / "bun.lockb").is_file() and shutil.which("bun"):
        return "bun"
    return "npm"


def _detect_framework(package_dir: Path, package_json: dict[str, Any]) -> str:
    deps = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        value = package_json.get(key)
        if isinstance(value, dict):
            deps.update({str(name).lower(): True for name in value})
    config_names = [
        "vite.config.ts", "vite.config.js", "vite.config.mjs", "vite.config.cjs",
        "next.config.js", "next.config.mjs", "next.config.ts",
        "nuxt.config.ts", "nuxt.config.js",
        "svelte.config.js", "astro.config.mjs", "astro.config.ts",
        "webpack.config.js", "react-scripts",
    ]
    existing = {name for name in config_names if (package_dir / name).is_file()}
    if "vite" in deps or any(name.startswith("vite.config.") for name in existing):
        return "vite"
    if "next" in deps or any(name.startswith("next.config.") for name in existing):
        return "next"
    if "nuxt" in deps or any(name.startswith("nuxt.config.") for name in existing):
        return "nuxt"
    if "astro" in deps or any(name.startswith("astro.config.") for name in existing):
        return "astro"
    if "@sveltejs/kit" in deps or "svelte.config.js" in existing:
        return "sveltekit"
    if "react-scripts" in deps:
        return "cra"
    if "webpack" in deps or "webpack.config.js" in existing:
        return "webpack"
    return "node"


def _pick_build_script(package_json: dict[str, Any], framework: str) -> str | None:
    scripts = package_json.get("scripts")
    if not isinstance(scripts, dict):
        scripts = {}
    preferred = ["build", "vite:build", "build:prod", "build:production", "export"]
    if framework == "next":
        preferred = ["build", "export", "build:static"] + preferred
    for name in preferred:
        if name in scripts and str(scripts[name]).strip():
            return name
    return None


def _find_output_html(package_dir: Path, source_root: Path) -> str | None:
    candidates: list[Path] = []
    for dirname in OUTPUT_DIR_NAMES:
        root = package_dir.joinpath(*dirname.split("/"))
        if not root.is_dir():
            continue
        for pattern in ("index.html", "index.htm", "**/index.html"):
            candidates.extend(root.glob(pattern))
    # Unique, prefer shallow index.html under known output dirs.
    unique: list[Path] = []
    seen = set()
    for path in candidates:
        if not path.is_file() or not is_html_path(path):
            continue
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    if not unique:
        return None
    unique.sort(key=lambda path: (len(path.relative_to(package_dir).parts), path.as_posix().lower()))
    return unique[0].relative_to(source_root).as_posix()


def detect_js_project(source_root: Path) -> JsProjectInfo | None:
    if not source_root.is_dir():
        return None
    package_files: list[Path] = []
    for path in source_root.rglob("package.json"):
        if not path.is_file():
            continue
        if any(part.lower() in SKIP_DIR_NAMES for part in path.relative_to(source_root).parts):
            continue
        # Ignore nested package.json inside packages/* for monorepos for MVP unless root missing.
        package_files.append(path)
    if not package_files:
        return None
    package_files.sort(key=lambda path: (len(path.relative_to(source_root).parts), path.as_posix()))
    package_json_path = package_files[0]
    package_json = _load_package_json(package_json_path)
    if not package_json:
        return None
    package_dir = package_json_path.parent
    framework = _detect_framework(package_dir, package_json)
    return JsProjectInfo(
        package_dir=package_dir,
        package_dir_rel=package_dir.relative_to(source_root).as_posix() if package_dir != source_root else ".",
        package_json=package_json,
        package_manager=_detect_package_manager(package_dir),
        framework=framework,
        build_script=_pick_build_script(package_json, framework),
        existing_output_entry=_find_output_html(package_dir, source_root),
    )


def prepare_js_project_after_import(project_dir: Path, source_root: Path) -> dict[str, Any]:
    """Detect JS tooling and prefer an existing build output when present."""
    info = detect_js_project(source_root)
    if not info:
        return write_build_status(
            project_dir,
            {"status": "skipped", "message": "No package.json detected.", "needsBuild": False},
        )
    if info.existing_output_entry:
        return write_build_status(
            project_dir,
            {
                "status": "succeeded",
                "message": f"Found existing build output at {info.existing_output_entry}.",
                "needsBuild": False,
                "framework": info.framework,
                "packageManager": info.package_manager,
                "packageDir": info.package_dir_rel,
                "outputEntry": info.existing_output_entry,
                "buildScript": info.build_script,
            },
        )
    if not js_build_enabled():
        return write_build_status(
            project_dir,
            {
                "status": "skipped",
                "message": "JS build is disabled on this server.",
                "needsBuild": False,
                "framework": info.framework,
                "packageManager": info.package_manager,
                "packageDir": info.package_dir_rel,
                "buildScript": info.build_script,
            },
        )
    if not info.build_script and info.framework == "node":
        return write_build_status(
            project_dir,
            {
                "status": "skipped",
                "message": "package.json found, but no supported build script was detected.",
                "needsBuild": False,
                "framework": info.framework,
                "packageManager": info.package_manager,
                "packageDir": info.package_dir_rel,
            },
        )
    return write_build_status(
        project_dir,
        {
            "status": "pending",
            "progress": 0,
            "phase": "pending",
            "message": f"Ready to install dependencies and build ({info.framework}).",
            "needsBuild": True,
            "framework": info.framework,
            "packageManager": info.package_manager,
            "packageDir": info.package_dir_rel,
            "buildScript": info.build_script or "build",
        },
    )


def _project_lock(project_id: str) -> threading.Lock:
    with _locks_guard:
        lock = _build_locks.get(project_id)
        if lock is None:
            lock = threading.Lock()
            _build_locks[project_id] = lock
        return lock


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str],
    on_progress: Callable[[int, str], None] | None = None,
    phase_low: int = 0,
    phase_high: int = 100,
    expected_seconds: int = 90,
) -> tuple[int, str]:
    """Run a command, optionally streaming progress updates via on_progress(percent, log_tail)."""
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        return 127, f"Command not found: {command[0]}"

    chunks: list[str] = []
    started = time.time()
    last_progress_write = 0.0
    current_progress = phase_low
    line_queue: queue.Queue[str | None] = queue.Queue()

    def _reader() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line_queue.put(line)
        finally:
            line_queue.put(None)

    def _bump_soft() -> None:
        nonlocal current_progress
        elapsed = time.time() - started
        soft = phase_low + (phase_high - phase_low) * min(0.92, elapsed / max(expected_seconds, 1))
        if soft > current_progress:
            current_progress = _clamp_progress(soft, phase_low, phase_high - 1)

    def _emit(force: bool = False) -> None:
        nonlocal last_progress_write
        now = time.time()
        if not on_progress:
            return
        if not force and (now - last_progress_write) < 0.75:
            return
        last_progress_write = now
        on_progress(current_progress, "".join(chunks)[-4000:])

    reader = threading.Thread(target=_reader, name="siaw-cmd-reader", daemon=True)
    reader.start()

    try:
        while True:
            if timeout and (time.time() - started) > timeout:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                chunks.append(f"\nTimed out after {timeout}s.")
                if on_progress:
                    on_progress(current_progress, "".join(chunks)[-4000:])
                return 124, "".join(chunks).strip()

            try:
                line = line_queue.get(timeout=0.25)
            except queue.Empty:
                _bump_soft()
                _emit()
                continue

            if line is None:
                break

            chunks.append(line)
            parsed = _progress_from_output(line, phase_low, phase_high)
            if parsed is not None and parsed > current_progress:
                current_progress = parsed
            else:
                _bump_soft()
            _emit()

        code = proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        raise
    finally:
        reader.join(timeout=2)

    output = "".join(chunks).strip()
    if on_progress:
        on_progress(
            _clamp_progress(phase_high if code == 0 else current_progress, phase_low, phase_high),
            output[-4000:],
        )
    return code, output


def _install_command(manager: str) -> list[str]:
    # Keep lifecycle scripts enabled so package bins (vite, next, etc.) are linked.
    if manager == "pnpm":
        return ["pnpm", "install", "--frozen-lockfile=false"]
    if manager == "yarn":
        return ["yarn", "install"]
    if manager == "bun":
        return ["bun", "install"]
    return ["npm", "install", "--no-audit", "--no-fund", "--prefer-online"]


def _vite_binary(package_dir: Path) -> Path | None:
    candidates = [
        package_dir / "node_modules" / "vite" / "bin" / "vite.js",
        package_dir / "node_modules" / "vite" / "bin" / "vite.mjs",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _build_command(manager: str, script: str, framework: str, package_dir: Path) -> list[str]:
    if framework == "vite":
        vite_bin = _vite_binary(package_dir)
        if vite_bin is not None:
            return ["node", str(vite_bin), "build"]
    if manager == "pnpm":
        return ["pnpm", "run", script]
    if manager == "yarn":
        return ["yarn", "run", script]
    if manager == "bun":
        return ["bun", "run", script]
    return ["npm", "run", script]


def activate_existing_ssr_preview(project_id: str, project_dir: Path, source_root: Path) -> dict[str, Any] | None:
    """Reuse an already-built Nitro/Node server without running npm install/build again."""
    info = detect_js_project(source_root)
    if not info:
        return None
    if _find_output_html(info.package_dir, source_root):
        return None
    from .preview_server import detect_ssr_preview, server_entry_rel, start_preview_server, stop_preview_server

    ssr = detect_ssr_preview(info.package_dir, source_root)
    if ssr is None:
        return None
    try:
        stop_preview_server(project_id)
        handle = start_preview_server(project_id, ssr)
    except Exception as exc:
        return write_build_status(
            project_dir,
            {
                "status": "failed",
                "needsBuild": True,
                "framework": info.framework,
                "packageManager": info.package_manager,
                "packageDir": info.package_dir_rel,
                "previewMode": "ssr",
                "previewKind": ssr.kind,
                "progress": 97,
                "phase": "preview",
                "message": f"Existing SSR build found, but preview failed to start: {exc}",
            },
        )
    return write_build_status(
        project_dir,
        {
            "status": "succeeded",
            "needsBuild": False,
            "framework": info.framework,
            "packageManager": info.package_manager,
            "packageDir": info.package_dir_rel,
            "buildScript": info.build_script or "build",
            "progress": 100,
            "phase": "done",
            "previewMode": "ssr",
            "previewKind": ssr.kind,
            "previewPort": handle.port,
            "serverEntry": server_entry_rel(ssr, source_root),
            "message": (
                f"Reused existing SSR build ({ssr.kind}). Opening the live website."
            ),
        },
    )


def run_js_build(project_id: str, project_dir: Path, source_root: Path) -> dict[str, Any]:
    lock = _project_lock(str(project_id))
    if not lock.acquire(blocking=False):
        status = read_build_status(project_dir)
        status["message"] = "A build is already running for this project."
        return status

    try:
        if not js_build_enabled():
            return write_build_status(
                project_dir,
                {"status": "skipped", "needsBuild": False, "message": "JS build is disabled."},
            )
        if not shutil.which("node") or not shutil.which("npm"):
            return write_build_status(
                project_dir,
                {
                    "status": "failed",
                    "needsBuild": True,
                    "message": "Node.js/npm is not available on this server.",
                },
            )

        info = detect_js_project(source_root)
        if not info:
            return write_build_status(
                project_dir,
                {"status": "skipped", "needsBuild": False, "message": "No package.json detected."},
            )

        base_status = {
            "status": "running",
            "needsBuild": True,
            "framework": info.framework,
            "packageManager": info.package_manager,
            "packageDir": info.package_dir_rel,
            "buildScript": info.build_script or "build",
        }

        def _update_progress(progress: int, message: str, log_tail: str = "", phase: str = "") -> None:
            write_build_status(
                project_dir,
                {
                    **base_status,
                    "progress": progress,
                    "phase": phase,
                    "message": message,
                    "logTail": log_tail,
                },
            )

        write_build_status(
            project_dir,
            {
                **base_status,
                "progress": 5,
                "phase": "install",
                "message": "Installing dependencies…",
                "logTail": "",
            },
        )

        timeout = int(getattr(settings, "JS_BUILD_TIMEOUT_SECONDS", 300))
        base_env = os.environ.copy()
        base_env["CI"] = "1"
        base_env["npm_config_fund"] = "false"
        base_env["npm_config_audit"] = "false"
        base_env["ADBLOCK"] = "1"
        # Important: do not set NODE_ENV=production during install, or npm skips
        # devDependencies (Vite, webpack, etc.).
        install_env = dict(base_env)
        install_env.pop("NODE_ENV", None)

        logs: list[str] = []
        install_cmd = _install_command(info.package_manager)

        def on_install_progress(percent: int, log_tail: str) -> None:
            _update_progress(
                percent,
                f"Installing dependencies… {percent}%",
                log_tail,
                phase="install",
            )

        code, output = _run_command(
            install_cmd,
            cwd=info.package_dir,
            timeout=timeout,
            env=install_env,
            on_progress=on_install_progress,
            phase_low=5,
            phase_high=60,
            expected_seconds=min(180, max(60, timeout // 2)),
        )
        logs.append("$ " + " ".join(install_cmd))
        logs.append(output)
        if code != 0:
            return write_build_status(
                project_dir,
                {
                    **base_status,
                    "status": "failed",
                    "progress": 60,
                    "phase": "install",
                    "message": "Dependency install failed.",
                    "logTail": "\n".join(logs)[-8000:],
                },
            )

        write_build_status(
            project_dir,
            {
                **base_status,
                "progress": 62,
                "phase": "build",
                "message": "Building production assets… 62%",
                "logTail": "\n".join(logs)[-4000:],
            },
        )

        script = info.build_script or "build"
        build_cmd = _build_command(info.package_manager, script, info.framework, info.package_dir)
        build_env = dict(base_env)
        build_env["NODE_ENV"] = "production"

        def on_build_progress(percent: int, log_tail: str) -> None:
            _update_progress(
                percent,
                f"Building production assets… {percent}%",
                log_tail,
                phase="build",
            )

        code, output = _run_command(
            build_cmd,
            cwd=info.package_dir,
            timeout=timeout,
            env=build_env,
            on_progress=on_build_progress,
            phase_low=62,
            phase_high=92,
            expected_seconds=min(120, max(30, timeout // 3)),
        )
        logs.append("$ " + " ".join(build_cmd))
        logs.append(output)

        # Next.js often needs `next export` for static HTML; try when build succeeded but no html.
        output_entry = _find_output_html(info.package_dir, source_root)
        if code == 0 and not output_entry and info.framework == "next":
            scripts = info.package_json.get("scripts") if isinstance(info.package_json.get("scripts"), dict) else {}
            if "export" in scripts:
                write_build_status(
                    project_dir,
                    {
                        **base_status,
                        "progress": 93,
                        "phase": "export",
                        "message": "Exporting static HTML… 93%",
                        "logTail": "\n".join(logs)[-4000:],
                    },
                )
                export_cmd = _build_command(info.package_manager, "export", info.framework, info.package_dir)
                code, output = _run_command(
                    export_cmd,
                    cwd=info.package_dir,
                    timeout=timeout,
                    env=build_env,
                    on_progress=lambda pct, tail: _update_progress(
                        pct, f"Exporting static HTML… {pct}%", tail, phase="export"
                    ),
                    phase_low=93,
                    phase_high=97,
                    expected_seconds=60,
                )
                logs.append("$ " + " ".join(export_cmd))
                logs.append(output)
                output_entry = _find_output_html(info.package_dir, source_root)

        if code != 0:
            return write_build_status(
                project_dir,
                {
                    **base_status,
                    "status": "failed",
                    "progress": 92,
                    "phase": "build",
                    "message": "Build command failed.",
                    "logTail": "\n".join(logs)[-8000:],
                },
            )

        write_build_status(
            project_dir,
            {
                **base_status,
                "progress": 96,
                "phase": "finalize",
                "message": "Locating build output… 96%",
                "logTail": "\n".join(logs)[-4000:],
            },
        )

        output_entry = output_entry or _find_output_html(info.package_dir, source_root)
        if not output_entry:
            # Nitro / TanStack Start / Nuxt-style builds emit a Node server, not static HTML.
            from .preview_server import detect_ssr_preview, server_entry_rel, start_preview_server, stop_preview_server

            ssr = detect_ssr_preview(info.package_dir, source_root)
            if ssr is not None:
                write_build_status(
                    project_dir,
                    {
                        **base_status,
                        "progress": 97,
                        "phase": "preview",
                        "message": "Starting SSR preview server… 97%",
                        "logTail": "\n".join(logs)[-4000:],
                        "previewMode": "ssr",
                        "previewKind": ssr.kind,
                    },
                )
                try:
                    stop_preview_server(project_id)
                    handle = start_preview_server(project_id, ssr)
                except Exception as exc:
                    return write_build_status(
                        project_dir,
                        {
                            **base_status,
                            "status": "failed",
                            "progress": 97,
                            "phase": "preview",
                            "previewMode": "ssr",
                            "previewKind": ssr.kind,
                            "message": f"Build succeeded, but SSR preview failed to start: {exc}",
                            "logTail": "\n".join(logs)[-8000:],
                        },
                    )
                return write_build_status(
                    project_dir,
                    {
                        **base_status,
                        "status": "succeeded",
                        "needsBuild": False,
                        "progress": 100,
                        "phase": "done",
                        "buildScript": script,
                        "previewMode": "ssr",
                        "previewKind": ssr.kind,
                        "previewPort": handle.port,
                        "serverEntry": server_entry_rel(ssr, source_root),
                        "packageDir": info.package_dir_rel,
                        "message": (
                            f"Build succeeded. SSR preview ({ssr.kind}) is running. "
                            "Opening the live website."
                        ),
                        "logTail": "\n".join(logs)[-8000:],
                    },
                )

            return write_build_status(
                project_dir,
                {
                    **base_status,
                    "status": "failed",
                    "progress": 96,
                    "phase": "finalize",
                    "message": "Build finished, but no HTML was found in dist/build/out.",
                    "logTail": "\n".join(logs)[-8000:],
                },
            )

        return write_build_status(
            project_dir,
            {
                **base_status,
                "status": "succeeded",
                "needsBuild": False,
                "progress": 100,
                "phase": "done",
                "buildScript": script,
                "previewMode": "static",
                "outputEntry": output_entry,
                "message": f"Build succeeded. Opening live preview for {output_entry}.",
                "logTail": "\n".join(logs)[-8000:],
            },
        )
    finally:
        lock.release()


def start_js_build_async(project_id: str, project_dir: Path, source_root: Path) -> dict[str, Any]:
    status = read_build_status(project_dir)
    if status.get("status") == "running":
        return status
    write_build_status(
        project_dir,
        {
            **status,
            "status": "running",
            "needsBuild": True,
            "progress": 2,
            "phase": "queued",
            "message": "Build queued… 2%",
        },
    )

    def worker() -> None:
        result = run_js_build(project_id, project_dir, source_root)
        if result.get("status") != "succeeded":
            return
        try:
            from builder.models import WebsiteProject
            from builder.services.archive import StylesheetParser

            project = WebsiteProject.objects.filter(id=project_id).first()
            if project is None:
                return
            # SSR previews do not produce a static HTML entry; keep source entry as-is.
            if result.get("previewMode") == "ssr":
                project.save(update_fields=["updated_at"])
                return
            output_entry = result.get("outputEntry")
            if not output_entry:
                return
            target = project.source_dir / output_entry
            if not target.is_file():
                return
            project.entry_file = output_entry
            parser = StylesheetParser()
            parser.feed(target.read_text(encoding="utf-8", errors="replace"))
            project.stylesheet_files = [
                href for href in parser.stylesheets
                if href.lower().startswith(("http://", "https://", "//"))
            ]
            project.save(update_fields=["entry_file", "stylesheet_files", "updated_at"])
        except Exception:
            # Status file already has the build result; editor can still point at outputEntry.
            return

    thread = threading.Thread(target=worker, name=f"siaw-js-build-{project_id}", daemon=True)
    thread.start()
    # Tiny delay so the first poll usually sees running.
    time.sleep(0.05)
    return read_build_status(project_dir)
