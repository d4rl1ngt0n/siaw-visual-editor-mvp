"""Route *.runtime.localhost requests to the per-project website root."""

from __future__ import annotations

from django.http import Http404
from django.utils.deprecation import MiddlewareMixin

from .models import WebsiteProject
from .services.project_access import attach_runtime_access_cookie, request_can_serve_runtime_path
from .services.runtime_site import parse_runtime_project_id, serve_runtime_request

# Shopify Admin embeds the app; allow framing only on Shopify app routes.
_SHOPIFY_APP_PREFIXES = (
    "/shopify/app",
    "/shopify/auth",
    "/shopify/session",
)


class ShopifyEmbeddedFrameMiddleware(MiddlewareMixin):
    """Allow Shopify Admin to iframe App Home while keeping the rest of the site locked down."""

    def process_response(self, request, response):
        path = request.path or ""
        if not any(path.startswith(prefix) for prefix in _SHOPIFY_APP_PREFIXES):
            return response
        if "X-Frame-Options" in response:
            del response["X-Frame-Options"]
        response["Content-Security-Policy"] = (
            "frame-ancestors https://admin.shopify.com https://*.myshopify.com;"
        )
        return response


class RuntimeHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        project_id = parse_runtime_project_id(request.get_host())
        if not project_id:
            return self.get_response(request)

        try:
            project = WebsiteProject.objects.get(id=project_id, deleted_at__isnull=True)
        except (WebsiteProject.DoesNotExist, ValueError) as exc:
            raise Http404("Runtime project not found.") from exc

        asset_path = request.path.lstrip("/")
        # Keep Django/admin/static out of the runtime host if someone hits them.
        if asset_path.startswith(("admin/", "static/")):
            return self.get_response(request)

        if not request_can_serve_runtime_path(request, project, asset_path):
            raise Http404("Runtime project not found.")

        response = serve_runtime_request(
            request,
            project,
            asset_path,
            rewrite_absolute_assets=False,
        )
        return attach_runtime_access_cookie(response, request, project)
