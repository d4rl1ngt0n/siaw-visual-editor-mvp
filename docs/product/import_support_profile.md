# Import support profile (Phase 1)

Version: 1.0

WebBridge / Siaw Visual Editor is an import-first visual editor for static HTML websites and HTML/CSS/JS ZIP packages. JavaScript apps can be inspected in Interactive mode and captured as static pages.

## Supported

- Static HTML / CSS / JavaScript websites packaged as ZIP
- Single `.html` / `.htm` uploads
- ZIP archives misnamed as `.html` (content detected automatically)
- Multi-page HTML sites with relative assets
- Safe Edit for text, images, links, layout and classes
- Interactive mode for JavaScript behaviour inspection
- Smart Navigation for compatible menus
- Component / route capture into editable static HTML
- Export of standard source files for host-anywhere use

## Partial

- Sites that generate major content with JavaScript (edit via capture)
- Lazy-loaded media (hydrated in Safe Edit when detectable)
- Scroll / reveal animations (temporarily shown in Safe Edit)
- Browser storage apps (run in isolated Interactive / Live Preview)
- Complex dropdowns (label and destination edits; structure may be locked)

## Unsupported

- Full React / Next.js / Vue / Svelte app editing without static capture
- Server-side backends (PHP apps, databases, authenticated APIs)
- Automatic conversion of every JS framework into editable blocks
- E-commerce checkout / payment migration
- Guaranteed perfect fidelity for every arbitrary website

This matrix is also shown in the editor Report tab.
