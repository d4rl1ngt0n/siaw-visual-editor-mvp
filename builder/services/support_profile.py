"""Declared import support profile for Phase 1 trust gate."""

from __future__ import annotations

SUPPORT_PROFILE = {
    "version": "1.0",
    "title": "Import support profile",
    "summary": (
        "WebBridge / Siaw Visual Editor is built for static HTML websites and "
        "HTML/CSS/JS ZIP packages. JavaScript apps can be inspected in Interactive "
        "mode and captured as static pages."
    ),
    "supported": [
        "Static HTML / CSS / JavaScript websites packaged as ZIP",
        "Single .html / .htm uploads",
        "ZIP archives misnamed as .html (content detected automatically)",
        "Multi-page HTML sites with relative assets",
        "Safe Edit for text, images, links, layout and classes",
        "Interactive mode for JavaScript behaviour inspection",
        "Smart Navigation for compatible menus",
        "Component / route capture into editable static HTML",
        "Export of standard source files for host-anywhere use",
    ],
    "partial": [
        "Sites that generate major content with JavaScript (edit via capture)",
        "Lazy-loaded media (hydrated in Safe Edit when detectable)",
        "Scroll / reveal animations (temporarily shown in Safe Edit)",
        "Browser storage apps (run in isolated Interactive / Live Preview)",
        "Complex dropdowns (label and destination edits; structure may be locked)",
    ],
    "unsupported": [
        "Full React / Next.js / Vue / Svelte app editing without static capture",
        "Server-side backends (PHP apps, databases, authenticated APIs)",
        "Automatic conversion of every JS framework into editable blocks",
        "E-commerce checkout / payment migration",
        "Guaranteed perfect fidelity for every arbitrary website",
    ],
}


def support_profile_payload() -> dict:
    return dict(SUPPORT_PROFILE)
