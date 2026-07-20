import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("builder", "0005_aiwebsitebrief_prefetch"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ShopifyShop",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("shop_domain", models.CharField(max_length=255)),
                ("access_token_encrypted", models.TextField()),
                ("scopes", models.CharField(blank=True, max_length=500)),
                ("shop_name", models.CharField(blank=True, max_length=255)),
                ("shop_email", models.EmailField(blank=True, max_length=254)),
                ("primary_domain", models.CharField(blank=True, max_length=255)),
                ("currency", models.CharField(blank=True, max_length=16)),
                ("plan_name", models.CharField(blank=True, max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                ("installed_at", models.DateTimeField(auto_now_add=True)),
                ("uninstalled_at", models.DateTimeField(blank=True, null=True)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("metadata_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="shopify_shops",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.AddIndex(
            model_name="shopifyshop",
            index=models.Index(fields=["owner", "is_active"], name="builder_sho_owner_i_5c9113_idx"),
        ),
        migrations.AddIndex(
            model_name="shopifyshop",
            index=models.Index(fields=["shop_domain"], name="builder_sho_shop_do_385d0f_idx"),
        ),
        migrations.AddConstraint(
            model_name="shopifyshop",
            constraint=models.UniqueConstraint(
                fields=("owner", "shop_domain"),
                name="uniq_shopify_shop_owner_domain",
            ),
        ),
    ]
