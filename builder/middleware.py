"""Route *.runtime.localhost requests to the per-project website root."""

from __future__ import annotations

from django.http import Http404

from .models import WebsiteProject
from .services.runtime_site import parse_runtime_project_id, serve_runtime_request


class RuntimeHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        project_id = parse_runtime_project_id(request.get_host())
        if not project_id:
            return self.get_response(request)

        try:
            project = WebsiteProject.objects.get(id=project_id)
        except (WebsiteProject.DoesNotExist, ValueError) as exc:
            raise Http404("Runtime project not found.") from exc

        asset_path = request.path.lstrip("/")
        # Keep Django/admin/static out of the runtime host if someone hits them.
        if asset_path.startswith(("admin/", "static/")):
            return self.get_response(request)
        return serve_runtime_request(
            request,
            project,
            asset_path,
            rewrite_absolute_assets=False,
        )
