"""Serve built websites from a real web root (Lovable-style preview).

Vite/React apps emit absolute asset paths like /assets/index-abc.js. Those only
work when the preview origin serves the build folder as /. Locally we use
{project}.runtime.localhost. On hosts without wildcard DNS we use
/projects/<id>/site/ and rewrite root-absolute asset tags in the entry HTML.
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from django.http import FileResponse, Http404, HttpResponse
from django.templatetags.static import static

from .js_build import read_build_status
from .preview_server import proxy_upstream_url, restart_ssr_from_status

if TYPE_CHECKING:
    from django.http import HttpRequest

    from builder.models import WebsiteProject

RUNTIME_HOST_SUFFIX = ".runtime.localhost"

ASSET_SUFFIXES = {
    ".js", ".mjs", ".cjs", ".css", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif", ".bmp",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".webm", ".ogg", ".mp3", ".wav", ".json", ".wasm", ".txt",
}

ROOT_ABS_REF_RE = re.compile(
    r"""(?P<prefix>\b(?:src|href)\s*=\s*)(?P<quote>['"])/(?!/)(?P<path>[^'"]+)(?P=quote)""",
    re.IGNORECASE,
)
ROOT_ABS_URL_FUNC_RE = re.compile(
    r"""(?P<prefix>\burl\(\s*)(?P<quote>['"]?)/(?!/)(?P<path>[^'")\s]+)(?P=quote)\s*\)""",
    re.IGNORECASE,
)


def parse_runtime_project_id(host: str) -> str | None:
    hostname = (host or "").split(":", 1)[0].lower()
    if not hostname.endswith(RUNTIME_HOST_SUFFIX):
        return None
    candidate = hostname[: -len(RUNTIME_HOST_SUFFIX)]
    try:
        return str(UUID(candidate))
    except (ValueError, TypeError):
        return None


def entry_web_root(project: WebsiteProject) -> Path:
    entry = project.source_dir / project.entry_file
    if entry.is_file():
        return entry.parent
    return project.source_dir


def should_rewrite_root_path(path: str) -> bool:
    cleaned = path.lstrip("/")
    if not cleaned or cleaned.startswith(("http:", "https:", "//")):
        return False
    lower = cleaned.lower()
    if lower.startswith(("assets/", "static/", "css/", "js/", "media/", "fonts/", "images/", "img/")):
        return True
    suffix = Path(cleaned).suffix.lower()
    return suffix in ASSET_SUFFIXES


def rewrite_root_absolute_assets(html_text: str) -> str:
    """Turn /assets/foo.js into assets/foo.js so path-based /site/ previews work."""

    def repl_attr(match: re.Match[str]) -> str:
        path = match.group("path")
        if not should_rewrite_root_path(path):
            return match.group(0)
        return f'{match.group("prefix")}{match.group("quote")}{path.lstrip("/")}{match.group("quote")}'

    def repl_url(match: re.Match[str]) -> str:
        path = match.group("path")
        if not should_rewrite_root_path(path):
            return match.group(0)
        quote = match.group("quote") or ""
        return f'{match.group("prefix")}{quote}{path.lstrip("/")}{quote})'

    html_text = ROOT_ABS_REF_RE.sub(repl_attr, html_text)
    return ROOT_ABS_URL_FUNC_RE.sub(repl_url, html_text)


def resolve_runtime_file(project: WebsiteProject, asset_path: str) -> Path | None:
    """Resolve a URL path against the entry web root, then the project source root."""
    relative = PurePosixPath(asset_path.replace("\\", "/").lstrip("/"))
    if relative.is_absolute() or ".." in relative.parts:
        return None
    if not relative.parts:
        return None

    candidates = [
        entry_web_root(project) / Path(*relative.parts),
        project.source_dir / Path(*relative.parts),
    ]
    source_root = project.source_dir.resolve()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(source_root)
        except (OSError, ValueError):
            continue
        if resolved.is_file():
            return resolved
    return None


def _inject_runtime_bridge(html_text: str, project: WebsiteProject) -> str:
    bridge = (
        f'<script src="{static("builder/runtime-bridge.js")}" '
        f'data-siaw-runtime-bridge="true" data-project-id="{project.id}"></script>'
    )
    if re.search(r"</body\s*>", html_text, re.I):
        return re.sub(r"</body\s*>", bridge + "\n</body>", html_text, count=1, flags=re.I)
    return html_text + bridge


def _runtime_headers(response: HttpResponse, *, framing: bool = True) -> HttpResponse:
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    if framing:
        # Preview iframe may be cross-origin (runtime subdomain).
        response["X-Frame-Options"] = "ALLOWALL"
        response["Cross-Origin-Resource-Policy"] = "cross-origin"
        response["Content-Security-Policy"] = (
            "default-src 'none'; "
            "img-src 'self' data: blob: https:; "
            "media-src 'self' data: blob: https:; "
            "style-src 'self' 'unsafe-inline' https:; "
            "font-src 'self' data: https:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
            "connect-src 'self' https:; "
            "frame-src 'self' https:; "
            "form-action 'self' https: mailto:; "
            "base-uri 'self'; "
            "frame-ancestors *; "
            "sandbox allow-scripts allow-forms allow-popups allow-modals allow-downloads allow-same-origin"
        )
    return response


def build_entry_html_response(
    project: WebsiteProject,
    *,
    rewrite_absolute_assets: bool = False,
) -> HttpResponse:
    entry = project.source_dir / project.entry_file
    if not entry.is_file():
        raise Http404("Project entry file is missing.")
    html_text = entry.read_text(encoding="utf-8", errors="replace")
    if rewrite_absolute_assets:
        html_text = rewrite_root_absolute_assets(html_text)
    html_text = _inject_runtime_bridge(html_text, project)
    content_type, _ = mimetypes.guess_type(entry.name)
    response = HttpResponse(html_text, content_type=content_type or "text/html")
    return _runtime_headers(response)


def build_asset_response(target: Path) -> HttpResponse:
    content_type, _ = mimetypes.guess_type(target.name)
    response = FileResponse(target.open("rb"), content_type=content_type or "application/octet-stream")
    return _runtime_headers(response, framing=target.suffix.lower() in {".html", ".htm", ".svg"})


def _proxy_ssr_response(
    request: HttpRequest,
    project: WebsiteProject,
    asset_path: str = "",
) -> HttpResponse | None:
    """Proxy Nitro/TanStack SSR previews through the runtime origin."""
    status = read_build_status(project.project_dir)
    if status.get("previewMode") != "ssr" or status.get("status") != "succeeded":
        return None

    upstream = proxy_upstream_url(str(project.id), asset_path)
    if upstream is None:
        try:
            restart_ssr_from_status(str(project.id), project.source_dir, status)
        except Exception:
            return HttpResponse(
                "SSR preview server is not running. Open the editor and retry the build.",
                status=503,
                content_type="text/plain",
            )
        upstream = proxy_upstream_url(str(project.id), asset_path)
        if upstream is None:
            return HttpResponse(
                "SSR preview server could not be restarted.",
                status=503,
                content_type="text/plain",
            )

    query = request.META.get("QUERY_STRING") or ""
    # Drop cache-buster only used by our preview chrome.
    if query:
        parts = [item for item in query.split("&") if item and not item.startswith("v=")]
        if parts:
            upstream = f"{upstream}{'&' if '?' in upstream else '?'}{'&'.join(parts)}"

    try:
        upstream_request = Request(
            upstream,
            headers={
                "Accept": request.headers.get("Accept", "*/*"),
                "User-Agent": request.headers.get("User-Agent", "SiawRuntimeProxy/1.0"),
            },
            method="GET",
        )
        with urlopen(upstream_request, timeout=30) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type") or "application/octet-stream"
            status_code = getattr(response, "status", 200)
    except HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        content_type = exc.headers.get("Content-Type") if exc.headers else "text/plain"
        status_code = exc.code
    except (URLError, OSError, TimeoutError) as exc:
        return HttpResponse(
            f"SSR preview proxy error: {exc}",
            status=502,
            content_type="text/plain",
        )

    if "text/html" in (content_type or "").lower():
        html_text = body.decode("utf-8", errors="replace")
        html_text = _inject_runtime_bridge(html_text, project)
        django_response = HttpResponse(html_text, status=status_code, content_type=content_type)
    else:
        django_response = HttpResponse(body, status=status_code, content_type=content_type)
    return _runtime_headers(django_response, framing="text/html" in (content_type or "").lower())


def serve_runtime_request(
    request: HttpRequest,
    project: WebsiteProject,
    asset_path: str = "",
    *,
    rewrite_absolute_assets: bool = False,
) -> HttpResponse:
    """Serve / or /assets/... as if the build folder were the website root."""
    proxied = _proxy_ssr_response(request, project, asset_path)
    if proxied is not None:
        return proxied

    cleaned = (asset_path or "").replace("\\", "/").lstrip("/")
    if not cleaned or cleaned.endswith("/"):
        return build_entry_html_response(project, rewrite_absolute_assets=rewrite_absolute_assets)

    target = resolve_runtime_file(project, cleaned)
    if target is not None:
        if target.suffix.lower() in {".html", ".htm"}:
            html_text = target.read_text(encoding="utf-8", errors="replace")
            if rewrite_absolute_assets:
                html_text = rewrite_root_absolute_assets(html_text)
            # Only inject bridge on the main entry to avoid double-injection on other pages.
            if target.resolve() == (project.source_dir / project.entry_file).resolve():
                html_text = _inject_runtime_bridge(html_text, project)
            content_type, _ = mimetypes.guess_type(target.name)
            return _runtime_headers(HttpResponse(html_text, content_type=content_type or "text/html"))
        return build_asset_response(target)

    # SPA client-router fallback: unknown paths without a file extension get the entry HTML.
    suffix = Path(cleaned).suffix.lower()
    if not suffix or suffix in {".html", ".htm"}:
        return build_entry_html_response(project, rewrite_absolute_assets=rewrite_absolute_assets)
    raise Http404("Runtime asset not found.")
