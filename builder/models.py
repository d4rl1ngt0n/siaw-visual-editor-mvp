import uuid
from pathlib import Path

from django.conf import settings
from django.db import models

PLAN_FREE = "free"
PLAN_PRO = "pro"
PLAN_STUDIO = "studio"
PLAN_CHOICES = (
    (PLAN_FREE, "Free"),
    (PLAN_PRO, "Pro"),
    (PLAN_STUDIO, "Studio"),
)


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default=PLAN_FREE)
    ai_generations_used = models.PositiveIntegerField(default=0)
    ai_period_start = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.user} ({self.plan})"


class WebsiteProject(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="website_projects",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=160)
    entry_file = models.CharField(max_length=500, default="index.html")
    stylesheet_files = models.JSONField(default=list, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["owner", "-updated_at"]),
            models.Index(fields=["owner", "deleted_at"]),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def project_dir(self) -> Path:
        return Path(settings.MEDIA_ROOT) / "projects" / str(self.id)

    @property
    def source_dir(self) -> Path:
        return self.project_dir / "source"

    @property
    def editor_dir(self) -> Path:
        return self.project_dir / "editor"

    @property
    def entry_path(self) -> Path:
        return self.source_dir / self.entry_file

    @property
    def project_data_path(self) -> Path:
        return self.editor_dir / "project.json"

    @property
    def original_zip_path(self) -> Path:
        return self.project_dir / "original.zip"

    @property
    def snapshots_dir(self) -> Path:
        return self.project_dir / "snapshots"


class AIWebsiteBrief(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("ready", "Ready"),
        ("generating", "Generating"),
        ("generated", "Generated"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_website_briefs",
        null=True,
        blank=True,
    )
    project = models.OneToOneField(
        WebsiteProject,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_brief",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    current_step = models.PositiveSmallIntegerField(default=1)
    starting_point = models.CharField(max_length=30, default="new", blank=True)
    business_name = models.CharField(max_length=160, blank=True)
    industry = models.CharField(max_length=160, blank=True)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=200, blank=True)
    language = models.CharField(max_length=80, default="English", blank=True)
    primary_goal = models.CharField(max_length=60, blank=True)
    primary_cta = models.JSONField(default=dict, blank=True)
    audience = models.JSONField(default=dict, blank=True)
    value_proposition = models.TextField(blank=True)
    tone = models.CharField(max_length=80, blank=True)
    visual_style = models.CharField(max_length=80, blank=True)
    existing_website_url = models.URLField(max_length=500, blank=True)
    redesign_json = models.JSONField(default=dict, blank=True)
    sitemap_json = models.JSONField(default=list, blank=True)
    services_json = models.JSONField(default=list, blank=True)
    trust_json = models.JSONField(default=dict, blank=True)
    contact_json = models.JSONField(default=dict, blank=True)
    brand_json = models.JSONField(default=dict, blank=True)
    generation_brief_json = models.JSONField(default=dict, blank=True)
    # Progressive build cache: rewrite master prompt on every autosave, then
    # optionally start Codex before the user clicks Generate.
    master_prompt = models.TextField(blank=True)
    content_fingerprint = models.CharField(max_length=64, blank=True)
    PREFETCH_IDLE = "idle"
    PREFETCH_QUEUED = "queued"
    PREFETCH_BUILDING = "building"
    PREFETCH_READY = "ready"
    PREFETCH_FAILED = "failed"
    PREFETCH_STALE = "stale"
    PREFETCH_STATUS_CHOICES = [
        (PREFETCH_IDLE, "Idle"),
        (PREFETCH_QUEUED, "Queued"),
        (PREFETCH_BUILDING, "Building"),
        (PREFETCH_READY, "Ready"),
        (PREFETCH_FAILED, "Failed"),
        (PREFETCH_STALE, "Stale"),
    ]
    prefetch_status = models.CharField(
        max_length=20,
        choices=PREFETCH_STATUS_CHOICES,
        default=PREFETCH_IDLE,
        blank=True,
    )
    prefetch_fingerprint = models.CharField(max_length=64, blank=True)
    prefetch_error = models.TextField(blank=True)
    prefetch_started_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["owner", "-updated_at"]),
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["owner", "prefetch_status"]),
        ]

    def __str__(self) -> str:
        return self.business_name or f"AI website brief {self.id}"


def ai_asset_upload_path(instance, filename):
    safe_name = Path(filename).name
    return f"ai-briefs/{instance.brief_id}/{safe_name}"


class AIWebsiteAsset(models.Model):
    brief = models.ForeignKey(AIWebsiteBrief, on_delete=models.CASCADE, related_name="assets")
    file = models.FileField(upload_to=ai_asset_upload_path)
    asset_type = models.CharField(max_length=40, default="reference")
    original_name = models.CharField(max_length=255)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.original_name


class ShopifyShop(models.Model):
    """A merchant Shopify store that installed the Siaw app (or connected from the web product)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="shopify_shops",
        null=True,
        blank=True,
        help_text="Optional linked Siaw account. Installs can exist before the merchant signs up.",
    )
    shop_domain = models.CharField(max_length=255, unique=True)
    access_token_encrypted = models.TextField(blank=True)
    scopes = models.CharField(max_length=500, blank=True)
    shop_name = models.CharField(max_length=255, blank=True)
    shop_email = models.EmailField(blank=True)
    primary_domain = models.CharField(max_length=255, blank=True)
    currency = models.CharField(max_length=16, blank=True)
    plan_name = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    installed_at = models.DateTimeField(auto_now_add=True)
    uninstalled_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["owner", "is_active"]),
            models.Index(fields=["is_active", "-updated_at"]),
        ]

    def __str__(self) -> str:
        return self.shop_name or self.shop_domain
