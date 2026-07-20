"""Ensure a default demo account exists for easy local / MVP login."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model


def demo_credentials() -> dict[str, str]:
    return {
        "username": (getattr(settings, "SIAW_DEMO_USERNAME", "") or "demo").strip() or "demo",
        "password": (getattr(settings, "SIAW_DEMO_PASSWORD", "") or "siawdemo123").strip() or "siawdemo123",
        "email": (getattr(settings, "SIAW_DEMO_EMAIL", "") or "demo@siaw.local").strip() or "demo@siaw.local",
    }


def ensure_demo_user() -> None:
    creds = demo_credentials()
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=creds["username"],
        defaults={
            "email": creds["email"],
            "is_staff": False,
            "is_superuser": False,
        },
    )
    # Keep the known demo password and email in sync so login / account hints stay valid.
    dirty = False
    if created or not user.check_password(creds["password"]):
        user.set_password(creds["password"])
        dirty = True
    if (user.email or "").strip().lower() != creds["email"].lower():
        user.email = creds["email"]
        dirty = True
    if dirty:
        user.save()
