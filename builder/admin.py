from django.contrib import admin

from .models import AIWebsiteAsset, AIWebsiteBrief, ShopifyShop, UserProfile, WebsiteProject


@admin.register(WebsiteProject)
class WebsiteProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "entry_file", "deleted_at", "updated_at", "created_at")
    list_filter = ("deleted_at",)
    search_fields = ("name", "entry_file", "owner__username", "owner__email")
    raw_id_fields = ("owner",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "ai_generations_used", "ai_period_start", "updated_at")
    list_filter = ("plan",)
    search_fields = ("user__username", "user__email")
    raw_id_fields = ("user",)


@admin.register(AIWebsiteBrief)
class AIWebsiteBriefAdmin(admin.ModelAdmin):
    list_display = ("business_name", "owner", "status", "current_step", "updated_at")
    list_filter = ("status",)
    search_fields = ("business_name", "industry", "owner__username", "owner__email")
    raw_id_fields = ("owner", "project")


@admin.register(AIWebsiteAsset)
class AIWebsiteAssetAdmin(admin.ModelAdmin):
    list_display = ("original_name", "asset_type", "brief", "created_at")
    list_filter = ("asset_type",)
    search_fields = ("original_name", "brief__business_name")
    raw_id_fields = ("brief",)


@admin.register(ShopifyShop)
class ShopifyShopAdmin(admin.ModelAdmin):
    list_display = (
        "shop_domain",
        "shop_name",
        "owner",
        "is_active",
        "currency",
        "plan_name",
        "updated_at",
    )
    list_filter = ("is_active",)
    search_fields = ("shop_domain", "shop_name", "shop_email", "owner__username", "owner__email")
    raw_id_fields = ("owner",)
    readonly_fields = ("access_token_encrypted", "installed_at", "created_at", "updated_at")
