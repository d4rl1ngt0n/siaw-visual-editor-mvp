import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("builder", "0006_shopifyshop"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="shopifyshop",
            name="uniq_shopify_shop_owner_domain",
        ),
        migrations.AlterField(
            model_name="shopifyshop",
            name="access_token_encrypted",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="shopifyshop",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional linked Siaw account. Installs can exist before the merchant signs up.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="shopify_shops",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="shopifyshop",
            name="shop_domain",
            field=models.CharField(max_length=255, unique=True),
        ),
        migrations.AddIndex(
            model_name="shopifyshop",
            index=models.Index(fields=["is_active", "-updated_at"], name="builder_sho_is_acti_7a1c2d_idx"),
        ),
    ]
