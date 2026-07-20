"""Progressive master-prompt cache and speculative website builds."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import shutil
import threading
from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.utils import timezone

from builder.models import AIWebsiteBrief, WebsiteProject

from .ai_website import (
    brief_goals,
    brief_to_generation_prompt,
    generate_website_from_brief,
    produce_generation_spec,
)
from .plans import assert_can_create_project, assert_can_generate_ai

logger = logging.getLogger(__name__)

# Start speculative Codex once name + description are present.
MIN_DESCRIPTION_CHARS = 1
# Adopt / fail thresholds for hung background builds.
ADOPT_AFTER_SECONDS = 75
ZOMBIE_FAIL_AFTER_SECONDS = 25
HARD_TIMEOUT_SECONDS = 720

_prefetch_guard = threading.Lock()
_prefetch_locks: dict[str, threading.Lock] = {}
_active_threads: dict[str, threading.Thread] = {}


def _brief_lock(brief_id: str) -> threading.Lock:
    with _prefetch_guard:
        lock = _prefetch_locks.get(brief_id)
        if lock is None:
            lock = threading.Lock()
            _prefetch_locks[brief_id] = lock
        return lock


def brief_content_fingerprint(brief: AIWebsiteBrief) -> str:
    assets = [
        {
            "id": asset.id,
            "type": asset.asset_type,
            "name": asset.original_name,
        }
        for asset in brief.assets.all().order_by("id")
    ]
    goals = brief_goals(brief)
    payload = {
        "starting_point": brief.starting_point,
        "business_name": brief.business_name,
        "industry": brief.industry,
        "description": brief.description,
        "location": brief.location,
        "language": brief.language,
        "primary_goal": brief.primary_goal,
        "goals": goals,
        "primary_cta": brief.primary_cta,
        "audience": brief.audience,
        "value_proposition": brief.value_proposition,
        "tone": brief.tone,
        "visual_style": brief.visual_style,
        "existing_website_url": brief.existing_website_url,
        "redesign_json": brief.redesign_json,
        "sitemap_json": brief.sitemap_json,
        "services_json": brief.services_json,
        "trust_json": brief.trust_json,
        "contact_json": brief.contact_json,
        "brand_json": brief.brand_json,
        "assets": assets,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def brief_can_prefetch(brief: AIWebsiteBrief) -> bool:
    """Enough business detail to start Codex in the background (before goals)."""
    name = (brief.business_name or "").strip()
    description = (brief.description or "").strip()
    return len(name) >= 2 and len(description) >= MIN_DESCRIPTION_CHARS


def brief_is_buildable(brief: AIWebsiteBrief) -> bool:
    """Ready for a final Generate click (includes at least one goal)."""
    return brief_can_prefetch(brief) and bool(brief_goals(brief))


def ensure_prefetch_goal(brief: AIWebsiteBrief) -> None:
    """Speculative builds need a goal. Use a safe default until the user picks one."""
    if brief_goals(brief):
        return
    brief.primary_goal = (brief.primary_goal or "credibility").strip() or "credibility"
    brief.save(update_fields=["primary_goal", "updated_at"])


def project_has_site(project: WebsiteProject | None) -> bool:
    if not project:
        return False
    try:
        index = project.source_dir / "index.html"
        return index.is_file() and index.stat().st_size >= 200
    except OSError:
        return False


def estimate_progress_pct(brief: AIWebsiteBrief, *, ready: bool, building: bool) -> int:
    if ready:
        return 100
    if building and brief.prefetch_started_at:
        elapsed = max(0.0, (timezone.now() - brief.prefetch_started_at).total_seconds())
        return int(min(92, 92 * (1 - math.exp(-elapsed / 45.0))))
    if brief.master_prompt:
        return 12
    if brief_can_prefetch(brief):
        return 6
    return 0


def refresh_master_prompt(brief: AIWebsiteBrief, *, start_prefetch: bool = False) -> dict[str, Any]:
    """Rewrite the cached master prompt after autosave. Optionally kick off a build."""
    fingerprint = brief_content_fingerprint(brief)
    prompt_changed = fingerprint != (brief.content_fingerprint or "")
    if prompt_changed or not brief.master_prompt:
        if goals := brief_goals(brief):
            if not brief.primary_goal:
                brief.primary_goal = goals[0]
        elif brief_can_prefetch(brief):
            ensure_prefetch_goal(brief)
        spec = produce_generation_spec(brief)
        can_prompt = brief_can_prefetch(brief)
        prompt = brief_to_generation_prompt(brief) if can_prompt else ""
        brief.master_prompt = prompt
        brief.content_fingerprint = fingerprint
        brief.generation_brief_json = {
            **(brief.generation_brief_json if isinstance(brief.generation_brief_json, dict) else {}),
            **spec,
            "fingerprint": fingerprint,
            "prompt_chars": len(prompt),
            "prompt_updated_at": timezone.now().isoformat(),
        }
        update_fields = [
            "master_prompt",
            "content_fingerprint",
            "generation_brief_json",
            "primary_goal",
            "updated_at",
        ]
        # Content change invalidates a finished speculative build for another fingerprint.
        if brief.prefetch_fingerprint and brief.prefetch_fingerprint != fingerprint:
            if brief.prefetch_status == AIWebsiteBrief.PREFETCH_READY:
                _discard_prefetch_project(brief)
                update_fields.append("project")
            brief.prefetch_status = AIWebsiteBrief.PREFETCH_STALE
            brief.prefetch_error = ""
            update_fields.extend(["prefetch_status", "prefetch_error"])
        brief.save(update_fields=list(dict.fromkeys(update_fields)))
    elif brief_can_prefetch(brief) and not brief.master_prompt:
        ensure_prefetch_goal(brief)
        brief.master_prompt = brief_to_generation_prompt(brief)
        brief.save(update_fields=["master_prompt", "updated_at"])

    started = False
    if start_prefetch and brief_can_prefetch(brief):
        started = maybe_start_prefetch(brief)

    building = brief.prefetch_status in {
        AIWebsiteBrief.PREFETCH_QUEUED,
        AIWebsiteBrief.PREFETCH_BUILDING,
        AIWebsiteBrief.PREFETCH_STALE,
    } and _thread_alive(str(brief.id))
    ready = (
        brief.prefetch_status == AIWebsiteBrief.PREFETCH_READY
        and brief.prefetch_fingerprint == (brief.content_fingerprint or "")
        and project_has_site(brief.project)
    )
    return {
        "fingerprint": brief.content_fingerprint,
        "promptChars": len(brief.master_prompt or ""),
        "prefetchStatus": brief.prefetch_status,
        "prefetchStarted": started,
        "buildable": brief_is_buildable(brief),
        "canPrefetch": brief_can_prefetch(brief),
        "progressPct": estimate_progress_pct(brief, ready=ready, building=building),
        "ready": ready,
        "building": building or started,
    }


def _discard_prefetch_project(brief: AIWebsiteBrief) -> None:
    """Remove a speculative project that no longer matches the brief."""
    if brief.status == "generated":
        return
    project = brief.project
    if not project:
        return
    brief.project = None
    project_dir = project.project_dir
    project_id = project.id
    try:
        project.delete()
    except Exception:
        logger.exception("Could not delete stale prefetch project %s", project_id)
    shutil.rmtree(project_dir, ignore_errors=True)


def maybe_start_prefetch(brief: AIWebsiteBrief) -> bool:
    """Start a background site build when the brief is complete enough."""
    if not brief_can_prefetch(brief):
        return False
    if brief.status == "generated":
        return False
    ensure_prefetch_goal(brief)
    fingerprint = brief.content_fingerprint or brief_content_fingerprint(brief)
    if (
        brief.prefetch_status == AIWebsiteBrief.PREFETCH_READY
        and brief.prefetch_fingerprint == fingerprint
        and project_has_site(brief.project)
    ):
        return False
    # One worker per brief. If content changed mid-build, the worker restarts after finish.
    with _prefetch_guard:
        active = _active_threads.get(str(brief.id))
        if active and active.is_alive():
            return False
    if brief.prefetch_status in {
        AIWebsiteBrief.PREFETCH_QUEUED,
        AIWebsiteBrief.PREFETCH_BUILDING,
    } and _thread_alive(str(brief.id)):
        return False

    owner_id = brief.owner_id
    if not owner_id:
        return False

    User = get_user_model()
    try:
        owner = User.objects.get(id=owner_id)
        assert_can_create_project(owner)
        assert_can_generate_ai(owner)
    except ValidationError as exc:
        brief.prefetch_status = AIWebsiteBrief.PREFETCH_FAILED
        brief.prefetch_error = (
            exc.messages[0] if getattr(exc, "messages", None) else str(exc)
        )[:2000]
        brief.save(update_fields=["prefetch_status", "prefetch_error", "updated_at"])
        return False
    except User.DoesNotExist:
        return False

    with _brief_lock(str(brief.id)):
        brief.refresh_from_db()
        fingerprint = brief.content_fingerprint or brief_content_fingerprint(brief)
        with _prefetch_guard:
            active = _active_threads.get(str(brief.id))
            if active and active.is_alive():
                return False
        if brief.prefetch_status in {
            AIWebsiteBrief.PREFETCH_QUEUED,
            AIWebsiteBrief.PREFETCH_BUILDING,
        } and _thread_alive(str(brief.id)):
            return False
        if (
            brief.prefetch_status == AIWebsiteBrief.PREFETCH_READY
            and brief.prefetch_fingerprint == fingerprint
            and project_has_site(brief.project)
        ):
            return False
        if brief.project_id and brief.prefetch_fingerprint != fingerprint:
            _discard_prefetch_project(brief)
        brief.prefetch_status = AIWebsiteBrief.PREFETCH_QUEUED
        brief.prefetch_fingerprint = fingerprint
        brief.prefetch_error = ""
        brief.prefetch_started_at = timezone.now()
        brief.save(
            update_fields=[
                "prefetch_status",
                "prefetch_fingerprint",
                "prefetch_error",
                "prefetch_started_at",
                "project",
                "updated_at",
            ]
        )

    thread = threading.Thread(
        target=_prefetch_worker,
        kwargs={"brief_id": str(brief.id), "fingerprint": fingerprint, "owner_id": owner_id},
        name=f"siaw-ai-prefetch-{brief.id}",
        daemon=True,
    )
    with _prefetch_guard:
        _active_threads[str(brief.id)] = thread
    thread.start()
    return True


def _prefetch_worker(*, brief_id: str, fingerprint: str, owner_id: int) -> None:
    close_old_connections()
    User = get_user_model()
    restart_after = False
    try:
        brief = AIWebsiteBrief.objects.select_related("owner").get(id=brief_id)
        owner = User.objects.get(id=owner_id)
        brief.prefetch_status = AIWebsiteBrief.PREFETCH_BUILDING
        brief.save(update_fields=["prefetch_status", "updated_at"])

        ensure_prefetch_goal(brief)
        prompt = brief.master_prompt or brief_to_generation_prompt(brief)
        project = generate_website_from_brief(
            brief,
            owner=owner,
            prompt=prompt,
            mode="prefetch",
        )

        brief.refresh_from_db()
        current_fp = brief.content_fingerprint or brief_content_fingerprint(brief)
        if current_fp != fingerprint:
            # User changed answers while we built. Throw away this result.
            if brief.project_id == project.id:
                brief.project = None
                brief.save(update_fields=["project", "updated_at"])
            shutil.rmtree(project.project_dir, ignore_errors=True)
            WebsiteProject.objects.filter(pk=project.pk).delete()
            brief.prefetch_status = AIWebsiteBrief.PREFETCH_STALE
            brief.prefetch_error = ""
            brief.save(update_fields=["prefetch_status", "prefetch_error", "updated_at"])
            restart_after = True
            return

        if not project_has_site(project):
            raise ValidationError("Background build finished without a usable index.html.")

        brief.project = project
        brief.status = "ready"
        brief.prefetch_status = AIWebsiteBrief.PREFETCH_READY
        brief.prefetch_fingerprint = fingerprint
        brief.prefetch_error = ""
        brief.save(
            update_fields=[
                "project",
                "status",
                "prefetch_status",
                "prefetch_fingerprint",
                "prefetch_error",
                "updated_at",
            ]
        )
    except Exception as exc:
        logger.exception("Prefetch build failed for brief %s", brief_id)
        close_old_connections()
        try:
            brief = AIWebsiteBrief.objects.get(id=brief_id)
            if brief.prefetch_fingerprint == fingerprint:
                # Keep a partial project linked if files exist; otherwise clear.
                if brief.project_id and not project_has_site(brief.project):
                    _discard_prefetch_project(brief)
                brief.prefetch_status = AIWebsiteBrief.PREFETCH_FAILED
                brief.prefetch_error = str(exc)[:2000]
                if brief.status != "generated":
                    brief.status = "ready" if brief_can_prefetch(brief) else "draft"
                brief.save(
                    update_fields=[
                        "prefetch_status",
                        "prefetch_error",
                        "status",
                        "project",
                        "updated_at",
                    ]
                )
        except Exception:
            logger.exception("Could not persist prefetch failure for %s", brief_id)
    finally:
        with _prefetch_guard:
            _active_threads.pop(brief_id, None)
        if restart_after:
            close_old_connections()
            try:
                brief = AIWebsiteBrief.objects.get(id=brief_id)
                maybe_start_prefetch(brief)
            except Exception:
                logger.exception("Could not restart prefetch for %s", brief_id)
        close_old_connections()


def _thread_alive(brief_id: str) -> bool:
    with _prefetch_guard:
        thread = _active_threads.get(str(brief_id))
        return bool(thread and thread.is_alive())


def _try_adopt_orphan_project(brief: AIWebsiteBrief) -> bool:
    """If Codex wrote a site but the worker never linked it, adopt that project."""
    if project_has_site(brief.project):
        brief.status = "ready" if brief.status != "generated" else brief.status
        brief.prefetch_status = AIWebsiteBrief.PREFETCH_READY
        brief.prefetch_fingerprint = brief.content_fingerprint or brief_content_fingerprint(brief)
        brief.prefetch_error = ""
        brief.save(
            update_fields=[
                "status",
                "prefetch_status",
                "prefetch_fingerprint",
                "prefetch_error",
                "updated_at",
            ]
        )
        return True

    if not brief.business_name:
        return False
    started = brief.prefetch_started_at or timezone.now()
    window_start = started - timedelta(minutes=5)
    candidates = WebsiteProject.objects.filter(
        owner_id=brief.owner_id,
        name=brief.business_name[:160],
        created_at__gte=window_start,
        deleted_at__isnull=True,
    ).order_by("-created_at")
    for project in candidates:
        if not project_has_site(project):
            continue
        other = AIWebsiteBrief.objects.filter(project_id=project.id).exclude(id=brief.id).exists()
        if other:
            continue
        from .ai_website import apply_brief_assets_to_source
        from .archive import StylesheetParser

        try:
            apply_brief_assets_to_source(project.source_dir, brief)
        except Exception:
            logger.exception("Could not re-apply assets while adopting %s", project.id)
        styles: list[str] = []
        try:
            html = (project.source_dir / "index.html").read_text(encoding="utf-8", errors="replace")
            parser = StylesheetParser()
            parser.feed(html)
            styles = [
                href
                for href in parser.stylesheets
                if href.lower().startswith(("http://", "https://", "//")) or str(href).endswith(".css")
            ]
        except Exception:
            styles = []
        for css in project.source_dir.rglob("*.css"):
            if css.is_file():
                rel = css.relative_to(project.source_dir).as_posix()
                if rel not in styles:
                    styles.append(rel)
        project.entry_file = "index.html"
        project.stylesheet_files = styles
        project.save(update_fields=["entry_file", "stylesheet_files", "updated_at"])
        brief.project = project
        brief.status = "ready"
        brief.prefetch_status = AIWebsiteBrief.PREFETCH_READY
        brief.prefetch_fingerprint = brief.content_fingerprint or brief_content_fingerprint(brief)
        brief.prefetch_error = ""
        brief.save(
            update_fields=[
                "project",
                "status",
                "prefetch_status",
                "prefetch_fingerprint",
                "prefetch_error",
                "updated_at",
            ]
        )
        return True
    return False


def recover_stale_prefetch(brief: AIWebsiteBrief) -> bool:
    """Clear zombie queued/building states when the worker thread is gone."""
    # Never leave status=generated without a real site on disk.
    if brief.status == "generated" and not project_has_site(brief.project):
        brief.status = "ready" if brief_can_prefetch(brief) else "draft"
        brief.prefetch_status = AIWebsiteBrief.PREFETCH_FAILED
        brief.prefetch_error = (
            "The generated project is missing from disk. Click Generate website to build again."
        )
        brief.project = None
        brief.save(
            update_fields=[
                "status",
                "prefetch_status",
                "prefetch_error",
                "project",
                "updated_at",
            ]
        )
        return True

    if brief.prefetch_status in {
        AIWebsiteBrief.PREFETCH_QUEUED,
        AIWebsiteBrief.PREFETCH_BUILDING,
        AIWebsiteBrief.PREFETCH_FAILED,
        AIWebsiteBrief.PREFETCH_STALE,
        AIWebsiteBrief.PREFETCH_READY,
    }:
        started = brief.prefetch_started_at
        age = (timezone.now() - started).total_seconds() if started else 999
        if (brief.prefetch_status != AIWebsiteBrief.PREFETCH_READY or not project_has_site(brief.project)) and age >= ADOPT_AFTER_SECONDS:
            if _try_adopt_orphan_project(brief):
                return True

    if brief.prefetch_status not in {
        AIWebsiteBrief.PREFETCH_QUEUED,
        AIWebsiteBrief.PREFETCH_BUILDING,
    }:
        # READY without files is not ready.
        if brief.prefetch_status == AIWebsiteBrief.PREFETCH_READY and not project_has_site(brief.project):
            brief.prefetch_status = AIWebsiteBrief.PREFETCH_FAILED
            brief.prefetch_error = (
                "The prepared site is incomplete. Click Generate website to build again."
            )
            brief.save(update_fields=["prefetch_status", "prefetch_error", "updated_at"])
            return True
        return False

    started = brief.prefetch_started_at
    age = (timezone.now() - started).total_seconds() if started else 0
    alive = _thread_alive(str(brief.id))

    if age >= ADOPT_AFTER_SECONDS and _try_adopt_orphan_project(brief):
        return True

    if alive and age < HARD_TIMEOUT_SECONDS:
        return False

    if age < ZOMBIE_FAIL_AFTER_SECONDS and not alive:
        return False

    if _try_adopt_orphan_project(brief):
        return True

    brief.prefetch_status = AIWebsiteBrief.PREFETCH_FAILED
    brief.prefetch_error = (
        "Background build stopped before it finished. "
        "Click Generate website to build again."
    )
    if brief.status not in {"generated", "generating"}:
        brief.status = "ready" if brief_can_prefetch(brief) else "draft"
    brief.save(update_fields=["prefetch_status", "prefetch_error", "status", "updated_at"])
    return True


def prefetch_status_payload(brief: AIWebsiteBrief) -> dict[str, Any]:
    recover_stale_prefetch(brief)
    brief.refresh_from_db()
    fingerprint = brief.content_fingerprint or ""
    ready = (
        brief.prefetch_status == AIWebsiteBrief.PREFETCH_READY
        and brief.prefetch_fingerprint == fingerprint
        and project_has_site(brief.project)
    )
    building = (
        brief.prefetch_status
        in {
            AIWebsiteBrief.PREFETCH_QUEUED,
            AIWebsiteBrief.PREFETCH_BUILDING,
        }
        and _thread_alive(str(brief.id))
    ) or (
        brief.prefetch_status == AIWebsiteBrief.PREFETCH_STALE
        and _thread_alive(str(brief.id))
    )
    # If DB says building but the worker is gone, recover_stale should have failed it.
    # Still expose a clear failed state for the UI.
    failed = brief.prefetch_status == AIWebsiteBrief.PREFETCH_FAILED and not ready
    progress = estimate_progress_pct(brief, ready=ready, building=building)
    return {
        "status": brief.prefetch_status or AIWebsiteBrief.PREFETCH_IDLE,
        "fingerprint": fingerprint,
        "prefetchFingerprint": brief.prefetch_fingerprint or "",
        "ready": ready,
        "building": building,
        "failed": failed,
        "error": brief.prefetch_error or "",
        "promptChars": len(brief.master_prompt or ""),
        "projectId": str(brief.project_id) if brief.project_id else "",
        "buildable": brief_is_buildable(brief),
        "canPrefetch": brief_can_prefetch(brief),
        "progressPct": progress,
        "startedAt": brief.prefetch_started_at.isoformat() if brief.prefetch_started_at else "",
    }


def claim_prefetch_project(brief: AIWebsiteBrief) -> WebsiteProject | None:
    """Promote a ready speculative build into the final generated project."""
    recover_stale_prefetch(brief)
    brief.refresh_from_db()
    fingerprint = brief.content_fingerprint or brief_content_fingerprint(brief)
    if brief.prefetch_status != AIWebsiteBrief.PREFETCH_READY:
        return None
    if brief.prefetch_fingerprint != fingerprint:
        return None
    project = brief.project
    if not project_has_site(project):
        if _try_adopt_orphan_project(brief):
            brief.refresh_from_db()
            project = brief.project
        if not project_has_site(project):
            brief.prefetch_status = AIWebsiteBrief.PREFETCH_FAILED
            brief.prefetch_error = (
                "The prepared site could not be opened. Click Generate website to build again."
            )
            brief.save(update_fields=["prefetch_status", "prefetch_error", "updated_at"])
            return None
    # Only mark generated when the project is linked and has real HTML.
    brief.project = project
    brief.status = "generated"
    brief.prefetch_status = AIWebsiteBrief.PREFETCH_READY
    brief.prefetch_error = ""
    brief.save(update_fields=["project", "status", "prefetch_status", "prefetch_error", "updated_at"])
    return project
