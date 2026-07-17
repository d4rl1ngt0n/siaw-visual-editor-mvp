# Siaw Visual Website Editor | MVP 4A

## Universal Compatibility Engine

MVP 4A focuses on opening a wider range of existing HTML websites accurately before adding more website-specific Smart Managers.

### New features

- **Safe Edit / Interactive modes** in the editor top bar.
  - Safe Edit keeps imported JavaScript disabled while you edit ordinary HTML safely.
  - Interactive mode runs the original website in an isolated per-project `*.runtime.localhost` origin so menus, reviews, carousels, filters, forms and browser storage can work.
- **Compatibility Report** tab with:
  - website type and compatibility score;
  - HTML page, CSS, script, image, SVG, form and media counts;
  - JavaScript-generated empty regions;
  - animation-hidden regions;
  - browser-storage usage;
  - missing local resources;
  - practical recommendations.
- **Universal runtime-region placeholders** instead of unexplained blank areas in Safe Edit.
- **Lazy-media hydration** for common `data-src`, `data-lazy-src`, `data-original`, `data-srcset` and `data-poster` patterns.
- **Universal animation visibility** for scroll-reveal elements while editing. Original website animations remain unchanged in Interactive mode, Live Preview and exported ZIPs.
- **Isolated Live Preview** now supports `localStorage` and `sessionStorage`, which is important for application-style projects such as Fahrklar.
- Existing MVP 3 **Smart Services Manager** remains available for compatible Order Siaw projects.

### Official compatibility test set

- Order Siaw Manufacturing v32
- Eurasien v50
- 3DNow
- Lung Compass
- Fahrklar Tax/Fahrtenbuch

### Important limitation

Interactive mode is for viewing and testing JavaScript-generated content. Return to Safe Edit to change ordinary text, images and styles. Future MVP 4B work will convert more detected runtime regions into editable Smart Components.
