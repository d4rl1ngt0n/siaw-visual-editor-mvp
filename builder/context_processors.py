from .services.site_edit import site_edit_allowed


def site_edit(request):
    enabled = site_edit_allowed(request)
    return {
        "site_edit_enabled": enabled,
    }
