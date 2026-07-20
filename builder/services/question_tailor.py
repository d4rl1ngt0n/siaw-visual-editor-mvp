"""Tailor the goals-step question from Idea-stage answers.

Deterministic: same idea fields always produce the same headline, lead, and
goal ordering. Different businesses still feel distinct.
"""

from __future__ import annotations

import re
from typing import Any

OTHER_GOAL = "other"

GOAL_CATALOG: dict[str, dict[str, str]] = {
    "leads": {
        "title": "Generate enquiries",
        "desc": "Turn visitors into qualified leads.",
    },
    "book": {
        "title": "Book appointments",
        "desc": "Make scheduling the natural next step.",
    },
    "sell": {
        "title": "Sell products",
        "desc": "Show products and encourage purchases.",
    },
    "services": {
        "title": "Present services",
        "desc": "Explain expertise with clarity.",
    },
    "credibility": {
        "title": "Build credibility",
        "desc": "Establish trust and authority.",
    },
    "event": {
        "title": "Promote an event",
        "desc": "Drive registrations and attendance.",
    },
    "community": {
        "title": "Grow a community",
        "desc": "Invite people to participate.",
    },
    "portfolio": {
        "title": "Display a portfolio",
        "desc": "Let excellent work lead the story.",
    },
    "reserve": {
        "title": "Take reservations",
        "desc": "Make booking a table or visit effortless.",
    },
    "hire": {
        "title": "Attract talent",
        "desc": "Help the right people join your team.",
    },
    "donate": {
        "title": "Drive donations",
        "desc": "Make supporting the cause simple.",
    },
    "educate": {
        "title": "Explain the offer",
        "desc": "Help people understand what you teach.",
    },
    "menu": {
        "title": "Show the menu",
        "desc": "Highlight dishes, drinks, and what to order.",
    },
    "membership": {
        "title": "Sell memberships",
        "desc": "Make joining or renewing feel simple.",
    },
    "trial": {
        "title": "Start free trials",
        "desc": "Get people into the product quickly.",
    },
    "listings": {
        "title": "Showcase listings",
        "desc": "Help people browse and enquire on properties.",
    },
    "quote": {
        "title": "Request a quote",
        "desc": "Make getting a price the clear next step.",
    },
}

INDUSTRY_GOALS: dict[str, list[str]] = {
    "Restaurants and hospitality": ["reserve", "menu", "event", "sell", "community"],
    "Health and wellness": ["book", "services", "educate", "credibility", "leads"],
    "Fitness and sports": ["membership", "book", "community", "sell", "credibility"],
    "Beauty and personal care": ["book", "services", "sell", "credibility", "leads"],
    "Professional services": ["leads", "quote", "services", "credibility", "book"],
    "Legal and accounting": ["leads", "book", "services", "credibility", "educate"],
    "Finance and insurance": ["leads", "educate", "services", "credibility", "book"],
    "Real estate": ["listings", "leads", "book", "credibility", "portfolio"],
    "Construction and trades": ["quote", "leads", "portfolio", "services", "credibility"],
    "Ecommerce and retail": ["sell", "community", "credibility", "event", "leads"],
    "Fashion and lifestyle": ["sell", "portfolio", "community", "event", "credibility"],
    "Technology and SaaS": ["trial", "leads", "educate", "hire", "credibility"],
    "Creative agencies and studios": ["portfolio", "leads", "services", "hire", "credibility"],
    "Education and coaching": ["educate", "book", "sell", "community", "leads"],
    "Nonprofit and community": ["donate", "community", "event", "credibility", "leads"],
    "Events and entertainment": ["event", "sell", "community", "leads", "credibility"],
    "Travel and tourism": ["book", "sell", "event", "community", "credibility"],
    "Automotive and mobility": ["sell", "book", "quote", "services", "leads"],
    "Home services": ["quote", "book", "leads", "services", "credibility"],
    "Other": ["leads", "services", "credibility", "sell", "book"],
}

# Short industry nicknames for headlines ("for your cafe", not the full select label).
INDUSTRY_NICK: dict[str, str] = {
    "Restaurants and hospitality": "restaurant",
    "Health and wellness": "practice",
    "Fitness and sports": "studio",
    "Beauty and personal care": "salon",
    "Professional services": "practice",
    "Legal and accounting": "firm",
    "Finance and insurance": "firm",
    "Real estate": "agency",
    "Construction and trades": "trade business",
    "Ecommerce and retail": "shop",
    "Fashion and lifestyle": "brand",
    "Technology and SaaS": "product",
    "Creative agencies and studios": "studio",
    "Education and coaching": "program",
    "Nonprofit and community": "organization",
    "Events and entertainment": "event brand",
    "Travel and tourism": "travel brand",
    "Automotive and mobility": "dealership",
    "Home services": "home service",
    "Other": "business",
}

# Description cues that bump a goal toward the front of the list.
SIGNAL_GOALS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(reserv|table|dine|dining|restaurant|cafe|café|menu)\b", re.I), "reserve"),
    (re.compile(r"\b(book|appointment|schedul|consult|session)\b", re.I), "book"),
    (re.compile(r"\b(sell|shop|store|product|ecommerce|e-commerce|checkout)\b", re.I), "sell"),
    (re.compile(r"\b(quote|estimat|bid|pricing request)\b", re.I), "quote"),
    (re.compile(r"\b(trial|demo|saas|software|app)\b", re.I), "trial"),
    (re.compile(r"\b(portfolio|case stud|showcase|gallery|my work)\b", re.I), "portfolio"),
    (re.compile(r"\b(donat|nonprofit|charity|cause|fundrais)\b", re.I), "donate"),
    (re.compile(r"\b(event|ticket|festival|conference|workshop)\b", re.I), "event"),
    (re.compile(r"\b(membership|member|subscribe|subscription)\b", re.I), "membership"),
    (re.compile(r"\b(hire|hiring|career|job|talent|recruit)\b", re.I), "hire"),
    (re.compile(r"\b(listing|propert|real estate|homes? for sale|rentals?)\b", re.I), "listings"),
    (re.compile(r"\b(lead|enquir|inquir|contact form|get in touch)\b", re.I), "leads"),
    (re.compile(r"\b(teach|course|coach|learn|class|training)\b", re.I), "educate"),
    (re.compile(r"\b(communit|club|member.?base|follow)\b", re.I), "community"),
]


def goal_label(value: str) -> str:
    key = str(value or "").strip()
    if key == OTHER_GOAL:
        return "Other"
    entry = GOAL_CATALOG.get(key)
    if entry:
        return entry["title"]
    return key.replace("_", " ").title()


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _short_name(name: str) -> str:
    name = _clean(name)
    if not name:
        return ""
    # Keep brand readable; drop trailing legal suffixes for the question.
    name = re.sub(
        r"\b(ltd|llc|inc|gmbh|plc|llp|co\.?|company)\b\.?\s*$",
        "",
        name,
        flags=re.I,
    ).strip(" ,.-")
    return name[:48] if name else ""


def _possessive(name: str) -> str:
    if not name:
        return ""
    if name.endswith(("s", "S")):
        return f"{name}'"
    return f"{name}'s"


def _detect_signals(description: str) -> list[str]:
    hits: list[str] = []
    for pattern, goal in SIGNAL_GOALS:
        if pattern.search(description) and goal not in hits:
            hits.append(goal)
    return hits


def _base_goal_keys(industry: str) -> list[str]:
    return list(INDUSTRY_GOALS.get(industry) or INDUSTRY_GOALS["Other"])


def _reorder_goals(keys: list[str], signals: list[str]) -> list[str]:
    if not signals:
        return keys
    boosted = [key for key in signals if key in keys]
    rest = [key for key in keys if key not in boosted]
    # Pull in a strong signal even if it is not in the industry default set.
    extras = [key for key in signals if key not in keys and key in GOAL_CATALOG]
    merged = boosted + rest
    for extra in extras[:1]:
        if len(merged) < 6:
            merged.append(extra)
    return merged[:6]


def _goal_desc(goal: str, *, industry: str, location: str, signals: list[str]) -> str:
    base = GOAL_CATALOG[goal]["desc"]
    place = _clean(location)
    place_bit = f" in {place}" if place and len(place) <= 40 else ""

    if goal == "reserve":
        return f"Make booking a table{place_bit} feel effortless."
    if goal == "book" and "Health" in industry:
        return f"Let patients book visits{place_bit} without calling around."
    if goal == "book" and industry == "Beauty and personal care":
        return f"Make booking treatments{place_bit} the obvious next step."
    if goal == "book" and industry == "Travel and tourism":
        return f"Help travellers lock in trips or stays{place_bit}."
    if goal == "listings":
        return f"Help people browse homes{place_bit} and enquire quickly."
    if goal == "quote" and industry in {"Construction and trades", "Home services"}:
        return f"Make requesting a quote{place_bit} the clear next step."
    if goal == "trial":
        return "Get the right people into a free trial or demo fast."
    if goal == "donate":
        return "Make supporting the cause simple and trustworthy."
    if goal == "portfolio" and "Creative" in industry:
        return "Let selected work sell your studio before the pitch."
    if goal == "menu":
        return "Highlight dishes and drinks people should try first."
    if goal == "sell" and signals and signals[0] == "sell":
        return "Put products front and centre and nudge the purchase."
    if goal == "leads" and place_bit:
        return f"Turn local visitors{place_bit} into real enquiries."
    return base


def _headline(name: str, industry: str, signals: list[str]) -> str:
    brand = _short_name(name)
    nick = INDUSTRY_NICK.get(industry, "business")
    primary = signals[0] if signals else ""

    templates_named = {
        "reserve": "What should {pos} website help guests do?",
        "book": "What should people do next on {pos} site?",
        "sell": "How should {pos} website drive sales?",
        "trial": "Where should {pos} product site send visitors?",
        "donate": "How should {pos} site move supporters to act?",
        "portfolio": "What should {pos} site prove first?",
        "listings": "What should browsers do on {pos} site?",
        "quote": "What should {pos} website unlock first?",
        "event": "What should {pos} event site achieve?",
        "leads": "What should {pos} website achieve?",
    }
    templates_unnamed = {
        "reserve": "What should this restaurant site help guests do?",
        "book": "What should visitors do next on this site?",
        "sell": "How should this shop's website drive sales?",
        "trial": "Where should this product site send visitors?",
        "donate": "How should this site move supporters to act?",
        "portfolio": "What should this studio site prove first?",
        "listings": "What should browsers do on this property site?",
        "quote": "What should this trade site unlock first?",
        "event": "What should this event site achieve?",
        "leads": "What should this website achieve?",
    }

    if brand:
        pos = _possessive(brand)
        if primary in templates_named:
            return templates_named[primary].format(pos=pos)
        # Rotate on a stable fingerprint of brand + industry so repeats feel consistent
        # but different brands do not all get the identical fallback line.
        variants = [
            f"What should {pos} website achieve?",
            f"What is the main job of {pos} site?",
            f"What should visitors do on {pos} {nick} site?",
            f"Which outcomes matter most for {brand}?",
        ]
        return variants[sum(ord(c) for c in brand + industry) % len(variants)]

    if primary in templates_unnamed:
        return templates_unnamed[primary]
    return f"What should this {nick} website achieve?"


def _lead(
    *,
    name: str,
    industry: str,
    location: str,
    language: str,
    description: str,
    signals: list[str],
) -> str:
    brand = _short_name(name)
    nick = INDUSTRY_NICK.get(industry, "business")
    place = _clean(location)
    lang = _clean(language)

    bits: list[str] = []
    if brand and industry:
        bits.append(f"Based on {brand} as a {nick}")
    elif industry:
        bits.append(f"Based on your {nick} idea")
    else:
        bits.append("Based on what you shared")

    if place:
        bits.append(f"serving {place}")

    cue = ""
    if signals:
        cue_map = {
            "reserve": "reservations feel central",
            "book": "booking is a big part of the offer",
            "sell": "selling products is in focus",
            "trial": "product trials look important",
            "donate": "support and donations matter",
            "portfolio": "showing work is key",
            "listings": "listings should lead",
            "quote": "quotes are a natural next step",
            "event": "an event is part of the story",
            "educate": "teaching or explaining comes first",
            "community": "community growth stands out",
            "leads": "enquiries are the priority",
            "membership": "memberships are in play",
            "hire": "hiring may matter too",
        }
        cue = cue_map.get(signals[0], "")
    elif description:
        cue = "your description"

    head = " ".join(bits)
    if cue and cue != "your description":
        mid = f"{head}, {cue}."
    elif cue == "your description":
        mid = f"{head}."
    else:
        mid = f"{head}."

    tail = "Pick up to three outcomes for the site."
    if lang and lang not in {"English", ""}:
        tail = f"Pick up to three outcomes. We will write the site in {lang}."
    return f"{mid} {tail}"


def tailor_goals_question(
    *,
    business_name: str = "",
    industry: str = "",
    description: str = "",
    location: str = "",
    language: str = "English",
) -> dict[str, Any]:
    """Return headline, lead, and industry-tuned goal cards for step 2."""
    name = _clean(business_name)
    industry = _clean(industry)
    description = _clean(description)
    location = _clean(location)
    language = _clean(language) or "English"

    signals = _detect_signals(description)
    keys = _reorder_goals(_base_goal_keys(industry or "Other"), signals)
    goals = [
        {
            "value": key,
            "title": GOAL_CATALOG[key]["title"],
            "desc": _goal_desc(key, industry=industry, location=location, signals=signals),
        }
        for key in keys
        if key in GOAL_CATALOG
    ]

    brand = _short_name(name)
    if brand and industry:
        industry_label = f"Goals shaped for {brand} · {industry}"
    elif industry:
        industry_label = f"Goals for {industry}"
    else:
        industry_label = ""

    return {
        "headline": _headline(name, industry, signals),
        "lead": _lead(
            name=name,
            industry=industry,
            location=location,
            language=language,
            description=description,
            signals=signals,
        ),
        "industryLabel": industry_label,
        "industry": industry,
        "signals": signals[:3],
        "goals": goals,
    }


def tailor_goals_question_for_brief(brief: Any) -> dict[str, Any]:
    return tailor_goals_question(
        business_name=getattr(brief, "business_name", "") or "",
        industry=getattr(brief, "industry", "") or "",
        description=getattr(brief, "description", "") or "",
        location=getattr(brief, "location", "") or "",
        language=getattr(brief, "language", "") or "English",
    )
