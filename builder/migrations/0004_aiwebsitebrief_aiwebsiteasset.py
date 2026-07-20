import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import builder.models


class Migration(migrations.Migration):

    dependencies = [
        ("builder", "0003_user_profile_soft_delete"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AIWebsiteBrief",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("ready", "Ready"),
                            ("generating", "Generating"),
                            ("generated", "Generated"),
                            ("failed", "Failed"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("current_step", models.PositiveSmallIntegerField(default=1)),
                ("starting_point", models.CharField(blank=True, default="new", max_length=30)),
                ("business_name", models.CharField(blank=True, max_length=160)),
                ("industry", models.CharField(blank=True, max_length=160)),
                ("description", models.TextField(blank=True)),
                ("location", models.CharField(blank=True, max_length=200)),
                ("language", models.CharField(blank=True, default="English", max_length=80)),
                ("primary_goal", models.CharField(blank=True, max_length=60)),
                ("primary_cta", models.JSONField(blank=True, default=dict)),
                ("audience", models.JSONField(blank=True, default=dict)),
                ("value_proposition", models.TextField(blank=True)),
                ("tone", models.CharField(blank=True, max_length=80)),
                ("visual_style", models.CharField(blank=True, max_length=80)),
                ("existing_website_url", models.URLField(blank=True, max_length=500)),
                ("redesign_json", models.JSONField(blank=True, default=dict)),
                ("sitemap_json", models.JSONField(blank=True, default=list)),
                ("services_json", models.JSONField(blank=True, default=list)),
                ("trust_json", models.JSONField(blank=True, default=dict)),
                ("contact_json", models.JSONField(blank=True, default=dict)),
                ("brand_json", models.JSONField(blank=True, default=dict)),
                ("generation_brief_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_website_briefs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "project",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_brief",
                        to="builder.websiteproject",
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="AIWebsiteAsset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to=builder.models.ai_asset_upload_path)),
                ("asset_type", models.CharField(default="reference", max_length=40)),
                ("original_name", models.CharField(max_length=255)),
                ("metadata_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "brief",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assets",
                        to="builder.aiwebsitebrief",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="aiwebsitebrief",
            index=models.Index(fields=["owner", "-updated_at"], name="builder_aiw_owner_i_7f2a1c_idx"),
        ),
        migrations.AddIndex(
            model_name="aiwebsitebrief",
            index=models.Index(fields=["owner", "status"], name="builder_aiw_owner_s_9c4e2d_idx"),
        ),
    ]
