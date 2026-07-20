"""Creative-brief helpers for the Codex-designed AI website wizard."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

from ..models import AIWebsiteBrief, WebsiteProject
from .ai_builder import create_website_from_prompt
from .question_tailor import OTHER_GOAL, goal_label
from .sitewright_prompt import sitewright_quality_rules


GOAL_SECTIONS = {
    "sell": [
        "Navigation",
        "Product hero",
        "Featured categories",
        "Popular products",
        "Benefits",
        "Reviews",
        "FAQ",
        "Newsletter",
        "Footer",
    ],
    "portfolio": [
        "Navigation",
        "Distinctive hero",
        "Selected work",
        "Capabilities",
        "About",
        "Process",
        "Testimonials",
        "Contact CTA",
        "Footer",
    ],
    "default": [
        "Navigation",
        "Outcome-focused hero",
        "Trust indicators",
        "Services",
        "Benefits",
        "Process",
        "Case studies",
        "Testimonials",
        "FAQ",
        "Contact",
        "Footer",
    ],
}


def recommend_homepage_sections(goal: str) -> list[str]:
    if goal == "sell":
        return GOAL_SECTIONS["sell"]
    if goal == "portfolio":
        return GOAL_SECTIONS["portfolio"]
    return GOAL_SECTIONS["default"]


def recommend_sitemap(goal: str) -> list[dict]:
    pages = ["Home", "About"]
    if goal == "sell":
        pages += ["Products"]
    elif goal == "portfolio":
        pages += ["Portfolio", "Services"]
    else:
        pages += ["Services"]
    pages += ["FAQ", "Contact"]
    return [
        {
            "title": title,
            "slug": "home" if title == "Home" else re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"),
        }
        for title in pages
    ]


def brief_custom_goal(brief: AIWebsiteBrief) -> str:
    cta = brief.primary_cta if isinstance(brief.primary_cta, dict) else {}
    return str(cta.get("other") or "").strip()[:160]


def brief_goals(brief: AIWebsiteBrief) -> list[str]:
    cta = brief.primary_cta if isinstance(brief.primary_cta, dict) else {}
    goals = cta.get("goals")
    cleaned: list[str] = []
    if isinstance(goals, list):
        cleaned = [str(item).strip() for item in goals if str(item).strip()]
    if not cleaned and brief.primary_goal:
        cleaned = [brief.primary_goal]
    custom = brief_custom_goal(brief)
    if custom:
        cleaned = [OTHER_GOAL] + [item for item in cleaned if item != OTHER_GOAL]
    else:
        cleaned = [item for item in cleaned if item != OTHER_GOAL]
    return cleaned[:3]


def display_goal(value: str, brief: AIWebsiteBrief | None = None) -> str:
    if value == OTHER_GOAL:
        custom = brief_custom_goal(brief) if brief is not None else ""
        return custom or "Custom outcome"
    return goal_label(value)


def identify_missing_information(brief: AIWebsiteBrief) -> list[str]:
    missing = []
    if not brief.business_name:
        missing.append("Business name")
    if not brief.industry:
        missing.append("Industry")
    if not brief.description:
        missing.append("Business description")
    if not brief_goals(brief):
        missing.append("Website goals")
    return missing


def produce_generation_spec(brief: AIWebsiteBrief) -> dict:
    goals = brief_goals(brief)
    primary = goals[0] if goals else brief.primary_goal
    structure_goal = "default" if primary == OTHER_GOAL else primary
    custom = brief_custom_goal(brief)
    sitemap = brief.sitemap_json or recommend_sitemap(structure_goal)
    return {
        "site": {
            "name": brief.business_name,
            "language": brief.language or "English",
            "goal": primary,
            "goals": goals,
            "custom_goal": custom,
            "industry": brief.industry,
        },
        "design_system": {
            "direction": brief.visual_style or "Clean and minimal",
            "brand": brief.brand_json,
        },
        "pages": sitemap,
        "homepage_sections": recommend_homepage_sections(structure_goal),
        "services": brief.services_json,
        "audience": brief.audience,
        "trust": brief.trust_json,
        "contact": brief.contact_json,
        "missing_claims": identify_missing_information(brief),
        "warnings": ["Review all generated copy and legal information before publishing."],
    }


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif"}


def _safe_asset_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).name).strip(".-")
    return cleaned or "asset.bin"


def brief_asset_seeds(brief: AIWebsiteBrief) -> dict[str, Path]:
    """Map site-relative paths to local uploaded files for seeding into source/."""
    seeds: dict[str, Path] = {}
    logo_used = False
    for asset in brief.assets.all().order_by("created_at"):
        if not asset.file:
            continue
        try:
            local_path = Path(asset.file.path)
        except (ValueError, NotImplementedError):
            continue
        if not local_path.is_file():
            continue
        suffix = local_path.suffix.lower() or Path(asset.original_name).suffix.lower()
        safe = _safe_asset_name(asset.original_name or local_path.name)
        is_image = suffix in IMAGE_SUFFIXES
        if asset.asset_type == "logo" and is_image and not logo_used:
            seeds[f"images/brand/logo{suffix or '.png'}"] = local_path
            logo_used = True
        elif is_image:
            seeds[f"images/uploads/{safe}"] = local_path
        else:
            seeds[f"images/uploads/{safe}"] = local_path
    # If user uploaded images but never marked one as logo, promote the first image.
    if not logo_used:
        for relative, path in list(seeds.items()):
            if relative.startswith("images/uploads/") and path.suffix.lower() in IMAGE_SUFFIXES:
                logo_rel = f"images/brand/logo{path.suffix.lower()}"
                seeds[logo_rel] = path
                break
    return seeds


def inject_brand_logo(source_dir: Path, *, logo_href: str, brand_name: str) -> None:
    """Ensure the uploaded logo appears in header/footer brand links across pages."""
    if not logo_href or not (source_dir / logo_href).is_file():
        return
    brand = re.sub(r"[<>\"&]", "", brand_name or "Home")
    img = (
        f'<img src="{logo_href}" alt="{brand}" class="brand-logo" '
        f'width="160" height="48" decoding="async">'
    )
    brand_link_re = re.compile(
        r'(<a\b[^>]*\b(?:class|id)\s*=\s*["\'][^"\']*\b(?:brand|logo|site-logo|navbar-brand)\b[^"\']*["\'][^>]*>)(.*?)(</a>)',
        re.IGNORECASE | re.DOTALL,
    )
    style_block = (
        "\n<style data-siaw-brand-logo>"
        ".brand-logo{display:block;height:40px;width:auto;max-width:180px;object-fit:contain;}"
        "a.brand,a.logo,.brand,.logo{display:inline-flex;align-items:center;gap:10px;}"
        "</style>\n"
    )

    for html_path in sorted(source_dir.rglob("*.html")):
        text = html_path.read_text(encoding="utf-8", errors="replace")
        original = text
        if logo_href in text and "brand-logo" in text:
            if "data-siaw-brand-logo" not in text and re.search(r"</head\s*>", text, re.I):
                text = re.sub(r"</head\s*>", style_block + "</head>", text, count=1, flags=re.I)
                if text != original:
                    html_path.write_text(text, encoding="utf-8")
            continue

        def replace_brand(match: re.Match[str]) -> str:
            inner = match.group(2)
            if "brand-logo" in inner or logo_href in inner:
                return match.group(0)
            # Keep a text label beside the logo when the brand had visible text.
            label = re.sub(r"<[^>]+>", "", inner).strip()
            label_html = f'<span class="brand-name">{label or brand}</span>' if (label or brand) else ""
            return f"{match.group(1)}{img}{label_html}{match.group(3)}"

        text, count = brand_link_re.subn(replace_brand, text, count=2)
        if count == 0:
            # Fallback: inject into the first header.
            header_re = re.compile(r"(<header\b[^>]*>)", re.IGNORECASE)
            if header_re.search(text):
                text = header_re.sub(
                    rf'\1<a class="brand" href="index.html" aria-label="{brand}">{img}'
                    rf'<span class="brand-name">{brand}</span></a>',
                    text,
                    count=1,
                )
        if "data-siaw-brand-logo" not in text and re.search(r"</head\s*>", text, re.I):
            text = re.sub(r"</head\s*>", style_block + "</head>", text, count=1, flags=re.I)
        if text != original:
            html_path.write_text(text, encoding="utf-8")


_IMG_SRC_RE = re.compile(
    r"""(?P<prefix>\bsrc\s*=\s*)(?P<quote>['"])(?P<src>[^'"]+)(?P=quote)""",
    re.IGNORECASE,
)
_EXTERNAL_IMG_RE = re.compile(r"^https?://", re.IGNORECASE)


def _html_references_path(html_text: str, relative: str) -> bool:
    needle = relative.replace("\\", "/")
    return needle in html_text or Path(needle).name in html_text


def inject_uploaded_photos(source_dir: Path, upload_hrefs: list[str], *, brand_name: str = "") -> None:
    """Ensure every local upload appears in HTML, preferring them over stock/external images.

    Strategy:
    1. Replace external <img src="https://..."> with unused uploads (hero/gallery first).
    2. Append a photo strip for any uploads still unused.
    Stock/generated URLs may remain as extras after uploads are placed.
    """
    image_hrefs = [
        href
        for href in upload_hrefs
        if Path(href).suffix.lower() in IMAGE_SUFFIXES and (source_dir / href).is_file()
    ]
    if not image_hrefs:
        return

    html_files = sorted(source_dir.rglob("*.html"))
    if not html_files:
        return

    # Track which uploads already appear anywhere.
    used: set[str] = set()
    all_html = []
    for html_path in html_files:
        text = html_path.read_text(encoding="utf-8", errors="replace")
        all_html.append((html_path, text))
        for href in image_hrefs:
            if _html_references_path(text, href):
                used.add(href)

    unused = [href for href in image_hrefs if href not in used]
    if not unused:
        return

    # Prefer replacing external images on the homepage first, then other pages.
    ordered_files = sorted(
        all_html,
        key=lambda item: (0 if item[0].name.lower() in {"index.html", "index.htm"} else 1, item[0].as_posix()),
    )

    for html_path, text in ordered_files:
        if not unused:
            break
        original = text

        def replacer(match: re.Match[str]) -> str:
            nonlocal unused
            src = match.group("src")
            if not unused:
                return match.group(0)
            # Leave local brand/logo and already-local upload refs alone.
            if src.startswith(("images/brand/", "images/uploads/", "./images/", "/images/")):
                return match.group(0)
            if not _EXTERNAL_IMG_RE.match(src) and not src.startswith(("data:", "blob:")):
                # Relative non-upload local paths: still replace stock-ish media placeholders.
                if "unsplash" not in src.lower() and "placeholder" not in src.lower():
                    return match.group(0)
            nxt = unused.pop(0)
            used.add(nxt)
            return f'{match.group("prefix")}{match.group("quote")}{nxt}{match.group("quote")}'

        text = _IMG_SRC_RE.sub(replacer, text)
        if text != original:
            html_path.write_text(text, encoding="utf-8")
            # refresh stored text for append pass
            for index, (path, _old) in enumerate(ordered_files):
                if path == html_path:
                    ordered_files[index] = (path, text)
                    break

    # Any remaining uploads get a dedicated gallery strip on the homepage.
    if unused:
        home = next((path for path, _ in ordered_files if path.name.lower() in {"index.html", "index.htm"}), ordered_files[0][0])
        text = home.read_text(encoding="utf-8", errors="replace")
        if any(_html_references_path(text, href) for href in unused):
            unused = [href for href in unused if not _html_references_path(text, href)]
        if unused:
            figures = []
            label = re.sub(r"[<>\"&]", "", brand_name or "Gallery")
            for href in unused:
                figures.append(
                    f'<figure class="siaw-upload-shot">'
                    f'<img src="{href}" alt="{label} photo" loading="lazy" decoding="async">'
                    f"</figure>"
                )
                used.add(href)
            section = (
                '<section class="section siaw-upload-gallery" aria-label="Uploaded photos">'
                '<div class="container">'
                '<p class="eyebrow">From your library</p>'
                "<h2>Photos you shared.</h2>"
                f'<div class="siaw-upload-grid">{"".join(figures)}</div>'
                "</div></section>"
            )
            style = (
                "\n<style data-siaw-upload-gallery>"
                ".siaw-upload-gallery{padding:72px 0}"
                ".siaw-upload-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-top:28px}"
                ".siaw-upload-shot{margin:0;border-radius:18px;overflow:hidden;background:#eee}"
                ".siaw-upload-shot img{width:100%;height:260px;object-fit:cover;display:block}"
                "</style>\n"
            )
            if "data-siaw-upload-gallery" not in text and re.search(r"</head\s*>", text, re.I):
                text = re.sub(r"</head\s*>", style + "</head>", text, count=1, flags=re.I)
            if re.search(r"</main\s*>", text, re.I):
                text = re.sub(r"</main\s*>", section + "\n</main>", text, count=1, flags=re.I)
            elif re.search(r"</body\s*>", text, re.I):
                text = re.sub(r"</body\s*>", section + "\n</body>", text, count=1, flags=re.I)
            else:
                text += section
            home.write_text(text, encoding="utf-8")
            unused = []


def apply_brief_assets_to_source(source_dir: Path, brief: AIWebsiteBrief) -> str | None:
    """Copy brief uploads into source and force-apply logo + photos in HTML."""
    seeds = brief_asset_seeds(brief)
    logo_href = None
    upload_hrefs: list[str] = []
    for relative, source_path in seeds.items():
        target = source_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source_path.resolve() != target.resolve():
            shutil.copy2(source_path, target)
        if relative.startswith("images/brand/logo"):
            logo_href = relative
        elif relative.startswith("images/uploads/"):
            upload_hrefs.append(relative)
    if logo_href:
        inject_brand_logo(
            source_dir,
            logo_href=logo_href,
            brand_name=brief.business_name or "Home",
        )
    if upload_hrefs:
        inject_uploaded_photos(
            source_dir,
            upload_hrefs,
            brand_name=brief.business_name or "",
        )
    return logo_href


def brief_to_generation_prompt(brief: AIWebsiteBrief) -> str:
    """Turn the structured creative brief into a site-build prompt for Codex."""
    spec = produce_generation_spec(brief)
    goals = brief_goals(brief)
    brand = brief.brand_json if isinstance(brief.brand_json, dict) else {}
    services = brief.services_json if isinstance(brief.services_json, list) else []
    pages = spec.get("pages") or []
    seeds = brief_asset_seeds(brief)
    logo_path = next((path for path in seeds if path.startswith("images/brand/logo")), "")

    lines = [
        sitewright_quality_rules(multipage=True),
        "",
        f"Build a complete multi-page marketing website for {brief.business_name or 'this business'}.",
        "",
        "BUSINESS",
        f"- Name: {brief.business_name or 'TBD'}",
        f"- Industry: {brief.industry or 'TBD'}",
        f"- Description: {brief.description or 'TBD'}",
        f"- Location: {brief.location or 'Not specified'}",
        f"- Language: {brief.language or 'English'}",
        "",
        "WEBSITE GOALS (prioritize in this order, max three)",
    ]
    custom = brief_custom_goal(brief)
    if goals:
        for index, goal in enumerate(goals, 1):
            if goal == OTHER_GOAL and custom:
                lines.append(
                    f"- {index}. PRIORITY (user-defined): {custom}"
                )
            else:
                lines.append(f"- {index}. {display_goal(goal, brief)} ({goal})")
        if custom and OTHER_GOAL in goals:
            lines.append(
                "- Treat the user-defined priority outcome as the primary conversion job of the site."
            )
    else:
        lines.append("- Build credibility and present services clearly")

    lines.extend(
        [
            "",
            "DESIGN",
            f"- Visual style: {brief.visual_style or 'sector-fit, polished, not generic'}",
            f"- Primary color: {brand.get('primary_color') or 'choose a sector-fit accent'}",
            "",
            "BRAND ASSETS ALREADY IN THE PROJECT FOLDER",
        ]
    )
    if seeds:
        for relative in seeds:
            kind = "LOGO (required in header/footer)" if relative.startswith("images/brand/logo") else "image/file"
            lines.append(f"- {relative} ({kind})")
        upload_paths = [path for path in seeds if path.startswith("images/uploads/")]
        if logo_path:
            lines.append(
                f"- MUST use <img src=\"{logo_path}\" alt=\"{brief.business_name or 'Logo'}\" class=\"brand-logo\"> "
                "inside the main header brand/logo link on every page."
            )
            lines.append("- Do not replace the logo with text initials or a generated mark when this file exists.")
        if upload_paths:
            lines.extend(
                [
                    "- MUST use EVERY uploaded photo below in visible <img> tags before any stock photography:",
                    *[f"  * {path}" for path in upload_paths],
                    "- Put the first upload in the hero, then use the rest in story/gallery/portfolio/cards.",
                    "- Stock Unsplash images are allowed only as extras after all uploads appear on the page.",
                ]
            )
    else:
        lines.append("- No local brand assets were uploaded. Prefer Unsplash URLs for photography.")
    lines.extend(["", "PAGES (create real HTML files for each)"])
    for page in pages:
        if isinstance(page, dict):
            lines.append(f"- {page.get('title') or 'Page'} ({page.get('slug') or 'page'}.html)")
        else:
            lines.append(f"- {page}")

    lines.extend(["", "HOMEPAGE SECTIONS"])
    for section in spec.get("homepage_sections") or []:
        lines.append(f"- {section}")

    if services:
        lines.extend(["", "SERVICES / PRODUCTS"])
        for item in services[:8]:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or "Service"
            detail = item.get("description") or item.get("benefit") or ""
            lines.append(f"- {name}: {detail}".rstrip(": "))

    lines.extend(
        [
            "",
            "TECHNICAL REQUIREMENTS",
            "- Ship index.html plus the other pages as separate .html files.",
            "- Use styles.css. Prefer no JavaScript.",
            "- Relative asset paths only.",
            "- Keep the seeded images/brand and images/uploads files. Do not delete them.",
            "- Prefer Unsplash image URLs for extra photography only.",
            "",
            "STRUCTURED SPEC (for reference)",
            json.dumps(spec, ensure_ascii=True, indent=2)[:6000],
        ]
    )

    if brief.starting_point == "redesign" and brief.existing_website_url:
        redesign = brief.redesign_json if isinstance(brief.redesign_json, dict) else {}
        lines.extend(
            [
                "",
                "REDESIGN CONTEXT",
                f"- Existing site: {brief.existing_website_url}",
                f"- Dislikes: {redesign.get('dislikes') or 'not specified'}",
                f"- Must keep: {redesign.get('keep') or 'not specified'}",
            ]
        )

    return "\n".join(lines)


def generate_website_from_brief(
    brief: AIWebsiteBrief,
    *,
    owner,
    prompt: str | None = None,
    mode: str = "final",
) -> WebsiteProject:
    """Generate a full site from the brief using Codex/OpenAI/offline providers.

    mode:
      - final: blocks editing (status=generating), then marks generated
      - prefetch: speculative background build; leaves brief editable
    """
    goals = brief_goals(brief)
    if not brief.business_name or not brief.description:
        raise ValidationError("Complete the required brief fields before generating.")
    if not goals:
        if mode == "prefetch":
            brief.primary_goal = (brief.primary_goal or "credibility").strip() or "credibility"
            brief.save(update_fields=["primary_goal", "updated_at"])
            goals = brief_goals(brief)
        else:
            raise ValidationError("Complete the required brief fields before generating.")
    if not brief.primary_goal:
        brief.primary_goal = goals[0]
        brief.save(update_fields=["primary_goal", "updated_at"])

    spec = produce_generation_spec(brief)
    resolved_prompt = (prompt or brief.master_prompt or brief_to_generation_prompt(brief)).strip()
    if not resolved_prompt:
        raise ValidationError("The generation prompt is empty. Complete the brief first.")
    seeds = brief_asset_seeds(brief)
    brief.generation_brief_json = {
        **(brief.generation_brief_json if isinstance(brief.generation_brief_json, dict) else {}),
        **spec,
        "seeded_assets": list(seeds.keys()),
        "mode": mode,
        "prompt_chars": len(resolved_prompt),
    }
    update_fields = ["generation_brief_json", "updated_at"]
    if mode == "final":
        brief.status = "generating"
        update_fields.append("status")
    brief.save(update_fields=update_fields)

    project = WebsiteProject.objects.create(
        name=brief.business_name[:160] or "AI Website",
        owner=owner,
        entry_file="index.html",
    )
    # Link immediately so a hung Codex process can still be adopted later.
    if mode == "prefetch":
        brief.project = project
        brief.save(update_fields=["project", "updated_at"])
    try:
        generated = create_website_from_prompt(
            project.project_dir,
            prompt=resolved_prompt,
            project_name=project.name,
            force_offline=bool(getattr(settings, "SIAW_AI_FORCE_OFFLINE", False)),
            seed_files=seeds,
        )
        project.entry_file = generated.entry_file
        project.stylesheet_files = generated.stylesheet_files
        project.save(update_fields=["entry_file", "stylesheet_files", "updated_at"])

        # Re-apply after generation in case the model overwrote or ignored assets.
        apply_brief_assets_to_source(project.source_dir, brief)

        if mode == "final":
            brief.project = project
            brief.status = "generated"
            brief.save(update_fields=["project", "status", "updated_at"])
        return project
    except Exception:
        if mode == "final":
            brief.status = "failed"
            brief.save(update_fields=["status", "updated_at"])
        elif brief.project_id == project.id:
            brief.project = None
            brief.save(update_fields=["project", "updated_at"])
        shutil.rmtree(project.project_dir, ignore_errors=True)
        WebsiteProject.objects.filter(pk=project.pk).delete()
        raise
