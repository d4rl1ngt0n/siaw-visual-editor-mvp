"""Plan limits and monthly AI usage for multi-user accounts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.contrib.auth.models import AbstractBaseUser
from django.utils import timezone

from builder.models import PLAN_FREE, PLAN_PRO, PLAN_STUDIO, UserProfile, WebsiteProject

__all__ = [
    "PLAN_FREE",
    "PLAN_PRO",
    "PLAN_STUDIO",
    "PLAN_LIMITS",
    "PlanLimits",
    "plan_limits",
    "ensure_profile",
    "usage_summary",
    "assert_can_create_project",
    "assert_can_generate_ai",
    "record_ai_generation",
]


@dataclass(frozen=True)
class PlanLimits:
    key: str
    label: str
    max_projects: int | None  # None = unlimited
    max_ai_generations: int | None


PLAN_LIMITS: dict[str, PlanLimits] = {
    PLAN_FREE: PlanLimits(PLAN_FREE, "Free", max_projects=2, max_ai_generations=3),
    PLAN_PRO: PlanLimits(PLAN_PRO, "Pro", max_projects=None, max_ai_generations=60),
    PLAN_STUDIO: PlanLimits(PLAN_STUDIO, "Studio", max_projects=None, max_ai_generations=None),
}


def plan_limits(plan: str) -> PlanLimits:
    return PLAN_LIMITS.get(plan) or PLAN_LIMITS[PLAN_FREE]


def ensure_profile(user: AbstractBaseUser) -> UserProfile:
    profile, _created = UserProfile.objects.get_or_create(user=user)
    return reset_usage_period_if_needed(profile)


def reset_usage_period_if_needed(profile: UserProfile) -> UserProfile:
    today = timezone.localdate()
    period = profile.ai_period_start
    if period is None or (period.year, period.month) != (today.year, today.month):
        profile.ai_period_start = date(today.year, today.month, 1)
        profile.ai_generations_used = 0
        profile.save(update_fields=["ai_period_start", "ai_generations_used", "updated_at"])
    return profile


def active_project_count(user: AbstractBaseUser) -> int:
    return WebsiteProject.objects.filter(owner=user, deleted_at__isnull=True).count()


def usage_summary(user: AbstractBaseUser) -> dict:
    profile = ensure_profile(user)
    limits = plan_limits(profile.plan)
    projects = active_project_count(user)
    projects_limit = limits.max_projects
    ai_used = profile.ai_generations_used
    ai_limit = limits.max_ai_generations
    projects_at_limit = projects_limit is not None and projects >= projects_limit
    ai_at_limit = ai_limit is not None and ai_used >= ai_limit
    projects_near_limit = (
        projects_limit is not None and projects_limit > 0 and projects >= max(1, projects_limit - 1)
    )
    ai_near_limit = ai_limit is not None and ai_limit > 0 and ai_used >= max(1, ai_limit - 1)
    return {
        "plan": limits.key,
        "plan_label": limits.label,
        "projects_used": projects,
        "projects_limit": projects_limit,
        "ai_used": ai_used,
        "ai_limit": ai_limit,
        "ai_period_start": profile.ai_period_start,
        "projects_at_limit": projects_at_limit,
        "ai_at_limit": ai_at_limit,
        "projects_near_limit": projects_near_limit,
        "ai_near_limit": ai_near_limit,
        "needs_upgrade": projects_at_limit or ai_at_limit,
    }


def assert_can_create_project(user: AbstractBaseUser) -> None:
    from django.core.exceptions import ValidationError

    profile = ensure_profile(user)
    limits = plan_limits(profile.plan)
    if limits.max_projects is None:
        return
    if active_project_count(user) >= limits.max_projects:
        raise ValidationError(
            f"Your {limits.label} plan allows {limits.max_projects} active projects. "
            "Delete one, or upgrade for more."
        )


def assert_can_generate_ai(user: AbstractBaseUser) -> None:
    from django.core.exceptions import ValidationError

    profile = ensure_profile(user)
    limits = plan_limits(profile.plan)
    if limits.max_ai_generations is None:
        return
    if profile.ai_generations_used >= limits.max_ai_generations:
        raise ValidationError(
            f"Your {limits.label} plan allows {limits.max_ai_generations} AI generations this month. "
            "Upgrade for more."
        )


def record_ai_generation(user: AbstractBaseUser) -> None:
    profile = ensure_profile(user)
    profile.ai_generations_used = int(profile.ai_generations_used or 0) + 1
    profile.save(update_fields=["ai_generations_used", "updated_at"])
