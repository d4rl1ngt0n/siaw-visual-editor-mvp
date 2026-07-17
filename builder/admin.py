from django.contrib import admin

from .models import WebsiteProject


@admin.register(WebsiteProject)
class WebsiteProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "entry_file", "updated_at", "created_at")
    search_fields = ("name", "entry_file")
