"""AI website builder: prompt → self-contained HTML project for Safe Edit.

Generates static, GrapesJS-friendly sites (semantic HTML + CSS, no app shell JS).
Prefers the Codex CLI for full site builds when available.
Falls back to OpenAI chat APIs or the offline design engine.
Ollama is disabled (local model loads can freeze the host machine).
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

from django.conf import settings
from django.core.exceptions import ValidationError

from .archive import StylesheetParser
from .sitewright_prompt import sitewright_quality_rules

# User-typed paste prompts stay short. Assembled wizard/Codex prompts include
# Sitewright rules + structured spec and need a much higher ceiling.
MAX_PROMPT_CHARS = 4000
MAX_BUILD_PROMPT_CHARS = 24000
MAX_HTML_BYTES = 1_500_000

SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
HTML_FENCE_RE = re.compile(r"```(?:html)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class GeneratedWebsite:
    entry_file: str
    stylesheet_files: list[str]
    provider: str
    brief: dict


@dataclass(frozen=True)
class SiteBrief:
    brand: str
    tagline: str
    sector: str
    palette: str
    summary: str
    cta: str
    audience: str
    features_title: str = "A homepage that feels finished on day one."
    features_lead: str = "Clear hierarchy, real sections, and copy you can rewrite in the visual editor."
    features: tuple[tuple[str, str], ...] = ()
    story_title: str = "Designed to convert without looking like a template."
    story_body: str = (
        "Generated from your brief, then opened in Safe Edit so you can change text, "
        "images and sections with drag and drop."
    )
    proofs: tuple[tuple[str, str], ...] = ()
    contact_lead: str = "Edit any line, swap images, restyle buttons, then export a clean ZIP for your client."
    contact_note: str = "Tell visitors exactly what happens next."


SECTOR_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("luxury", ("luxury", "perfume", "fragrance", "boutique", "jewelry", "spa", "beauty")),
    ("health", ("health", "wellness", "clinic", "fitness", "yoga", "mindful", "therapy")),
    ("finance", ("finance", "fintech", "bank", "invest", "payment", "crypto", "accounting")),
    ("food", ("restaurant", "cafe", "coffee", "food", "kitchen", "chef", "bakery")),
    ("travel", ("travel", "hotel", "resort", "tour", "flight", "hospitality")),
    ("realestate", ("real estate", "property", "homes", "apartment", "realtor")),
    ("education", ("school", "course", "learn", "academy", "tutoring", "education")),
    ("saas", ("saas", "software", "platform", "app", "startup", "ai ", "tool")),
    ("creative", ("studio", "agency", "design", "portfolio", "creative", "brand")),
    ("ecommerce", ("shop", "store", "ecommerce", "product", "retail", "merch")),
]

PALETTES = {
    "luxury": {
        "bg": "#f7f2ea",
        "ink": "#1c1712",
        "muted": "#6e6256",
        "accent": "#9a7040",
        "surface": "#fffaf3",
        "line": "#e5d8c6",
        "display": "Cormorant Garamond",
        "body": "Jost",
        "hero": "https://images.unsplash.com/photo-1541643600914-78b084683601?auto=format&fit=crop&w=1600&q=80",
        "feature": "https://images.unsplash.com/photo-1594035910387-fea47794261f?auto=format&fit=crop&w=1200&q=80",
    },
    "health": {
        "bg": "#f4f7f5",
        "ink": "#14201a",
        "muted": "#5c6b62",
        "accent": "#2f7d5b",
        "surface": "#ffffff",
        "line": "#d7e2db",
        "display": "Fraunces",
        "body": "DM Sans",
        "hero": "https://images.unsplash.com/photo-1544367567-0f2fcb009e0b?auto=format&fit=crop&w=1600&q=80",
        "feature": "https://images.unsplash.com/photo-1571019614242-c5c5dee9f50b?auto=format&fit=crop&w=1200&q=80",
    },
    "finance": {
        "bg": "#f2f5f8",
        "ink": "#0f1720",
        "muted": "#5b6775",
        "accent": "#0f6e56",
        "surface": "#ffffff",
        "line": "#d8e3ea",
        "display": "Instrument Serif",
        "body": "IBM Plex Sans",
        "hero": "https://images.unsplash.com/photo-1553729459-efe14ef6055d?auto=format&fit=crop&w=1600&q=80",
        "feature": "https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=1200&q=80",
    },
    "food": {
        "bg": "#efe6db",
        "ink": "#1a1612",
        "muted": "#6a5c50",
        "accent": "#b87333",
        "surface": "#f7f0e7",
        "line": "#d9cbb8",
        "display": "Cormorant Garamond",
        "body": "DM Sans",
        "hero": "https://images.unsplash.com/photo-1414235077428-338989a2e8c0?auto=format&fit=crop&w=2000&q=80",
        "feature": "https://images.unsplash.com/photo-1559339352-11d035aa65de?auto=format&fit=crop&w=1400&q=80",
        "alt1": "https://images.unsplash.com/photo-1504674900247-0877df9cc836?auto=format&fit=crop&w=1200&q=80",
        "alt2": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?auto=format&fit=crop&w=1400&q=80",
        "alt3": "https://images.unsplash.com/photo-1550966871-3ed3cdb5ed0c?auto=format&fit=crop&w=1200&q=80",
    },
    "travel": {
        "bg": "#f3f7f9",
        "ink": "#132029",
        "muted": "#5a6b74",
        "accent": "#1f6f8b",
        "surface": "#ffffff",
        "line": "#d5e2e8",
        "display": "Libre Baskerville",
        "body": "Nunito Sans",
        "hero": "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1600&q=80",
        "feature": "https://images.unsplash.com/photo-1469474968028-56623f02e42e?auto=format&fit=crop&w=1200&q=80",
    },
    "realestate": {
        "bg": "#f5f4f1",
        "ink": "#1a1a18",
        "muted": "#66635c",
        "accent": "#8b7355",
        "surface": "#ffffff",
        "line": "#e2ddd3",
        "display": "Newsreader",
        "body": "Manrope",
        "hero": "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?auto=format&fit=crop&w=1600&q=80",
        "feature": "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1200&q=80",
    },
    "education": {
        "bg": "#f5f7fb",
        "ink": "#151b28",
        "muted": "#5d6678",
        "accent": "#335cff",
        "surface": "#ffffff",
        "line": "#d9e0ec",
        "display": "Literata",
        "body": "Figtree",
        "hero": "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?auto=format&fit=crop&w=1600&q=80",
        "feature": "https://images.unsplash.com/photo-1434030216411-0b793f4b4173?auto=format&fit=crop&w=1200&q=80",
    },
    "saas": {
        "bg": "#f4f5f7",
        "ink": "#111318",
        "muted": "#606774",
        "accent": "#e11d48",
        "surface": "#ffffff",
        "line": "#e1e4ea",
        "display": "Space Grotesk",
        "body": "Inter",
        "hero": "https://images.unsplash.com/photo-1551434678-e076c015b6b9?auto=format&fit=crop&w=1600&q=80",
        "feature": "https://images.unsplash.com/photo-1460925895917-afdab827c52f?auto=format&fit=crop&w=1200&q=80",
    },
    "creative": {
        "bg": "#f7f4f0",
        "ink": "#17130f",
        "muted": "#6a5f55",
        "accent": "#d9480f",
        "surface": "#fffdfb",
        "line": "#e8ddd2",
        "display": "Syne",
        "body": "Outfit",
        "hero": "https://images.unsplash.com/photo-1561070791-2526d30994b5?auto=format&fit=crop&w=1600&q=80",
        "feature": "https://images.unsplash.com/photo-1558655146-d09347e92766?auto=format&fit=crop&w=1200&q=80",
    },
    "ecommerce": {
        "bg": "#f7f7f5",
        "ink": "#161616",
        "muted": "#666666",
        "accent": "#111111",
        "surface": "#ffffff",
        "line": "#e5e5e5",
        "display": "Bodoni Moda",
        "body": "Helvetica Neue",
        "hero": "https://images.unsplash.com/photo-1441986300917-64674bd600d8?auto=format&fit=crop&w=1600&q=80",
        "feature": "https://images.unsplash.com/photo-1523381210434-443e0c4f1f8f?auto=format&fit=crop&w=1200&q=80",
    },
}


PROMPT_FIELD_LABELS = (
    "Brand name",
    "Sector",
    "Location / market",
    "Audience",
    "Offer",
    "Personality / tone",
    "Must include",
    "Avoid",
    "Primary CTA",
    "Reference feeling",
    "Extra notes",
    "Client brief",
)
BANNED_BRAND_STARTS = {
    "create", "complete", "static", "website", "client", "brand", "sector", "location",
    "audience", "offer", "personality", "requirements", "primary", "reference",
}


def _is_assembled_build_prompt(prompt: str) -> bool:
    text = prompt or ""
    markers = (
        "Siaw Sitewright",
        "WEBSITE GOALS",
        "STRUCTURED SPEC",
        "TECHNICAL REQUIREMENTS",
        "Write real files into this working directory",
    )
    return any(marker in text for marker in markers)


def _clean_prompt(prompt: str) -> str:
    raw = (prompt or "").strip()
    if not raw:
        raise ValidationError("Describe the website you want to create.")
    if _is_assembled_build_prompt(raw):
        # Keep structure for Codex/wizard builds. Only tidy runaway blank lines.
        text = re.sub(r"[ \t]+\n", "\n", raw)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        limit = MAX_BUILD_PROMPT_CHARS
        if len(text) > limit:
            raise ValidationError(
                f"The generation brief is too large ({len(text)} characters). "
                f"Maximum is {limit}."
            )
        return text

    text = re.sub(r"\s+", " ", raw)
    if len(text) > MAX_PROMPT_CHARS:
        raise ValidationError(f"Keep the brief under {MAX_PROMPT_CHARS} characters.")
    return text


def _prompt_fields(prompt: str) -> dict[str, str]:
    """Parse labeled brief fields from the user prompt template (multiline or one line)."""
    text = prompt or ""
    label_alt = "|".join(re.escape(label) for label in PROMPT_FIELD_LABELS)
    splitter = re.compile(rf"(?i)\b({label_alt})\s*:\s*")
    parts = splitter.split(text)
    fields: dict[str, str] = {}
    # parts: [preamble, label, value, label, value, ...]
    index = 1
    while index + 1 < len(parts):
        key = re.sub(r"\s+", " ", parts[index].strip().lower())
        value = parts[index + 1].strip()
        # Stop a value when the next label was glued without a clean split leftover.
        value = re.split(r"\n{2,}", value, maxsplit=1)[0].strip()
        if value:
            fields[key] = value
        index += 2
    return fields


def detect_sector(prompt: str) -> str:
    lowered = prompt.lower()
    fields = _prompt_fields(prompt)
    explicit = (fields.get("sector") or "").lower()
    if explicit:
        for sector, keywords in SECTOR_HINTS:
            if sector in explicit or any(keyword in explicit for keyword in keywords):
                return sector
        if any(token in explicit for token in ("restaurant", "dining", "cafe", "coffee", "bistro", "chef")):
            return "food"

    # Score keywords so incidental words like "luxury" do not beat "restaurant".
    scores: dict[str, int] = {}
    for sector, keywords in SECTOR_HINTS:
        score = 0
        for keyword in keywords:
            if keyword in lowered:
                # Strong business nouns weigh more than adjectives.
                score += 3 if len(keyword) > 5 else 1
                if keyword in {"restaurant", "cafe", "hotel", "clinic", "perfume", "saas", "shop"}:
                    score += 4
        if score:
            scores[sector] = score
    if scores:
        return max(scores.items(), key=lambda item: item[1])[0]
    return "saas"


def extract_brand(prompt: str, fallback: str = "Studio") -> str:
    fields = _prompt_fields(prompt)
    labeled = (fields.get("brand name") or "").strip()
    if labeled and labeled.lower().split()[0] not in BANNED_BRAND_STARTS:
        return labeled[:60]

    patterns = [
        r"(?i)brand name\s*:\s*([^\n]+)",
        r"(?:called|named)\s+[\"']?([A-Z][\w&'’-]{1,40}(?:\s+[A-Z][\w&'’-]{1,40}){0,3})",
    ]
    for pattern in patterns:
        match = re.search(pattern, prompt)
        if match:
            candidate = match.group(1).strip().strip("\"'")
            candidate = re.split(r"\s{2,}|Sector:|Location", candidate)[0].strip()
            first = candidate.split()[0].lower() if candidate else ""
            if candidate and first not in BANNED_BRAND_STARTS:
                return candidate[:60]

    fallback_clean = (fallback or "").strip()
    if fallback_clean and fallback_clean.lower().split()[0] not in BANNED_BRAND_STARTS:
        return fallback_clean[:60]
    return "Studio"


def _summary_from_prompt(prompt: str, *, brand: str, sector: str, audience: str) -> str:
    """Never dump the raw instruction prompt onto the website."""
    fields = _prompt_fields(prompt)
    offer = fields.get("offer") or ""
    location = fields.get("location / market") or fields.get("location/market") or ""
    audience_field = fields.get("audience") or audience
    if offer:
        parts = [offer.rstrip(".")]
        if location:
            parts.append(f"Based in {location.rstrip('.')}")
        if audience_field:
            parts.append(f"For {audience_field.rstrip('.')}")
        summary = ". ".join(parts) + "."
        return summary[:220]

    # Strip boilerplate instruction lines, keep a short human sentence.
    cleaned = prompt
    cleaned = re.sub(r"(?is)create a complete static website for this client\.?", " ", cleaned)
    cleaned = re.sub(r"(?is)requirements reminder:.*$", " ", cleaned)
    cleaned = re.sub(r"(?im)^\s*(brand name|sector|avoid|must include|primary cta|reference feeling|extra notes)\s*:.*$", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
    if cleaned and not cleaned.lower().startswith("create a complete"):
        return cleaned[:180] + ("..." if len(cleaned) > 180 else "")

    sector_label = sector.replace("realestate", "real estate")
    return f"{brand} is a {sector_label} brand built for {audience_field}."[:220]


def build_brief(prompt: str, project_name: str = "") -> SiteBrief:
    clean = _clean_prompt(prompt)
    fields = _prompt_fields(prompt)
    sector = detect_sector(prompt)
    project = (project_name or "").strip()
    brand = extract_brand(prompt, fallback=project or "Studio")
    if project and brand.lower() in {"studio", "complete static", "create a"}:
        brand = project[:60]
    elif project and len(project) >= 2:
        # Form project name wins when the prompt is the long instruction template.
        if "create a complete static website" in clean.lower() or fields.get("brand name"):
            brand = (fields.get("brand name") or project)[:60]

    tagline_map = {
        "luxury": "Crafted for those who notice the details.",
        "health": "Feel better, move clearer, live lighter.",
        "finance": "Money tools that stay out of the way.",
        "food": "Flavours worth gathering for.",
        "travel": "Arrivals that feel like belonging.",
        "realestate": "Homes with room to breathe.",
        "education": "Learn with focus, not friction.",
        "saas": "Ship work that looks intentional.",
        "creative": "Brands that leave a mark.",
        "ecommerce": "Products people keep reaching for.",
    }
    cta_map = {
        "luxury": "Book a private visit",
        "health": "Start your plan",
        "finance": "Open an account",
        "food": "Reserve a table",
        "travel": "Plan your stay",
        "realestate": "Browse listings",
        "education": "Explore courses",
        "saas": "Start free",
        "creative": "Start a project",
        "ecommerce": "Shop the collection",
    }
    audience = (fields.get("audience") or "clients and visitors who care about craft").strip()[:80]
    cta = (fields.get("primary cta") or cta_map.get(sector, "Get started")).strip()[:40]
    summary = _summary_from_prompt(prompt, brand=brand, sector=sector, audience=audience)
    sector_features = {
        "food": (
            ("Seasonal tasting", "A paced seafood menu that follows the tide and the market morning."),
            ("Sunset terrace", "Open-air seating for long dinners as the light drops over the water."),
            ("Chef's table", "A quieter seat for guests who want the kitchen's full attention."),
        ),
        "luxury": (
            ("Private consultation", "Quiet guidance for clients who treat scent as an heirloom."),
            ("Curated shelves", "A short list of bottles chosen for character, not trend cycles."),
            ("Atelier visits", "Appointments that feel unhurried from the first greeting."),
        ),
    }
    default_features = sector_features.get(
        sector,
        (
            ("Signal clarity", "A focused first impression that says who you are in one breath."),
            ("Editorial craft", "Typography, spacing and imagery chosen for the category, not a template dump."),
            ("Easy to edit", "Every section is real HTML you can click, restyle and export."),
        ),
    )
    default_proofs = (
        (("4.9", "Guest rating"), ("18", "Seats at the chef's table"), ("Sunsets", "Worth lingering for"))
        if sector == "food"
        else (("4.9", "Average client rating"), ("120+", "Projects shipped"), ("48h", "Typical first draft"))
    )
    food_defaults = sector == "food"
    return SiteBrief(
        brand=brand,
        tagline=tagline_map.get(sector, "Built to feel premium from the first scroll."),
        sector=sector,
        palette=sector if sector in PALETTES else "saas",
        summary=summary,
        cta=cta,
        audience=audience,
        features_title="Signature plates, paced for the evening." if food_defaults else "A homepage that feels finished on day one.",
        features_lead="Seafood, fire, and a terrace that holds the last light of the day." if food_defaults else "Clear hierarchy, real sections, and copy you can rewrite in the visual editor.",
        features=default_features,
        story_title="Dinners that linger past sunset." if food_defaults else "Designed to convert without looking like a template.",
        story_body=(
            f"{brand} is built for unhurried dinners: tasting menus, terrace seating, and a chef's table when you want the kitchen close."
            if food_defaults
            else "Generated from your brief, then opened in Safe Edit so you can change text, images and sections with drag and drop."
        ),
        proofs=default_proofs,
        contact_lead="Private tables and tasting seatings. WhatsApp-friendly confirmations." if food_defaults else "Edit any line, swap images, restyle buttons, then export a clean ZIP for your client.",
        contact_note="Tell us the date, party size, and whether you want the terrace or chef's table." if food_defaults else "Tell visitors exactly what happens next.",
    )


def _font_href(display: str, body: str) -> str:
    families = []
    for name in (display, body):
        if not name or name == "Helvetica Neue":
            continue
        families.append(name.replace(" ", "+") + ":wght@300;400;500;600;700")
    if not families:
        return ""
    return "https://fonts.googleapis.com/css2?family=" + "&family=".join(families) + "&display=swap"



def _nav_labels(brief: SiteBrief) -> dict[str, str]:
    if brief.sector == "food":
        return {
            "home": "Home",
            "features": "Menu",
            "story": "Experience",
            "contact": brief.cta or "Reserve",
        }
    if brief.sector == "luxury":
        return {
            "home": "Home",
            "features": "Collection",
            "story": "Atelier",
            "contact": brief.cta or "Visit",
        }
    return {
        "home": "Home",
        "features": "Features",
        "story": "Story",
        "contact": brief.cta or "Contact",
    }


def _shared_css(brief: SiteBrief) -> str:
    palette = PALETTES[brief.palette]
    display_stack = f"'{palette['display']}', Georgia, serif" if palette["display"] != "Space Grotesk" else f"'{palette['display']}', Inter, sans-serif"
    body_stack = f"'{palette['body']}', system-ui, sans-serif" if palette["body"] != "Helvetica Neue" else "Helvetica Neue, Helvetica, Arial, sans-serif"
    return f"""
:root {{
  --bg: {palette["bg"]};
  --ink: {palette["ink"]};
  --muted: {palette["muted"]};
  --accent: {palette["accent"]};
  --surface: {palette["surface"]};
  --line: {palette["line"]};
  --display: {display_stack};
  --body: {body_stack};
  --radius: 4px;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  font-family: var(--body);
  color: var(--ink);
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--accent) 8%, var(--bg)) 0%, var(--bg) 28%, var(--bg) 100%);
  line-height: 1.6;
}}
img {{ max-width: 100%; display: block; }}
a {{ color: inherit; text-decoration: none; }}
.wrap {{ width: min(1180px, calc(100% - 2.5rem)); margin: 0 auto; }}
.site-header {{
  position: sticky; top: 0; z-index: 20;
  backdrop-filter: blur(16px);
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--line) 80%, transparent);
}}
.nav {{ display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 1.05rem 0; }}
.brand {{ font-family: var(--display); font-size: clamp(1.55rem, 2.4vw, 2rem); letter-spacing: -0.03em; font-weight: 600; }}
.nav-links {{ display: flex; gap: 1.5rem; align-items: center; color: var(--muted); font-size: .95rem; }}
.nav-links a:hover, .nav-links a.is-active {{ color: var(--ink); }}
.btn {{
  display: inline-flex; align-items: center; justify-content: center;
  padding: .9rem 1.35rem; border-radius: 999px; border: 1px solid transparent;
  font-weight: 600; font-size: .95rem; transition: transform .22s ease, background .22s ease, color .22s ease, border-color .22s ease;
}}
.btn:hover {{ transform: translateY(-1px); }}
.btn-primary {{ background: var(--accent); color: #fffaf3; }}
.btn-ghost {{ border-color: var(--line); background: transparent; color: var(--ink); }}
.btn-light {{ background: #fffaf3; color: var(--ink); }}
.eyebrow {{ margin: 0 0 .85rem; color: var(--accent); font-size: .72rem; letter-spacing: .18em; text-transform: uppercase; font-weight: 700; }}
.hero-bleed {{
  position: relative; min-height: min(92vh, 820px); display: grid; align-items: end;
  color: #f7f1e8; overflow: hidden;
}}
.hero-bleed-media {{ position: absolute; inset: 0; }}
.hero-bleed-media img {{ width: 100%; height: 100%; object-fit: cover; transform: scale(1.02); }}
.hero-bleed-shade {{
  position: absolute; inset: 0;
  background:
    linear-gradient(180deg, rgba(12,10,8,.18) 0%, rgba(12,10,8,.28) 40%, rgba(12,10,8,.78) 100%),
    linear-gradient(90deg, rgba(12,10,8,.55) 0%, rgba(12,10,8,.08) 70%);
}}
.hero-bleed-copy {{
  position: relative; z-index: 1; width: min(1180px, calc(100% - 2.5rem)); margin: 0 auto;
  padding: clamp(5rem, 12vw, 8rem) 0 clamp(3rem, 7vw, 5rem);
  max-width: 40rem;
  animation: rise .7s ease-out both;
}}
.hero-bleed .brand-mark {{
  margin: 0 0 1rem; font-family: var(--display); font-size: clamp(2.8rem, 7vw, 5.2rem);
  line-height: .92; letter-spacing: -0.04em; font-weight: 500;
}}
.hero-bleed h1 {{
  margin: 0; font-family: var(--display); font-weight: 500;
  font-size: clamp(1.7rem, 3.4vw, 2.55rem); line-height: 1.15; letter-spacing: -0.02em;
  max-width: 18ch; color: rgba(255,248,238,.94);
}}
.hero-bleed .hero-lead {{ margin: 1.15rem 0 0; color: rgba(255,245,232,.78); font-size: 1.05rem; max-width: 34rem; }}
.hero-actions {{ display: flex; flex-wrap: wrap; gap: .75rem; margin-top: 1.75rem; }}
.hero {{
  display: grid; grid-template-columns: 1.05fr .95fr; gap: clamp(1.5rem, 4vw, 3.5rem);
  align-items: center; padding: clamp(3rem, 8vw, 6rem) 0 clamp(2.5rem, 6vw, 4.5rem);
}}
.hero h1, .page-hero h1 {{
  margin: 0; font-family: var(--display); font-weight: 500;
  font-size: clamp(2.4rem, 5.5vw, 4.2rem); line-height: .98; letter-spacing: -0.04em;
}}
.hero-lead, .section-lead {{ margin: 1.25rem 0 0; color: var(--muted); font-size: 1.08rem; max-width: 36rem; }}
.hero-media, .split-media {{
  position: relative; border-radius: calc(var(--radius) + 10px); overflow: hidden;
  min-height: min(52vh, 480px); background: var(--surface); border: 1px solid var(--line);
  box-shadow: 0 30px 80px rgba(20, 20, 20, .12);
}}
.hero-media img, .split-media img {{ width: 100%; height: 100%; object-fit: cover; min-height: min(52vh, 480px); }}
section, .page-block {{ padding: clamp(3rem, 7vw, 5.5rem) 0; }}
.page-hero {{ padding: clamp(2.5rem, 6vw, 4rem) 0 1rem; }}
.section-title {{
  margin: 0 0 .65rem; font-family: var(--display); font-size: clamp(1.9rem, 3.5vw, 2.8rem);
  letter-spacing: -0.03em; line-height: 1.05;
}}
.feature-grid, .stats, .dish-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-top: 2rem; }}
.feature-card, .stat, .quote-card {{
  background: var(--surface); border: 1px solid var(--line); border-radius: calc(var(--radius) + 10px);
  padding: 1.35rem 1.3rem;
}}
.feature-card {{ min-height: 180px; }}
.feature-card h3, .dish-card h3 {{ margin: 0 0 .55rem; font-size: 1.15rem; font-family: var(--display); font-weight: 600; }}
.feature-card p, .stat span, .dish-card p, .quote-card p {{ margin: 0; color: var(--muted); }}
.dish-card {{
  background: var(--surface); border: 1px solid var(--line); border-radius: calc(var(--radius) + 10px);
  overflow: hidden; display: grid; grid-template-rows: 190px 1fr;
}}
.dish-card img {{ width: 100%; height: 190px; object-fit: cover; }}
.dish-card .dish-copy {{ padding: 1.2rem 1.2rem 1.35rem; }}
.split {{ display: grid; grid-template-columns: 1fr 1fr; gap: clamp(1.25rem, 3vw, 2.5rem); align-items: center; }}
.stat strong {{ display: block; font-family: var(--display); font-size: 2rem; letter-spacing: -0.03em; }}
.quote-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; margin-top: 2rem; }}
.quote-card q {{ display: block; font-family: var(--display); font-size: 1.35rem; line-height: 1.25; margin-bottom: .85rem; }}
.evening-band {{
  margin: 0; min-height: 420px; position: relative; color: #f7f1e8; display: grid; align-items: center;
}}
.evening-band img {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }}
.evening-band::after {{
  content: ""; position: absolute; inset: 0;
  background: linear-gradient(90deg, rgba(14,11,9,.82), rgba(14,11,9,.35) 55%, rgba(14,11,9,.2));
}}
.evening-copy {{ position: relative; z-index: 1; width: min(1180px, calc(100% - 2.5rem)); margin: 0 auto; max-width: 34rem; padding: 3.5rem 0; }}
.evening-copy h2 {{ margin: 0; font-family: var(--display); font-size: clamp(2rem, 4vw, 3rem); letter-spacing: -0.03em; }}
.evening-copy p {{ margin: 1rem 0 0; color: rgba(255,245,232,.8); }}
.cta-band {{
  border-radius: calc(var(--radius) + 8px); padding: clamp(2rem, 5vw, 3rem);
  background: linear-gradient(135deg, var(--ink), color-mix(in srgb, var(--ink) 78%, var(--accent)));
  color: white; display: flex; flex-wrap: wrap; justify-content: space-between; gap: 1.25rem; align-items: center;
}}
.cta-band h2 {{ margin: 0; font-family: var(--display); font-size: clamp(1.8rem, 3vw, 2.5rem); letter-spacing: -0.03em; }}
.cta-band p {{ margin: .55rem 0 0; color: rgba(255,255,255,.78); max-width: 34rem; }}
.cta-band .btn-primary {{ background: #fffaf3; color: var(--ink); }}
.site-footer {{ border-top: 1px solid var(--line); padding: 2rem 0 2.5rem; color: var(--muted); font-size: .92rem; }}
.footer-row {{ display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }}
@keyframes rise {{
  from {{ opacity: 0; transform: translateY(18px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}
@media (prefers-reduced-motion: reduce) {{
  .hero-bleed-copy, .btn {{ animation: none; transition: none; }}
}}
@media (max-width: 860px) {{
  .hero, .split, .feature-grid, .stats, .dish-grid, .quote-grid {{ grid-template-columns: 1fr; }}
  .nav-links {{ display: none; }}
  .hero-media, .hero-media img, .split-media, .split-media img {{ min-height: 280px; }}
  .hero-bleed {{ min-height: 78vh; }}
}}
""".strip()


def _shell(brief: SiteBrief, *, title: str, active: str, body: str) -> str:
    palette = PALETTES[brief.palette]
    brand = html.escape(brief.brand)
    cta = html.escape(brief.cta)
    labels = _nav_labels(brief)
    font_href = _font_href(palette["display"], palette["body"])
    font_links = ""
    if font_href:
        font_links = (
            '<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            f'<link rel="stylesheet" href="{font_href}">'
        )
    def nav_item(href: str, label: str) -> str:
        cls = ' class="is-active"' if active == href else ""
        return f'<a href="{href}"{cls}>{html.escape(label)}</a>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <meta name="description" content="{html.escape(brief.summary)}">
  {font_links}
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <header class="site-header">
    <div class="wrap nav">
      <a class="brand" href="index.html">{brand}</a>
      <nav class="nav-links" aria-label="Primary">
        {nav_item("index.html", labels["home"])}
        {nav_item("features.html", labels["features"])}
        {nav_item("story.html", labels["story"])}
        {nav_item("contact.html", labels["contact"])}
      </nav>
      <a class="btn btn-primary" href="contact.html">{cta}</a>
    </div>
  </header>
  <main>
{body}
  </main>
  <footer class="site-footer">
    <div class="wrap footer-row">
      <span>© {brand}</span>
      <span>Edit freely in Safe Edit</span>
    </div>
  </footer>
</body>
</html>
"""


def _food_home_body(brief: SiteBrief, palette: dict) -> str:
    brand = html.escape(brief.brand)
    tagline = html.escape(brief.tagline)
    summary = html.escape(brief.summary)
    cta = html.escape(brief.cta)
    features = list(brief.features)[:3] or [
        ("Seasonal tasting", "A paced seafood menu that follows the tide and the market."),
        ("Sunset terrace", "Open-air seating for long dinners as the light drops over the water."),
        ("Chef's table", "A quieter seat for guests who want the kitchen's full attention."),
    ]
    img1 = palette.get("alt1") or palette["feature"]
    img2 = palette.get("feature") or palette["hero"]
    img3 = palette.get("alt3") or palette["hero"]
    evening = palette.get("alt2") or palette["feature"]
    dishes = "".join(
        f"""<article class="dish-card">
          <img src="{src}" alt="{html.escape(title)}">
          <div class="dish-copy"><h3>{html.escape(title)}</h3><p>{html.escape(body)}</p></div>
        </article>"""
        for (title, body), src in zip(features, (img1, img2, img3))
    )
    return f"""
    <section class="hero-bleed" id="top">
      <div class="hero-bleed-media"><img src="{palette["hero"]}" alt="{brand} dining room"></div>
      <div class="hero-bleed-shade" aria-hidden="true"></div>
      <div class="hero-bleed-copy">
        <p class="brand-mark">{brand}</p>
        <h1>{tagline}</h1>
        <p class="hero-lead">{summary}</p>
        <div class="hero-actions">
          <a class="btn btn-light" href="contact.html">{cta}</a>
          <a class="btn btn-ghost" href="features.html" style="border-color:rgba(255,245,232,.35);color:#fff8ee">View the menu</a>
        </div>
      </div>
    </section>
    <section class="wrap page-block" id="features">
      <p class="eyebrow">On the table</p>
      <h2 class="section-title">{html.escape(brief.features_title if brief.features_title != "A homepage that feels finished on day one." else "Signature plates, paced for the evening.")}</h2>
      <p class="section-lead">{html.escape(brief.features_lead if "visual editor" not in brief.features_lead.lower() else "Seafood, fire, and a terrace that holds the last light of the day.")}</p>
      <div class="dish-grid">{dishes}</div>
    </section>
    <section class="evening-band" id="story">
      <img src="{evening}" alt="{brand} terrace evening">
      <div class="evening-copy">
        <p class="eyebrow" style="color:#d8a56a">The evening</p>
        <h2>{html.escape(brief.story_title if "template" not in brief.story_title.lower() else "Dinners that linger past sunset.")}</h2>
        <p>{html.escape(brief.story_body if "Generated from your brief" not in brief.story_body else "Come for the tasting menu. Stay for the terrace air, copper light, and a room that never hurries you out.")}</p>
        <div class="hero-actions"><a class="btn btn-light" href="story.html">Read the experience</a></div>
      </div>
    </section>
"""


def render_offline_site(brief: SiteBrief) -> dict[str, str]:
    """Sector-aware multipage site. Menu links are real HTML pages for the Pages tab."""
    palette = PALETTES.get(brief.palette) or PALETTES["saas"]
    brand = html.escape(brief.brand)
    tagline = html.escape(brief.tagline)
    summary = html.escape(brief.summary)
    cta = html.escape(brief.cta)
    sector = html.escape(brief.sector.replace("realestate", "real estate").title())
    labels = _nav_labels(brief)
    features = list(brief.features) or [
        ("Signal clarity", "A focused first impression that says who you are in one breath."),
        ("Editorial craft", "Typography, spacing and imagery chosen for the category, not a template dump."),
        ("Easy to edit", "Every section is real HTML you can click, restyle and export."),
    ]
    proofs = list(brief.proofs) or (
        (("4.9", "Guest rating"), ("18", "Seats at the chef's table"), ("Sunsets", "Worth lingering for"))
        if brief.sector == "food"
        else (("4.9", "Average client rating"), ("120+", "Projects shipped"), ("48h", "Typical first draft"))
    )
    features_title = html.escape(brief.features_title)
    features_lead = html.escape(brief.features_lead)
    story_title = html.escape(brief.story_title)
    story_body_copy = html.escape(brief.story_body)
    contact_lead = html.escape(brief.contact_lead)
    contact_note = html.escape(brief.contact_note)

    if brief.sector == "food":
        home_body = _food_home_body(brief, palette)
        features_body = f"""
    <section class="wrap page-hero" id="features">
      <p class="eyebrow">Menu</p>
      <h1 class="section-title">{features_title if "finished on day one" not in brief.features_title.lower() else "A tasting menu shaped by the coast."}</h1>
      <p class="section-lead">{features_lead if "visual editor" not in brief.features_lead.lower() else "Courses move from raw brightness to smoke and slow heat, with wine pairings that stay out of the way."}</p>
      <div class="dish-grid">
        {"".join(
            f'<article class="dish-card"><img src="{(palette.get("alt1"), palette.get("feature"), palette.get("alt3"))[i % 3] or palette["hero"]}" alt="{html.escape(t)}"><div class="dish-copy"><h3>{html.escape(t)}</h3><p>{html.escape(b)}</p></div></article>'
            for i, (t, b) in enumerate(features)
        )}
      </div>
      <div class="hero-actions" style="margin-top:2rem">
        <a class="btn btn-primary" href="contact.html">{cta}</a>
        <a class="btn btn-ghost" href="story.html">The experience</a>
      </div>
    </section>
"""
        story_body = f"""
    <section class="wrap page-block split" id="story">
      <div class="split-media"><img src="{palette.get("alt2") or palette["feature"]}" alt="{brand} atmosphere"></div>
      <div>
        <p class="eyebrow">Experience</p>
        <h1 class="section-title">{story_title if "template" not in brief.story_title.lower() else "Hospitality with salt air and copper light."}</h1>
        <p class="section-lead">{story_body_copy if "Generated from your brief" not in brief.story_body else f"{brand} is built for unhurried dinners: tasting menus, terrace seating, and a chef's table when you want the kitchen close."}</p>
        <div class="hero-actions"><a class="btn btn-primary" href="contact.html">{cta}</a></div>
      </div>
    </section>
    <section class="wrap page-block" id="proof">
      <p class="eyebrow">From the room</p>
      <h2 class="section-title">Guests come for dinner. They remember the pace.</h2>
      <div class="stats">
        {"".join(f'<div class="stat"><strong>{html.escape(v)}</strong><span>{html.escape(l)}</span></div>' for v, l in proofs)}
      </div>
      <div class="quote-grid">
        <article class="quote-card"><q>The terrace at dusk felt like the whole reason we booked Cape Coast.</q><p>Ama K., Accra</p></article>
        <article class="quote-card"><q>Quiet service, bright seafood, and a chef's table that never felt theatrical.</q><p>Daniel O., London</p></article>
      </div>
    </section>
"""
        contact_title = "Reserve your evening."
        contact_secondary = "Private tables and tasting seatings. WhatsApp-friendly confirmations."
    else:
        home_body = f"""
    <section class="wrap hero" id="top">
      <div>
        <p class="eyebrow">{sector}</p>
        <h1>{tagline}</h1>
        <p class="hero-lead">{summary}</p>
        <div class="hero-actions">
          <a class="btn btn-primary" href="contact.html">{cta}</a>
          <a class="btn btn-ghost" href="features.html">Explore the offer</a>
        </div>
      </div>
      <div class="hero-media">
        <img src="{palette["hero"]}" alt="{brand} hero">
      </div>
    </section>
    <section class="wrap page-block" id="features">
      <p class="eyebrow">Why {brand}</p>
      <h2 class="section-title">{features_title}</h2>
      <p class="section-lead">{features_lead}</p>
      <div class="feature-grid">
        {"".join(f'<article class="feature-card"><h3>{html.escape(t)}</h3><p>{html.escape(b)}</p></article>' for t, b in features[:3])}
      </div>
    </section>
"""
        features_body = f"""
    <section class="wrap page-hero" id="features"><p class="eyebrow">{html.escape(labels["features"])}</p>
      <h1 class="section-title">{features_title}</h1>
      <p class="section-lead">{features_lead}</p>
      <div class="feature-grid">
        {"".join(f'<article class="feature-card"><h3>{html.escape(t)}</h3><p>{html.escape(b)}</p></article>' for t, b in features)}
      </div>
      <div class="hero-actions" style="margin-top:2rem">
        <a class="btn btn-primary" href="contact.html">{cta}</a>
        <a class="btn btn-ghost" href="story.html">{html.escape(labels["story"])}</a>
      </div>
    </section>
"""
        story_body = f"""
    <section class="wrap page-block split" id="story">
      <div class="split-media"><img src="{palette["feature"]}" alt="{brand} atmosphere"></div>
      <div>
        <p class="eyebrow">{html.escape(labels["story"])}</p>
        <h1 class="section-title">{story_title}</h1>
        <p class="section-lead">{story_body_copy}</p>
        <div class="hero-actions"><a class="btn btn-primary" href="contact.html">{cta}</a></div>
      </div>
    </section>
    <section class="wrap page-block" id="proof">
      <p class="eyebrow">Social proof</p>
      <h2 class="section-title">Numbers that make the story believable.</h2>
      <div class="stats">
        {"".join(f'<div class="stat"><strong>{html.escape(v)}</strong><span>{html.escape(l)}</span></div>' for v, l in proofs)}
      </div>
    </section>
"""
        contact_title = "Ready when you are."
        contact_secondary = contact_note

    mail = html.escape(re.sub(r"[^a-z0-9]+", "", brief.brand.lower()) or "studio")
    contact_body = f"""
    <section class="wrap page-hero" id="contact">
      <p class="eyebrow">{html.escape(labels["contact"])}</p>
      <h1 class="section-title">{html.escape(contact_title)}</h1>
      <p class="section-lead">{contact_lead if "Edit any line" not in brief.contact_lead else html.escape(contact_secondary)}</p>
      <div class="cta-band" style="margin-top:2rem">
        <div>
          <h2>{cta}</h2>
          <p>{html.escape(contact_secondary) if brief.sector == "food" else contact_note}</p>
        </div>
        <a class="btn btn-primary" href="mailto:hello@{mail}.com">{cta}</a>
      </div>
    </section>
"""
    return {
        "styles.css": _shared_css(brief) + "\n",
        "index.html": _shell(brief, title=brief.brand, active="index.html", body=home_body),
        "features.html": _shell(brief, title=f"{labels['features']} | {brief.brand}", active="features.html", body=features_body),
        "story.html": _shell(brief, title=f"{labels['story']} | {brief.brand}", active="story.html", body=story_body),
        "contact.html": _shell(brief, title=f"{labels['contact']} | {brief.brand}", active="contact.html", body=contact_body),
    }


def render_offline_website(brief: SiteBrief) -> str:
    """Backward-compatible single-file render (home page HTML only)."""
    return render_offline_site(brief)["index.html"]


def _ollama_host() -> str:
    return (getattr(settings, "SIAW_OLLAMA_HOST", "") or "http://127.0.0.1:11434").rstrip("/")


def _ollama_list_models(host: str | None = None) -> list[str]:
    # Ollama is intentionally disabled. Never probe the local daemon.
    return []


def _ollama_reachable() -> bool:
    return False


def _model_capability_score(name: str) -> int:
    """Higher = more likely to emit a full Claude-class HTML site."""
    n = (name or "").lower()
    score = 25
    size_marks = (
        ("120b", 100),
        ("70b", 90),
        ("72b", 90),
        ("65b", 85),
        ("34b", 78),
        ("32b", 78),
        ("27b", 72),
        ("14b", 55),
        ("13b", 55),
        ("9b", 42),
        ("8b", 35),
        ("7b", 32),
        ("3b", 15),
        ("1b", 5),
    )
    for marker, points in size_marks:
        if marker in n:
            score = max(score, points)
    if "gpt-oss" in n:
        score = max(score, 95)
    if "qwen2.5" in n and score < 55:
        score = max(score, 50)
    if "llama3.1" in n or "llama3.2" in n:
        score = max(score, score + 2)
    return score


def _model_can_emit_full_html(name: str) -> bool:
    return _model_capability_score(name) >= 70


def _model_is_local_friendly(name: str) -> bool:
    """True for models that usually run on a laptop without tensor overflow."""
    score = _model_capability_score(name)
    return 20 <= score <= 60


def _resolve_preferred_model(available: list[str], preferred: str) -> str:
    if not preferred:
        return ""
    if preferred in available:
        return preferred
    for name in available:
        if name == preferred or name.startswith(preferred + ":"):
            return name
        if preferred.startswith(name.split(":")[0]) and name.split(":")[0] == preferred.split(":")[0]:
            return name
    return ""


def _pick_ollama_model(available: list[str], preferred: str = "") -> str:
    if not available:
        return preferred or "llama3.1:8b"

    resolved_preferred = _resolve_preferred_model(available, preferred)
    if resolved_preferred:
        return resolved_preferred

    # Prefer a reliable local chat model over huge weights that often fail to load.
    friendly = [name for name in available if _model_is_local_friendly(name)]
    pool = friendly or available
    return sorted(pool, key=_model_capability_score, reverse=True)[0]


def _ollama_models_to_try(preferred: str = "") -> list[str]:
    available = _ollama_list_models()
    if not available:
        return [preferred or "llama3.1:8b"]
    primary = _pick_ollama_model(available, preferred)
    ranked = sorted(available, key=_model_capability_score, reverse=True)
    # Prefer laptop-friendly chat models. Skip huge weights unless the user
    # explicitly set SIAW_AI_MODEL (they often 500 or starve smaller models).
    friendly = [name for name in ranked if _model_is_local_friendly(name)]
    huge = [name for name in ranked if _model_capability_score(name) >= 90]
    mid = [name for name in ranked if name not in friendly and name not in huge]
    preferred_resolved = _resolve_preferred_model(available, preferred)
    allow_huge = preferred_resolved in huge
    ordered: list[str] = []
    for name in [primary, *friendly, *mid, *(huge if allow_huge else [])]:
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def _codex_binary() -> Path | None:
    """Locate the Codex CLI used for full website builds."""
    candidates: list[Path] = []
    configured = (getattr(settings, "SIAW_CODEX_BIN", "") or "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    which = shutil.which("codex")
    if which:
        candidates.append(Path(which))
    candidates.append(Path("/Applications/ChatGPT.app/Contents/Resources/codex"))
    for path in candidates:
        try:
            if path.is_file() and os.access(path, os.X_OK):
                return path.resolve()
        except OSError:
            continue
    return None


def _codex_available() -> bool:
    if getattr(settings, "SIAW_CODEX_DISABLE", False):
        return False
    return _codex_binary() is not None


def _openai_key() -> str:
    return (
        getattr(settings, "SIAW_AI_API_KEY", "")
        or getattr(settings, "OPENAI_API_KEY", "")
        or ""
    ).strip()


def _resolve_chat_provider() -> str:
    """Chat backend for short JSON/copy calls. Same stack as site builds: Codex first."""
    if getattr(settings, "SIAW_AI_FORCE_OFFLINE", False):
        return "offline"
    forced = (getattr(settings, "SIAW_AI_PROVIDER", "auto") or "auto").strip().lower()
    if forced == "offline":
        return "offline"
    if forced == "openai":
        return "openai" if _openai_key() else "offline"
    # Prefer Codex + gpt-5.6 for drafts too. Ollama is disabled.
    if forced in {"auto", "codex", "ollama"} and _codex_available():
        return "codex"
    if _openai_key():
        return "openai"
    return "offline"


def _resolve_provider() -> str:
    """Site-build provider: Codex, then OpenAI, then offline. Ollama is never used."""
    if getattr(settings, "SIAW_AI_FORCE_OFFLINE", False):
        return "offline"
    forced = (getattr(settings, "SIAW_AI_PROVIDER", "auto") or "auto").strip().lower()
    if forced == "offline":
        return "offline"
    if forced == "openai":
        return "openai" if _openai_key() else "offline"

    # ollama env values are ignored; prefer Codex, then OpenAI.
    if forced in {"auto", "codex", "ollama"} and _codex_available():
        return "codex"
    if forced == "codex":
        return "offline"

    if _openai_key():
        return "openai"
    return "offline"


def _ai_settings(*, chat: bool = False) -> dict:
    provider = _resolve_chat_provider() if chat else _resolve_provider()
    preferred_model = (getattr(settings, "SIAW_AI_MODEL", "") or "").strip()
    timeout_setting = int(getattr(settings, "SIAW_AI_TIMEOUT_SECONDS", 0) or 0)
    explicit_base = (getattr(settings, "SIAW_AI_BASE_URL", "") or "").strip().rstrip("/")

    if provider == "codex":
        binary = _codex_binary()
        model = (getattr(settings, "SIAW_CODEX_MODEL", "") or "").strip() or "gpt-5.6-sol"
        # Chat/draft calls should not wait a full site-build timeout by default.
        chat_timeout = timeout_setting or (180 if chat else 0)
        site_timeout = int(getattr(settings, "SIAW_CODEX_TIMEOUT_SECONDS", 900) or 900)
        return {
            "provider": "codex",
            "api_key": "",
            "base_url": "",
            "model": model,
            "timeout": chat_timeout or site_timeout,
            "label": f"Codex CLI ({model})",
            "binary": str(binary) if binary else "",
        }

    if provider == "openai":
        api_key = _openai_key()
        model = preferred_model or (
            (getattr(settings, "SIAW_CODEX_MODEL", "") or "").strip() or "gpt-5.6-sol"
        )
        return {
            "provider": "openai",
            "api_key": api_key,
            "base_url": explicit_base or "https://api.openai.com/v1",
            "model": model,
            "timeout": timeout_setting or 90,
            "label": f"OpenAI ({model})",
        }

    return {
        "provider": "offline",
        "api_key": "",
        "base_url": "",
        "model": "",
        "timeout": 0,
        "label": "built-in design engine",
    }


def ai_configured() -> bool:
    return _resolve_provider() in {"codex", "openai"}


def ai_status() -> dict:
    cfg = _ai_settings()
    return {
        "provider": cfg["provider"],
        "model": cfg.get("model") or "",
        "label": cfg.get("label") or cfg["provider"],
        "configured": cfg["provider"] in {"codex", "openai"},
    }


def _system_prompt() -> str:
    """Prefer the trained Sitewright prompt from docs when present."""
    prompt_path = Path(__file__).resolve().parents[2] / "docs" / "product" / "ai_website_agent_system_prompt.md"
    try:
        raw = prompt_path.read_text(encoding="utf-8")
        marker = "## System prompt (copy from here)"
        if marker in raw:
            body = raw.split(marker, 1)[1]
            body = body.split("---", 1)[0].strip()
            # Drop the markdown heading line if present.
            lines = [line for line in body.splitlines() if not line.strip().startswith("#")]
            cleaned = "\n".join(lines).strip()
            if len(cleaned) > 400:
                return cleaned
    except OSError:
        pass
    return (
        "You are Siaw Sitewright, an elite web designer for the Siaw Visual Editor. "
        "Return ONE complete HTML5 document only (no markdown, no explanation). "
        "Requirements: semantic sections with stable ids (features, story, proof, contact); "
        "primary nav links MUST use href=\"#features\", href=\"#story\", href=\"#proof\", href=\"#contact\" "
        "(these become real pages in the editor); "
        "specialized sector-true design, not a generic AI SaaS template; "
        "stunning visual design with CSS variables; expressive Google Fonts via <link>; "
        "real Unsplash image URLs; responsive layout; accessible landmarks; "
        "NO JavaScript, NO frameworks, NO purple-to-pink default SaaS cliches unless the brief asks; "
        "all content editable as normal HTML elements for a visual editor; "
        "inline <style> in <head>; keep under 120KB of HTML."
    )


def _user_prompt(brief: SiteBrief, prompt: str) -> str:
    return (
        f"Create a full landing website for this brief.\n"
        f"Brand: {brief.brand}\n"
        f"Sector: {brief.sector}\n"
        f"Tagline direction: {brief.tagline}\n"
        f"Primary CTA: {brief.cta}\n"
        f"Client brief: {prompt}\n"
        f"Make it feel premium and specific to the sector."
    )


def _extract_html(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        raise ValidationError("The AI returned an empty response.")
    fence = HTML_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    lower = text.lower()
    start = lower.find("<!doctype html")
    if start < 0:
        start = lower.find("<html")
    if start >= 0:
        text = text[start:]
    end = text.lower().rfind("</html>")
    if end >= 0:
        text = text[: end + len("</html>")]
    if "<html" not in text.lower():
        raise ValidationError("The AI response was not a complete HTML document.")
    return text


def _sanitise_generated_html(html_text: str) -> str:
    text = SCRIPT_RE.sub("", html_text)
    text = re.sub(r"\son\w+\s*=\s*([\"']).*?\1", "", text, flags=re.IGNORECASE | re.DOTALL)
    if len(text.encode("utf-8")) > MAX_HTML_BYTES:
        raise ValidationError("Generated website is too large.")
    if "<body" not in text.lower():
        raise ValidationError("Generated website is missing a body.")
    return text


MIN_FULL_SITE_CHARS = 7000


def _messages_to_prompt(messages: list[dict]) -> str:
    parts: list[str] = [
        "You are answering a short text request for the Siaw AI Builder.",
        "Do not create a website. Do not write HTML, CSS, or project files.",
        "Reply with ONLY the requested text content. No preamble.",
        "",
    ]
    for message in messages:
        role = str(message.get("role") or "user").strip().upper()
        content = str(message.get("content") or "").strip()
        if content:
            parts.append(f"{role}:\n{content}")
            parts.append("")
    return "\n".join(parts).strip()


def _codex_text_completion(prompt: str, *, timeout: int | None = None) -> str:
    """Run a short Codex chat call with the same model used for site builds."""
    binary = _codex_binary()
    if not binary:
        raise ValidationError(
            "Codex CLI was not found. Install Codex / ChatGPT desktop, or set SIAW_CODEX_BIN."
        )
    model = (getattr(settings, "SIAW_CODEX_MODEL", "") or "").strip() or "gpt-5.6-sol"
    request_timeout = int(
        timeout
        if timeout is not None
        else (getattr(settings, "SIAW_AI_TIMEOUT_SECONDS", 0) or 180)
    )
    with tempfile.TemporaryDirectory(prefix="siaw-codex-chat-") as tmp:
        work_dir = Path(tmp) / "work"
        work_dir.mkdir(parents=True, exist_ok=True)
        last_message = Path(tmp) / "codex-last-message.txt"
        exec_log = Path(tmp) / "codex-chat.log"
        cmd = [
            str(binary),
            "exec",
            "-C",
            str(work_dir),
            "--skip-git-repo-check",
            "--ephemeral",
            "-s",
            "workspace-write",
            "-c",
            'approval_policy="never"',
            "-o",
            str(last_message),
            "-m",
            model,
            prompt,
        ]
        try:
            with exec_log.open("w", encoding="utf-8") as log_file:
                completed = subprocess.run(
                    cmd,
                    cwd=str(work_dir),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=request_timeout,
                    env=os.environ.copy(),
                )
        except subprocess.TimeoutExpired as exc:
            raise ValidationError(
                f"Codex timed out after {request_timeout} seconds while drafting."
            ) from exc
        except FileNotFoundError as exc:
            raise ValidationError("Codex CLI could not be started.") from exc
        except OSError as exc:
            raise ValidationError(f"Could not run Codex: {exc}") from exc

        if completed.returncode != 0:
            detail = ""
            try:
                detail = exec_log.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                detail = ""
            detail = detail[-1400:] if detail else "No error output."
            raise ValidationError(f"Codex failed to draft the prompt. {detail}")

        if last_message.is_file():
            text = last_message.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return text
        raise ValidationError("Codex finished without returning draft text.")


def _chat_completion(
    messages: list[dict],
    *,
    temperature: float = 0.7,
    timeout: int | None = None,
    max_tokens: int | None = None,
) -> str:
    cfg = _ai_settings(chat=True)
    if cfg["provider"] == "codex":
        return _codex_text_completion(_messages_to_prompt(messages), timeout=timeout)
    if cfg["provider"] != "openai":
        raise ValidationError("No AI provider is configured.")

    request_timeout = int(timeout if timeout is not None else cfg["timeout"])
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "SiawVisualEditor/1.0",
    }
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    payload = {
        "model": cfg["model"],
        "temperature": temperature,
        "stream": False,
        "messages": messages,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    body = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        f"{cfg['base_url']}/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=request_timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        if exc.code == 429:
            raise ValidationError(
                "AI quota exceeded. Check your OpenAI plan, or wait and try again."
            ) from exc
        raise ValidationError(f"AI provider error ({exc.code}): {detail or exc.reason}") from exc
    except urlerror.URLError as exc:
        reason = str(getattr(exc, "reason", exc) or "").lower()
        if "timed out" in reason or "timeout" in reason:
            raise ValidationError(
                "The AI request timed out. Raise SIAW_AI_TIMEOUT_SECONDS and try again."
            ) from exc
        raise ValidationError(f"Could not reach the AI provider: {exc.reason}.") from exc
    except TimeoutError as exc:
        raise ValidationError(
            "The AI request timed out. Raise SIAW_AI_TIMEOUT_SECONDS and try again."
        ) from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValidationError("Unexpected AI response format.") from exc
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content or "").strip()


def _extract_json_object(raw: str) -> dict:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValidationError("The model did not return JSON copy for the website.")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValidationError("The model returned invalid JSON for the website brief.") from exc
    if not isinstance(data, dict):
        raise ValidationError("The model JSON brief must be an object.")
    return data


def _pairs_from_json(items, *, title_key: str, body_key: str, limit: int = 3) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    if not isinstance(items, list):
        return ()
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        title = str(item.get(title_key) or item.get("name") or "").strip()
        body = str(item.get(body_key) or item.get("text") or item.get("description") or "").strip()
        if title and body:
            pairs.append((title[:80], body[:280]))
    return tuple(pairs)


def compose_prompt_from_answers(answers: dict) -> str:
    """Deterministic labeled brief used when no chat AI provider is available."""
    brand = str(answers.get("brand") or "").strip()
    sector = str(answers.get("sector") or "").strip()
    market = str(answers.get("market") or "").strip()
    goal_tone = str(answers.get("goal_tone") or "").strip()
    must = str(answers.get("must_include") or "").strip()
    if not brand or not sector or not market or not goal_tone:
        raise ValidationError("Answer brand, sector, market, and goal before drafting a prompt.")

    parts = re.split(r"[.;\n]", goal_tone)
    parts = [part.strip() for part in parts if part.strip()]
    offer = parts[0] if parts else goal_tone
    tone = ". ".join(parts[1:]) if len(parts) > 1 else offer
    lower = goal_tone.lower()
    cta = "Get started"
    if "book" in lower:
        cta = "Book now"
    elif "buy" in lower or "shop" in lower:
        cta = "Shop now"
    elif "contact" in lower or "call" in lower:
        cta = "Contact us"
    elif "demo" in lower or "trial" in lower:
        cta = "Book a demo"
    elif "sign up" in lower or "join" in lower:
        cta = "Sign up"

    audience = market
    if "," in market:
        audience = market.split(",", 1)[1].strip() or market

    lines = [
        f"Brand name: {brand}",
        f"Sector: {sector}",
        f"Location / market: {market}",
        f"Audience: {audience}",
        f"Offer: {offer}",
        f"Personality / tone: {tone}",
        f"Primary CTA: {cta}",
    ]
    if must:
        lines.append(f"Must include: {must}")
    lines.append(
        "Extra notes: Create a complete static multipage website with a strong hero, "
        "clear sections, and export-ready HTML."
    )
    return "\n".join(lines)


def draft_prompt_from_answers(answers: dict) -> tuple[str, str, str]:
    """Turn help-wizard answers into a labeled brief via Codex (gpt-5.6) when available.

    Returns (prompt, suggested_name, provider). Falls back to local compose if the
    model is offline or returns unusable text.
    """
    brand = str(answers.get("brand") or "").strip()
    sector = str(answers.get("sector") or "").strip()
    market = str(answers.get("market") or "").strip()
    goal_tone = str(answers.get("goal_tone") or "").strip()
    must = str(answers.get("must_include") or "").strip()
    fallback = compose_prompt_from_answers(answers)
    suggested = brand[:160]

    if not ai_configured():
        return fallback, suggested, "offline"

    labels = ", ".join(PROMPT_FIELD_LABELS)
    system = (
        "You write website briefs for a visual website builder. "
        "Return ONLY a labeled brief using these exact field labels, one per line, "
        f"as Label: value. Use these labels when relevant: {labels}. "
        "Always include: Brand name, Sector, Location / market, Audience, Offer, "
        "Personality / tone, Primary CTA, Extra notes. "
        "Expand short answers into clear, specific copy. Do not invent fake awards. "
        "No markdown fences. No HTML. No preamble."
    )
    user = (
        "Turn these answers into a strong website brief:\n"
        f"- Brand or business name: {brand}\n"
        f"- Kind of business: {sector}\n"
        f"- Where / who for: {market}\n"
        f"- Visitor goal and feeling: {goal_tone}\n"
        f"- Must include: {must or '(none)'}\n"
        "Keep the whole brief under 1200 characters."
    )
    try:
        raw = _chat_completion(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.55,
            timeout=90,
            max_tokens=900,
        )
    except ValidationError:
        return fallback, suggested, "offline"

    text = (raw or "").strip()
    # Strip accidental fences / chatter.
    fence = re.search(r"```(?:text|markdown)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Keep from first known label onward if the model added a lead-in.
    for label in PROMPT_FIELD_LABELS:
        marker = f"{label}:"
        idx = text.lower().find(marker.lower())
        if idx >= 0:
            text = text[idx:].strip()
            break

    fields = _prompt_fields(text)
    if "brand name" not in fields and brand:
        text = f"Brand name: {brand}\n{text}".strip()
        fields = _prompt_fields(text)
    if len(text) < 40 or "brand name" not in fields:
        return fallback, suggested, "offline"

    if len(text) > MAX_PROMPT_CHARS:
        text = text[:MAX_PROMPT_CHARS].rsplit("\n", 1)[0].strip()

    return text, suggested, _resolve_chat_provider()


def enrich_brief_via_llm(prompt: str, brief: SiteBrief) -> SiteBrief:
    """Ask the model for specialized copy only, then assemble a full multipage site locally."""
    system = (
        "You write website copy for premium landing pages. "
        "Return ONLY a JSON object with keys: "
        "brand, tagline, summary, cta, audience, sector, "
        "features_title, features_lead, features (array of {title, body}), "
        "story_title, story_body, proofs (array of {value, label}), "
        "contact_lead, contact_note. "
        "sector must be one of: luxury, health, finance, food, travel, realestate, education, saas, creative, ecommerce. "
        "No markdown. No HTML. Keep strings concise and sector-specific."
    )
    user = (
        f"Client brief:\n{prompt}\n\n"
        f"Seed brand: {brief.brand}\n"
        f"Seed sector: {brief.sector}\n"
        f"Seed CTA: {brief.cta}\n"
        "Write specialized copy for a full multi-section website."
    )
    raw = _chat_completion(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.65,
    )
    data = _extract_json_object(raw)

    sector = str(data.get("sector") or brief.sector).strip().lower().replace(" ", "")
    if sector not in PALETTES:
        sector = brief.sector if brief.sector in PALETTES else "saas"

    features = _pairs_from_json(data.get("features"), title_key="title", body_key="body", limit=3) or brief.features
    proofs = _pairs_from_json(data.get("proofs"), title_key="value", body_key="label", limit=3) or brief.proofs

    def pick(key: str, fallback: str, limit: int = 220) -> str:
        value = str(data.get(key) or "").strip()
        if not value:
            return fallback
        lowered = value.lower()
        # Never let instruction text leak onto the live website.
        if "create a complete static website" in lowered or lowered.startswith("brand name:"):
            return fallback
        return value[:limit]

    return SiteBrief(
        brand=pick("brand", brief.brand, 60),
        tagline=pick("tagline", brief.tagline, 90),
        sector=sector,
        palette=sector,
        summary=pick("summary", brief.summary, 220),
        cta=pick("cta", brief.cta, 40),
        audience=pick("audience", brief.audience, 80),
        features_title=pick("features_title", brief.features_title, 90),
        features_lead=pick("features_lead", brief.features_lead, 180),
        features=features,
        story_title=pick("story_title", brief.story_title, 90),
        story_body=pick("story_body", brief.story_body, 280),
        proofs=proofs,
        contact_lead=pick("contact_lead", brief.contact_lead, 180),
        contact_note=pick("contact_note", brief.contact_note, 120),
    )


def generate_with_llm(prompt: str, brief: SiteBrief) -> str:
    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": _user_prompt(brief, prompt)},
        {
            "role": "user",
            "content": "Output the full HTML document now. Start with <!DOCTYPE html>. No markdown. No explanation.",
        },
    ]
    content = _chat_completion(messages, temperature=0.85)
    return _sanitise_generated_html(_extract_html(content))


def _html_is_thin(html_text: str) -> bool:
    text = html_text or ""
    if len(text) < MIN_FULL_SITE_CHARS:
        return True
    lowered = text.lower()
    required = ('id="features"', 'id="story"', 'id="proof"', 'id="contact"')
    return not all(token in lowered for token in required)


def _codex_build_prompt(
    prompt: str,
    brief: SiteBrief,
    project_name: str,
    *,
    seed_files: dict[str, Path] | None = None,
) -> str:
    brand = (project_name or brief.brand or "Brand").strip()[:80]
    seed_paths = sorted((seed_files or {}).keys())
    logo_paths = [path for path in seed_paths if path.startswith("images/brand/logo")]
    upload_paths = [path for path in seed_paths if path.startswith("images/uploads/")]
    media_rules = [
        "Speed rules (important):",
        "- Do NOT generate, download, or invent new image binary files.",
        "- Do NOT use image-generation tools.",
        "- Do not create a separate assets/ folder for new downloads.",
        "- Stop as soon as index.html + styles.css are complete and look good.",
    ]
    if seed_paths:
        media_rules.extend(
            [
                "",
                "Local media already present in this folder (REQUIRED):",
                *[f"- {path}" for path in seed_paths],
                "- Keep these files. Do not delete or rename them.",
            ]
        )
        if logo_paths:
            media_rules.append(
                f"- Use {logo_paths[0]} as the header/footer brand logo via <img class=\"brand-logo\">."
            )
        if upload_paths:
            media_rules.extend(
                [
                    "- You MUST use EVERY file under images/uploads/ in visible <img> tags "
                    "(hero, story, gallery/portfolio, service cards, or about).",
                    "- Prefer local uploads over stock photos.",
                    "- After all local uploads are used, you may add extra Unsplash https://images.unsplash.com/... URLs.",
                ]
            )
        else:
            media_rules.append(
                "- For extra photography only, use direct https://images.unsplash.com/... URLs in <img src>."
            )
    else:
        media_rules.append(
            "- For photos, use direct https://images.unsplash.com/... URLs in <img src>."
        )

    return (
        f"{sitewright_quality_rules(multipage=False)}\n\n"
        "Write real files into this working directory now.\n"
        "Speed matters, but quality and sector fidelity matter more.\n"
        "Hard file requirements:\n"
        "1. Create index.html as the homepage entry file.\n"
        "2. One linked CSS file only: styles.css.\n"
        "3. No React/Vite/Next app shell. No build step. No package.json.\n"
        "4. Delete SIAW_BUILD_BRIEF.md when finished.\n\n"
        + "\n".join(media_rules)
        + "\n\n"
        f"Project name: {brand}\n"
        f"Seed brand: {brief.brand}\n"
        f"Sector: {brief.sector}\n"
        f"Tagline direction: {brief.tagline}\n"
        f"Primary CTA: {brief.cta}\n"
        f"Audience: {brief.audience}\n\n"
        f"Client brief:\n{prompt.strip()}\n"
    )


def _run_codex_exec(work_dir: Path, prompt: str) -> None:
    binary = _codex_binary()
    if not binary:
        raise ValidationError(
            "Codex CLI was not found. Install Codex / ChatGPT desktop, or set SIAW_CODEX_BIN."
        )
    timeout = int(getattr(settings, "SIAW_CODEX_TIMEOUT_SECONDS", 900) or 900)
    last_message = work_dir.parent / "codex-last-message.txt"
    cmd = [
        str(binary),
        "exec",
        "-C",
        str(work_dir),
        "--skip-git-repo-check",
        "--ephemeral",
        "-s",
        "workspace-write",
        "-c",
        'approval_policy="never"',
        "-o",
        str(last_message),
    ]
    model = (getattr(settings, "SIAW_CODEX_MODEL", "") or "").strip() or "gpt-5.6-sol"
    cmd.extend(["-m", model])
    cmd.append(prompt)

    # Stream Codex output to a log file. capture_output=True can deadlock when the
    # CLI writes enough stdout/stderr to fill the OS pipe buffer.
    exec_log = work_dir.parent / "codex-exec.log"
    try:
        with exec_log.open("w", encoding="utf-8") as log_file:
            completed = subprocess.run(
                cmd,
                cwd=str(work_dir),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                env=os.environ.copy(),
            )
    except subprocess.TimeoutExpired as exc:
        raise ValidationError(
            f"Codex timed out after {timeout} seconds while building the website."
        ) from exc
    except FileNotFoundError as exc:
        raise ValidationError("Codex CLI could not be started.") from exc
    except OSError as exc:
        raise ValidationError(f"Could not run Codex: {exc}") from exc

    if completed.returncode != 0:
        detail = ""
        try:
            detail = exec_log.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            detail = ""
        detail = detail[-1400:] if detail else "No error output."
        raise ValidationError(f"Codex failed to build the website. {detail}")


def _finalize_codex_source(project_dir: Path, *, brief: SiteBrief) -> GeneratedWebsite:
    source_dir = project_dir / "source"
    editor_dir = project_dir / "editor"
    editor_dir.mkdir(parents=True, exist_ok=True)

    brief_helper = source_dir / "SIAW_BUILD_BRIEF.md"
    if brief_helper.is_file():
        brief_helper.unlink(missing_ok=True)

    html_files = sorted(
        path for path in source_dir.rglob("*.html")
        if path.is_file() and "node_modules" not in path.parts
    )
    if not html_files:
        raise ValidationError("Codex finished but did not create any HTML files.")

    entry_path = source_dir / "index.html"
    if not entry_path.is_file():
        # Promote the first HTML file to index.html when Codex used another name.
        chosen = html_files[0]
        if chosen.resolve() != entry_path.resolve():
            entry_path.write_text(chosen.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

    from .pages import expand_hash_navigation_to_pages

    expand_hash_navigation_to_pages(source_dir, "index.html")

    original = project_dir / "original.zip"
    with zipfile.ZipFile(original, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir).as_posix())

    entry_file = "index.html"
    entry_html = (source_dir / entry_file).read_text(encoding="utf-8", errors="replace")
    parser = StylesheetParser()
    parser.feed(entry_html)
    stylesheets = [
        href for href in parser.stylesheets
        if href.lower().startswith(("http://", "https://", "//")) or str(href).endswith(".css")
    ]
    for item in [
        path.relative_to(source_dir).as_posix()
        for path in source_dir.rglob("*.css")
        if path.is_file()
    ]:
        if item not in stylesheets:
            stylesheets.append(item)

    return GeneratedWebsite(
        entry_file=entry_file,
        stylesheet_files=stylesheets,
        provider="codex",
        brief={
            "brand": brief.brand,
            "sector": brief.sector,
            "tagline": brief.tagline,
            "cta": brief.cta,
            "summary": brief.summary,
        },
    )


def create_website_with_codex(
    project_dir: Path,
    *,
    prompt: str,
    project_name: str = "",
    brief: SiteBrief | None = None,
    seed_files: dict[str, Path] | None = None,
) -> GeneratedWebsite:
    """Build a full website into project_dir/source using Codex exec."""
    site_brief = brief or build_brief(prompt, project_name=project_name)
    source_dir = project_dir / "source"
    editor_dir = project_dir / "editor"
    if source_dir.exists():
        for child in list(source_dir.iterdir()):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
    source_dir.mkdir(parents=True, exist_ok=True)
    editor_dir.mkdir(parents=True, exist_ok=True)

    (source_dir / "SIAW_BUILD_BRIEF.md").write_text(
        f"# Build brief\n\nProject: {project_name or site_brief.brand}\n\n{prompt.strip()}\n",
        encoding="utf-8",
    )
    # Seed brand assets before Codex runs so the model can reference real files.
    for relative, source_path in (seed_files or {}).items():
        if not source_path or not Path(source_path).is_file():
            continue
        target = source_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
    _run_codex_exec(
        source_dir,
        _codex_build_prompt(prompt, site_brief, project_name, seed_files=seed_files),
    )
    return _finalize_codex_source(project_dir, brief=site_brief)


def generate_website_files(prompt: str, *, project_name: str = "", force_offline: bool = False) -> tuple[dict[str, str], str, SiteBrief]:
    """Return (files_by_relative_path, provider, brief)."""
    brief = build_brief(prompt, project_name=project_name)
    if force_offline:
        return render_offline_site(brief), "offline", brief

    provider = _resolve_provider()

    # Local models usually cannot emit a full polished multipage HTML site in one shot.
    # Ask them for specialized copy, then assemble the complete website locally.
    def _prefer_project_brand(current: SiteBrief) -> SiteBrief:
        name = (project_name or "").strip()
        if name and len(name) >= 2:
            return replace(current, brand=name[:60])
        return current

    # Codex builds directly into a project directory via create_website_from_prompt.
    # For file-dict callers, fall through to chat/offline assemblers.
    if provider == "codex":
        provider = _resolve_chat_provider() if _resolve_chat_provider() != "offline" else "offline"

    if provider == "openai":
        try:
            html_text = generate_with_llm(prompt, brief)
            if not _html_is_thin(html_text):
                return {"index.html": html_text}, "openai", brief
        except ValidationError:
            pass
        try:
            brief = enrich_brief_via_llm(prompt, brief)
        except ValidationError:
            pass
        brief = _prefer_project_brand(brief)
        return render_offline_site(brief), "openai", brief

    return render_offline_site(brief), "offline", brief


def generate_website_html(prompt: str, *, project_name: str = "", force_offline: bool = False) -> tuple[str, str, SiteBrief]:
    files, provider, brief = generate_website_files(prompt, project_name=project_name, force_offline=force_offline)
    return files.get("index.html") or next(iter(files.values())), provider, brief


def materialize_generated_project(
    project_dir: Path,
    *,
    files: dict[str, str] | None = None,
    html_text: str | None = None,
) -> GeneratedWebsite:
    """Write a generated site into an existing WebsiteProject directory layout."""
    import shutil

    project_dir.mkdir(parents=True, exist_ok=True)
    source_dir = project_dir / "source"
    editor_dir = project_dir / "editor"
    if source_dir.exists():
        for child in list(source_dir.iterdir()):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
    source_dir.mkdir(parents=True, exist_ok=True)
    editor_dir.mkdir(parents=True, exist_ok=True)

    payload = dict(files or {})
    if html_text and "index.html" not in payload:
        payload["index.html"] = html_text
    if not payload:
        raise ValidationError("Generated website had no files.")

    for relative, content in payload.items():
        target = source_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    from .pages import expand_hash_navigation_to_pages

    expand_hash_navigation_to_pages(source_dir, "index.html")

    entry_file = "index.html" if (source_dir / "index.html").is_file() else next(iter(payload.keys()))
    original = project_dir / "original.zip"
    with zipfile.ZipFile(original, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir).as_posix())

    entry_html = (source_dir / entry_file).read_text(encoding="utf-8", errors="replace")
    parser = StylesheetParser()
    parser.feed(entry_html)
    stylesheets = [
        href for href in parser.stylesheets
        if href.lower().startswith(("http://", "https://", "//")) or str(href).endswith(".css")
    ]
    for item in [
        p.relative_to(source_dir).as_posix()
        for p in source_dir.rglob("*.css")
        if p.is_file()
    ]:
        if item not in stylesheets:
            stylesheets.append(item)
    return GeneratedWebsite(
        entry_file=entry_file,
        stylesheet_files=stylesheets,
        provider="",
        brief={},
    )


def create_website_from_prompt(
    project_dir: Path,
    *,
    prompt: str,
    project_name: str = "",
    force_offline: bool = False,
    seed_files: dict[str, Path] | None = None,
) -> GeneratedWebsite:
    brief = build_brief(prompt, project_name=project_name)
    if not force_offline and _resolve_provider() == "codex":
        return create_website_with_codex(
            project_dir,
            prompt=prompt,
            project_name=project_name,
            brief=brief,
            seed_files=seed_files,
        )

    files, provider, brief = generate_website_files(
        prompt,
        project_name=project_name,
        force_offline=force_offline,
    )
    result = materialize_generated_project(project_dir, files=files)
    source_dir = project_dir / "source"
    for relative, source_path in (seed_files or {}).items():
        if not source_path or not Path(source_path).is_file():
            continue
        target = source_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
    return GeneratedWebsite(
        entry_file=result.entry_file,
        stylesheet_files=result.stylesheet_files,
        provider=provider,
        brief={
            "brand": brief.brand,
            "sector": brief.sector,
            "tagline": brief.tagline,
            "cta": brief.cta,
            "summary": brief.summary,
        },
    )
