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
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.core.files import File
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from django.conf import settings as django_settings

from .forms import LoginForm, SignUpForm, WebsiteGenerateForm, WebsiteUploadForm
from .models import WebsiteProject
from .services.archive import (
    StylesheetParser,
    import_website_zip,
    is_html_path,
    is_text_path,
    list_source_files,
    safe_project_path,
)
from .services.ai_builder import ai_configured, ai_status, create_website_from_prompt
from .services.editor_assets import materialize_entry_for_visual_editor
from .services.route_capture import (
    collect_stylesheet_refs,
    rewrite_html_for_editor_entry,
    save_captured_route,
)
from .services.compatibility import analyze_website
from .services.js_build import (
    activate_existing_ssr_preview,
    prepare_js_project_after_import,
    read_build_status,
    start_js_build_async,
    run_js_build,
    write_build_status,
)
from .services.runtime_site import serve_runtime_request
from .services.export_validation import validate_export
from .services.navigation import apply_javascript_navigation, load_smart_navigation
from .services.pages import (
    add_blank_page,
    describe_site_pages,
    duplicate_page,
    list_html_pages,
    rename_page,
)
from .services.snapshots import create_snapshot, list_snapshots, restore_snapshot
from .services.html_tools import (
    build_dynamic_script_updates,
    editor_override_path,
    extract_document_context,
    extract_editable_body,
    extract_hero_photos,
    extract_reviews,
    guard_hero_carousel_script,
    hydrate_js_hero_carousel,
    hydrate_js_reviews,
    hydrate_lazy_media,
    list_image_assets,
    load_smart_services,
    load_project_data,
    materialize_hero_photo_files,
    merge_editor_body,
    normalize_project_urls,
    normalize_slideshow_photos,
    sync_js_interactive_arrays,
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
    return host in {"127.0.0.1", "localhost", "testserver"} or host.endswith(".localhost")


def _prefer_preview_landing(project: WebsiteProject, build_status: dict | None = None) -> bool:
    """True when the imported/built site should open Live Preview instead of Safe Edit."""
    status = build_status if build_status is not None else read_build_status(project.project_dir)
    if status.get("needsBuild") or status.get("status") in {"pending", "running"}:
        return False
    # Nitro / TanStack Start SSR builds have no static HTML entry.
    if status.get("previewMode") == "ssr" and status.get("status") == "succeeded":
        return True
    if not is_html_path(project.entry_file) or not project.entry_path.is_file():
        return False
    # Still pointing at the Vite/build shell: prefer live preview without waiting on heuristics.
    output_entry = status.get("outputEntry")
    if output_entry and project.entry_file == output_entry:
        return True
    try:
        report = analyze_website(
            project.source_dir,
            project.entry_file,
            project.entry_path.read_text(encoding="utf-8", errors="replace"),
        )
    except Exception:
        return False
    return bool(report.get("preferLivePreview") or report.get("spaShell", {}).get("isSpaShell"))


def _isolated_runtime_url(request, project: WebsiteProject) -> str:
    """Serve each imported website from an isolated runtime origin when possible.

    Locally, each project uses a *.runtime.localhost subdomain with the build folder
    mounted at /, so Vite absolute /assets paths work like a real deploy.
    On deployed hosts without wildcard DNS, /projects/<id>/site/ is used and the
    entry HTML is rewritten to relative asset paths.
    """
    version = int(project.updated_at.timestamp()) if getattr(project, "updated_at", None) else 0
    if _uses_local_runtime_hosts(request):
        port = request.get_port()
        host = f"{project.id}.runtime.localhost"
        authority = f"{host}:{port}" if port else host
        return f"{request.scheme}://{authority}/?v={version}"
    site_path = reverse("builder:runtime_site", args=[project.id])
    return request.build_absolute_uri(f"{site_path}?v={version}")


def _dashboard_context(**extra):
    from .services.thumbnails import attach_project_thumbnails

    projects = list(WebsiteProject.objects.all())
    context = {
        "projects": projects,
        "project_rows": attach_project_thumbnails(projects),
        "form": WebsiteUploadForm(),
        "generate_form": WebsiteGenerateForm(),
        "ai_configured": ai_configured(),
        "ai_status": ai_status(),
        "active_create_tab": "ai",
    }
    context.update(extra)
    return context


@require_GET
def dashboard(request):
    return render(request, "builder/dashboard.html", _dashboard_context())


@require_GET
def pricing(request):
    return render(request, "builder/pricing.html")


class UserLoginView(LoginView):
    template_name = "builder/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("builder:dashboard")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        auth_login(request, user)
        messages.success(request, "Welcome to Siaw. Your account is ready.")
        return redirect("builder:dashboard")
    return render(request, "builder/signup.html", {"form": form})


@require_http_methods(["GET", "POST"])
def logout_view(request):
    if request.user.is_authenticated:
        auth_logout(request)
        messages.info(request, "You are logged out.")
    return redirect("builder:dashboard")


@require_POST
def generate_project(request):
    form = WebsiteGenerateForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "builder/dashboard.html",
            _dashboard_context(generate_form=form, active_create_tab="ai"),
            status=400,
        )

    project = WebsiteProject.objects.create(name=form.cleaned_data["name"])
    try:
        generated = create_website_from_prompt(
            project.project_dir,
            prompt=form.cleaned_data["prompt"],
            project_name=form.cleaned_data["name"],
            force_offline=bool(getattr(django_settings, "SIAW_AI_FORCE_OFFLINE", False)),
        )
        project.entry_file = generated.entry_file
        project.stylesheet_files = generated.stylesheet_files
        project.save(update_fields=["entry_file", "stylesheet_files", "updated_at"])
    except ValidationError as exc:
        shutil.rmtree(project.project_dir, ignore_errors=True)
        project.delete()
        form.add_error(None, exc.messages[0] if getattr(exc, "messages", None) else str(exc))
        return render(
            request,
            "builder/dashboard.html",
            _dashboard_context(generate_form=form, active_create_tab="ai"),
            status=400,
        )
    except Exception:
        shutil.rmtree(project.project_dir, ignore_errors=True)
        project.delete()
        raise

    if generated.provider == "ollama":
        provider_label = "Ollama"
    elif generated.provider == "openai":
        provider_label = "OpenAI"
    else:
        provider_label = "built-in design engine"
    messages.success(
        request,
        f"Created '{project.name}' with {provider_label}. Edit anything in Safe Edit, then export.",
    )
    return redirect(f"{reverse('builder:editor', args=[project.id])}?mode=safe")


@require_POST
def upload_project(request):
    form = WebsiteUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(
            request,
            "builder/dashboard.html",
            _dashboard_context(form=form, active_create_tab="import"),
            status=400,
        )

    project = WebsiteProject.objects.create(name=form.cleaned_data["name"])
    preferred_entry = form.cleaned_data.get("entry_file") or None
    try:
        imported = import_website_zip(
            form.cleaned_data["website_zip"],
            project.project_dir,
            preferred_entry=preferred_entry,
        )

        project.entry_file = imported.entry_file
        project.stylesheet_files = imported.stylesheet_files

        build_status = prepare_js_project_after_import(project.project_dir, project.source_dir)
        output_entry = build_status.get("outputEntry")
        if output_entry and (project.source_dir / output_entry).is_file():
            project.entry_file = output_entry
            parser = StylesheetParser()
            parser.feed((project.source_dir / output_entry).read_text(encoding="utf-8", errors="replace"))
            project.stylesheet_files = [
                href for href in parser.stylesheets
                if href.lower().startswith(("http://", "https://", "//"))
            ]

        project.save(update_fields=["entry_file", "stylesheet_files", "updated_at"])
    except ValidationError as exc:
        shutil.rmtree(project.project_dir, ignore_errors=True)
        project.delete()
        form.add_error("website_zip", exc.messages[0])
        return render(
            request,
            "builder/dashboard.html",
            _dashboard_context(form=form, active_create_tab="import"),
            status=400,
        )
    except Exception:
        shutil.rmtree(project.project_dir, ignore_errors=True)
        project.delete()
        raise

    if build_status.get("needsBuild"):
        messages.success(
            request,
            "Imported successfully. Installing dependencies and building, then opening the live website preview.",
        )
        return redirect("builder:editor", project_id=project.id)

    if _prefer_preview_landing(project, build_status):
        messages.success(
            request,
            "Imported successfully. Opening the live website preview.",
        )
        return redirect("builder:preview", project_id=project.id)

    messages.success(request, "Imported successfully.")
    return redirect("builder:editor", project_id=project.id)


@require_POST
def delete_project(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    name = project.name
    try:
        from .services.preview_server import stop_preview_server

        stop_preview_server(str(project.id))
    except Exception:
        pass
    shutil.rmtree(project.project_dir, ignore_errors=True)
    project.delete()
    messages.success(request, f'Deleted "{name}".')
    return redirect("builder:dashboard")


@require_GET
def editor(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    js_build = read_build_status(project.project_dir)
    ssr_preview = js_build.get("previewMode") == "ssr" and js_build.get("status") == "succeeded"
    visual_mode = is_html_path(project.entry_file) or ssr_preview
    prefer_live = _prefer_preview_landing(project, js_build)
    requested_mode = (request.GET.get("mode") or "").strip().lower()
    if requested_mode not in {"interactive", "safe", "code"}:
        requested_mode = "interactive" if prefer_live and visual_mode else ("visual" if visual_mode else "code")
    config = {
        "projectId": str(project.id),
        "projectName": project.name,
        "entryFile": project.entry_file,
        "editorMode": "visual" if visual_mode else "code",
        "defaultViewMode": requested_mode,
        "preferLivePreview": prefer_live,
        "ssrPreview": ssr_preview,
        "dataUrl": reverse("builder:editor_data", args=[project.id]),
        "saveUrl": reverse("builder:save_project", args=[project.id]),
        "filesUrl": reverse("builder:project_files", args=[project.id]),
        "sourceFileUrlTemplate": reverse(
            "builder:source_file",
            kwargs={"project_id": project.id, "file_path": "__SIAW_PATH__"},
        ),
        "setEntryUrl": reverse("builder:set_entry_file", args=[project.id]),
        "captureRouteUrl": reverse("builder:capture_route", args=[project.id]),
        "assetUploadUrl": reverse("builder:upload_asset", args=[project.id]),
        "previewUrl": reverse("builder:preview", args=[project.id]),
        "runtimeUrl": _isolated_runtime_url(request, project),
        "exportUrl": reverse("builder:export_project", args=[project.id]),
        "exportValidateUrl": reverse("builder:export_validate", args=[project.id]),
        "pagesUrl": reverse("builder:project_pages", args=[project.id]),
        "snapshotsUrl": reverse("builder:project_snapshots", args=[project.id]),
        "buildStatusUrl": reverse("builder:build_status", args=[project.id]),
        "buildStartUrl": reverse("builder:build_start", args=[project.id]),
        "buildSkipUrl": reverse("builder:build_skip", args=[project.id]),
        "dashboardUrl": reverse("builder:dashboard"),
        "runtimeBridgeUrl": static("builder/runtime-bridge.js"),
        "jsBuild": js_build,
    }
    return render(request, "builder/editor.html", {"project": project, "editor_config": config})


def _apply_build_output_entry(project: WebsiteProject, build_status: dict) -> bool:
    if build_status.get("previewMode") == "ssr":
        return False
    output_entry = build_status.get("outputEntry")
    if not output_entry:
        return False
    target = project.source_dir / output_entry
    if not target.is_file():
        return False
    project.entry_file = output_entry
    parser = StylesheetParser()
    parser.feed(target.read_text(encoding="utf-8", errors="replace"))
    project.stylesheet_files = [
        href for href in parser.stylesheets
        if href.lower().startswith(("http://", "https://", "//"))
    ]
    project.save(update_fields=["entry_file", "stylesheet_files", "updated_at"])
    return True


@require_GET
def build_status(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    status = read_build_status(project.project_dir)
    status["entryFile"] = project.entry_file
    return JsonResponse(status)


@require_POST
def build_start(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    sync = str(request.GET.get("sync") or "").lower() in {"1", "true", "yes"}
    reuse = str(request.GET.get("reuse") or "").lower() in {"1", "true", "yes"}
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        payload = {}
    if isinstance(payload, dict) and payload.get("reuseExisting"):
        reuse = True

    status = None
    if reuse:
        status = activate_existing_ssr_preview(str(project.id), project.project_dir, project.source_dir)

    if status is None:
        if sync:
            status = run_js_build(str(project.id), project.project_dir, project.source_dir)
        else:
            status = start_js_build_async(str(project.id), project.project_dir, project.source_dir)
    if status.get("status") == "succeeded":
        _apply_build_output_entry(project, status)
        status = read_build_status(project.project_dir)
        status["entryFile"] = project.entry_file
        status["reload"] = True
        if status.get("previewMode") == "ssr":
            status["openPreview"] = True
    return JsonResponse(status)


@require_POST
def build_skip(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    current = read_build_status(project.project_dir)
    status = write_build_status(
        project.project_dir,
        {
            **current,
            "status": "skipped",
            "needsBuild": False,
            "message": "Build skipped. You can still edit source files, or retry the build later.",
        },
    )
    status["entryFile"] = project.entry_file
    return JsonResponse(status)


@require_GET
def editor_data(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    if not project.entry_path.is_file():
        return JsonResponse({"error": "The project entry file is missing."}, status=404)

    files = list_source_files(project.source_dir)
    build_status = read_build_status(project.project_dir)
    ssr_preview = build_status.get("previewMode") == "ssr" and build_status.get("status") == "succeeded"
    if not is_html_path(project.entry_file) and not ssr_preview:
        content = ""
        if is_text_path(project.entry_file):
            content = project.entry_path.read_text(encoding="utf-8", errors="replace")
        return JsonResponse(
            {
                "mode": "code",
                "entryFile": project.entry_file,
                "content": content,
                "files": files,
                "runtimeUrl": _isolated_runtime_url(request, project),
                "canVisualEdit": False,
                "canPreview": False,
            }
        )

    if ssr_preview and not is_html_path(project.entry_file):
        # SSR apps have no static HTML entry. Interactive mode loads the live Node preview.
        try:
            from .services.preview_server import restart_ssr_from_status

            restart_ssr_from_status(str(project.id), project.source_dir, build_status)
        except Exception:
            pass
        return JsonResponse(
            {
                "mode": "visual",
                "html": '<div id="root" data-siaw-ssr-shell="true"></div>',
                "projectData": None,
                "canvasStyles": [],
                "assetBaseUrl": request.build_absolute_uri(_project_file_prefix(project)),
                "runtimeUrl": _isolated_runtime_url(request, project),
                "projectFilePrefix": _project_file_prefix(project),
                "assets": [],
                "entryFile": project.entry_file,
                "files": files,
                "inlineStyles": [],
                "htmlAttributes": "",
                "bodyAttributes": "",
                "compatibility": {
                    "websiteType": f"SSR app ({build_status.get('previewKind') or 'node'})",
                    "preferLivePreview": True,
                    "canSafeEdit": False,
                    "hasEditableStaticContent": False,
                    "spaShell": {
                        "isSpaShell": True,
                        "emptyMounts": ["#root"],
                        "reasons": ["Nitro/Node SSR preview (no static HTML entry)"],
                        "guidance": (
                            "This project runs as a live Node server. Use Interactive mode or Live Preview. "
                            "Capture this page to create editable static HTML."
                        ),
                    },
                    "recommendations": [
                        "Use Live Preview or Interactive mode for the real website.",
                        "Capture this page when you want a Safe Edit snapshot.",
                    ],
                    "pages": [],
                    "runtimeRegions": [],
                },
                "smartServices": [],
                "smartNavigation": {},
                "canVisualEdit": False,
                "canPreview": True,
                "preferLivePreview": True,
                "ssrPreview": True,
            }
        )

    html_text = project.entry_path.read_text(encoding="utf-8", errors="replace")
    repaired_html = rewrite_html_for_editor_entry(html_text, relative_html_path=project.entry_file)
    if repaired_html != html_text and (
        project.entry_file.replace("\\", "/").startswith("captured/")
        or "/assets/" in html_text
        or ".runtime.localhost" in html_text
    ):
        temporary = project.entry_path.with_suffix(project.entry_path.suffix + ".tmp")
        temporary.write_text(repaired_html, encoding="utf-8")
        os.replace(temporary, project.entry_path)
        discovered = collect_stylesheet_refs(
            repaired_html,
            relative_html_path=project.entry_file,
            source_root=project.source_dir,
        )
        if discovered:
            merged = []
            for item in list(project.stylesheet_files) + discovered:
                if item and item not in merged:
                    merged.append(item)
            project.stylesheet_files = merged
            project.save(update_fields=["stylesheet_files", "updated_at"])
        html_text = repaired_html
    else:
        html_text = repaired_html

    prefix = _project_file_prefix(project)
    origin = f"{request.scheme}://{request.get_host()}"
    saved_project_data = load_project_data(project.project_data_path)
    materialized = materialize_entry_for_visual_editor(
        html_text,
        source_root=project.source_dir,
        entry_file=project.entry_file,
        project_file_prefix=prefix,
        origin=origin,
        stylesheet_files=list(project.stylesheet_files or []),
        project_data=saved_project_data if isinstance(saved_project_data, dict) else None,
    )
    if materialized.get("stylesheetFiles") and materialized["stylesheetFiles"] != list(project.stylesheet_files or []):
        project.stylesheet_files = materialized["stylesheetFiles"]
        project.save(update_fields=["stylesheet_files", "updated_at"])

    editable_body, _scripts = extract_editable_body(materialized["html"])
    editable_body, hydrated_lazy_media = hydrate_lazy_media(editable_body)
    hero_photos = materialize_hero_photo_files(project.source_dir, extract_hero_photos(html_text))
    # Use absolute project-file URLs in Safe Edit HTML so slides and Asset Manager
    # previews work without depending on the canvas <base> tag alone.
    editor_hero_photos = []
    for photo in hero_photos:
        src = photo.get("src") or ""
        if src and not src.startswith(("http://", "https://", "//", "data:")):
            src = request.build_absolute_uri(_file_url(project, src))
        next_photo = dict(photo)
        next_photo["src"] = src
        editor_hero_photos.append(next_photo)
    editable_body, hydrated_hero_slides = hydrate_js_hero_carousel(editable_body, editor_hero_photos)
    reviews = extract_reviews(html_text)
    editable_body, hydrated_reviews = hydrate_js_reviews(editable_body, reviews)
    hero_carousel_photos = [
        {
            "src": photo.get("src") or "",
            "alt": photo.get("alt") or "",
            "alt_en": photo.get("alt_en") or "",
            "alt_de": photo.get("alt_de") or "",
        }
        for photo in editor_hero_photos
    ]
    document_context = extract_document_context(html_text)
    entry_dir = _entry_directory(project)

    # Remote stylesheets stay as URLs; local CSS is inlined for GrapesJS reliability.
    canvas_styles: list[str] = list(materialized.get("remoteStylesheets") or [])
    # Editor-only CSS reveals scroll-animated content while JavaScript is disabled.
    # It is loaded only inside GrapesJS and is never written into the website export.
    canvas_styles.append(request.build_absolute_uri(static("builder/canvas-fixes.css")))

    override_target, _override_href = editor_override_path(project.entry_file)
    override_source_path = project.source_dir / override_target
    # Always load editor override CSS in the canvas. GrapesJS project JSON may also
    # contain rules, but the original site CSS still comes from inlineStyles.
    if override_source_path.is_file():
        override_relative = override_target.as_posix()
        override_url = request.build_absolute_uri(_file_url(project, override_relative))
        if override_url not in canvas_styles:
            canvas_styles.append(override_url)

    assets = []
    for relative_path in list_image_assets(project.source_dir):
        assets.append(
            {
                "src": request.build_absolute_uri(_file_url(project, relative_path)),
                "name": Path(relative_path).name,
                "relativePath": relative_path,
            }
        )

    # Point the canvas base at the project file root so root-relative assets resolve.
    base_path = prefix
    smart_services = load_smart_services(project.source_dir, html_text)
    smart_navigation = load_smart_navigation(project.source_dir, project.entry_file, html_text)
    compatibility = analyze_website(project.source_dir, project.entry_file, html_text)
    page_details = describe_site_pages(project.source_dir, project.entry_file)
    compatibility["pages"] = [item["path"] for item in page_details]
    compatibility["pageDetails"] = page_details
    compatibility["htmlPageCount"] = len(page_details)
    # Backward-compatible fields used by the MVP 3 Smart panel.
    compatibility["externalStyleCount"] = compatibility.get("linkedStyleCount", 0)
    compatibility["selfContained"] = bool(document_context.inline_styles) and not any(
        not str(item).lower().startswith(("http://", "https://", "//"))
        for item in project.stylesheet_files
    )
    compatibility["hydratedLazyMediaCount"] = hydrated_lazy_media
    compatibility["hydratedHeroSlideCount"] = hydrated_hero_slides
    compatibility["hydratedReviewCount"] = hydrated_reviews
    hydrated_selectors = set()
    if hydrated_hero_slides:
        hydrated_selectors.update({".js-hc-track", ".js-hc-dots"})
    if hydrated_reviews:
        hydrated_selectors.update({"#reviewsTrack", "#reviewsDots"})
    if hydrated_selectors:
        compatibility["runtimeRegions"] = [
            region
            for region in compatibility.get("runtimeRegions") or []
            if region.get("selector") not in hydrated_selectors
        ]
        compatibility["runtimeRegionCount"] = len(compatibility["runtimeRegions"])

    # Prefer disk HTML styles + inlined CSS; keep any native <style> blocks too.
    combined_inline_styles = list(document_context.inline_styles) + list(materialized.get("inlineStyles") or [])

    payload = {
        "mode": "visual",
        "html": editable_body,
        "projectData": materialized.get("projectData"),
        "canvasStyles": canvas_styles,
        "assetBaseUrl": request.build_absolute_uri(base_path),
        "runtimeUrl": _isolated_runtime_url(request, project),
        "projectFilePrefix": prefix,
        "assets": assets,
        "entryFile": project.entry_file,
        "files": files,
        "inlineStyles": combined_inline_styles,
        "htmlAttributes": document_context.html_attributes,
        "bodyAttributes": document_context.body_attributes,
        "compatibility": compatibility,
        "heroCarouselPhotos": hero_carousel_photos,
        "reviewsData": reviews,
        "smartServices": smart_services,
        "smartNavigation": smart_navigation,
        "canVisualEdit": bool(compatibility.get("canSafeEdit", True)),
        "canPreview": True,
        "preferLivePreview": bool(compatibility.get("preferLivePreview")),
    }
    return JsonResponse(payload)


@require_GET
def project_files(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    files = list_source_files(project.source_dir)
    image_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif"}
    assets = [
        path for path in files
        if Path(path).suffix.lower() in image_suffixes
    ]
    return JsonResponse(
        {
            "files": files,
            "entryFile": project.entry_file,
            "pages": list_html_pages(project.source_dir),
            "assets": assets,
        }
    )


def _pages_payload(project: WebsiteProject) -> dict:
    descriptors = describe_site_pages(project.source_dir, project.entry_file)
    return {
        "pages": [item["path"] for item in descriptors],
        "pageDetails": descriptors,
        "entryFile": project.entry_file,
    }


@require_http_methods(["GET", "POST"])
def project_pages(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    if request.method == "GET":
        return JsonResponse(_pages_payload(project))

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid page payload."}, status=400)

    action = str(payload.get("action") or "").strip().lower()
    try:
        if action == "add":
            relative = add_blank_page(
                project.source_dir,
                name=str(payload.get("name") or "page.html"),
                title=str(payload.get("title") or "") or None,
            )
        elif action == "duplicate":
            relative = duplicate_page(project.source_dir, str(payload.get("path") or ""))
        elif action == "rename":
            old_path = str(payload.get("path") or "")
            relative = rename_page(
                project.source_dir,
                old_path,
                str(payload.get("name") or ""),
            )
            if project.entry_file == old_path:
                project.entry_file = relative
                project.save(update_fields=["entry_file", "updated_at"])
            else:
                project.save(update_fields=["updated_at"])
            body = _pages_payload(project)
            body.update({"ok": True, "path": relative, "reload": project.entry_file == relative})
            return JsonResponse(body)
        else:
            return JsonResponse({"error": "Unknown page action."}, status=400)
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)

    project.save(update_fields=["updated_at"])
    body = _pages_payload(project)
    body.update({"ok": True, "path": relative})
    return JsonResponse(body)


@require_GET
def export_validate(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    report = validate_export(project.source_dir, project.entry_file)
    return JsonResponse(report)


@require_http_methods(["GET", "POST"])
def project_snapshots(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    if request.method == "GET":
        return JsonResponse({"snapshots": list_snapshots(project.project_dir)})

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid snapshot payload."}, status=400)

    action = str(payload.get("action") or "create").strip().lower()
    try:
        if action == "create":
            meta = create_snapshot(
                project.project_dir,
                project.source_dir,
                project.editor_dir,
                project.entry_file,
                label=str(payload.get("label") or "Restore point"),
            )
            return JsonResponse({"ok": True, "snapshot": meta, "snapshots": list_snapshots(project.project_dir)})
        if action == "restore":
            meta = restore_snapshot(
                project.project_dir,
                project.source_dir,
                project.editor_dir,
                str(payload.get("id") or ""),
            )
            entry = str(meta.get("entryFile") or project.entry_file)
            if (project.source_dir / entry).is_file():
                project.entry_file = entry
            project.save(update_fields=["entry_file", "updated_at"])
            return JsonResponse(
                {
                    "ok": True,
                    "snapshot": meta,
                    "entryFile": project.entry_file,
                    "reload": True,
                    "message": f"Restored '{meta.get('label') or meta.get('id')}'.",
                }
            )
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)

    return JsonResponse({"error": "Unknown snapshot action."}, status=400)


@require_http_methods(["GET", "POST"])
def source_file(request, project_id, file_path):
    project = get_object_or_404(WebsiteProject, id=project_id)
    try:
        target = safe_project_path(project.source_dir, file_path)
    except FileNotFoundError as exc:
        raise Http404 from exc
    if not target.is_file():
        raise Http404
    if not is_text_path(target):
        return JsonResponse({"error": "That file type can be exported, but not edited as text."}, status=400)

    if request.method == "GET":
        return JsonResponse(
            {
                "path": PurePosixPath(file_path).as_posix(),
                "content": target.read_text(encoding="utf-8", errors="replace"),
                "isHtml": is_html_path(target),
            }
        )

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid file payload."}, status=400)
    content = payload.get("content")
    if not isinstance(content, str):
        return JsonResponse({"error": "File content must be a string."}, status=400)
    if len(content.encode("utf-8")) > 5 * 1024 * 1024:
        return JsonResponse({"error": "File is too large to save in the editor."}, status=400)

    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, target)
    project.save(update_fields=["updated_at"])
    return JsonResponse({"ok": True, "path": PurePosixPath(file_path).as_posix()})


@require_POST
def set_entry_file(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid entry payload."}, status=400)
    entry = str(payload.get("entryFile") or "").replace("\\", "/").lstrip("/")
    if not entry or ".." in entry.split("/"):
        return JsonResponse({"error": "Invalid entry file."}, status=400)
    try:
        target = safe_project_path(project.source_dir, entry)
    except FileNotFoundError:
        return JsonResponse({"error": "That file does not exist in the project."}, status=404)
    if not target.is_file():
        return JsonResponse({"error": "That file does not exist in the project."}, status=404)
    project.entry_file = entry
    if is_html_path(entry):
        original_html = target.read_text(encoding="utf-8", errors="replace")
        html_text = rewrite_html_for_editor_entry(original_html, relative_html_path=entry)
        if html_text != original_html:
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_text(html_text, encoding="utf-8")
            os.replace(temporary, target)
        project.stylesheet_files = collect_stylesheet_refs(
            html_text,
            relative_html_path=entry,
            source_root=project.source_dir,
        )
        project.save(update_fields=["entry_file", "stylesheet_files", "updated_at"])
    else:
        project.save(update_fields=["entry_file", "updated_at"])
    return JsonResponse(
        {
            "ok": True,
            "entryFile": project.entry_file,
            "editorMode": "visual" if is_html_path(project.entry_file) else "code",
            "reload": True,
        }
    )


@require_POST
def capture_route(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid capture payload."}, status=400)

    html_text = payload.get("html")
    if not isinstance(html_text, str) or not html_text.strip():
        return JsonResponse({"error": "Captured HTML is required."}, status=400)

    try:
        relative, stylesheets = save_captured_route(
            project.source_dir,
            html_text=html_text,
            route_url=str(payload.get("routeUrl") or ""),
            title=str(payload.get("title") or ""),
        )
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)

    set_as_entry = payload.get("setAsEntry", True)
    if set_as_entry:
        project.entry_file = relative
        project.stylesheet_files = stylesheets
        project.save(update_fields=["entry_file", "stylesheet_files", "updated_at"])
        # Clear stale GrapesJS project JSON so the captured page loads fresh with styles.
        if project.project_data_path.is_file():
            project.project_data_path.unlink(missing_ok=True)
    else:
        project.save(update_fields=["updated_at"])

    return JsonResponse(
        {
            "ok": True,
            "path": relative,
            "entryFile": project.entry_file,
            "stylesheets": stylesheets,
            "reload": bool(set_as_entry),
            "message": f"Saved editable page as {relative}.",
        }
    )


@require_POST
def save_project(request, project_id):
    project = get_object_or_404(WebsiteProject, id=project_id)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid save data."}, status=400)

    if payload.get("mode") == "code" or not is_html_path(project.entry_file):
        content = payload.get("content")
        path = str(payload.get("path") or project.entry_file).replace("\\", "/").lstrip("/")
        if not isinstance(content, str):
            return JsonResponse({"error": "Incomplete code editor data."}, status=400)
        try:
            target = safe_project_path(project.source_dir, path)
        except FileNotFoundError:
            return JsonResponse({"error": "File not found."}, status=404)
        if not target.is_file() or not is_text_path(target):
            return JsonResponse({"error": "That file cannot be saved as text."}, status=400)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, target)
        project.save(update_fields=["updated_at"])
        return JsonResponse({"ok": True, "message": f"Saved {path}."})

    edited_html = payload.get("html")
    generated_css = payload.get("css", "")
    project_data = payload.get("projectData")
    smart_services = payload.get("smartServices")
    smart_navigation = payload.get("smartNavigation")
    raw_slideshow_photos = payload.get("slideshowPhotos")
    slideshow_photos = (
        normalize_slideshow_photos(raw_slideshow_photos)
        if isinstance(raw_slideshow_photos, list)
        else None
    )
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
    if slideshow_photos is not None:
        slideshow_photos = normalize_project_urls(
            slideshow_photos,
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
    merged_html = guard_hero_carousel_script(merged_html)
    merged_html, interactive_synced = sync_js_interactive_arrays(
        merged_html,
        normalized_html,
        slideshow_photos=slideshow_photos,
    )
    synced_dynamic_fields = list(synced_dynamic_fields) + interactive_synced

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
    build_status = read_build_status(project.project_dir)
    prefer_live = False
    website_type = ""
    if build_status.get("previewMode") == "ssr":
        prefer_live = True
        website_type = f"SSR app ({build_status.get('previewKind') or 'node'})"
        # Ensure the Node preview process is up when the user opens Live Preview.
        try:
            from .services.preview_server import restart_ssr_from_status

            if build_status.get("status") == "succeeded":
                restart_ssr_from_status(str(project.id), project.source_dir, build_status)
        except Exception:
            pass
    elif is_html_path(project.entry_file) and project.entry_path.is_file():
        try:
            report = analyze_website(
                project.source_dir,
                project.entry_file,
                project.entry_path.read_text(encoding="utf-8", errors="replace"),
            )
            prefer_live = bool(report.get("preferLivePreview") or report.get("spaShell", {}).get("isSpaShell"))
            website_type = report.get("websiteType") or ""
        except Exception:
            prefer_live = _prefer_preview_landing(project)
    editor_href = reverse("builder:editor", args=[project.id])
    if prefer_live:
        editor_href = f"{editor_href}?mode=interactive"
    return render(
        request,
        "builder/preview.html",
        {
            "project": project,
            "preview_src": _isolated_runtime_url(request, project),
            "prefer_live": prefer_live,
            "website_type": website_type,
            "entry_file": project.entry_file,
            "editor_href": editor_href,
        },
    )


@require_GET
def runtime_site(request, project_id, asset_path=""):
    """Path-based website root for production hosts without *.runtime.localhost DNS."""
    project = get_object_or_404(WebsiteProject, id=project_id)
    return serve_runtime_request(
        request,
        project,
        asset_path or "",
        rewrite_absolute_assets=True,
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
    skip_parts = {
        "node_modules", ".git", "__pycache__", ".venv", "venv", ".next", ".nuxt",
        ".svelte-kit", ".turbo", ".cache", "coverage", ".idea", ".vscode",
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in project.source_dir.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(project.source_dir)
            if any(part in skip_parts for part in relative.parts):
                continue
            archive.write(path, relative.as_posix())
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
