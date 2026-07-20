from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("builder", "0004_aiwebsitebrief_aiwebsiteasset"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiwebsitebrief",
            name="master_prompt",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="aiwebsitebrief",
            name="content_fingerprint",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="aiwebsitebrief",
            name="prefetch_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("idle", "Idle"),
                    ("queued", "Queued"),
                    ("building", "Building"),
                    ("ready", "Ready"),
                    ("failed", "Failed"),
                    ("stale", "Stale"),
                ],
                default="idle",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="aiwebsitebrief",
            name="prefetch_fingerprint",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="aiwebsitebrief",
            name="prefetch_error",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="aiwebsitebrief",
            name="prefetch_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="aiwebsitebrief",
            index=models.Index(fields=["owner", "prefetch_status"], name="builder_aiw_owner_p_8e2f1a_idx"),
        ),
    ]
