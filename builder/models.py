import uuid
from pathlib import Path

from django.conf import settings
from django.db import models


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["owner", "-updated_at"]),
        ]

    def __str__(self) -> str:
        return self.name

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
