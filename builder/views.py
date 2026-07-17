from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.files import File
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import WebsiteUploadForm
from .models import WebsiteProject
from .services.archive import import_website_zip, safe_project_path
from .services.compatibility import analyze_website
from .services.navigation import apply_javascript_navigation, load_smart_navigation
from .services.html_tools import (
    build_dynamic_script_updates,
    editor_override_path,
    extract_document_context,
    extract_editable_body,
    hydrate_lazy_media,
    list_image_assets,
    load_smart_services,
    load_project_data,
    merge_editor_body,
    normalize_project_urls,
)

IMAGE_UPLOAD_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}


def _project_file_prefix(project: WebsiteProject) -> str:
    marker = "__SIAW_PATH__"
    url = reverse("builder:project_file", kwargs={"project_id": project.id, "file_path": marker})
    return url.replace(marker, "")


def _file_url(project: WebsiteProject, file_path: str) -> str:
    return reverse(
        "builder:project_file",
        kwargs={"project_id": project.id, "file_path": file_path},
    )


def _entry_directory(project: WebsiteProject) -> str:
    parent = PurePosixPath(project.entry_file).parent
    return "" if str(parent) == "." else parent.as_posix()


def _uses_local_runtime_hosts(request) -> bool:
    """Local browsers resolve *.localhost; production hosts need path-based runtime."""
    host = request.get_host().split(":", 1)[0].lower()
    return host in {"127.0.0.1", "localhost"} or host.endswith(".localhost")


def _isolated_runtime_url(request, project: WebsiteProject) -> str:
    """Serve each imported website from an isolated runtime origin when possible.

    Locally, each project uses a *.runtime.localhost subdomain so web apps get a
    working origin for localStorage without sharing the editor cookies or DOM.
    On deployed hosts without wildcard DNS, the same host is used with ?runtime=1.
    """
    version = int(project.updated_at.timestamp())
    path = _file_url(project, project.entry_file)
    if _uses_local_runtime_hosts(request):
        port = request.get_port()
        host = f"{project.id}.runtime.localhost"
        authority = f"{host}:{port}" if port else host
        return f"{request.scheme}://{authority}{path}?runtime=1&v={version}"
    return request.build_absolute_uri(f"{path}?runtime=1&v={version}")


@require_GET
def dashboard(request):
    return render(
        request,
        "builder/dashboard.html",
        {
            "projects": WebsiteProject.objects.all(),
            "form": WebsiteUploadForm(),
        },
    )


@require_POST
def upload_project(request):
    form = WebsiteUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(
            request,
            "builder/dashboard.html",
            {"projects": WebsiteProject.objects.all(), "form": form},
            status=400,
        )

    project = WebsiteProject.objects.create(name=form.cleaned_data["name"])
    try:
        imported = import_website_zip(form.cleaned_data["website_zip"], project.project_dir)
        project.entry_file = imported.entry_file
        project.stylesheet_files = imported.stylesheet_files
        project.save(update_fields=["entry_file", "stylesheet_files", "updated_at"])
    except ValidationError as exc:
        shutil.rmtree(project.project_dir, ignore_errors=True)
        project.delete()
        form.add_error("website_zip", exc.messages[0])
        return render(
            request,
            "builder/dashboard.html",
            {"projects": WebsiteProject.objects.all(), "form": form},
            status=400,
        )
    except Exception:
        shutil.rmtree(project.project_dir, ignore_errors=True)
        project.delete()
        raise

    messages.success(request, "Website imported successfully. The original ZIP was preserved.")
    return redirect("builder:editor", project_id=project.id)


@require_GET
def editor(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    config = {
        "projectId": str(project.id),
        "projectName": project.name,
        "dataUrl": reverse("builder:editor_data", args=[project.id]),
        "saveUrl": reverse("builder:save_project", args=[project.id]),
        "assetUploadUrl": reverse("builder:upload_asset", args=[project.id]),
        "previewUrl": reverse("builder:preview", args=[project.id]),
        "runtimeUrl": _isolated_runtime_url(request, project),
        "exportUrl": reverse("builder:export_project", args=[project.id]),
        "dashboardUrl": reverse("builder:dashboard"),
        "runtimeBridgeUrl": static("builder/runtime-bridge.js"),
    }
    return render(request, "builder/editor.html", {"project": project, "editor_config": config})


@require_GET
def editor_data(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    if not project.entry_path.is_file():
        return JsonResponse({"error": "The project entry file is missing."}, status=404)

    html_text = project.entry_path.read_text(encoding="utf-8", errors="replace")
    editable_body, _scripts = extract_editable_body(html_text)
    editable_body, hydrated_lazy_media = hydrate_lazy_media(editable_body)
    document_context = extract_document_context(html_text)
    prefix = _project_file_prefix(project)
    entry_dir = _entry_directory(project)

    canvas_styles: list[str] = []
    for stylesheet in project.stylesheet_files:
        lowered = stylesheet.lower()
        if lowered.startswith(("http://", "https://", "//")):
            canvas_styles.append(stylesheet)
        else:
            canvas_styles.append(request.build_absolute_uri(_file_url(project, stylesheet)))

    # Editor-only CSS reveals scroll-animated content while JavaScript is disabled.
    # It is loaded only inside GrapesJS and is never written into the website export.
    canvas_styles.append(request.build_absolute_uri(static("builder/canvas-fixes.css")))

    saved_project_data = load_project_data(project.project_data_path)
    override_target, _override_href = editor_override_path(project.entry_file)
    override_source_path = project.source_dir / override_target
    # When project JSON exists, GrapesJS already restores the visual override styles.
    # Load the exported override CSS only as a fallback when JSON is unavailable.
    if override_source_path.is_file() and not saved_project_data:
        override_relative = override_target.as_posix()
        canvas_styles.append(request.build_absolute_uri(_file_url(project, override_relative)))

    assets = []
    for relative_path in list_image_assets(project.source_dir):
        assets.append(
            {
                "src": request.build_absolute_uri(_file_url(project, relative_path)),
                "name": Path(relative_path).name,
                "relativePath": relative_path,
            }
        )

    base_path = prefix + (entry_dir.rstrip("/") + "/" if entry_dir else "")
    smart_services = load_smart_services(project.source_dir, html_text)
    smart_navigation = load_smart_navigation(project.source_dir, project.entry_file, html_text)
    compatibility = analyze_website(project.source_dir, project.entry_file, html_text)
    # Backward-compatible fields used by the MVP 3 Smart panel.
    compatibility["externalStyleCount"] = compatibility.get("linkedStyleCount", 0)
    compatibility["selfContained"] = bool(document_context.inline_styles) and not any(
        not str(item).lower().startswith(("http://", "https://", "//"))
        for item in project.stylesheet_files
    )
    compatibility["hydratedLazyMediaCount"] = hydrated_lazy_media

    payload = {
        "html": editable_body,
        "projectData": saved_project_data,
        "canvasStyles": canvas_styles,
        "assetBaseUrl": request.build_absolute_uri(base_path),
        "runtimeUrl": _isolated_runtime_url(request, project),
        "projectFilePrefix": prefix,
        "assets": assets,
        "entryFile": project.entry_file,
        "inlineStyles": document_context.inline_styles,
        "htmlAttributes": document_context.html_attributes,
        "bodyAttributes": document_context.body_attributes,
        "compatibility": compatibility,
        "smartServices": smart_services,
        "smartNavigation": smart_navigation,
    }
    return JsonResponse(payload)


@require_POST
def save_project(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid save data."}, status=400)

    edited_html = payload.get("html")
    generated_css = payload.get("css", "")
    project_data = payload.get("projectData")
    smart_services = payload.get("smartServices")
    smart_navigation = payload.get("smartNavigation")
    if not isinstance(edited_html, str) or not isinstance(generated_css, str) or not isinstance(project_data, dict):
        return JsonResponse({"error": "Incomplete editor data."}, status=400)

    prefix = _project_file_prefix(project)
    origin = f"{request.scheme}://{request.get_host()}"
    entry_dir = _entry_directory(project)
    normalized_html = normalize_project_urls(
        edited_html,
        project_file_prefix=prefix,
        origin=origin,
        entry_dir=entry_dir,
    )
    normalized_css = normalize_project_urls(
        generated_css,
        project_file_prefix=prefix,
        origin=origin,
        entry_dir=entry_dir,
    )
    normalized_project_data = normalize_project_urls(
        project_data,
        project_file_prefix=prefix,
        origin=origin,
        entry_dir=entry_dir,
    )

    if not project.entry_path.is_file():
        return JsonResponse({"error": "The project entry file is missing."}, status=404)

    current_html = project.entry_path.read_text(encoding="utf-8", errors="replace")
    dynamic_updates, synced_dynamic_fields = build_dynamic_script_updates(
        project.source_dir,
        normalized_html,
        smart_services=normalize_project_urls(
            smart_services,
            project_file_prefix=prefix,
            origin=origin,
            entry_dir=entry_dir,
        ),
    )
    normalized_navigation = normalize_project_urls(
        smart_navigation,
        project_file_prefix=prefix,
        origin=origin,
        entry_dir=entry_dir,
    )
    current_html, navigation_updates, navigation_synced = apply_javascript_navigation(
        project.source_dir,
        current_html,
        normalized_navigation,
        source_overrides=dynamic_updates,
    )
    dynamic_updates.update(navigation_updates)
    synced_dynamic_fields = navigation_synced + synced_dynamic_fields

    override_target, override_href = editor_override_path(project.entry_file)
    merged_html = merge_editor_body(current_html, normalized_html, override_href)

    override_path = project.source_dir / override_target
    override_path.parent.mkdir(parents=True, exist_ok=True)
    project.editor_dir.mkdir(parents=True, exist_ok=True)

    html_tmp = project.entry_path.with_suffix(project.entry_path.suffix + ".tmp")
    css_tmp = override_path.with_suffix(override_path.suffix + ".tmp")
    json_tmp = project.project_data_path.with_suffix(".json.tmp")
    dynamic_temps: list[tuple[Path, Path]] = []

    html_tmp.write_text(merged_html, encoding="utf-8")
    css_tmp.write_text(normalized_css.strip() + "\n", encoding="utf-8")
    json_tmp.write_text(json.dumps(normalized_project_data, indent=2), encoding="utf-8")
    for target_path, content in dynamic_updates.items():
        temporary_path = target_path.with_suffix(target_path.suffix + ".tmp")
        temporary_path.write_text(content, encoding="utf-8")
        dynamic_temps.append((temporary_path, target_path))

    os.replace(html_tmp, project.entry_path)
    os.replace(css_tmp, override_path)
    os.replace(json_tmp, project.project_data_path)
    for temporary_path, target_path in dynamic_temps:
        os.replace(temporary_path, target_path)

    project.save(update_fields=["updated_at"])
    message = "Project saved."
    if synced_dynamic_fields:
        message += " Synced: " + ", ".join(synced_dynamic_fields) + "."
    return JsonResponse({"ok": True, "message": message, "synced": synced_dynamic_fields})


@require_POST
def upload_asset(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    uploaded = request.FILES.get("file")
    if uploaded is None:
        return JsonResponse({"error": "No image was uploaded."}, status=400)
    if uploaded.size > 10 * 1024 * 1024:
        return JsonResponse({"error": "Images must be 10 MB or smaller."}, status=400)

    suffix = Path(uploaded.name).suffix.lower()
    if suffix not in IMAGE_UPLOAD_SUFFIXES:
        return JsonResponse({"error": "Unsupported image format."}, status=400)

    safe_name = get_valid_filename(Path(uploaded.name).name) or f"image{suffix}"
    target_dir = project.source_dir / "images" / "uploads"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_name
    stem = target.stem
    counter = 2
    while target.exists():
        target = target_dir / f"{stem}-{counter}{suffix}"
        counter += 1

    with target.open("wb") as output:
        for chunk in uploaded.chunks():
            output.write(chunk)

    relative = target.relative_to(project.source_dir).as_posix()
    return JsonResponse(
        {
            "data": [
                {
                    "src": request.build_absolute_uri(_file_url(project, relative)),
                    "name": target.name,
                    "relativePath": relative,
                }
            ]
        }
    )


@require_GET
def preview(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    return render(
        request,
        "builder/preview.html",
        {
            "project": project,
            "preview_src": _isolated_runtime_url(request, project),
        },
    )


@require_GET
def project_file(request, project_id, file_path):
    project = get_object_or_404(WebsiteProject, id=project_id)
    try:
        target = safe_project_path(project.source_dir, file_path)
    except FileNotFoundError as exc:
        raise Http404 from exc
    if not target.is_file():
        raise Http404

    content_type, _encoding = mimetypes.guess_type(target.name)
    content_type = content_type or "application/octet-stream"
    request_host = request.get_host().split(":", 1)[0].lower()
    isolated_host = f"{project.id}.runtime.localhost"
    isolated_runtime = request_host == isolated_host or request.GET.get("runtime") == "1"

    if isolated_runtime and target.resolve() == project.entry_path.resolve() and target.suffix.lower() in {".html", ".htm"}:
        html_text = target.read_text(encoding="utf-8", errors="replace")
        bridge = (
            f'<script src="{static("builder/runtime-bridge.js")}" '
            f'data-siaw-runtime-bridge="true" data-project-id="{project.id}"></script>'
        )
        if re.search(r"</body\s*>", html_text, re.I):
            html_text = re.sub(r"</body\s*>", bridge + "\n</body>", html_text, count=1, flags=re.I)
        else:
            html_text += bridge
        response = HttpResponse(html_text, content_type=content_type)
    else:
        response = FileResponse(target.open("rb"), content_type=content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"

    if target.suffix.lower() in {".html", ".htm", ".svg"}:
        sandbox_tokens = "allow-scripts allow-forms allow-popups allow-modals allow-downloads"
        if isolated_runtime:
            # The unique per-project origin safely enables localStorage and other
            # normal browser APIs required by imported web applications.
            sandbox_tokens += " allow-same-origin"
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
            + ("frame-ancestors *; " if isolated_runtime else "frame-ancestors 'self'; ")
            + f"sandbox {sandbox_tokens}"
        )
    return response


@require_GET
def export_project(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in project.source_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(project.source_dir).as_posix())
    output.seek(0)
    safe_project_name = get_valid_filename(project.name).replace(" ", "_") or "website"
    response = HttpResponse(output.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{safe_project_name}_edited.zip"'
    return response


@require_POST
def restore_original(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    if not project.original_zip_path.is_file():
        messages.error(request, "The original backup ZIP is missing.")
        return redirect("builder:editor", project_id=project.id)

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        shutil.copy2(project.original_zip_path, temporary_path)
        with temporary_path.open("rb") as source:
            imported = import_website_zip(File(source, name="original.zip"), project.project_dir)
        project.entry_file = imported.entry_file
        project.stylesheet_files = imported.stylesheet_files
        project.save(update_fields=["entry_file", "stylesheet_files", "updated_at"])
        shutil.rmtree(project.editor_dir, ignore_errors=True)
        project.editor_dir.mkdir(parents=True, exist_ok=True)
        messages.success(request, "The project was restored from its original ZIP backup.")
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    finally:
        temporary_path.unlink(missing_ok=True)
    return redirect("builder:editor", project_id=project.id)
