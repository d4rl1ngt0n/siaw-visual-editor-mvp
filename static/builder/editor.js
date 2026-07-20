(() => {
  "use strict";

  const config = JSON.parse(document.getElementById("editor-config").textContent);
  const saveStatus = document.getElementById("saveStatus");
  const saveBtn = document.getElementById("saveBtn");
  const previewBtn = document.getElementById("previewBtn");
  const exportBtn = document.getElementById("exportBtn");
  const protectedHint = document.getElementById("protectedHint");
  const notice = document.getElementById("editorNotice");
  const smartManager = document.getElementById("smartManager");
  const compatibilityReport = document.getElementById("compatibilityReport");
  const captureManager = document.getElementById("captureManager");
  const captureStartBtn = document.getElementById("captureStartBtn");
  const captureRouteBtn = document.getElementById("captureRouteBtn");
  const safeModeBtn = document.getElementById("safeModeBtn");
  const interactiveModeBtn = document.getElementById("interactiveModeBtn");
  const interactiveMode = document.getElementById("interactiveMode");
  const safeEditShellEmpty = document.getElementById("safeEditShellEmpty");
  const safeEditShellMessage = document.getElementById("safeEditShellMessage");
  const safeEditShellInteractive = document.getElementById("safeEditShellInteractive");
  const safeEditShellCapture = document.getElementById("safeEditShellCapture");
  const interactiveFrame = document.getElementById("interactiveFrame");
  const canvasArea = document.querySelector(".canvas-area");
  const pagesManager = document.getElementById("pagesManager");
  const assetsManager = document.getElementById("assetsManager");
  const assetUploadInput = document.getElementById("assetUploadInput");
  const snapshotsManager = document.getElementById("snapshotsManager");
  const linkManager = document.getElementById("linkManager");
  const slideshowManager = document.getElementById("slideshowManager");
  const responsiveManager = document.getElementById("responsiveManager");
  const imageManager = document.getElementById("imageManager");

  let editor = null;
  let editorReady = false;
  let dirty = false;
  let autosaveTimer = null;
  let savingPromise = null;
  let smartServiceState = new Map();
  let smartServiceAvailable = false;
  let selectedSmartServiceKey = null;
  let activeEditorMode = "safe";
  let currentDevice = "Desktop";
  let loadedData = null;
  let smartNavigationState = null;
  let selectedNavigationKey = null;
  let serviceStateInitialised = false;
  let capturedComponents = [];
  let runtimeSnapshot = null;
  let captureWaiting = false;

  const protectedIds = new Set([
    "focusPanel",
    "projectSpotlight",
    "productGrid",
    "productDetail",
    "infoModal",
    "orderModal",
  ]);

  const protectedClasses = [
    "interactive-card",
    "service-detail-trigger",
    "project-select",
    "project-spotlight",
    "shop-tools",
    "product-detail",
    "request-center",
    "modal",
    "order-modal",
  ];

  function csrfToken() {
    const name = "csrftoken=";
    const cookie = document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith(name));
    return cookie ? decodeURIComponent(cookie.slice(name.length)) : "";
  }

  function setStatus(text, state = "") {
    saveStatus.textContent = text;
    saveStatus.className = `save-status ${state}`.trim();
    window.siawEditorLayout?.markSaveDirty?.(state === "dirty" || dirty);
  }

  function markDirty() {
    if (!editorReady) return;
    dirty = true;
    setStatus("Unsaved changes", "dirty");
    clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(() => saveProject({ silent: true }), 25000);
  }

  function isProtectedElement(el) {
    if (!el || !el.getAttribute) return false;
    const id = el.getAttribute("id");
    if (id && protectedIds.has(id)) return true;
    const className = el.getAttribute("class") || "";
    return protectedClasses.some((name) => className.split(/\s+/).includes(name));
  }

  function registerProtectedComponents(instance) {
    instance.DomComponents.addType("siaw-protected", {
      isComponent(el) {
        return isProtectedElement(el) ? { type: "siaw-protected" } : false;
      },
      model: {
        defaults: {
          draggable: false,
          droppable: false,
          removable: false,
          copyable: false,
          badgable: true,
          stylable: true,
        },
      },
    });
  }

  function blockLabel(icon, text) {
    return `<span style="display:block;font-size:18px;font-weight:900;margin-bottom:5px">${icon}</span><span>${text}</span>`;
  }

  const RESPONSIVE_VISIBILITY_CSS = `
/* siaw-responsive-visibility */
@media (min-width: 993px) {
  .siaw-hide-desktop { display: none !important; }
}
@media (max-width: 992px) and (min-width: 576px) {
  .siaw-hide-tablet { display: none !important; }
}
@media (max-width: 575px) {
  .siaw-hide-mobile { display: none !important; }
}
`.trim();

  function columnCell(label = "Drop widgets here") {
    return (
      `<div class="siaw-column" data-siaw-layout="column" style="min-height:80px;padding:16px;border:1px dashed #d0d5db;border-radius:10px;background:#fafbfc">`
      + `<p style="margin:0;color:#737b85;font-size:13px">${label}</p>`
      + `</div>`
    );
  }

  function registerLayoutComponents(instance) {
    const dom = instance.DomComponents;
    ["siaw-container", "siaw-section", "siaw-column"].forEach((type) => {
      dom.addType(type, {
        isComponent(el) {
          if (!el || !el.getAttribute) return false;
          const layout = el.getAttribute("data-siaw-layout");
          if (type === "siaw-container" && layout === "container") return { type };
          if (type === "siaw-section" && (layout === "section" || el.tagName === "SECTION" && el.classList?.contains("siaw-section"))) {
            return { type };
          }
          if (type === "siaw-column" && layout === "column") return { type };
          return false;
        },
        model: {
          defaults: {
            tagName: type === "siaw-section" ? "section" : "div",
            droppable: true,
            stylable: true,
            attributes: {
              "data-siaw-layout": type === "siaw-container" ? "container" : type === "siaw-section" ? "section" : "column",
            },
          },
        },
      });
    });
  }

  function registerBlocks(instance, data) {
    const blocks = instance.BlockManager;
    const firstAsset = data.assets.length ? data.assets[0].src : "";

    // Layout (Elementor-style structure, same Blocks panel)
    blocks.add("siaw-container", {
      label: blockLabel("▢", "Container"),
      category: "Layout",
      content: {
        type: "siaw-container",
        attributes: { "data-siaw-layout": "container", class: "siaw-container" },
        style: {
          display: "flex",
          "flex-direction": "column",
          gap: "16px",
          width: "100%",
          "max-width": "1140px",
          margin: "0 auto",
          padding: "24px 16px",
          "min-height": "80px",
        },
        components: "<p>Drop widgets into this container.</p>",
      },
    });
    blocks.add("siaw-section", {
      label: blockLabel("§", "Section"),
      category: "Layout",
      content: {
        type: "siaw-section",
        attributes: { "data-siaw-layout": "section", class: "siaw-section section" },
        style: { padding: "48px 16px", width: "100%" },
        components: `
          <div class="siaw-container" data-siaw-layout="container" style="display:flex;flex-direction:column;gap:16px;max-width:1140px;margin:0 auto">
            <h2>New section</h2>
            <p>Add headings, text, images and columns here.</p>
          </div>
        `,
      },
    });
    blocks.add("columns-2", {
      label: blockLabel("▥", "2 Columns"),
      category: "Layout",
      content: `<div class="siaw-columns" data-siaw-layout="columns" style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px;width:100%">${columnCell("Column 1")}${columnCell("Column 2")}</div>`,
    });
    blocks.add("columns-3", {
      label: blockLabel("▦", "3 Columns"),
      category: "Layout",
      content: `<div class="siaw-columns" data-siaw-layout="columns" style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;width:100%">${columnCell("Column 1")}${columnCell("Column 2")}${columnCell("Column 3")}</div>`,
    });
    blocks.add("columns-4", {
      label: blockLabel("▤", "4 Columns"),
      category: "Layout",
      content: `<div class="siaw-columns" data-siaw-layout="columns" style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;width:100%">${columnCell("Col 1")}${columnCell("Col 2")}${columnCell("Col 3")}${columnCell("Col 4")}</div>`,
    });
    blocks.add("inner-section", {
      label: blockLabel("⧉", "Inner Section"),
      category: "Layout",
      content: `<div class="siaw-inner-section" data-siaw-layout="inner-section" style="display:grid;grid-template-columns:1.2fr 0.8fr;gap:24px;width:100%;padding:16px;border:1px dashed #d8dde3;border-radius:12px">${columnCell("Main")}${columnCell("Aside")}</div>`,
    });

    // Basic widgets
    blocks.add("heading", {
      label: blockLabel("H", "Heading"),
      category: "Basic",
      content: '<h2>New heading</h2>',
    });
    blocks.add("paragraph", {
      label: blockLabel("¶", "Text Editor"),
      category: "Basic",
      content: '<p>Add your text here. Double-click the text to edit it.</p>',
    });
    blocks.add("image", {
      label: blockLabel("▧", "Image"),
      category: "Basic",
      activate: true,
      content: {
        type: "image",
        attributes: {
          src: firstAsset,
          alt: "Website image",
          loading: "lazy",
        },
        style: { "max-width": "100%", height: "auto" },
      },
    });
    blocks.add("primary-button", {
      label: blockLabel("▣", "Button"),
      category: "Basic",
      content: '<a href="#contact" class="btn btn-primary" style="display:inline-block;padding:12px 18px;border-radius:8px;background:#171717;color:#fff;text-decoration:none">New Button</a>',
    });
    blocks.add("video", {
      label: blockLabel("▶", "Video"),
      category: "Basic",
      content: `
        <div class="siaw-video" data-siaw-widget="video" style="position:relative;width:100%;aspect-ratio:16/9;background:#111;border-radius:12px;overflow:hidden">
          <iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ" title="Video" style="position:absolute;inset:0;width:100%;height:100%;border:0" allowfullscreen loading="lazy"></iframe>
        </div>
      `,
    });
    blocks.add("divider", {
      label: blockLabel("/", "Divider"),
      category: "Basic",
      content: '<hr class="siaw-divider" data-siaw-widget="divider" style="border:0;border-top:1px solid #d8dde3;margin:24px 0;width:100%">',
    });
    blocks.add("spacer", {
      label: blockLabel("↕", "Spacer"),
      category: "Basic",
      content: '<div class="siaw-spacer" data-siaw-widget="spacer" style="height:48px" aria-hidden="true"></div>',
    });
    blocks.add("icon-box", {
      label: blockLabel("◆", "Icon Box"),
      category: "Basic",
      content: `
        <div class="siaw-icon-box" data-siaw-widget="icon-box" style="padding:24px;border:1px solid #e5e8eb;border-radius:14px;background:#fff;text-align:left">
          <div style="width:40px;height:40px;border-radius:10px;background:#171717;color:#fff;display:grid;place-items:center;font-weight:800;margin-bottom:12px">i</div>
          <h3 style="margin:0 0 8px">Icon box title</h3>
          <p style="margin:0;color:#5c6570">Short supporting text for this feature or benefit.</p>
        </div>
      `,
    });
    blocks.add("icon-list", {
      label: blockLabel("☰", "Icon List"),
      category: "Basic",
      content: `
        <ul class="siaw-icon-list" data-siaw-widget="icon-list" style="margin:0;padding:0;list-style:none;display:grid;gap:10px">
          <li style="display:flex;gap:10px;align-items:flex-start"><span aria-hidden="true">✓</span><span>List item one</span></li>
          <li style="display:flex;gap:10px;align-items:flex-start"><span aria-hidden="true">✓</span><span>List item two</span></li>
          <li style="display:flex;gap:10px;align-items:flex-start"><span aria-hidden="true">✓</span><span>List item three</span></li>
        </ul>
      `,
    });
    blocks.add("accordion", {
      label: blockLabel("▾", "Accordion"),
      category: "Basic",
      content: `
        <div class="siaw-accordion" data-siaw-widget="accordion" style="display:grid;gap:8px">
          <details open style="border:1px solid #e5e8eb;border-radius:10px;padding:12px 14px;background:#fff">
            <summary style="cursor:pointer;font-weight:700">Accordion item 1</summary>
            <p style="margin:10px 0 0;color:#5c6570">Answer or details for the first item.</p>
          </details>
          <details style="border:1px solid #e5e8eb;border-radius:10px;padding:12px 14px;background:#fff">
            <summary style="cursor:pointer;font-weight:700">Accordion item 2</summary>
            <p style="margin:10px 0 0;color:#5c6570">Answer or details for the second item.</p>
          </details>
        </div>
      `,
    });
    blocks.add("html-widget", {
      label: blockLabel("</>", "HTML"),
      category: "Basic",
      content: '<div class="siaw-html" data-siaw-widget="html"><p>Custom HTML block. Edit this content in Layers or as text.</p></div>',
    });

    // Navigation / Cards / Sections (kept for existing workflows)
    blocks.add("nav-link", {
      label: blockLabel("↗", "Navigation Link"),
      category: "Navigation",
      content: '<a href="#projects">New Menu Link</a>',
    });
    blocks.add("whatsapp-button", {
      label: blockLabel("W", "WhatsApp Button"),
      category: "Navigation",
      content: '<a href="https://wa.me/233248984746" class="btn btn-primary">Chat on WhatsApp</a>',
    });
    blocks.add("content-section", {
      label: blockLabel("§", "Content Section"),
      category: "Sections",
      content: `
        <section class="section">
          <div class="section-heading">
            <p class="section-label">New Section</p>
            <h2>Section heading</h2>
            <p class="section-intro">Add a short introduction for this section.</p>
          </div>
          <div style="max-width:900px;margin:0 auto">
            <p>Double-click this text and replace it with your content.</p>
          </div>
        </section>
      `,
    });
    blocks.add("two-columns", {
      label: blockLabel("▥", "Two Columns (legacy)"),
      category: "Sections",
      content: `
        <section class="section">
          <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px;max-width:1100px;margin:0 auto">
            <div><h3>Column one</h3><p>Add content here.</p></div>
            <div><h3>Column two</h3><p>Add content here.</p></div>
          </div>
        </section>
      `,
    });
    blocks.add("simple-card", {
      label: blockLabel("□", "Simple Card"),
      category: "Cards",
      content: `
        <article style="padding:24px;border:1px solid #dedede;border-radius:16px;background:#fff">
          <h3>Card title</h3>
          <p>Describe the service, project or product here.</p>
          <a href="#contact" class="btn btn-primary">Learn More</a>
        </article>
      `,
    });
    blocks.add("project-card", {
      label: blockLabel("P", "Static Project Card"),
      category: "Cards",
      content: `
        <article class="image-card">
          ${firstAsset ? `<img src="${firstAsset}" alt="Project image" loading="lazy">` : ""}
          <div class="image-card-label"><span>NEW</span><h3>New Project</h3><p>Project summary</p></div>
        </article>
      `,
    });
    blocks.add("cta", {
      label: blockLabel("★", "Call to Action"),
      category: "Sections",
      content: `
        <section class="final-cta-section">
          <div class="final-cta-box">
            <p class="section-label">Ready to Start?</p>
            <h2>Let us build your next solution.</h2>
            <p>Tell us what you are working on and the support you need.</p>
            <div class="final-cta-actions"><a href="#contact" class="btn btn-primary">Request a Quote</a></div>
          </div>
        </section>
      `,
    });
    blocks.add("testimonial", {
      label: blockLabel("❝", "Testimonial"),
      category: "Cards",
      content: `
        <figure class="siaw-testimonial" data-siaw-widget="testimonial" style="padding:24px;border:1px solid #e5e8eb;border-radius:14px;background:#fff;margin:0">
          <blockquote style="margin:0 0 12px;font-size:16px;line-height:1.5">“This product made our workflow faster and clearer.”</blockquote>
          <figcaption style="color:#5c6570;font-size:13px"><strong>Alex Rivera</strong> · Customer</figcaption>
        </figure>
      `,
    });
  }

  function styleSectors() {
    return [
      {
        name: "Layout",
        open: true,
        buildProps: ["display", "position", "width", "max-width", "height", "min-height", "margin", "padding", "overflow"],
        properties: [
          {
            property: "display",
            type: "select",
            defaults: "block",
            options: [
              { id: "block", label: "Block" },
              { id: "inline-block", label: "Inline block" },
              { id: "flex", label: "Flex" },
              { id: "grid", label: "Grid" },
              { id: "none", label: "Hidden" },
            ],
          },
        ],
      },
      {
        name: "Typography",
        open: false,
        buildProps: ["font-family", "font-size", "font-weight", "line-height", "letter-spacing", "color", "text-align", "text-decoration"],
      },
      {
        name: "Background & Border",
        open: false,
        buildProps: ["background-color", "background-image", "border", "border-radius", "box-shadow", "opacity"],
      },
      {
        name: "Flex",
        open: false,
        buildProps: ["flex-direction", "flex-wrap", "justify-content", "align-items", "align-content", "gap", "order", "flex-basis", "flex-grow", "flex-shrink"],
      },
      {
        name: "Grid",
        open: false,
        buildProps: ["grid-template-columns", "grid-template-rows", "grid-column", "grid-row", "justify-items", "align-content", "gap"],
      },
      {
        name: "Effects",
        open: false,
        buildProps: ["transform", "transition", "cursor"],
      },
    ];
  }

  function applyImportedAttributes(element, attributes = {}) {
    if (!element || !attributes || typeof attributes !== "object") return;
    Object.entries(attributes).forEach(([name, value]) => {
      if (!name || name.toLowerCase() === "xmlns") return;
      if (name.toLowerCase() === "class") {
        String(value || "").split(/\s+/).filter(Boolean).forEach((className) => element.classList.add(className));
        return;
      }
      try {
        element.setAttribute(name, value == null ? "" : String(value));
      } catch (error) {
        console.warn("Could not apply imported attribute", name, error);
      }
    });
  }

  let importedStyleBlobUrls = [];

  function revokeImportedStyleBlobs() {
    importedStyleBlobUrls.forEach((url) => {
      try { URL.revokeObjectURL(url); } catch (_error) { /* ignore */ }
    });
    importedStyleBlobUrls = [];
  }

  function buildCanvasStyles(data) {
    revokeImportedStyleBlobs();
    const urls = [];
    // Site CSS often lives in <style> tags. GrapesJS only auto-loads stylesheet URLs,
    // so expose those inline blocks as blob URLs before remote font CSS.
    (Array.isArray(data.inlineStyles) ? data.inlineStyles : []).forEach((cssText) => {
      if (!cssText || !String(cssText).trim()) return;
      const blobUrl = URL.createObjectURL(new Blob([cssText], { type: "text/css" }));
      importedStyleBlobUrls.push(blobUrl);
      urls.push(blobUrl);
    });
    (Array.isArray(data.canvasStyles) ? data.canvasStyles : []).forEach((url) => {
      if (url && !urls.includes(url)) urls.push(url);
    });
    return urls;
  }

  function injectInlineStyles(doc, styles = []) {
    if (!doc?.head) return;
    doc.querySelectorAll("style[data-siaw-imported-style]").forEach((node) => node.remove());
    styles.forEach((cssText, index) => {
      if (!cssText || !String(cssText).trim()) return;
      const style = doc.createElement("style");
      style.setAttribute("data-siaw-imported-style", String(index));
      style.textContent = cssText;
      doc.head.appendChild(style);
    });
  }

  function ensureCanvasStylesheets(doc, styleUrls = []) {
    if (!doc?.head || !styleUrls.length) return;
    styleUrls.forEach((href, index) => {
      if (!href) return;
      const existing = doc.head.querySelector(`link[data-siaw-canvas-style="${index}"]`);
      if (existing) {
        if (existing.getAttribute("href") !== href) existing.setAttribute("href", href);
        return;
      }
      const link = doc.createElement("link");
      link.rel = "stylesheet";
      link.href = href;
      link.setAttribute("data-siaw-canvas-style", String(index));
      doc.head.appendChild(link);
    });
  }

  function injectCanvasSafety(data) {
    const doc = editor?.Canvas?.getDocument?.();
    if (!doc) return;

    let base = doc.querySelector("base[data-siaw-base]");
    if (!base) {
      base = doc.createElement("base");
      base.setAttribute("data-siaw-base", "true");
      doc.head.insertBefore(base, doc.head.firstChild);
    }
    base.href = data.assetBaseUrl;
    applyImportedAttributes(doc.documentElement, data.htmlAttributes);
    applyImportedAttributes(doc.body, data.bodyAttributes);
    const styleUrls = Array.isArray(data._canvasStyleUrls) ? data._canvasStyleUrls : buildCanvasStyles(data);
    data._canvasStyleUrls = styleUrls;
    // Apply both ways: link tags (GrapesJS-friendly) and raw <style> backup.
    ensureCanvasStylesheets(doc, styleUrls);
    injectInlineStyles(doc, Array.isArray(data.inlineStyles) ? data.inlineStyles : []);
    doc.documentElement.classList.add("siaw-visual-edit-mode");

    if (!doc.documentElement.dataset.siawClickGuard) {
      doc.documentElement.dataset.siawClickGuard = "true";
      doc.addEventListener(
        "click",
        (event) => {
          const link = event.target.closest && event.target.closest("a");
          if (link) event.preventDefault();
        },
        true,
      );
    }
  }


  function heroSlideHtml(src, alt, active = false) {
    const activeClass = active ? " is-active" : "";
    const loading = active ? "eager" : "lazy";
    return (
      `<div class="hc-slide${activeClass}" data-siaw-hydrated="hero-carousel" data-siaw-slideshow-slide="true">`
      + `<img src="${escapeHtml(src)}" alt="${escapeHtml(alt || "Slideshow image")}" draggable="false" decoding="async" loading="${loading}">`
      + `</div>`
    );
  }

  function heroCarouselTrack() {
    return (editor?.getWrapper()?.find?.(".js-hc-track") || [])[0] || null;
  }

  function heroCarouselDots() {
    return (editor?.getWrapper()?.find?.(".js-hc-dots") || [])[0] || null;
  }

  function heroSlides(track = heroCarouselTrack()) {
    if (!track) return [];
    return track.find?.(".hc-slide") || [];
  }

  function componentClassList(component) {
    const raw = component?.getClasses?.();
    if (Array.isArray(raw)) return raw.map(String).filter(Boolean);
    if (typeof raw === "string") return raw.split(/\s+/).filter(Boolean);
    const attr = component?.getAttributes?.().class || "";
    return String(attr).split(/\s+/).filter(Boolean);
  }

  function markHeroCarouselManaged(track = heroCarouselTrack()) {
    if (!track?.addAttributes) return;
    track.addAttributes({ "data-siaw-slideshow": "hero" });
  }

  function syncHeroCarouselDots(track = heroCarouselTrack()) {
    const dotsWrap = heroCarouselDots();
    if (!dotsWrap) return;
    const slides = heroSlides(track);
    const activeIndex = Math.max(
      0,
      slides.findIndex((slide) => componentClassList(slide).includes("is-active")),
    );
    const dotsHtml = slides.map((_slide, index) => {
      const active = index === activeIndex ? " is-active" : "";
      const current = index === activeIndex ? ' aria-current="true"' : "";
      return `<button type="button" class="hc-dot${active}" data-siaw-hydrated="hero-carousel"${current}></button>`;
    }).join("");
    dotsWrap.components(dotsHtml);
  }

  function setActiveHeroSlide(track, index) {
    const slides = heroSlides(track);
    slides.forEach((slide, slideIndex) => {
      if (slideIndex === index) {
        if (slide.addClass) slide.addClass("is-active");
        else {
          const classes = new Set(componentClassList(slide));
          classes.add("is-active");
          slide.setClass?.(Array.from(classes).join(" "));
        }
      } else if (slide.removeClass) {
        slide.removeClass("is-active");
      } else {
        const classes = new Set(componentClassList(slide));
        classes.delete("is-active");
        slide.setClass?.(Array.from(classes).join(" "));
      }
    });
    syncHeroCarouselDots(track);
  }

  function findHeroCarouselContext(component) {
    if (!component) return null;
    let current = component;
    while (current) {
      const classes = componentClassList(current);
      const attrs = current.getAttributes?.() || {};
      if (classes.includes("hc-slide") || attrs["data-siaw-slideshow-slide"]) {
        const track = current.parent?.() || heroCarouselTrack();
        const slides = heroSlides(track);
        const index = slides.indexOf(current);
        return { track, slide: current, index: index >= 0 ? index : 0, slides };
      }
      if (classes.includes("js-hc-track") || attrs["data-siaw-slideshow"] === "hero") {
        const slides = heroSlides(current);
        return { track: current, slide: slides[0] || null, index: 0, slides };
      }
      if (classes.includes("hero-carousel") || classes.includes("hc-frame") || attrs["data-hero-carousel"] != null) {
        const track = current.find?.(".js-hc-track")?.[0] || heroCarouselTrack();
        const slides = heroSlides(track);
        return { track, slide: slides[0] || null, index: 0, slides };
      }
      if (current.get?.("type") === "image") {
        const parent = current.parent?.();
        if (parent && componentClassList(parent).includes("hc-slide")) {
          return findHeroCarouselContext(parent);
        }
      }
      current = current.parent ? current.parent() : null;
    }
    return null;
  }

  function hydrateHeroCarouselFromData(data = loadedData || {}) {
    if (!editor) return;
    const photos = Array.isArray(data.heroCarouselPhotos) ? data.heroCarouselPhotos : [];
    const track = heroCarouselTrack();
    if (!track) return;
    markHeroCarouselManaged(track);
    const existing = track.find?.(".hc-slide") || [];
    if (existing.length) {
      existing.forEach((slide) => {
        const image = slide.find?.("img")?.[0];
        const current = image?.getAttributes?.()?.src || "";
        const fixed = toEditorAssetUrl(current);
        if (image && fixed && fixed !== current) image.addAttributes({ src: fixed });
      });
      syncHeroCarouselDots(track);
      return;
    }
    if (!photos.length) return;

    const slidesHtml = photos.map((photo, index) => (
      heroSlideHtml(
        toEditorAssetUrl(photo.src || ""),
        photo.alt || photo.alt_en || `Slide ${index + 1}`,
        index === 0,
      )
    )).join("");
    track.components(slidesHtml);
    syncHeroCarouselDots(track);
  }

  function hydrateReviewsFromData(data = loadedData || {}) {
    if (!editor) return;
    const reviews = Array.isArray(data.reviewsData) ? data.reviewsData : [];
    if (!reviews.length) return;
    const tracks = editor.getWrapper()?.find?.("#reviewsTrack") || [];
    const track = tracks[0];
    if (!track) return;
    if ((track.find?.(".review") || []).length) return;

    const cardsHtml = reviews.map((review) => {
      const stars = Math.max(0, Math.min(5, Number(review.stars) || 5));
      const starText = `${"★".repeat(stars)}${"☆".repeat(5 - stars)}`;
      const text = String(review.text || "");
      const isLong = text.length > 170;
      const clamp = isLong ? " clamp" : "";
      const more = isLong
        ? '<button type="button" class="readmore-btn" data-siaw-hydrated="reviews">Read more</button>'
        : "";
      return (
        `<div class="review" data-siaw-hydrated="reviews">`
        + `<div class="review-stars">${escapeHtml(starText)}</div>`
        + `<p class="review-text${clamp}">${escapeHtml(text)}</p>`
        + more
        + `<div class="review-foot"><div class="review-name">${escapeHtml(review.name || "Customer")}</div></div>`
        + `</div>`
      );
    }).join("");
    track.components(cardsHtml);

    const dotsWrap = (editor.getWrapper()?.find?.("#reviewsDots") || [])[0];
    if (dotsWrap && !(dotsWrap.find?.(".rc-dot") || []).length) {
      const pageCount = Math.max(1, Math.ceil(reviews.length / 3));
      const dotsHtml = Array.from({ length: pageCount }, (_item, index) => {
        const active = index === 0 ? " active" : "";
        return `<button type="button" class="rc-dot${active}" data-siaw-hydrated="reviews" aria-label="Review group ${index + 1}"></button>`;
      }).join("");
      dotsWrap.components(dotsHtml);
    }
  }

  let imageSwapBound = false;
  let pendingSlideshowAction = null;
  let imagePickerState = null;

  function assetSrc(asset) {
    return asset?.getSrc?.() || asset?.get?.("src") || "";
  }

  function recoverExternalImageUrl(src) {
    const raw = String(src || "").trim();
    if (!raw) return "";
    // Shopify CDN paths wrongly hosted on ngrok / localhost after a bad rewrite.
    const shopifyPath = raw.match(/\/s\/files\/\d+\/[^\s"'<>]+/i);
    if (shopifyPath) {
      const path = shopifyPath[0].replace(/&amp;/g, "&");
      try {
        const parsed = new URL(raw, window.location.origin);
        const host = parsed.hostname.toLowerCase();
        const isProjectHost =
          host === window.location.hostname ||
          host.endsWith(".ngrok-free.app") ||
          host.endsWith(".ngrok.io") ||
          host.endsWith(".ngrok.app");
        if (isProjectHost || raw.startsWith("/s/files/")) {
          return `https://cdn.shopify.com${path}`;
        }
      } catch (_error) {
        if (raw.startsWith("/s/files/")) return `https://cdn.shopify.com${path}`;
      }
    }
    return raw;
  }

  function isProjectFilesPath(pathname) {
    return /^\/projects\/[0-9a-f-]{36}\/files\//i.test(String(pathname || ""));
  }

  function toEditorAssetUrl(src) {
    const recovered = recoverExternalImageUrl(src);
    const raw = String(recovered || "").trim();
    if (!raw) return "";
    if (/^(data:|blob:)/i.test(raw)) return raw;
    const prefix = loadedData?.projectFilePrefix || `/projects/${config.projectId}/files/`;
    const origin = window.location.origin;
    try {
      if (/^(https?:)?\/\//i.test(raw)) {
        const absolute = new URL(raw, origin);
        // Only remap our project file proxy, never Shopify `/s/files/...`.
        if (isProjectFilesPath(absolute.pathname)) {
          return `${origin}${absolute.pathname}${absolute.search}`;
        }
        return absolute.href;
      }
    } catch (_error) {
      /* keep falling through */
    }
    if (isProjectFilesPath(raw) || (raw.startsWith("/projects/") && raw.includes("/files/"))) {
      return `${origin}${raw.startsWith("/") ? raw : `/${raw}`}`;
    }
    if (raw.startsWith(prefix)) {
      return `${origin}${raw}`;
    }
    if (raw.startsWith("/s/files/")) {
      return recoverExternalImageUrl(raw);
    }
    const relative = raw.replace(/^\.\//, "").replace(/^\/+/, "");
    return `${origin}${prefix}${relative.split("/").map(encodeURIComponent).join("/")}`;
  }

  function repairEditorMediaUrls(data = loadedData || {}) {
    if (!editor) return;
    const am = editor.AssetManager;
    const serverAssets = Array.isArray(data.assets) ? data.assets : [];
    const seen = new Set();

    if (am) {
      am.getAll().forEach((asset) => {
        const current = assetSrc(asset);
        const fixed = toEditorAssetUrl(current);
        if (fixed && fixed !== current) asset.set({ src: fixed });
        if (fixed) seen.add(fixed);
      });
      serverAssets.forEach((item) => {
        const src = toEditorAssetUrl(item.src || item.relativePath || "");
        if (!src || seen.has(src)) return;
        am.add({
          type: "image",
          src,
          name: item.name || src.split("/").pop(),
          relativePath: item.relativePath || "",
        });
        seen.add(src);
      });
    }

    const images = editor.getWrapper?.()?.find?.("img") || [];
    images.forEach((image) => {
      const current = image.getAttributes?.()?.src || "";
      const fixed = toEditorAssetUrl(current);
      if (fixed && fixed !== current) image.addAttributes({ src: fixed });
    });
  }

  function collectImagePickerItems() {
    const items = [];
    const seen = new Set();
    const push = (src, name = "") => {
      const absolute = toEditorAssetUrl(src);
      if (!absolute || seen.has(absolute)) return;
      seen.add(absolute);
      items.push({
        src: absolute,
        name: name || absolute.split("/").pop() || "image",
      });
    };

    (Array.isArray(loadedData?.assets) ? loadedData.assets : []).forEach((item) => {
      push(item.src || item.relativePath || "", item.name || "");
    });
    (Array.isArray(loadedData?.heroCarouselPhotos) ? loadedData.heroCarouselPhotos : []).forEach((item, index) => {
      push(item.src || "", item.alt || `Slide ${index + 1}`);
    });
    heroSlides().forEach((slide, index) => {
      const image = slide.find?.("img")?.[0];
      const src = image?.getAttributes?.()?.src || "";
      push(src, `Current slide ${index + 1}`);
    });
    try {
      editor?.AssetManager?.getAll?.().forEach((asset) => {
        push(assetSrc(asset), asset.get?.("name") || "");
      });
    } catch (_error) {
      /* ignore */
    }
    return items;
  }

  function ensureImagePicker() {
    let root = document.getElementById("siawImagePicker");
    if (root) return root;
    root = document.createElement("div");
    root.id = "siawImagePicker";
    root.className = "siaw-image-picker";
    root.hidden = true;
    root.innerHTML = `
      <div class="siaw-image-picker-backdrop" data-image-picker-close></div>
      <div class="siaw-image-picker-dialog" role="dialog" aria-modal="true" aria-labelledby="siawImagePickerTitle">
        <header class="siaw-image-picker-header">
          <strong id="siawImagePickerTitle">Select image</strong>
          <button type="button" class="siaw-image-picker-close" data-image-picker-close aria-label="Close">×</button>
        </header>
        <div class="siaw-image-picker-body">
          <label class="siaw-image-picker-drop" data-image-picker-drop>
            <input type="file" accept="image/*" data-image-picker-upload hidden>
            <strong>Drop a file here or click to upload</strong>
            <span>Uploaded images are applied to the slideshow immediately</span>
          </label>
          <div class="siaw-image-picker-side">
            <div class="siaw-image-picker-url">
              <input type="url" placeholder="https://example.com/image.jpg" data-image-picker-url>
              <button type="button" class="secondary-btn" data-image-picker-add-url>Add URL</button>
            </div>
            <div class="siaw-image-picker-grid" data-image-picker-grid></div>
            <p class="siaw-image-picker-empty" data-image-picker-empty hidden>No images yet. Upload one or paste an image URL.</p>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(root);

    const uploadInput = root.querySelector("[data-image-picker-upload]");
    const dropZone = root.querySelector("[data-image-picker-drop]");

    async function handlePickerUpload(fileList) {
      const fakeEvent = { target: { files: fileList, value: "" }, dataTransfer: { files: fileList } };
      const uploaded = await uploadAssets(fakeEvent);
      repairEditorMediaUrls(loadedData || {});
      renderImagePickerGrid();
      const first = uploaded?.[0]?.src;
      if (first) {
        // Uploading while the picker is open means "use this image now".
        chooseImagePickerSrc(first);
      }
    }

    root.querySelectorAll("[data-image-picker-close]").forEach((node) => {
      node.addEventListener("click", () => closeImagePicker());
    });
    root.querySelector("[data-image-picker-add-url]")?.addEventListener("click", () => {
      const input = root.querySelector("[data-image-picker-url]");
      const src = toEditorAssetUrl(input?.value || "");
      if (!src) return;
      chooseImagePickerSrc(src);
    });
    uploadInput?.addEventListener("change", async (event) => {
      try {
        await handlePickerUpload(event.target.files);
        event.target.value = "";
      } catch (error) {
        console.error(error);
        await siawAlert(error.message || "Image upload failed.");
      }
    });
    dropZone?.addEventListener("dragover", (event) => {
      event.preventDefault();
      dropZone.classList.add("is-dragover");
    });
    dropZone?.addEventListener("dragleave", () => {
      dropZone.classList.remove("is-dragover");
    });
    dropZone?.addEventListener("drop", async (event) => {
      event.preventDefault();
      dropZone.classList.remove("is-dragover");
      try {
        await handlePickerUpload(event.dataTransfer?.files);
      } catch (error) {
        console.error(error);
        await siawAlert(error.message || "Image upload failed.");
      }
    });
    return root;
  }

  function renderImagePickerGrid() {
    const root = ensureImagePicker();
    const grid = root.querySelector("[data-image-picker-grid]");
    const empty = root.querySelector("[data-image-picker-empty]");
    if (!grid) return;
    const items = collectImagePickerItems();
    grid.innerHTML = items.map((item) => `
      <button type="button" class="siaw-image-picker-item" data-image-src="${escapeHtml(item.src)}" title="${escapeHtml(item.name)}">
        <img src="${escapeHtml(item.src)}" alt="" loading="lazy">
        <span>${escapeHtml(item.name)}</span>
      </button>
    `).join("");
    if (empty) empty.hidden = items.length > 0;
    grid.querySelectorAll("[data-image-src]").forEach((button) => {
      button.addEventListener("click", () => {
        chooseImagePickerSrc(button.getAttribute("data-image-src") || "");
      });
    });
  }

  function closeImagePicker() {
    const root = document.getElementById("siawImagePicker");
    if (root) root.hidden = true;
    imagePickerState = null;
  }

  function chooseImagePickerSrc(src) {
    const absolute = toEditorAssetUrl(src);
    const onSelect = imagePickerState?.onSelect;
    closeImagePicker();
    if (absolute) onSelect?.(absolute);
  }

  function openImageAssetPicker({ onSelect, title = "Select image" } = {}) {
    repairEditorMediaUrls(loadedData || {});
    imagePickerState = { onSelect };
    const root = ensureImagePicker();
    const titleNode = root.querySelector("#siawImagePickerTitle");
    if (titleNode) titleNode.textContent = title;
    renderImagePickerGrid();
    root.hidden = false;
  }

  function collectHeroSlideshowForSave(track = heroCarouselTrack()) {
    return heroSlides(track).map((slide, index) => {
      const image = slide.find?.("img")?.[0];
      const attrs = image?.getAttributes?.() || {};
      const alt = String(attrs.alt || `Slide ${index + 1}`);
      return {
        src: String(attrs.src || ""),
        alt,
        alt_en: alt,
        alt_de: alt,
      };
    }).filter((item) => item.src);
  }

  function addHeroSlide(src, alt = "Slideshow image") {
    const track = heroCarouselTrack();
    if (!track || !src) return null;
    markHeroCarouselManaged(track);
    const slides = heroSlides(track);
    const wasEmpty = !slides.length;
    track.append(heroSlideHtml(src, alt, wasEmpty));
    const nextSlides = heroSlides(track);
    const newIndex = Math.max(0, nextSlides.length - 1);
    setActiveHeroSlide(track, newIndex);
    const created = nextSlides[newIndex] || null;
    if (created) editor.select(created.find?.("img")?.[0] || created);
    markDirty();
    renderSlideshowManager(created || track);
    return created;
  }

  function reorderHeroSlides(track, fromIndex, toIndex) {
    if (!track) return;
    const slides = heroSlides(track);
    if (
      fromIndex === toIndex
      || fromIndex < 0
      || toIndex < 0
      || fromIndex >= slides.length
      || toIndex >= slides.length
    ) {
      return;
    }
    const ordered = slides.slice();
    const [moved] = ordered.splice(fromIndex, 1);
    ordered.splice(toIndex, 0, moved);
    const html = ordered.map((slide, index) => {
      const image = slide.find?.("img")?.[0];
      const attrs = image?.getAttributes?.() || {};
      return heroSlideHtml(
        attrs.src || "",
        attrs.alt || `Slide ${index + 1}`,
        index === toIndex,
      );
    }).join("");
    track.components(html);
    setActiveHeroSlide(track, toIndex);
    const next = heroSlides(track)[toIndex];
    if (next) editor.select(next.find?.("img")?.[0] || next);
    markDirty();
    renderSlideshowManager(next || track);
  }

  async function removeHeroSlide(context) {
    const track = context?.track || heroCarouselTrack();
    const slides = heroSlides(track);
    if (!track || !slides.length) return;
    const index = Math.max(0, context?.index ?? 0);
    const target = slides[index] || context?.slide;
    if (!target) return;
    if (slides.length === 1) {
      const confirmed = await siawConfirm("Remove the last slideshow image? The carousel will be empty until you add another.", {
        danger: true,
        confirmLabel: "Remove",
        title: "Remove slide",
      });
      if (!confirmed) return;
    }
    target.remove();
    const remaining = heroSlides(track);
    if (remaining.length) {
      const nextIndex = Math.min(index, remaining.length - 1);
      setActiveHeroSlide(track, nextIndex);
      editor.select(remaining[nextIndex].find?.("img")?.[0] || remaining[nextIndex]);
      renderSlideshowManager(remaining[nextIndex]);
    } else {
      syncHeroCarouselDots(track);
      editor.select(track);
      renderSlideshowManager(track);
    }
    markDirty();
  }

  function toggleComponentClass(component, className, enabled) {
    if (!component) return;
    if (enabled) {
      if (component.addClass) component.addClass(className);
      else {
        const classes = new Set(componentClassList(component));
        classes.add(className);
        component.setClass?.(Array.from(classes).join(" "));
      }
      return;
    }
    if (component.removeClass) component.removeClass(className);
    else {
      const classes = new Set(componentClassList(component));
      classes.delete(className);
      component.setClass?.(Array.from(classes).join(" "));
    }
  }

  function renderResponsiveManager(component) {
    if (!responsiveManager) return;
    if (!component || component.get?.("type") === "wrapper") {
      responsiveManager.hidden = true;
      responsiveManager.innerHTML = "";
      return;
    }
    const classes = new Set(componentClassList(component));
    const deviceHint = currentDevice === "Desktop"
      ? "Style changes apply to the base (desktop-first) styles."
      : `Editing ${currentDevice}. GrapesJS can store device-specific style overrides for this breakpoint.`;
    responsiveManager.hidden = false;
    responsiveManager.innerHTML = `
      <div class="responsive-manager-card">
        <strong>Responsive</strong>
        <p class="smart-help">${escapeHtml(deviceHint)}</p>
        <label class="responsive-check"><input type="checkbox" data-hide-desktop ${classes.has("siaw-hide-desktop") ? "checked" : ""}> Hide on desktop</label>
        <label class="responsive-check"><input type="checkbox" data-hide-tablet ${classes.has("siaw-hide-tablet") ? "checked" : ""}> Hide on tablet</label>
        <label class="responsive-check"><input type="checkbox" data-hide-mobile ${classes.has("siaw-hide-mobile") ? "checked" : ""}> Hide on mobile</label>
      </div>
    `;
    responsiveManager.querySelector("[data-hide-desktop]")?.addEventListener("change", (event) => {
      toggleComponentClass(component, "siaw-hide-desktop", event.target.checked);
      markDirty();
    });
    responsiveManager.querySelector("[data-hide-tablet]")?.addEventListener("change", (event) => {
      toggleComponentClass(component, "siaw-hide-tablet", event.target.checked);
      markDirty();
    });
    responsiveManager.querySelector("[data-hide-mobile]")?.addEventListener("change", (event) => {
      toggleComponentClass(component, "siaw-hide-mobile", event.target.checked);
      markDirty();
    });
  }

  function bindEditorShortcuts() {
    if (!editor || editor.__siawShortcutsBound) return;
    editor.__siawShortcutsBound = true;
    document.addEventListener("keydown", (event) => {
      if (!editorReady || activeEditorMode !== "safe") return;
      const key = String(event.key || "").toLowerCase();
      const meta = event.metaKey || event.ctrlKey;
      const target = event.target;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (typing) return;

      if (meta && key === "z" && !event.shiftKey) {
        event.preventDefault();
        editor.UndoManager.undo();
        return;
      }
      if (meta && (key === "y" || (key === "z" && event.shiftKey))) {
        event.preventDefault();
        editor.UndoManager.redo();
        return;
      }
      if (meta && key === "d") {
        event.preventDefault();
        const selected = editor.getSelected();
        if (!selected || selected.get?.("type") === "wrapper") return;
        if (selected.get?.("copyable") === false) return;
        const parent = selected.parent?.();
        if (!parent) return;
        const index = parent.components().indexOf(selected);
        const clone = selected.clone();
        parent.append(clone, { at: index + 1 });
        editor.select(clone);
        markDirty();
        return;
      }
      if ((key === "delete" || key === "backspace") && !meta) {
        const selected = editor.getSelected();
        if (!selected || selected.get?.("type") === "wrapper") return;
        if (selected.get?.("removable") === false) return;
        event.preventDefault();
        selected.remove();
        markDirty();
      }
    });
  }

  function withResponsiveVisibilityCss(cssText) {
    const css = String(cssText || "");
    if (css.includes("siaw-responsive-visibility")) return css;
    return `${css.trim()}\n\n${RESPONSIVE_VISIBILITY_CSS}\n`;
  }

  function resolveImageComponent(component) {
    if (!component) return null;
    if (component.get?.("type") === "image" || component.get?.("tagName") === "img") {
      return component;
    }
    const nested = component.find?.("img") || [];
    return nested[0] || null;
  }

  function renderImageManager(component) {
    if (!imageManager) return;
    const image = resolveImageComponent(component);
    if (!image) {
      imageManager.hidden = true;
      imageManager.innerHTML = "";
      return;
    }
    const attrs = image.getAttributes?.() || {};
    const src = toEditorAssetUrl(attrs.src || "");
    const alt = String(attrs.alt || "");
    imageManager.hidden = false;
    imageManager.innerHTML = `
      <div class="image-manager-card">
        <strong>Image</strong>
        <p class="smart-help">Replace this image, or edit the source and alt text.</p>
        <div class="image-manager-preview">${
          src
            ? `<img src="${escapeHtml(src)}" alt="${escapeHtml(alt)}" loading="lazy">`
            : `<span class="image-manager-missing">No image source</span>`
        }</div>
        <label class="smart-field"><span>Image source</span>
          <input type="text" data-image-src value="${escapeHtml(attrs.src || "")}" placeholder="https://… or images/photo.jpg">
        </label>
        <label class="smart-field"><span>Alt text</span>
          <input type="text" data-image-alt value="${escapeHtml(alt)}" placeholder="Describe the image">
        </label>
        <div class="image-manager-actions">
          <button type="button" class="primary-btn" data-image-swap>Replace image…</button>
        </div>
      </div>
    `;
    const srcInput = imageManager.querySelector("[data-image-src]");
    const altInput = imageManager.querySelector("[data-image-alt]");
    const applySrc = () => {
      const next = toEditorAssetUrl(srcInput?.value || "");
      image.addAttributes({ src: next });
      markDirty();
      const preview = imageManager.querySelector(".image-manager-preview img");
      if (preview) preview.src = next;
      else renderImageManager(image);
    };
    srcInput?.addEventListener("change", applySrc);
    altInput?.addEventListener("change", () => {
      image.addAttributes({ alt: String(altInput.value || "") });
      markDirty();
    });
    imageManager.querySelector("[data-image-swap]")?.addEventListener("click", () => {
      pendingSlideshowAction = { type: "swap", image };
      openImageAssetPicker({
        title: "Replace image",
        onSelect: (picked) => {
          pendingSlideshowAction = null;
          const absolute = toEditorAssetUrl(picked);
          image.addAttributes({ src: absolute });
          if (srcInput) srcInput.value = absolute;
          markDirty();
          renderImageManager(image);
        },
      });
    });
  }

  function renderSlideshowManager(component) {
    if (!slideshowManager) return;
    const context = findHeroCarouselContext(component);
    if (!context?.track) {
      slideshowManager.hidden = true;
      slideshowManager.innerHTML = "";
      return;
    }
    const count = context.slides.length;
    const current = count ? context.index + 1 : 0;
    const thumbs = context.slides.map((slide, index) => {
      const image = slide.find?.("img")?.[0];
      const src = toEditorAssetUrl(image?.getAttributes?.()?.src || "");
      const active = index === context.index ? " is-active" : "";
      return `
        <button type="button" class="slideshow-thumb${active}" draggable="true" data-slideshow-index="${index}" title="Drag to reorder. Click to select slide ${index + 1}.">
          ${src ? `<img src="${escapeHtml(src)}" alt="" draggable="false">` : `<span>${index + 1}</span>`}
        </button>
      `;
    }).join("");
    slideshowManager.hidden = false;
    slideshowManager.innerHTML = `
      <div class="slideshow-manager-card">
        <strong>Slideshow</strong>
        <p class="smart-help">${count ? `Slide ${current} of ${count}. Drag thumbnails to reorder. Add, swap, or remove, then save the slideshow.` : "No images yet. Add the first slideshow image, then save."}</p>
        ${count ? `<div class="slideshow-thumbs" data-slideshow-thumbs>${thumbs}</div>` : ""}
        <div class="slideshow-manager-actions">
          <button type="button" class="secondary-btn" data-slideshow-add>Add image</button>
          <button type="button" class="secondary-btn" data-slideshow-swap ${context.slide ? "" : "disabled"}>Swap image</button>
          <button type="button" class="delete-btn" data-slideshow-remove ${context.slide ? "" : "disabled"}>Remove slide</button>
          <button type="button" class="primary-btn" data-slideshow-save>Save slideshow</button>
        </div>
      </div>
    `;

    let dragFromIndex = null;
    let suppressThumbClick = false;
    slideshowManager.querySelectorAll("[data-slideshow-index]").forEach((button) => {
      const index = Number(button.getAttribute("data-slideshow-index"));
      button.addEventListener("dragstart", (event) => {
        if (!Number.isFinite(index)) return;
        dragFromIndex = index;
        suppressThumbClick = false;
        button.classList.add("is-dragging");
        try {
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", String(index));
        } catch (_error) {
          /* older browsers */
        }
      });
      button.addEventListener("dragend", () => {
        button.classList.remove("is-dragging");
        slideshowManager.querySelectorAll(".slideshow-thumb.is-drop-target").forEach((node) => {
          node.classList.remove("is-drop-target");
        });
        dragFromIndex = null;
      });
      button.addEventListener("dragover", (event) => {
        event.preventDefault();
        try { event.dataTransfer.dropEffect = "move"; } catch (_error) { /* ignore */ }
        button.classList.add("is-drop-target");
      });
      button.addEventListener("dragleave", () => {
        button.classList.remove("is-drop-target");
      });
      button.addEventListener("drop", (event) => {
        event.preventDefault();
        button.classList.remove("is-drop-target");
        let fromIndex = dragFromIndex;
        try {
          const raw = event.dataTransfer.getData("text/plain");
          if (raw !== "") fromIndex = Number(raw);
        } catch (_error) {
          /* ignore */
        }
        if (!Number.isFinite(fromIndex) || !Number.isFinite(index) || fromIndex === index) return;
        suppressThumbClick = true;
        reorderHeroSlides(context.track, fromIndex, index);
      });
      button.addEventListener("click", () => {
        if (suppressThumbClick) {
          suppressThumbClick = false;
          return;
        }
        if (!Number.isFinite(index)) return;
        setActiveHeroSlide(context.track, index);
        const slide = heroSlides(context.track)[index];
        if (slide) editor.select(slide.find?.("img")?.[0] || slide);
        renderSlideshowManager(slide || context.track);
      });
    });

    slideshowManager.querySelector("[data-slideshow-add]")?.addEventListener("click", () => {
      pendingSlideshowAction = { type: "add" };
      openImageAssetPicker({
        title: "Add slideshow image",
        onSelect: (src) => {
          pendingSlideshowAction = null;
          addHeroSlide(toEditorAssetUrl(src));
        },
      });
    });
    slideshowManager.querySelector("[data-slideshow-swap]")?.addEventListener("click", () => {
      if (!context.slide) return;
      const image = context.slide.find?.("img")?.[0] || (context.slide.get?.("type") === "image" ? context.slide : null);
      pendingSlideshowAction = { type: "swap", image, slide: context.slide };
      openImageAssetPicker({
        title: "Swap slideshow image",
        onSelect: (src) => {
          const absolute = toEditorAssetUrl(src);
          pendingSlideshowAction = null;
          if (image) image.addAttributes({ src: absolute });
          else if (context.slide) {
            context.slide.components(
              `<img src="${escapeHtml(absolute)}" alt="Slideshow image" draggable="false" decoding="async" loading="eager">`,
            );
          }
          markDirty();
          renderSlideshowManager(context.slide);
        },
      });
    });
    slideshowManager.querySelector("[data-slideshow-remove]")?.addEventListener("click", () => {
      void removeHeroSlide(context);
    });
    slideshowManager.querySelector("[data-slideshow-save]")?.addEventListener("click", async () => {
      dirty = true;
      const photos = collectHeroSlideshowForSave(context.track);
      const saved = await saveProject({ force: true });
      if (saved) {
        if (loadedData) loadedData.heroCarouselPhotos = photos;
        await siawAlert(`Slideshow saved with ${photos.length} slide${photos.length === 1 ? "" : "s"}.`);
      }
    });
  }

  function bindImageSwapEditing() {
    if (!editor || imageSwapBound) return;
    imageSwapBound = true;

    editor.on("component:dblclick", (component) => {
      if (!component || component.get("type") !== "image") return;
      const context = findHeroCarouselContext(component);
      pendingSlideshowAction = context
        ? { type: "swap", image: component, slide: context.slide }
        : { type: "swap", image: component };
      openImageAssetPicker({
        title: context ? "Swap slideshow image" : "Swap image",
        onSelect: (src) => {
          pendingSlideshowAction = null;
          component.addAttributes({ src: toEditorAssetUrl(src) });
          markDirty();
          if (context) renderSlideshowManager(context.slide || component);
        },
      });
    });

    editor.on("asset:selected", (asset) => {
      const src = toEditorAssetUrl(assetSrc(asset));
      if (!src) return;
      if (pendingSlideshowAction?.type === "add") {
        pendingSlideshowAction = null;
        addHeroSlide(src);
        try { editor.AssetManager.close(); } catch (_error) { /* ignore */ }
        return;
      }
      if (pendingSlideshowAction?.type === "swap" && pendingSlideshowAction.image) {
        pendingSlideshowAction.image.addAttributes({ src });
        const slide = pendingSlideshowAction.slide;
        pendingSlideshowAction = null;
        markDirty();
        if (slide) renderSlideshowManager(slide);
        try { editor.AssetManager.close(); } catch (_error) { /* ignore */ }
        return;
      }
      const selected = editor.getSelected?.();
      if (!selected || selected.get("type") !== "image") return;
      selected.addAttributes({ src });
      markDirty();
    });
  }

  function injectEditorOnlyHelpers(data = loadedData || {}) {
    const doc = editor?.Canvas?.getDocument();
    if (!doc) return;
    repairEditorMediaUrls(data);
    forceRevealAnimationElements();
    hydrateHeroCarouselFromData(data);
    hydrateReviewsFromData(data);
    addRuntimeRegionNotes(data);

    const productGrid = doc.getElementById("productGrid");
    if (productGrid && !productGrid.children.length && !productGrid.querySelector("[data-siaw-editor-only]")) {
      const note = doc.createElement("div");
      note.dataset.siawEditorOnly = "true";
      note.className = "siaw-editor-runtime-note";
      note.innerHTML = "<strong>Dynamic product cards</strong><br>These cards are generated by the original website JavaScript and appear in Live Preview. Edit the featured product panel below; image changes are synchronised to the live catalogue when you save.";
      productGrid.appendChild(note);
    }

    const emptyRuntimeAreas = [
      ["detailFeatures", "Product feature cards are generated in Live Preview."],
      ["detailSteps", "Product steps are generated in Live Preview."],
    ];
    emptyRuntimeAreas.forEach(([id, message]) => {
      const target = doc.getElementById(id);
      if (!target || target.children.length || target.querySelector("[data-siaw-editor-only]")) return;
      const note = doc.createElement(id === "detailSteps" ? "li" : "div");
      note.dataset.siawEditorOnly = "true";
      note.textContent = message;
      note.style.cssText = "padding:12px;border:1px dashed #ff4545;border-radius:10px;background:#fff7f7;color:#5f1e1e";
      target.appendChild(note);
    });
  }

  function componentIsInsideProtected(component) {
    let current = component;
    while (current) {
      if (current.get && current.get("type") === "siaw-protected") return true;
      current = current.parent ? current.parent() : null;
    }
    return false;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function serviceComponents() {
    if (!editor) return [];
    return editor.getWrapper().find(".service-card").filter((component) => {
      const attrs = component.getAttributes ? component.getAttributes() : {};
      return Boolean(attrs["data-service"]);
    });
  }

  function serviceKey(component) {
    return String(component?.getAttributes?.()["data-service"] || "").trim();
  }

  function componentPart(component, selector) {
    return component?.find?.(selector)?.[0] || null;
  }

  function componentText(component, selector) {
    const part = componentPart(component, selector);
    const element = part?.getEl?.();
    if (element) return element.textContent.trim();
    return String(part?.get?.("content") || "").trim();
  }

  function setComponentText(component, selector, value) {
    const part = componentPart(component, selector);
    if (part) part.components(escapeHtml(value));
  }

  function componentImage(component) {
    return String(componentPart(component, "img")?.getAttributes?.().src || "");
  }

  function ensureSmartState(component) {
    const key = serviceKey(component);
    if (!key) return null;
    if (!smartServiceState.has(key)) {
      smartServiceState.set(key, {
        key,
        title: componentText(component, "h3") || "New Service",
        cardDescription: componentText(component, "p"),
        buttonText: componentText(component, ".service-detail-link") || "View service details →",
        image: componentImage(component),
        detailSummary: "Describe the service and who it supports.",
        detailSectionOneHeading: "What we help with",
        detailSectionOneText: "Explain what happens in this service.",
        detailSectionTwoHeading: "Examples of support",
        detailSectionTwoBullets: ["Add the first example", "Add the second example"],
        detailSectionThreeHeading: "What you get",
        detailSectionThreeText: "Explain the result the client receives.",
      });
    }
    return smartServiceState.get(key);
  }

  function currentSmartComponent() {
    return serviceComponents().find((component) => serviceKey(component) === selectedSmartServiceKey) || null;
  }

  function smartField(name, label, value, textarea = false) {
    const tag = textarea
      ? `<textarea data-smart-field="${name}">${escapeHtml(value)}</textarea>`
      : `<input data-smart-field="${name}" value="${escapeHtml(value)}">`;
    return `<label class="smart-field"><span>${label}</span>${tag}</label>`;
  }

  function compatibilityText(data) {
    const inlineCount = Number(data.compatibility?.inlineStyleCount || 0);
    const externalCount = Number(data.compatibility?.externalStyleCount || 0);
    if (inlineCount) return `Compatibility engine loaded ${inlineCount} inline style block${inlineCount === 1 ? "" : "s"}. Self-contained HTML designs should now match Live Preview much more closely.`;
    if (externalCount) return `Compatibility engine loaded ${externalCount} linked stylesheet${externalCount === 1 ? "" : "s"}.`;
    return "No website stylesheet was detected. The editor is using safe media-size fallbacks.";
  }

  function reportStat(value, label) {
    return `<div class="report-stat"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`;
  }

  function profileList(items, className) {
    if (!items.length) return "";
    return `<ul class="report-list ${className || ""}">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
  }

  function renderCompatibilityReport(data) {
    if (!compatibilityReport) return;
    const report = data.compatibility || {};
    const score = Math.max(0, Math.min(100, Number(report.compatibilityScore || 0)));
    const runtimeRegions = Array.isArray(report.runtimeRegions) ? report.runtimeRegions : [];
    const missing = Array.isArray(report.missingResources) ? report.missingResources : [];
    const recommendations = Array.isArray(report.recommendations) ? report.recommendations : [];
    const pages = Array.isArray(report.pages) ? report.pages : [];
    const profile = report.supportProfile || {};

    const regionMarkup = runtimeRegions.length
      ? runtimeRegions.slice(0, 18).map((region) => `<div class="report-region"><code>${escapeHtml(region.selector || `#${region.id}`)}</code><span>${escapeHtml(region.reason || "JavaScript-generated")}</span></div>`).join("")
      : '<p class="smart-help">No empty JavaScript-generated regions were detected in the original HTML.</p>';
    const missingMarkup = missing.length
      ? `<div class="report-section report-danger"><strong>Missing local resources (${missing.length})</strong><ul class="report-list">${missing.slice(0, 12).map((item) => `<li>${escapeHtml(typeof item === "string" ? item : item.value || item)}</li>`).join("")}</ul></div>`
      : '<div class="report-section"><strong>Local resources</strong><p class="smart-help">No missing local files were detected.</p></div>';
    const pageMarkup = pages.length > 1
      ? `<div class="report-section"><strong>HTML pages (${pages.length})</strong><ul class="report-list">${pages.slice(0, 10).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`
      : "";

    const spa = report.spaShell || {};
    const spaMarkup = spa.isSpaShell
      ? `<div class="report-section report-warning">
          <strong>JavaScript app / SPA shell detected</strong>
          <p class="smart-help">${escapeHtml(spa.guidance || "Safe Edit cannot see JS-rendered routes.")}</p>
          <ul class="report-list">${(spa.reasons || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
          <button type="button" class="report-mode-btn" data-open-interactive>Open Interactive mode</button>
        </div>`
      : "";

    const profileMarkup = profile.title
      ? `<div class="report-section">
          <strong>${escapeHtml(profile.title)}</strong>
          <p class="smart-help">${escapeHtml(profile.summary || "")}</p>
          <div class="support-grid">
            <div><em>Supported</em>${profileList(profile.supported || [])}</div>
            <div><em>Partial</em>${profileList(profile.partial || [])}</div>
            <div><em>Unsupported</em>${profileList(profile.unsupported || [], "report-danger-text")}</div>
          </div>
        </div>`
      : "";

    compatibilityReport.innerHTML = `
      <div class="report-score">
        <div class="report-score-row"><strong>Compatibility</strong><div class="report-score-number">${score}<small>/100</small></div></div>
        <div class="report-type">${escapeHtml(report.websiteType || "Imported HTML website")}</div>
        <div class="report-meter"><span style="width:${score}%"></span></div>
      </div>
      ${profileMarkup}
      ${spaMarkup}
      <div class="report-grid">
        ${reportStat(report.directEditableEstimate || 0, "estimated editable items")}
        ${reportStat(report.runtimeRegionCount || 0, "JavaScript regions")}
        ${reportStat((report.imageFileCount || 0) + (report.inlineSvgCount || 0), "images & SVGs")}
        ${reportStat(report.cssBackgroundCount || 0, "CSS media references")}
        ${reportStat(report.animationSelectorCount || 0, "animation selectors")}
        ${reportStat(report.formCount || 0, "forms")}
        ${reportStat((report.inlineScriptCount || 0) + (report.linkedScriptCount || 0), "scripts")}
        ${reportStat(report.storageUsageCount || 0, "browser storage uses")}
      </div>
      <div class="report-section ${runtimeRegions.length ? "report-warning" : ""}">
        <strong>JavaScript-generated regions</strong>
        ${regionMarkup}
        ${runtimeRegions.length ? '<button type="button" class="report-mode-btn" data-open-interactive>Open Interactive mode</button>' : ""}
      </div>
      <div class="report-section"><strong>What the engine is doing</strong><ul class="report-list">${recommendations.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>
      ${pageMarkup}
      ${missingMarkup}
    `;
    compatibilityReport.querySelectorAll("[data-open-interactive]").forEach((button) => {
      button.addEventListener("click", () => setEditorMode("interactive"));
    });
  }

  function detectLinkType(href) {
    const value = String(href || "").trim();
    if (!value) return "external";
    if (value.startsWith("#")) return "section";
    if (value.toLowerCase().startsWith("mailto:")) return "email";
    if (value.toLowerCase().startsWith("tel:")) return "tel";
    if (/^https?:\/\/(wa\.me|api\.whatsapp\.com)\//i.test(value) || value.toLowerCase().startsWith("whatsapp:")) {
      return "whatsapp";
    }
    const pages = Array.isArray(loadedData?.compatibility?.pages)
      ? loadedData.compatibility.pages
      : Array.isArray(loadedData?.files)
        ? loadedData.files.filter((item) => isHtmlPath(item))
        : [];
    const clean = value.split("?")[0].split("#")[0];
    if (pages.some((page) => page === clean || page.endsWith("/" + clean) || clean.endsWith(page))) {
      return "page";
    }
    if (!/^[a-z][a-z0-9+.-]*:/i.test(value) && /\.html?(?:$|[?#])/i.test(value)) return "page";
    return "external";
  }

  function buildHref(type, value, pages) {
    const raw = String(value || "").trim();
    if (type === "section") return raw.startsWith("#") ? raw : `#${raw.replace(/^#/, "")}`;
    if (type === "email") return raw.toLowerCase().startsWith("mailto:") ? raw : `mailto:${raw.replace(/^mailto:/i, "")}`;
    if (type === "tel") return raw.toLowerCase().startsWith("tel:") ? raw : `tel:${raw.replace(/^tel:/i, "")}`;
    if (type === "whatsapp") {
      if (/^https?:\/\//i.test(raw) || raw.toLowerCase().startsWith("whatsapp:")) return raw;
      const digits = raw.replace(/[^\d]/g, "");
      return digits ? `https://wa.me/${digits}` : "https://wa.me/";
    }
    if (type === "page") {
      if (!raw) return pages[0] || "index.html";
      return raw;
    }
    return raw || "#";
  }

  function linkInputValue(type, href) {
    const value = String(href || "");
    if (type === "email") return value.replace(/^mailto:/i, "");
    if (type === "tel") return value.replace(/^tel:/i, "");
    if (type === "section") return value.replace(/^#/, "");
    if (type === "whatsapp") {
      const match = value.match(/wa\.me\/(\d+)/i);
      return match ? match[1] : value.replace(/^whatsapp:/i, "");
    }
    return value;
  }

  function renderLinkManager(component) {
    if (!linkManager) return;
    const tag = String(component?.get?.("tagName") || "").toLowerCase();
    const isLink = tag === "a" || Boolean(component?.getAttributes?.().href);
    if (!isLink || !component) {
      linkManager.hidden = true;
      linkManager.innerHTML = "";
      return;
    }
    const attrs = component.getAttributes() || {};
    const href = attrs.href || "";
    const type = detectLinkType(href);
    const pages = Array.isArray(loadedData?.compatibility?.pages)
      ? loadedData.compatibility.pages
      : (loadedData?.files || []).filter((item) => isHtmlPath(item));
    const pageOptions = pages.map((page) => {
      const selected = detectLinkType(href) === "page" && (href === page || href.startsWith(page + "#")) ? " selected" : "";
      return `<option value="${escapeHtml(page)}"${selected}>${escapeHtml(page)}</option>`;
    }).join("");

    linkManager.hidden = false;
    linkManager.innerHTML = `
      <div class="link-manager-card">
        <strong>Link manager</strong>
        <label class="smart-field"><span>Link type</span>
          <select data-link-type>
            <option value="page"${type === "page" ? " selected" : ""}>Page</option>
            <option value="section"${type === "section" ? " selected" : ""}>Section</option>
            <option value="external"${type === "external" ? " selected" : ""}>External URL</option>
            <option value="email"${type === "email" ? " selected" : ""}>Email</option>
            <option value="tel"${type === "tel" ? " selected" : ""}>Telephone</option>
            <option value="whatsapp"${type === "whatsapp" ? " selected" : ""}>WhatsApp</option>
          </select>
        </label>
        <label class="smart-field" data-link-value-wrap>
          <span data-link-label>Destination</span>
          ${type === "page"
            ? `<select data-link-value>${pageOptions || '<option value="">No pages</option>'}</select>`
            : `<input data-link-value value="${escapeHtml(linkInputValue(type, href))}" placeholder="Destination">`}
        </label>
        <p class="smart-help">External links open in a normal browser tab from Live Preview. Section links use in-page anchors.</p>
      </div>
    `;

    const typeSelect = linkManager.querySelector("[data-link-type]");
    const applyLink = () => {
      const nextType = typeSelect.value;
      const valueEl = linkManager.querySelector("[data-link-value]");
      const nextHref = buildHref(nextType, valueEl?.value || "", pages);
      component.addAttributes({ href: nextHref });
      if (nextType === "external" || nextType === "whatsapp") {
        component.addAttributes({ target: "_blank", rel: "noopener noreferrer" });
      }
      markDirty();
    };
    typeSelect.addEventListener("change", () => {
      const nextType = typeSelect.value;
      const wrap = linkManager.querySelector("[data-link-value-wrap]");
      const label = linkManager.querySelector("[data-link-label]");
      if (label) {
        label.textContent = nextType === "section" ? "Section id" : nextType === "whatsapp" ? "Phone number" : "Destination";
      }
      if (wrap) {
        wrap.querySelector("[data-link-value]")?.remove();
        if (nextType === "page") {
          wrap.insertAdjacentHTML("beforeend", `<select data-link-value>${pageOptions || '<option value="">No pages</option>'}</select>`);
        } else {
          wrap.insertAdjacentHTML("beforeend", `<input data-link-value value="${escapeHtml(linkInputValue(nextType, href))}" placeholder="Destination">`);
        }
        wrap.querySelector("[data-link-value]")?.addEventListener("change", applyLink);
        wrap.querySelector("[data-link-value]")?.addEventListener("input", applyLink);
      }
      applyLink();
    });
    linkManager.querySelector("[data-link-value]")?.addEventListener("change", applyLink);
    linkManager.querySelector("[data-link-value]")?.addEventListener("input", applyLink);
  }

  async function pageAction(action, payload = {}) {
    const response = await fetch(config.pagesUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify({ action, ...payload }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Page action failed.");
    return result;
  }

  function normalizePageDetails(pages, entryFile, pageDetails) {
    if (Array.isArray(pageDetails) && pageDetails.length) {
      return pageDetails.map((item) => ({
        path: item.path || item,
        label: item.label || String(item.path || item).split("/").pop(),
        inNav: Boolean(item.inNav),
        isHome: Boolean(item.isHome) || item.path === entryFile,
      }));
    }
    const list = Array.isArray(pages) ? pages : [];
    return list.map((page) => ({
      path: page,
      label: String(page).split("/").pop().replace(/\.html?$/i, "").replace(/[-_]/g, " "),
      inNav: false,
      isHome: page === entryFile,
    }));
  }

  function renderPagesManager(pages, entryFile, pageDetails) {
    if (!pagesManager) return;
    const details = normalizePageDetails(pages, entryFile, pageDetails || loadedData?.compatibility?.pageDetails);
    if (!details.length) {
      pagesManager.innerHTML = `<div class="smart-empty">No HTML pages found.</div>`;
      return;
    }
    pagesManager.innerHTML = `
      <div class="pages-toolbar">
        <button type="button" class="smart-action" data-page-add>Add page</button>
      </div>
      <p class="smart-help">Menu pages appear first. Open any page to edit it in Safe Edit.</p>
      <div class="pages-list">
        ${details.map((item) => `
          <div class="pages-item${item.isHome ? " is-home" : ""}${item.inNav ? " in-nav" : ""}" data-page="${escapeHtml(item.path)}">
            <button type="button" class="pages-open" data-page-open="${escapeHtml(item.path)}">
              <strong>${escapeHtml(item.label)}</strong>
              <small>${escapeHtml(item.path)}${item.isHome ? " · home" : ""}${item.inNav && !item.isHome ? " · menu" : ""}</small>
            </button>
            <div class="pages-item-actions">
              <button type="button" data-page-home="${escapeHtml(item.path)}" title="Set homepage">Home</button>
              <button type="button" data-page-dup="${escapeHtml(item.path)}" title="Duplicate">Dup</button>
              <button type="button" data-page-rename="${escapeHtml(item.path)}" title="Rename">Rename</button>
            </div>
          </div>
        `).join("")}
      </div>
    `;
    pagesManager.querySelector("[data-page-add]")?.addEventListener("click", async () => {
      const name = await siawPrompt("New page filename", "page.html");
      if (!name) return;
      try {
        const result = await pageAction("add", { name });
        if (loadedData) {
          loadedData.files = Array.from(new Set([...(loadedData.files || []), result.path]));
          if (loadedData.compatibility) {
            loadedData.compatibility.pages = result.pages;
            loadedData.compatibility.pageDetails = result.pageDetails;
          }
        }
        renderPagesManager(result.pages, result.entryFile, result.pageDetails);
        renderFileTree(loadedData?.files || result.pages, result.entryFile);
        setStatus("Page added", "saved");
      } catch (error) {
        await siawAlert(error.message);
      }
    });
    pagesManager.querySelectorAll("[data-page-open]").forEach((button) => {
      button.addEventListener("click", () => void openProjectFile(button.getAttribute("data-page-open")));
    });
    pagesManager.querySelectorAll("[data-page-home]").forEach((button) => {
      button.addEventListener("click", async () => {
        const path = button.getAttribute("data-page-home");
        try {
          const response = await fetch(config.setEntryUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": csrfToken(),
            },
            body: JSON.stringify({ entryFile: path }),
          });
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || "Could not set homepage.");
          window.location.reload();
        } catch (error) {
          await siawAlert(error.message);
        }
      });
    });
    pagesManager.querySelectorAll("[data-page-dup]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          const result = await pageAction("duplicate", { path: button.getAttribute("data-page-dup") });
          if (loadedData?.compatibility) {
            loadedData.compatibility.pages = result.pages;
            loadedData.compatibility.pageDetails = result.pageDetails;
          }
          renderPagesManager(result.pages, result.entryFile, result.pageDetails);
          setStatus("Page duplicated", "saved");
        } catch (error) {
          await siawAlert(error.message);
        }
      });
    });
    pagesManager.querySelectorAll("[data-page-rename]").forEach((button) => {
      button.addEventListener("click", async () => {
        const path = button.getAttribute("data-page-rename");
        const next = await siawPrompt("Rename page to", path.split("/").pop());
        if (!next) return;
        try {
          const result = await pageAction("rename", { path, name: next });
          if (result.reload) {
            window.location.reload();
            return;
          }
          if (loadedData?.compatibility) {
            loadedData.compatibility.pages = result.pages;
            loadedData.compatibility.pageDetails = result.pageDetails;
          }
          renderPagesManager(result.pages, result.entryFile, result.pageDetails);
          setStatus("Page renamed", "saved");
        } catch (error) {
          await siawAlert(error.message);
        }
      });
    });
  }

  function assetFileUrl(path) {
    const prefix = loadedData?.projectFilePrefix || `/projects/${config.projectId}/files/`;
    return `${window.location.origin}${prefix}${String(path).split("/").map(encodeURIComponent).join("/")}`;
  }

  function renderAssetsManager(assets) {
    if (!assetsManager) return;
    const list = Array.isArray(assets) ? assets : [];
    if (!list.length) {
      assetsManager.innerHTML = `<div class="smart-empty">No image assets found yet. Upload one above.</div>`;
      return;
    }
    assetsManager.innerHTML = list.slice(0, 80).map((path) => `
      <button type="button" class="asset-item" data-asset="${escapeHtml(path)}">
        <img src="${escapeHtml(assetFileUrl(path))}" alt="" loading="lazy">
        <span>${escapeHtml(path)}</span>
      </button>
    `).join("");
    assetsManager.querySelectorAll("[data-asset]").forEach((button) => {
      button.addEventListener("click", () => {
        const path = button.getAttribute("data-asset");
        const src = assetFileUrl(path);
        if (editor?.AssetManager) {
          editor.AssetManager.add([{ src, name: path.split("/").pop(), relativePath: path, type: "image" }]);
        }
        openImageAssetPicker({
          title: "Select image",
          onSelect: (chosen) => {
            if (!applyUploadedSrcToPendingOrSelected(chosen)) {
              setStatus(path, "saved");
            }
          },
        });
      });
    });
  }

  async function refreshTreeManagers() {
    if (!config.filesUrl) return;
    try {
      const [filesResponse, pagesResponse] = await Promise.all([
        fetch(config.filesUrl, { headers: { Accept: "application/json" } }),
        config.pagesUrl
          ? fetch(config.pagesUrl, { headers: { Accept: "application/json" } })
          : Promise.resolve(null),
      ]);
      const result = await filesResponse.json();
      if (!filesResponse.ok) return;
      let pageDetails = null;
      let pages = result.pages || [];
      let entryFile = result.entryFile || config.entryFile;
      if (pagesResponse) {
        const pagesResult = await pagesResponse.json();
        if (pagesResponse.ok) {
          pages = pagesResult.pages || pages;
          pageDetails = pagesResult.pageDetails || null;
          entryFile = pagesResult.entryFile || entryFile;
        }
      }
      if (loadedData) {
        loadedData.files = result.files || [];
        if (loadedData.compatibility) {
          loadedData.compatibility.pages = pages;
          if (pageDetails) loadedData.compatibility.pageDetails = pageDetails;
        }
      }
      renderFileTree(result.files || [], entryFile);
      renderPagesManager(pages, entryFile, pageDetails);
      renderAssetsManager(result.assets || []);
    } catch (error) {
      console.error(error);
    }
  }

  async function renderSnapshotsManager() {
    if (!snapshotsManager || !config.snapshotsUrl) return;
    try {
      const response = await fetch(config.snapshotsUrl, { headers: { Accept: "application/json" } });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not load restore points.");
      const snapshots = Array.isArray(result.snapshots) ? result.snapshots : [];
      snapshotsManager.innerHTML = `
        <div class="snapshots-toolbar">
          <button type="button" class="smart-action" data-snapshot-create>Save restore point</button>
        </div>
        ${snapshots.length
          ? `<div class="snapshots-list">${snapshots.map((item) => `
              <div class="snapshots-item">
                <div><strong>${escapeHtml(item.label || item.id)}</strong><span>${escapeHtml(item.createdAt || "")}</span></div>
                <button type="button" data-snapshot-restore="${escapeHtml(item.id)}">Restore</button>
              </div>
            `).join("")}</div>`
          : '<p class="smart-help">No restore points yet.</p>'}
      `;
      snapshotsManager.querySelector("[data-snapshot-create]")?.addEventListener("click", async () => {
        const label = await siawPrompt("Restore point name", "Before big edit");
        if (!label) return;
        const saved = await saveProject({ silent: true });
        if (!saved && dirty) {
          await siawAlert("Save your current changes before creating a restore point.");
          return;
        }
        try {
          const createResponse = await fetch(config.snapshotsUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": csrfToken(),
            },
            body: JSON.stringify({ action: "create", label }),
          });
          const created = await createResponse.json();
          if (!createResponse.ok) throw new Error(created.error || "Could not save restore point.");
          setStatus("Restore point saved", "saved");
          renderSnapshotsManager();
        } catch (error) {
          await siawAlert(error.message);
        }
      });
      snapshotsManager.querySelectorAll("[data-snapshot-restore]").forEach((button) => {
        button.addEventListener("click", async () => {
          const confirmed = await siawConfirm(
            "Restore this snapshot? Current unsaved editor state will be replaced.",
            { danger: true, confirmLabel: "Restore", title: "Restore snapshot" },
          );
          if (!confirmed) return;
          try {
            const restoreResponse = await fetch(config.snapshotsUrl, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrfToken(),
              },
              body: JSON.stringify({ action: "restore", id: button.getAttribute("data-snapshot-restore") }),
            });
            const restored = await restoreResponse.json();
            if (!restoreResponse.ok) throw new Error(restored.error || "Could not restore.");
            window.location.reload();
          } catch (error) {
            await siawAlert(error.message);
          }
        });
      });
    } catch (error) {
      snapshotsManager.innerHTML = `<div class="smart-empty">${escapeHtml(error.message)}</div>`;
    }
  }

  async function exportWithValidation() {
    const saved = await saveProject();
    if (!saved) return;
    try {
      const response = await fetch(config.exportValidateUrl, { headers: { Accept: "application/json" } });
      const report = await response.json();
      if (!response.ok) throw new Error(report.error || "Could not validate export.");
      if (!report.ok) {
        const missing = (report.missingResources || []).slice(0, 8).map((item) => `${item.page}: ${item.value}`).join("\n");
        const empty = (report.emptyLinks || []).slice(0, 4).map((item) => `${item.page}: empty ${item.attribute}`).join("\n");
        const details = [missing, empty].filter(Boolean).join("\n");
        const proceed = await siawConfirm(
          `${report.summary}\n\n${details}\n\nExport anyway?`,
          { title: "Export warnings", confirmLabel: "Export anyway" },
        );
        if (!proceed) return;
      } else {
        setStatus(report.summary || "Export looks clean", "saved");
      }
    } catch (error) {
      console.error(error);
      const proceed = await siawConfirm(
        `${error.message}\n\nExport without validation?`,
        { title: "Export validation failed", confirmLabel: "Export anyway" },
      );
      if (!proceed) return;
    }
    window.location.assign(config.exportUrl);
  }

  function interactiveWidth(device) {
    if (device === "Tablet") return "768px";
    if (device === "Mobile") return "390px";
    return "100%";
  }

  function applyInteractiveDevice() {
    if (!interactiveFrame) return;
    interactiveFrame.style.width = interactiveWidth(currentDevice);
    interactiveFrame.style.margin = "0 auto";
    interactiveFrame.style.boxShadow = currentDevice === "Desktop" ? "none" : "0 0 0 1px #cfd5db";
  }

  function isJsAppShell() {
    return Boolean(
      loadedData?.ssrPreview
      || loadedData?.preferLivePreview
      || loadedData?.compatibility?.preferLivePreview
      || loadedData?.compatibility?.spaShell?.isSpaShell
      || config.ssrPreview
      || config.preferLivePreview
    );
  }

  function hasCapturedEditableEntry() {
    const entry = String(loadedData?.entryFile || config.entryFile || "").toLowerCase();
    return entry.includes("captured/") || Boolean(loadedData?.compatibility?.canSafeEdit);
  }

  function updateSafeEditShellEmpty(showSafe) {
    if (!safeEditShellEmpty) return;
    const show = Boolean(showSafe && isJsAppShell() && !hasCapturedEditableEntry());
    safeEditShellEmpty.hidden = !show;
    if (show && safeEditShellMessage) {
      const kind = loadedData?.ssrPreview || config.ssrPreview
        ? "This is a Nitro / SSR app"
        : "This is a JavaScript app shell";
      safeEditShellMessage.textContent = (
        `${kind}. Interactive mode shows the real website. Safe Edit stays blank until you capture the rendered page as HTML.`
      );
    }
  }

  function setEditorMode(mode) {
    if (!interactiveMode || !interactiveFrame || !canvasArea) return;
    activeEditorMode = mode === "interactive" ? "interactive" : "safe";
    const interactive = activeEditorMode === "interactive";
    safeModeBtn?.classList.toggle("active", !interactive);
    interactiveModeBtn?.classList.toggle("active", interactive);
    canvasArea.classList.toggle("interactive-active", interactive);
    interactiveMode.hidden = !interactive;
    updateSafeEditShellEmpty(!interactive);
    if (interactive) {
      if (!interactiveFrame.src) interactiveFrame.src = loadedData?.runtimeUrl || config.runtimeUrl;
      applyInteractiveDevice();
      protectedHint.hidden = true;
      notice.classList.add("hidden");
    }
  }

  function forceRevealAnimationElements() {
    const doc = editor?.Canvas?.getDocument();
    if (!doc?.body) return;
    const hintPattern = /(reveal|animate|animation|fade|slide|scroll|appear|inview|in-view|aos)/i;
    const candidates = Array.from(doc.body.querySelectorAll("*"));
    candidates.forEach((element) => {
      if (element.closest("dialog,.modal,[role='dialog'],[aria-modal='true']")) return;
      if (element.hasAttribute("hidden") || element.getAttribute("aria-hidden") === "true") return;
      const signature = `${element.id || ""} ${element.className || ""} ${Array.from(element.attributes || []).map((attr) => attr.name).join(" ")}`;
      if (!hintPattern.test(signature)) return;
      const style = doc.defaultView?.getComputedStyle(element);
      if (!style || style.display === "none") return;
      if (Number.parseFloat(style.opacity || "1") > 0.02 && style.visibility !== "hidden") return;
      element.classList.add("siaw-editor-force-visible");
    });
  }

  function addRuntimeRegionNotes(data) {
    const doc = editor?.Canvas?.getDocument();
    if (!doc) return;
    const regions = Array.isArray(data.compatibility?.runtimeRegions) ? data.compatibility.runtimeRegions : [];
    const notedRoots = new Set();

    function attachNote(target, selector, label) {
      if (!target || target.querySelector("[data-siaw-editor-runtime-note]")) return false;
      const meaningful = Array.from(target.children).some((child) => !child.hasAttribute("data-siaw-editor-only"));
      if (meaningful || target.textContent.trim()) return false;
      const note = doc.createElement("div");
      note.dataset.siawEditorOnly = "true";
      note.dataset.siawEditorRuntimeNote = "true";
      note.className = "siaw-editor-runtime-note";
      note.innerHTML = (
        `<strong>${escapeHtml(label)}</strong><br>`
        + "This region is filled by the original website script and appears in Interactive mode and Live Preview. "
        + `Selector: <code>${escapeHtml(selector)}</code>`
      );
      target.appendChild(note);
      return true;
    }

    regions.forEach((region) => {
      const selector = region.selector || (region.id ? `#${region.id}` : "");
      if (!selector) return;
      let targets = [];
      try { targets = Array.from(doc.querySelectorAll(selector)); } catch (_error) { return; }
      targets.forEach((target) => {
        // Prefer one note on the carousel shell instead of separate empty track/dots boxes.
        const carousel = target.closest?.("[data-hero-carousel], .hero-carousel, .hc-frame");
        if (carousel && (selector.includes("js-hc-") || selector.includes("hc-track") || selector.includes("hc-dots"))) {
          if (notedRoots.has(carousel)) return;
          const host = carousel.matches?.(".hc-frame") ? carousel : (carousel.querySelector?.(".hc-frame") || carousel);
          if (attachNote(host, selector, "Hero photo carousel")) {
            notedRoots.add(carousel);
            host.classList.add("siaw-editor-empty-carousel");
          }
          return;
        }
        const reviewsShell = target.closest?.("#reviewsCarousel, .reviews-carousel");
        if (reviewsShell && (selector.includes("reviewsTrack") || selector.includes("reviewsDots"))) {
          if (notedRoots.has(reviewsShell)) return;
          const host = reviewsShell.querySelector?.("#reviewsTrack") || target;
          if (attachNote(host, selector, "Customer reviews carousel")) {
            notedRoots.add(reviewsShell);
            reviewsShell.classList.add("siaw-editor-empty-carousel");
          }
          return;
        }
        attachNote(target, selector, "JavaScript-generated content");
      });
    });
  }

  function smartNavigationPanel() {
    return document.getElementById("smartNavigationManager");
  }

  function smartServicesPanel() {
    return document.getElementById("smartServicesManager");
  }

  function navigationContainerComponent() {
    if (!editor || smartNavigationState?.mode !== "static-html") return null;
    const selector = smartNavigationState.containerSelector || "nav";
    const matches = editor.getWrapper().find(selector);
    const index = Math.max(0, Number(smartNavigationState.containerIndex || 0));
    return matches[index] || matches[0] || null;
  }

  function navigationComponents() {
    const container = navigationContainerComponent();
    if (!container) return [];
    return container.find("a,button").filter((component) => {
      const attrs = component.getAttributes?.() || {};
      const classes = String(attrs.class || "").split(/\s+/);
      if (classes.includes("brand") || classes.includes("logo")) return false;
      const text = navComponentLabel(component);
      return Boolean(text);
    });
  }

  function navComponentLabel(component) {
    if (!component) return "";
    const span = component.find?.("span")?.at?.(-1) || component.find?.("span")?.slice?.(-1)?.[0];
    const spanElement = span?.getEl?.();
    if (spanElement?.textContent?.trim()) return spanElement.textContent.trim();
    const element = component.getEl?.();
    return element?.textContent?.replace(/\s+/g, " ").trim() || String(component.get?.("content") || "").trim();
  }

  function setNavComponentLabel(component, value) {
    if (!component) return;
    const spans = component.find?.("span") || [];
    const span = spans.length ? spans[spans.length - 1] : null;
    if (span) span.components(escapeHtml(value));
    else component.components(escapeHtml(value));
  }

  function navDestination(component, fallback = {}) {
    const attrs = component?.getAttributes?.() || {};
    const name = fallback.destinationAttribute || (component?.get?.("tagName") === "a" ? "href" : "");
    const candidates = [name, "href", "data-view", "data-goto", "data-go", "data-page", "data-scroll-to", "data-target"].filter(Boolean);
    const attribute = candidates.find((item) => Object.prototype.hasOwnProperty.call(attrs, item)) || name || "href";
    return { attribute, value: String(attrs[attribute] || fallback.destination || "") };
  }

  function initialiseSmartNavigation(data) {
    if (smartNavigationState) return;
    const navigation = data.smartNavigation || { available: false, mode: "none", items: [] };
    smartNavigationState = JSON.parse(JSON.stringify(navigation));
    if (navigation.mode === "static-html") {
      const components = navigationComponents();
      components.forEach((component, index) => {
        const state = smartNavigationState.items[index] || {
          key: `item-${index + 1}`,
          label: navComponentLabel(component),
          destination: "",
          destinationAttribute: "",
          visible: true,
          tag: component.get?.("tagName") || "a",
        };
        component.set("siawNavKey", state.key);
        const destination = navDestination(component, state);
        state.label = navComponentLabel(component) || state.label;
        state.destination = destination.value;
        state.destinationAttribute = destination.attribute;
        smartNavigationState.items[index] = state;
      });
      smartNavigationState.items = smartNavigationState.items.slice(0, components.length || smartNavigationState.items.length);
    }
    selectedNavigationKey = smartNavigationState.items?.[0]?.key || null;
  }

  function currentNavigationItem() {
    return smartNavigationState?.items?.find((item) => item.key === selectedNavigationKey) || smartNavigationState?.items?.[0] || null;
  }

  function currentNavigationComponent() {
    if (smartNavigationState?.mode !== "static-html") return null;
    const items = smartNavigationState.items || [];
    const index = items.findIndex((item) => item.key === selectedNavigationKey);
    return navigationComponents()[Math.max(0, index)] || null;
  }

  function uniqueNavigationKey(base = "menu-item") {
    const used = new Set((smartNavigationState?.items || []).map((item) => item.key));
    const clean = String(base).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "menu-item";
    let candidate = clean;
    let number = 2;
    while (used.has(candidate)) candidate = `${clean}-${number++}`;
    return candidate;
  }

  function navigationField(name, label, value, options = {}) {
    if (options.checkbox) {
      return `<label class="smart-check"><input type="checkbox" data-nav-field="${name}" ${value ? "checked" : ""}><span>${label}</span></label>`;
    }
    const readonly = options.readonly ? " readonly" : "";
    return `<label class="smart-field"><span>${label}</span><input data-nav-field="${name}" value="${escapeHtml(value)}"${readonly}></label>`;
  }

  function renderNavigationManager() {
    const panel = smartNavigationPanel();
    if (!panel) return;
    const navigation = smartNavigationState;
    if (!navigation?.available || !Array.isArray(navigation.items) || !navigation.items.length) {
      panel.innerHTML = `<div class="smart-empty"><strong>Navigation Manager</strong><br><br>No supported main navigation was detected. The normal visual editor can still edit individual links.</div>`;
      return;
    }
    if (!selectedNavigationKey || !navigation.items.some((item) => item.key === selectedNavigationKey)) {
      selectedNavigationKey = navigation.items[0].key;
    }
    const item = currentNavigationItem();
    const itemIndex = navigation.items.indexOf(item);
    const options = navigation.items.map((entry) => `<option value="${escapeHtml(entry.key)}" ${entry.key === selectedNavigationKey ? "selected" : ""}>${escapeHtml(entry.label || entry.key)}</option>`).join("");
    const structureDisabled = navigation.supportsStructure === false;
    const destinationLabel = navigation.mode === "javascript-array" ? "Route / destination" : "Link or destination";
    panel.innerHTML = `
      <div class="smart-manager-head"><strong>Navigation Manager</strong><span class="smart-badge">${navigation.items.length} item${navigation.items.length === 1 ? "" : "s"}</span></div>
      <p class="smart-help">${escapeHtml(navigation.description || "Safely edit the website menu.")}</p>
      ${navigation.complex ? '<div class="compatibility-note">Complex dropdown navigation detected. Labels and links are editable, while add, delete and reordering are locked to protect the dropdown structure.</div>' : ""}
      <select id="smartNavigationPicker" class="smart-service-picker">${options}</select>
      <div class="smart-actions">
        <button type="button" class="smart-action" data-nav-action="add" ${navigation.supportsAdd === false || structureDisabled ? "disabled" : ""}>+ Add</button>
        <button type="button" class="smart-action" data-nav-action="duplicate" ${structureDisabled || navigation.supportsAdd === false ? "disabled" : ""}>Duplicate</button>
        <button type="button" class="smart-action" data-nav-action="up" ${structureDisabled || itemIndex <= 0 ? "disabled" : ""}>Move up</button>
        <button type="button" class="smart-action" data-nav-action="down" ${structureDisabled || itemIndex >= navigation.items.length - 1 ? "disabled" : ""}>Move down</button>
        <button type="button" class="smart-action danger" data-nav-action="delete" ${structureDisabled || navigation.items.length <= 1 ? "disabled" : ""}>Delete</button>
      </div>
      <div class="smart-section">
        <strong>Menu item</strong>
        ${navigationField("label", "Menu text", item.label || "")}
        ${navigationField("destination", destinationLabel, item.destination || "")}
        ${navigation.mode === "static-html" ? navigationField("newTab", "Open in a new tab", item.target === "_blank", { checkbox: true }) : ""}
        ${navigationField("visible", "Show this item", item.visible !== false, { checkbox: true })}
        ${navigation.mode === "javascript-array" ? navigationField("cta", "Use call-to-action style", Boolean(item.cta), { checkbox: true }) : ""}
        <div class="smart-key">Technical key: <code>${escapeHtml(item.key)}</code></div>
      </div>
      <p class="smart-help">Click <strong>Save changes</strong> after editing. Static menus update the HTML. JavaScript menus update their data array while preserving their original menu code.</p>
    `;

    panel.querySelector("#smartNavigationPicker")?.addEventListener("change", (event) => {
      selectedNavigationKey = event.target.value;
      const component = currentNavigationComponent();
      if (component) {
        editor.select(component);
        component.getEl()?.scrollIntoView({behavior: "smooth", block: "center"});
      }
      renderNavigationManager();
    });

    panel.querySelectorAll("[data-nav-field]").forEach((field) => {
      field.addEventListener("input", () => {
        const current = currentNavigationItem();
        if (!current) return;
        const name = field.dataset.navField;
        const value = field.type === "checkbox" ? field.checked : field.value;
        current[name] = value;
        if (smartNavigationState.mode === "static-html") {
          const component = currentNavigationComponent();
          if (name === "label") setNavComponentLabel(component, value);
          if (name === "destination") {
            const attr = current.destinationAttribute || navDestination(component, current).attribute;
            component?.addAttributes?.({[attr]: value});
          }
          if (name === "newTab") {
            if (value) component?.addAttributes?.({target: "_blank", rel: "noopener"});
            else component?.removeAttributes?.(["target", "rel"]);
            current.target = value ? "_blank" : "";
          }
          if (name === "visible") {
            if (value) component?.removeStyle?.("display");
            else component?.addStyle?.({display: "none"});
          }
        }
        const option = panel.querySelector(`#smartNavigationPicker option[value="${CSS.escape(current.key)}"]`);
        if (option && name === "label") option.textContent = value;
        markDirty();
      });
    });

    panel.querySelectorAll("[data-nav-action]").forEach((button) => {
      button.addEventListener("click", () => void handleNavigationAction(button.dataset.navAction));
    });
  }

  async function handleNavigationAction(action) {
    const navigation = smartNavigationState;
    const item = currentNavigationItem();
    if (!navigation || !item) return;
    const index = navigation.items.indexOf(item);
    const staticMode = navigation.mode === "static-html";
    const component = currentNavigationComponent();
    const container = navigationContainerComponent();

    if (action === "up" && index > 0) {
      navigation.items.splice(index - 1, 0, navigation.items.splice(index, 1)[0]);
      if (staticMode && component && container) component.move(container, {at: index - 1});
    } else if (action === "down" && index < navigation.items.length - 1) {
      navigation.items.splice(index + 1, 0, navigation.items.splice(index, 1)[0]);
      if (staticMode && component && container) component.move(container, {at: index + 1});
    } else if (action === "delete") {
      const confirmed = await siawConfirm(`Delete the menu item “${item.label}”?`, {
        danger: true,
        confirmLabel: "Delete",
        title: "Delete menu item",
      });
      if (!confirmed) return;
      navigation.items.splice(index, 1);
      component?.remove?.();
      selectedNavigationKey = navigation.items[Math.min(index, navigation.items.length - 1)]?.key || null;
    } else if (action === "duplicate" || action === "add") {
      const key = uniqueNavigationKey(action === "add" ? "new-link" : `${item.key}-copy`);
      const newItem = {
        ...JSON.parse(JSON.stringify(item)),
        key,
        label: action === "add" ? "New Link" : `${item.label} Copy`,
        destination: action === "add" ? "#new-section" : item.destination,
        visible: true,
        isNew: true,
      };
      navigation.items.splice(index + 1, 0, newItem);
      if (staticMode && container) {
        let clone = component?.clone?.();
        if (!clone) clone = editor.Components.addComponent({tagName: "a", attributes: {href: "#new-section"}, components: "New Link"});
        clone.set("siawNavKey", key);
        setNavComponentLabel(clone, newItem.label);
        const destination = navDestination(clone, newItem);
        clone.addAttributes({[destination.attribute]: newItem.destination});
        container.append(clone, {at: index + 1});
        editor.select(clone);
      }
      selectedNavigationKey = key;
    }
    markDirty();
    window.setTimeout(renderNavigationManager, 40);
  }

  function collectSmartNavigation() {
    if (!smartNavigationState?.available) return null;
    if (smartNavigationState.mode === "static-html") {
      const components = navigationComponents();
      smartNavigationState.items = smartNavigationState.items.slice(0, components.length).map((item, index) => {
        const component = components[index];
        const destination = navDestination(component, item);
        return {
          ...item,
          label: navComponentLabel(component) || item.label,
          destination: destination.value,
          destinationAttribute: destination.attribute,
          target: String(component?.getAttributes?.().target || ""),
        };
      });
    }
    return JSON.parse(JSON.stringify(smartNavigationState));
  }

  function renderSmartManager(data) {
    if (!smartManager) return;
    initialiseSmartNavigation(data);
    const components = serviceComponents();
    smartServiceAvailable = Boolean(data.smartServices?.available && components.length);
    if (!serviceStateInitialised) {
      smartServiceState = new Map((data.smartServices?.services || []).map((item) => [String(item.key), {...item}]));
      components.forEach(ensureSmartState);
      serviceStateInitialised = true;
    }

    smartManager.innerHTML = `
      <div class="compatibility-note">${escapeHtml(compatibilityText(data))}</div>
      <div id="smartNavigationManager" class="smart-module"></div>
      <div id="smartServicesManager" class="smart-module"></div>
    `;
    renderNavigationManager();

    const servicesPanel = smartServicesPanel();
    if (!smartServiceAvailable) {
      servicesPanel.innerHTML = `<div class="smart-empty"><strong>Services Manager</strong><br><br>No supported connected service-card pattern was detected. Normal text and images remain editable.</div>`;
      return;
    }
    if (!selectedSmartServiceKey || !components.some((component) => serviceKey(component) === selectedSmartServiceKey)) {
      selectedSmartServiceKey = serviceKey(components[0]);
    }
    renderSelectedSmartService(data);
  }

  function renderSelectedSmartService(data) {
    const panel = smartServicesPanel();
    if (!panel) return;
    const components = serviceComponents();
    const component = currentSmartComponent() || components[0];
    if (!component) return renderSmartManager(data);
    selectedSmartServiceKey = serviceKey(component);
    const state = ensureSmartState(component);
    state.title = componentText(component, "h3") || state.title;
    state.cardDescription = componentText(component, "p");
    state.buttonText = componentText(component, ".service-detail-link") || state.buttonText;
    state.image = componentImage(component) || state.image;

    const options = components.map((item) => {
      const key = serviceKey(item);
      const title = componentText(item, "h3") || key;
      return `<option value="${escapeHtml(key)}" ${key === selectedSmartServiceKey ? "selected" : ""}>${escapeHtml(title)}</option>`;
    }).join("");

    panel.innerHTML = `
      <div class="compatibility-note">${escapeHtml(compatibilityText(data))}</div>
      <div class="smart-manager-head"><strong>Services Manager</strong><span class="smart-badge">${components.length} service${components.length === 1 ? "" : "s"}</span></div>
      <select id="smartServicePicker" class="smart-service-picker">${options}</select>
      <div class="smart-actions">
        <button type="button" class="smart-action" data-smart-action="add">+ Add</button>
        <button type="button" class="smart-action" data-smart-action="duplicate">Duplicate</button>
        <button type="button" class="smart-action" data-smart-action="up">Move up</button>
        <button type="button" class="smart-action" data-smart-action="down">Move down</button>
        <button type="button" class="smart-action danger" data-smart-action="delete">Delete</button>
      </div>
      <div class="smart-section">
        <strong>Card content</strong>
        <div class="smart-key">Technical key: <code>${escapeHtml(state.key)}</code></div><br>
        ${smartField("title", "Service title", state.title)}
        ${smartField("cardDescription", "Short card description", state.cardDescription, true)}
        ${smartField("buttonText", "Card link text", state.buttonText)}
        <label class="smart-field"><span>Service image</span><div class="smart-image-row"><img id="smartImagePreview" class="smart-image-preview" src="${escapeHtml(state.image)}" alt=""><button type="button" id="smartImageButton" class="smart-image-btn">Choose image</button></div></label>
      </div>
      <div class="smart-section">
        <strong>Popup introduction</strong>
        ${smartField("detailSummary", "Summary", state.detailSummary, true)}
      </div>
      <div class="smart-section">
        <strong>Detail section 1</strong>
        ${smartField("detailSectionOneHeading", "Heading", state.detailSectionOneHeading)}
        ${smartField("detailSectionOneText", "Paragraph", state.detailSectionOneText, true)}
      </div>
      <div class="smart-section">
        <strong>Detail section 2</strong>
        ${smartField("detailSectionTwoHeading", "Heading", state.detailSectionTwoHeading)}
        ${smartField("detailSectionTwoBullets", "Bullet points (one per line)", (state.detailSectionTwoBullets || []).join("\n"), true)}
      </div>
      <div class="smart-section">
        <strong>Detail section 3</strong>
        ${smartField("detailSectionThreeHeading", "Heading", state.detailSectionThreeHeading)}
        ${smartField("detailSectionThreeText", "Paragraph", state.detailSectionThreeText, true)}
      </div>
      <p class="smart-help">Changes are applied to the card immediately. Click <strong>Save changes</strong> to update both the HTML and its connected JavaScript popup details.</p>
    `;

    const picker = document.getElementById("smartServicePicker");
    picker?.addEventListener("change", () => {
      selectedSmartServiceKey = picker.value;
      const selected = currentSmartComponent();
      if (selected) {
        editor.select(selected);
        selected.getEl()?.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      renderSelectedSmartService(data);
    });

    panel.querySelectorAll("[data-smart-field]").forEach((field) => {
      field.addEventListener("input", () => {
        const current = ensureSmartState(currentSmartComponent());
        if (!current) return;
        const name = field.dataset.smartField;
        current[name] = name === "detailSectionTwoBullets"
          ? field.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
          : field.value;
        const card = currentSmartComponent();
        if (name === "title") {
          setComponentText(card, "h3", field.value);
          card.addAttributes({ "aria-label": `View ${field.value} details` });
          const option = picker?.querySelector(`option[value="${CSS.escape(current.key)}"]`);
          if (option) option.textContent = field.value;
        } else if (name === "cardDescription") {
          setComponentText(card, "p", field.value);
        } else if (name === "buttonText") {
          setComponentText(card, ".service-detail-link", field.value);
        }
        markDirty();
      });
    });

    document.getElementById("smartImageButton")?.addEventListener("click", () => {
      const image = componentPart(currentSmartComponent(), "img");
      if (image) editor.runCommand("open-assets", { target: image, types: ["image"], accept: "image/*" });
    });

    panel.querySelectorAll("[data-smart-action]").forEach((button) => {
      button.addEventListener("click", () => void handleSmartAction(button.dataset.smartAction, data));
    });
  }

  function uniqueServiceKey(base = "new-service") {
    const used = new Set(serviceComponents().map(serviceKey));
    let key = String(base).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "new-service";
    if (!/^[a-z]/.test(key)) key = `service-${key}`;
    key = key.slice(0, 52);
    let candidate = key;
    let number = 2;
    while (used.has(candidate)) candidate = `${key}-${number++}`;
    return candidate;
  }

  function cloneState(source, key, title) {
    return {
      ...JSON.parse(JSON.stringify(source)),
      key,
      title,
    };
  }

  async function handleSmartAction(action, data) {
    const components = serviceComponents();
    const component = currentSmartComponent();
    if (!component) return;
    const parent = component.parent();
    const index = components.indexOf(component);

    if (action === "up" && index > 0) {
      component.move(parent, { at: index - 1 });
    } else if (action === "down" && index < components.length - 1) {
      component.move(parent, { at: index + 1 });
    } else if (action === "duplicate" || action === "add") {
      const source = ensureSmartState(component);
      const key = uniqueServiceKey(action === "add" ? "new-service" : `${source.key}-copy`);
      const title = action === "add" ? "New Service" : `${source.title} Copy`;
      const clone = component.clone();
      clone.addAttributes({ "data-service": key, "aria-label": `View ${title} details` });
      setComponentText(clone, "h3", title);
      if (action === "add") {
        setComponentText(clone, "p", "Describe this new service.");
        setComponentText(clone, ".service-detail-link", "View service details →");
      }
      parent.append(clone, { at: index + 1 });
      const newState = cloneState(source, key, title);
      if (action === "add") {
        newState.cardDescription = "Describe this new service.";
        newState.detailSummary = "Describe the service and who it supports.";
        newState.detailSectionOneText = "Explain what happens in this service.";
        newState.detailSectionTwoBullets = ["Add the first example", "Add the second example"];
        newState.detailSectionThreeText = "Explain the result the client receives.";
      }
      smartServiceState.set(key, newState);
      selectedSmartServiceKey = key;
      editor.select(clone);
    } else if (action === "delete") {
      if (components.length <= 1) {
        await siawAlert("At least one service must remain.");
        return;
      }
      const confirmed = await siawConfirm(`Delete ${componentText(component, "h3") || "this service"}?`, {
        danger: true,
        confirmLabel: "Delete",
        title: "Delete service",
      });
      if (!confirmed) return;
      const next = components[index + 1] || components[index - 1];
      smartServiceState.delete(serviceKey(component));
      component.remove();
      selectedSmartServiceKey = serviceKey(next);
      if (next) editor.select(next);
    }
    markDirty();
    window.setTimeout(() => renderSmartManager(data), 50);
  }

  function collectSmartServices() {
    if (!smartServiceAvailable) return null;
    return serviceComponents().map((component) => {
      const state = ensureSmartState(component);
      state.title = componentText(component, "h3") || state.title;
      state.cardDescription = componentText(component, "p");
      state.buttonText = componentText(component, ".service-detail-link") || state.buttonText;
      state.image = componentImage(component) || state.image;
      return { ...state, detailSectionTwoBullets: [...(state.detailSectionTwoBullets || [])] };
    });
  }

  function registerCapturedBlock(component) {
    if (!editor || !component?.html) return;
    const blockId = `captured-${String(component.id || Date.now()).replace(/[^a-z0-9_-]/gi, "-")}`;
    if (editor.BlockManager.get(blockId)) return;
    editor.BlockManager.add(blockId, {
      label: blockLabel("◫", component.name || "Captured component"),
      category: "Captured",
      content: component.html,
      attributes: {title: component.selector || component.name || "Captured component"},
    });
  }

  function renderCaptureManager() {
    if (!captureManager) return;
    const navigationCount = runtimeSnapshot?.navigation?.reduce((total, item) => total + (item.items?.length || 0), 0) || 0;
    const dynamicCount = runtimeSnapshot?.dynamicRegions?.length || 0;
    const cards = capturedComponents.length
      ? capturedComponents.map((component, index) => `
        <div class="capture-card">
          <div class="capture-card-head"><strong>${escapeHtml(component.name || "Captured component")}</strong><code>${escapeHtml(component.selector || component.tag || "element")}</code></div>
          <p>${escapeHtml(component.text || "Dynamic website component captured from Interactive mode.")}</p>
          <div class="capture-card-actions">
            <button type="button" data-capture-action="insert" data-capture-index="${index}">Insert static copy</button>
            <button type="button" data-capture-action="block" data-capture-index="${index}">Add to Blocks</button>
            <button type="button" data-capture-action="remove" data-capture-index="${index}" class="danger">Remove</button>
          </div>
        </div>`).join("")
      : '<div class="smart-empty"><strong>No components captured yet.</strong><br><br>Open Interactive mode, click <strong>Capture component</strong>, then click the menu, review, carousel, card or application region you want to collect.</div>';

    const spaDetected = Boolean(loadedData?.compatibility?.spaShell?.isSpaShell);
    captureManager.innerHTML = `
      <div class="capture-summary">
        <strong>${spaDetected ? "SPA / JS app capture" : runtimeSnapshot ? "Interactive page detected" : "Waiting for Interactive mode"}</strong>
        <span>${
          spaDetected
            ? "This project looks like a JavaScript app. Navigate in Interactive mode, then capture the rendered page for Safe Edit."
            : runtimeSnapshot
              ? `${navigationCount} menu items and ${dynamicCount} dynamic regions found.`
              : "The capture bridge will analyse the running website after Interactive mode opens."
        }</span>
      </div>
      <button type="button" id="capturePanelRoute" class="capture-panel-start">Capture this page as editable HTML</button>
      <button type="button" id="capturePanelStart" class="capture-panel-start capture-panel-start-secondary">${captureWaiting ? "Click a component in the website…" : "Start component capture"}</button>
      <div class="capture-warning"><strong>Static-copy safety</strong><span>A captured page or component becomes editable HTML. The original JavaScript router is not rewritten automatically.</span></div>
      <div class="capture-list">${cards}</div>
    `;
    captureManager.querySelector("#capturePanelRoute")?.addEventListener("click", startRouteCapture);
    captureManager.querySelector("#capturePanelStart")?.addEventListener("click", startInteractiveCapture);
    captureManager.querySelectorAll("[data-capture-action]").forEach((button) => {
      button.addEventListener("click", async () => {
        const index = Number(button.dataset.captureIndex);
        const component = capturedComponents[index];
        if (!component) return;
        if (button.dataset.captureAction === "insert") {
          setEditorMode("safe");
          const added = editor.addComponents(component.html);
          const selected = Array.isArray(added) ? added[0] : added;
          if (selected) {
            editor.select(selected);
            selected.getEl()?.scrollIntoView({behavior: "smooth", block: "center"});
          }
          markDirty();
        } else if (button.dataset.captureAction === "block") {
          registerCapturedBlock(component);
          await siawAlert("The captured component is now available in the left Blocks panel under Captured.");
        } else if (button.dataset.captureAction === "remove") {
          capturedComponents.splice(index, 1);
          markDirty();
          renderCaptureManager();
        }
      });
    });
  }

  function startInteractiveCapture() {
    setEditorMode("interactive");
    captureWaiting = true;
    renderCaptureManager();
    const request = () => interactiveFrame?.contentWindow?.postMessage({type: "siaw:capture:start", projectId: config.projectId}, "*");
    if (interactiveFrame?.contentWindow) window.setTimeout(request, 250);
  }

  function startRouteCapture() {
    setEditorMode("interactive");
    setStatus("Capturing rendered page…", "saving");
    const request = () => interactiveFrame?.contentWindow?.postMessage({type: "siaw:route:capture", projectId: config.projectId}, "*");
    if (interactiveFrame?.contentWindow) {
      window.setTimeout(request, interactiveFrame.src ? 250 : 900);
    } else {
      window.setTimeout(request, 900);
    }
  }

  async function persistCapturedRoute(page) {
    if (!page?.html) {
      await siawAlert("No rendered page HTML was returned.");
      return;
    }
    if ((page.textLength || 0) < 40) {
      const proceed = await siawConfirm(
        "This route still looks almost empty. Wait for the app to finish rendering, then try again.\n\nSave the snapshot anyway?",
      );
      if (!proceed) {
        setStatus("Capture cancelled", "error");
        return;
      }
    }
    try {
      const response = await fetch(config.captureRouteUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: JSON.stringify({
          html: page.html,
          routeUrl: page.routeUrl || "",
          title: page.title || "",
          setAsEntry: true,
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not save the captured page.");
      setStatus("Page captured", "saved");
      await siawAlert(`${result.message || "Captured page saved."}\n\nSafe Edit will now open the static snapshot.`);
      window.location.reload();
    } catch (error) {
      console.error(error);
      setStatus("Capture failed", "error");
      await siawAlert(error.message || "Could not save the captured page.");
    }
  }

  function handleRuntimeMessage(event) {
    const data = event.data || {};
    if (String(data.projectId || "") !== String(config.projectId)) return;
    if (data.type === "siaw:runtime:snapshot") {
      runtimeSnapshot = data;
      renderCaptureManager();
    } else if (data.type === "siaw:capture:ready") {
      captureWaiting = true;
      renderCaptureManager();
    } else if (data.type === "siaw:capture:stopped") {
      captureWaiting = false;
      renderCaptureManager();
    } else if (data.type === "siaw:capture:result" && data.component?.html) {
      captureWaiting = false;
      const component = {...data.component};
      capturedComponents.unshift(component);
      capturedComponents = capturedComponents.slice(0, 30);
      registerCapturedBlock(component);
      renderCaptureManager();
      const captureTab = document.querySelector('.right-tab[data-target="capturePanel"]');
      captureTab?.click();
      markDirty();
    } else if (data.type === "siaw:route:capture:result" && data.page) {
      void persistCapturedRoute(data.page);
    }
  }

  function projectDataForSave() {
    const data = editor.getProjectData();
    data.siawCaptures = capturedComponents;
    return data;
  }

  async function uploadAssets(event) {
    const files = Array.from(event.dataTransfer?.files || event.target?.files || []);
    if (!files.length) return [];

    const uploadedAll = [];
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(config.assetUploadUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken() },
        body: form,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Image upload failed.");
      const uploaded = (result.data || []).map((item) => ({
        ...item,
        src: toEditorAssetUrl(item.src || item.relativePath || ""),
        type: "image",
      }));
      editor?.AssetManager?.add?.(uploaded);
      if (loadedData) {
        loadedData.assets = [...(loadedData.assets || []), ...uploaded];
      }
      uploadedAll.push(...uploaded);
    }
    return uploadedAll;
  }

  function applyUploadedSrcToPendingOrSelected(src) {
    const absolute = toEditorAssetUrl(src);
    if (!absolute) return false;
    if (pendingSlideshowAction?.type === "add") {
      pendingSlideshowAction = null;
      addHeroSlide(absolute);
      return true;
    }
    if (pendingSlideshowAction?.type === "swap") {
      const image = pendingSlideshowAction.image;
      const slide = pendingSlideshowAction.slide;
      pendingSlideshowAction = null;
      if (image) image.addAttributes({ src: absolute });
      markDirty();
      if (slide) renderSlideshowManager(slide);
      else if (image) renderSlideshowManager(image);
      return true;
    }
    const selected = editor?.getSelected?.();
    if (selected?.get?.("type") === "image") {
      selected.addAttributes({ src: absolute });
      markDirty();
      const context = findHeroCarouselContext(selected);
      if (context) renderSlideshowManager(context.slide || selected);
      return true;
    }
    return false;
  }

  function bindAssetManagerOverride() {
    if (!editor?.AssetManager || editor.__siawAmOverrideBound) return;
    editor.__siawAmOverrideBound = true;
    const am = editor.AssetManager;
    const nativeOpen = typeof am.open === "function" ? am.open.bind(am) : null;
    am.open = (options = {}) => {
      // Keep GrapesJS from showing its own broken selector; always use ours.
      const selectCb = typeof options.select === "function" ? options.select : null;
      const selected = options.target || editor.getSelected?.();
      openImageAssetPicker({
        title: "Select image",
        onSelect: (src) => {
          const absolute = toEditorAssetUrl(src);
          if (!absolute) return;
          if (selectCb) {
            selectCb(
              {
                getSrc: () => absolute,
                get: (key) => (key === "src" ? absolute : ""),
              },
              true,
            );
            return;
          }
          if (applyUploadedSrcToPendingOrSelected(absolute)) return;
          if (selected?.get?.("type") === "image") {
            selected.addAttributes({ src: absolute });
            markDirty();
          }
        },
      });
    };
    // Retain a hidden escape hatch for debugging if needed.
    am.__siawNativeOpen = nativeOpen;
  }

  let codeMode = config.editorMode === "code";
  let activeSourcePath = config.entryFile || "";
  let codeEditorReady = false;
  const codeEditorShell = document.getElementById("codeEditorShell");
  const codeEditor = document.getElementById("codeEditor");
  const codeEditorPath = document.getElementById("codeEditorPath");
  const fileTree = document.getElementById("fileTree");

  function sourceFileUrl(path) {
    return config.sourceFileUrlTemplate.replace(
      "__SIAW_PATH__",
      String(path).split("/").map(encodeURIComponent).join("/"),
    );
  }

  function isHtmlPath(path) {
    return /\.(html|htm|xhtml|shtml)$/i.test(path || "");
  }

  function renderFileTree(files, activePath) {
    if (!fileTree) return;
    if (!files.length) {
      fileTree.innerHTML = `<div class="smart-loading">No editable files found.</div>`;
      return;
    }
    fileTree.innerHTML = "";
    files.forEach((path) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "file-tree-item";
      if (path === activePath) button.classList.add("is-active");
      if (path === (loadedData?.entryFile || config.entryFile)) button.classList.add("is-entry");
      button.textContent = path;
      button.addEventListener("click", () => {
        void openProjectFile(path);
      });
      fileTree.appendChild(button);
    });
  }

  function showCodeEditor(path, content) {
    codeMode = true;
    activeSourcePath = path;
    canvasArea?.classList.add("is-code");
    if (codeEditorShell) codeEditorShell.hidden = false;
    if (codeEditorPath) codeEditorPath.textContent = path;
    if (codeEditor) codeEditor.value = content;
    const titleSmall = document.querySelector(".project-title small");
    if (titleSmall) titleSmall.textContent = path;
    renderFileTree(loadedData?.files || [], path);
  }

  function showVisualEditorShell() {
    codeMode = false;
    canvasArea?.classList.remove("is-code");
    if (codeEditorShell) codeEditorShell.hidden = true;
  }

  async function openProjectFile(path) {
    if (dirty) {
      const saved = await saveProject({ silent: true });
      if (!saved) return;
    }
    if (isHtmlPath(path) && path !== (loadedData?.entryFile || config.entryFile)) {
      const response = await fetch(config.setEntryUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: JSON.stringify({ entryFile: path }),
      });
      const result = await response.json();
      if (!response.ok) {
        await siawAlert(result.error || "Could not open that HTML file.");
        return;
      }
      window.location.reload();
      return;
    }
    if (isHtmlPath(path) && !codeMode && editor) {
      activeSourcePath = path;
      renderFileTree(loadedData?.files || [], path);
      window.siawEditorLayout?.closeMobileDrawers?.();
      return;
    }
    const response = await fetch(sourceFileUrl(path), { headers: { Accept: "application/json" } });
    const result = await response.json();
    if (!response.ok) {
      await siawAlert(result.error || "Could not open that file.");
      return;
    }
    showCodeEditor(path, result.content || "");
    dirty = false;
    codeEditorReady = true;
    editorReady = true;
    window.siawEditorLayout?.closeMobileDrawers?.();
    setStatus("All changes saved", "saved");
  }

  async function saveProject({ silent = false, force = false } = {}) {
    if (codeMode) {
      if (!codeEditorReady && !codeEditor) return false;
      if (savingPromise) return savingPromise;
      if (!dirty && silent && !force) return true;
      clearTimeout(autosaveTimer);
      setStatus("Saving…", "saving");
      saveBtn.disabled = true;
      savingPromise = (async () => {
        try {
          const response = await fetch(config.saveUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": csrfToken(),
            },
            body: JSON.stringify({
              mode: "code",
              path: activeSourcePath,
              content: codeEditor?.value || "",
            }),
          });
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || "The file could not be saved.");
          dirty = false;
          setStatus("Saved", "saved");
          window.setTimeout(() => {
            if (!dirty) setStatus("All changes saved", "saved");
          }, 1200);
          return true;
        } catch (error) {
          console.error(error);
          setStatus("Save failed", "error");
          if (!silent) await siawAlert(error.message);
          return false;
        } finally {
          saveBtn.disabled = false;
          savingPromise = null;
        }
      })();
      return savingPromise;
    }

    if (!editor || !editorReady) return false;
    if (savingPromise) return savingPromise;
    if (!dirty && silent && !force) return true;

    clearTimeout(autosaveTimer);
    setStatus("Saving…", "saving");
    saveBtn.disabled = true;

    savingPromise = (async () => {
      try {
        const slideshowPhotos = collectHeroSlideshowForSave();
        const response = await fetch(config.saveUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken(),
          },
          body: JSON.stringify({
            html: editor.getHtml(),
            css: withResponsiveVisibilityCss(editor.getCss()),
            projectData: projectDataForSave(),
            smartServices: collectSmartServices(),
            smartNavigation: collectSmartNavigation(),
            slideshowPhotos,
          }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "The project could not be saved.");
        dirty = false;
        editor.clearDirtyCount();
        if (loadedData) {
          loadedData.heroCarouselPhotos = slideshowPhotos;
        }
        const synced = Array.isArray(result.synced) ? result.synced : [];
        const slideshowSynced = synced.some((item) => String(item).toLowerCase().includes("slideshow"));
        setStatus(
          slideshowSynced
            ? `Saved slideshow (${slideshowPhotos.length} slides)`
            : (synced.length ? "Saved + smart components synced" : "Saved"),
          "saved",
        );
        window.setTimeout(() => {
          if (!dirty) setStatus("All changes saved", "saved");
        }, synced.length ? 2200 : 1200);
        return true;
      } catch (error) {
        console.error(error);
        setStatus("Save failed", "error");
        if (!silent) await siawAlert(error.message);
        return false;
      } finally {
        saveBtn.disabled = false;
        savingPromise = null;
      }
    })();

    return savingPromise;
  }

  function isMobileLayout() {
    return window.matchMedia("(max-width: 1024px)").matches;
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  let panelChromeReady = false;

  function closeMobileDrawers() {
    document.body.classList.remove("mobile-left-open", "mobile-right-open");
    const backdrop = document.getElementById("panelBackdrop");
    if (backdrop) backdrop.hidden = true;
    document.querySelectorAll("#mobileDock [data-mobile-view]").forEach((button) => {
      const active = button.dataset.mobileView === "canvas";
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function openMobilePanel(side) {
    document.body.classList.add("mobile-layout");
    const backdrop = document.getElementById("panelBackdrop");
    if (side === "left") {
      document.body.classList.add("mobile-left-open");
      document.body.classList.remove("mobile-right-open");
      document.querySelectorAll("#mobileDock [data-mobile-view]").forEach((button) => {
        const active = button.dataset.mobileView === "files";
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
    } else {
      document.body.classList.add("mobile-right-open");
      document.body.classList.remove("mobile-left-open");
      document.querySelectorAll("#mobileDock [data-mobile-view]").forEach((button) => {
        const active = button.dataset.mobileView === "inspect";
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
    }
    if (backdrop) backdrop.hidden = false;
    const shell = document.getElementById("editorShell");
    if (side === "left") shell?.classList.remove("left-collapsed");
    else shell?.classList.remove("right-collapsed");
    window.requestAnimationFrame(() => {
      try { editor?.refresh?.(); } catch (_error) { /* ignore */ }
    });
  }

  function initPanelChrome() {
    const shell = document.getElementById("editorShell");
    const root = document.documentElement;
    const backdrop = document.getElementById("panelBackdrop");
    const mobileDock = document.getElementById("mobileDock");
    const leftResizer = document.getElementById("leftResizer");
    const rightResizer = document.getElementById("rightResizer");
    const expandLeftBtn = document.getElementById("expandLeftBtn");
    const expandRightBtn = document.getElementById("expandRightBtn");
    const toggleLeftPanelBtn = document.getElementById("toggleLeftPanelBtn");
    const toggleRightPanelBtn = document.getElementById("toggleRightPanelBtn");
    if (!shell || panelChromeReady) {
      if (shell) {
        document.body.classList.toggle("mobile-layout", isMobileLayout());
        root.classList.toggle("is-mobile-editor", isMobileLayout());
      }
      return;
    }
    panelChromeReady = true;

    const storageKey = "siaw-editor-layout-v1";
    const defaults = { leftWidth: 244, rightWidth: 284, leftCollapsed: false, rightCollapsed: false };
    let layout = { ...defaults };
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (saved && typeof saved === "object") layout = { ...defaults, ...saved };
    } catch (_error) {
      layout = { ...defaults };
    }

    let resizeState = null;

    function persist() {
      try {
        localStorage.setItem(storageKey, JSON.stringify(layout));
      } catch (_error) {
        /* ignore quota / private mode */
      }
    }

    function refreshEditorCanvas() {
      window.requestAnimationFrame(() => {
        try {
          editor?.refresh?.();
        } catch (_error) {
          /* editor may not be ready */
        }
      });
    }

    function applyDesktopWidths() {
      root.style.setProperty("--left-panel-w", `${layout.leftWidth}px`);
      root.style.setProperty("--right-panel-w", `${layout.rightWidth}px`);
    }

    function syncCollapseClasses() {
      shell.classList.toggle("left-collapsed", !!layout.leftCollapsed);
      shell.classList.toggle("right-collapsed", !!layout.rightCollapsed);
      toggleLeftPanelBtn?.setAttribute("aria-pressed", layout.leftCollapsed ? "false" : "true");
      toggleRightPanelBtn?.setAttribute("aria-pressed", layout.rightCollapsed ? "false" : "true");
    }

    function setMobileDockActive(view) {
      mobileDock?.querySelectorAll("[data-mobile-view]").forEach((button) => {
        const active = button.dataset.mobileView === view;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
    }

    function applyLayoutMode() {
      const mobile = isMobileLayout();
      document.body.classList.toggle("mobile-layout", mobile);
      root.classList.toggle("is-mobile-editor", mobile);
      applyDesktopWidths();
      if (mobile) {
        shell.classList.remove("left-collapsed", "right-collapsed");
        if (!document.body.classList.contains("mobile-left-open") && !document.body.classList.contains("mobile-right-open")) {
          if (backdrop) backdrop.hidden = true;
          setMobileDockActive("canvas");
        }
      } else {
        document.body.classList.remove("mobile-left-open", "mobile-right-open");
        if (backdrop) backdrop.hidden = true;
        syncCollapseClasses();
      }
      refreshEditorCanvas();
    }

    function setCollapsed(side, collapsed) {
      if (side === "left") layout.leftCollapsed = collapsed;
      else layout.rightCollapsed = collapsed;
      persist();
      if (isMobileLayout()) {
        if (collapsed) closeMobileDrawers();
        else openMobilePanel(side);
        return;
      }
      syncCollapseClasses();
      refreshEditorCanvas();
    }

    function togglePanel(side) {
      if (isMobileLayout()) {
        const openClass = side === "left" ? "mobile-left-open" : "mobile-right-open";
        if (document.body.classList.contains(openClass)) closeMobileDrawers();
        else openMobilePanel(side);
        return;
      }
      const collapsed = side === "left" ? layout.leftCollapsed : layout.rightCollapsed;
      setCollapsed(side, !collapsed);
    }

    window.siawEditorLayout = {
      closeMobileDrawers,
      openMobilePanel,
      isMobileLayout,
      markSaveDirty(isDirty) {
        mobileDock?.querySelector(".mobile-dock-save")?.classList.toggle("is-dirty", !!isDirty);
      },
    };

    document.querySelectorAll("[data-collapse]").forEach((button) => {
      button.addEventListener("click", () => {
        const side = button.dataset.collapse === "right" ? "right" : "left";
        if (isMobileLayout()) closeMobileDrawers();
        else setCollapsed(side, true);
      });
    });

    expandLeftBtn?.addEventListener("click", () => setCollapsed("left", false));
    expandRightBtn?.addEventListener("click", () => setCollapsed("right", false));
    toggleLeftPanelBtn?.addEventListener("click", () => togglePanel("left"));
    toggleRightPanelBtn?.addEventListener("click", () => togglePanel("right"));
    backdrop?.addEventListener("click", () => closeMobileDrawers());

    mobileDock?.querySelectorAll("[data-mobile-view]").forEach((button) => {
      button.addEventListener("click", () => {
        const view = button.dataset.mobileView;
        if (view === "save") {
          if (typeof saveProject === "function") void saveProject();
          return;
        }
        if (view === "files") {
          openMobilePanel("left");
          return;
        }
        if (view === "inspect") {
          openMobilePanel("right");
          return;
        }
        closeMobileDrawers();
      });
    });

    function startResize(side, event) {
      if (isMobileLayout()) return;
      event.preventDefault();
      const startX = event.clientX ?? event.touches?.[0]?.clientX;
      if (typeof startX !== "number") return;
      resizeState = {
        side,
        startX,
        startWidth: side === "left" ? layout.leftWidth : layout.rightWidth,
      };
      shell.classList.add("is-resizing");
      const handle = side === "left" ? leftResizer : rightResizer;
      handle?.setAttribute("data-active", "true");
    }

    function onResizeMove(event) {
      if (!resizeState) return;
      const clientX = event.clientX ?? event.touches?.[0]?.clientX;
      if (typeof clientX !== "number") return;
      const delta = clientX - resizeState.startX;
      if (resizeState.side === "left") {
        layout.leftWidth = clamp(resizeState.startWidth + delta, 180, 480);
      } else {
        layout.rightWidth = clamp(resizeState.startWidth - delta, 200, 520);
      }
      applyDesktopWidths();
      refreshEditorCanvas();
    }

    function stopResize() {
      if (!resizeState) return;
      resizeState = null;
      shell.classList.remove("is-resizing");
      leftResizer?.removeAttribute("data-active");
      rightResizer?.removeAttribute("data-active");
      persist();
      refreshEditorCanvas();
    }

    leftResizer?.addEventListener("pointerdown", (event) => startResize("left", event));
    rightResizer?.addEventListener("pointerdown", (event) => startResize("right", event));
    window.addEventListener("pointermove", onResizeMove);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);

    [leftResizer, rightResizer].forEach((handle) => {
      handle?.addEventListener("keydown", (event) => {
        if (isMobileLayout()) return;
        const side = handle.dataset.resize === "right" ? "right" : "left";
        const step = event.shiftKey ? 32 : 12;
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          if (side === "left") layout.leftWidth = clamp(layout.leftWidth - step, 180, 480);
          else layout.rightWidth = clamp(layout.rightWidth + step, 200, 520);
          applyDesktopWidths();
          persist();
          refreshEditorCanvas();
        }
        if (event.key === "ArrowRight") {
          event.preventDefault();
          if (side === "left") layout.leftWidth = clamp(layout.leftWidth + step, 180, 480);
          else layout.rightWidth = clamp(layout.rightWidth - step, 200, 520);
          applyDesktopWidths();
          persist();
          refreshEditorCanvas();
        }
      });
    });

    window.addEventListener("resize", () => {
      applyLayoutMode();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && isMobileLayout()) closeMobileDrawers();
    });

    applyLayoutMode();
  }

  function bindInterface() {
    initPanelChrome();

    document.querySelectorAll(".panel-tab").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".panel-tab").forEach((item) => item.classList.remove("active"));
        document.querySelectorAll(".panel-content").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
        document.getElementById(button.dataset.target).classList.add("active");
        if (isMobileLayout()) openMobilePanel("left");
      });
    });

    document.querySelectorAll(".right-tab").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".right-tab").forEach((item) => item.classList.remove("active"));
        document.querySelectorAll(".right-content").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
        document.getElementById(button.dataset.target).classList.add("active");
        if (isMobileLayout()) openMobilePanel("right");
      });
    });

    safeModeBtn?.addEventListener("click", () => setEditorMode("safe"));
    interactiveModeBtn?.addEventListener("click", () => setEditorMode("interactive"));
    safeEditShellInteractive?.addEventListener("click", () => setEditorMode("interactive"));
    safeEditShellCapture?.addEventListener("click", startRouteCapture);
    captureStartBtn?.addEventListener("click", startInteractiveCapture);
    captureRouteBtn?.addEventListener("click", startRouteCapture);
    interactiveFrame?.addEventListener("load", () => {
      window.setTimeout(() => interactiveFrame.contentWindow?.postMessage({type: "siaw:runtime:snapshot:request", projectId: config.projectId}, "*"), 350);
      if (captureWaiting) window.setTimeout(() => interactiveFrame.contentWindow?.postMessage({type: "siaw:capture:start", projectId: config.projectId}, "*"), 450);
    });
    window.addEventListener("message", handleRuntimeMessage);

    document.querySelectorAll(".device-btn").forEach((button) => {
      button.addEventListener("click", () => {
        currentDevice = button.dataset.device || "Desktop";
        editor.setDevice(currentDevice);
        applyInteractiveDevice();
        document.querySelectorAll(".device-btn").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
        const selected = editor.getSelected?.();
        if (selected) renderResponsiveManager(selected);
      });
    });

    document.getElementById("undoBtn").addEventListener("click", () => editor.UndoManager.undo());
    document.getElementById("redoBtn").addEventListener("click", () => editor.UndoManager.redo());
    saveBtn.addEventListener("click", () => saveProject());

    previewBtn.addEventListener("click", async (event) => {
      event.preventDefault();
      const previewWindow = window.open("about:blank", "_blank");
      const saved = await saveProject();
      if (saved) {
        if (previewWindow) previewWindow.location = config.previewUrl;
        else window.open(config.previewUrl, "_blank");
      } else if (previewWindow) {
        previewWindow.close();
      }
    });

    exportBtn.addEventListener("click", async (event) => {
      event.preventDefault();
      await exportWithValidation();
    });

    assetUploadInput?.addEventListener("change", async (event) => {
      try {
        await uploadAssets(event);
        await refreshTreeManagers();
        setStatus("Image uploaded", "saved");
      } catch (error) {
        await siawAlert(error.message);
      } finally {
        event.target.value = "";
      }
    });

    notice.querySelector("button").addEventListener("click", () => notice.classList.add("hidden"));

    document.getElementById("restoreForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const confirmed = await siawConfirm(
        "Restore the original uploaded website? All visual-editor changes will be removed.",
        { danger: true, confirmLabel: "Restore", title: "Restore original" },
      );
      if (confirmed) event.target.submit();
    });

    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveProject();
      }
    });

    window.addEventListener("beforeunload", (event) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    });
  }

  const jsBuildOverlay = document.getElementById("jsBuildOverlay");
  const jsBuildTitle = document.getElementById("jsBuildTitle");
  const jsBuildMessage = document.getElementById("jsBuildMessage");
  const jsBuildLog = document.getElementById("jsBuildLog");
  const jsBuildRetry = document.getElementById("jsBuildRetry");
  const jsBuildSkip = document.getElementById("jsBuildSkip");
  const jsBuildProgress = document.getElementById("jsBuildProgress");
  const jsBuildProgressBar = document.getElementById("jsBuildProgressBar");
  const jsBuildProgressTrack = document.getElementById("jsBuildProgressTrack");
  const jsBuildPercent = document.getElementById("jsBuildPercent");
  const jsBuildPhase = document.getElementById("jsBuildPhase");
  let jsBuildPollTimer = null;
  let jsBuildSkipped = false;
  let jsBuildShownProgress = 0;

  const JS_BUILD_PHASE_LABELS = {
    pending: "Ready",
    queued: "Queued",
    install: "Installing",
    build: "Building",
    export: "Exporting",
    finalize: "Finalizing",
    done: "Complete",
  };

  function estimateJsBuildProgress(status) {
    if (typeof status?.progress === "number" && Number.isFinite(status.progress)) {
      return Math.max(0, Math.min(100, Math.round(status.progress)));
    }
    const state = status?.status || "idle";
    if (state === "succeeded") return 100;
    if (state === "failed") return Math.max(jsBuildShownProgress, 1);
    if (state === "pending") return 0;
    const message = String(status?.message || "").toLowerCase();
    if (message.includes("queued")) return 2;
    if (message.includes("install")) return Math.max(jsBuildShownProgress, 10);
    if (message.includes("build")) return Math.max(jsBuildShownProgress, 65);
    if (message.includes("export") || message.includes("locat")) return Math.max(jsBuildShownProgress, 93);
    return Math.max(jsBuildShownProgress, 5);
  }

  function renderJsBuildProgress(status) {
    if (!jsBuildProgress) return;
    const state = status?.status || "idle";
    const active = state === "running" || state === "pending" || state === "failed" || state === "succeeded";
    jsBuildProgress.hidden = !active;
    if (!active) return;

    let next = estimateJsBuildProgress(status);
    // Never let the bar jump backwards while still running.
    if (state === "running" || state === "pending") {
      next = Math.max(jsBuildShownProgress, next);
    }
    if (state === "succeeded") next = 100;
    jsBuildShownProgress = next;

    if (jsBuildProgressBar) jsBuildProgressBar.style.width = `${next}%`;
    if (jsBuildPercent) jsBuildPercent.textContent = `${next}%`;
    if (jsBuildProgressTrack) jsBuildProgressTrack.setAttribute("aria-valuenow", String(next));
    if (jsBuildPhase) {
      const phaseKey = String(status?.phase || "").toLowerCase();
      jsBuildPhase.textContent = JS_BUILD_PHASE_LABELS[phaseKey]
        || (state === "failed" ? "Failed" : state === "succeeded" ? "Complete" : "Working");
    }
  }

  function renderJsBuildStatus(status) {
    if (!jsBuildOverlay) return;
    const state = status?.status || "idle";
    const needsBuild = Boolean(status?.needsBuild);
    if (jsBuildSkipped || (!needsBuild && state !== "running" && state !== "pending" && state !== "failed")) {
      jsBuildOverlay.hidden = true;
      return;
    }
    jsBuildOverlay.hidden = false;
    if (jsBuildTitle) {
      jsBuildTitle.textContent = state === "failed"
        ? "Build failed"
        : state === "succeeded"
          ? "Build complete"
          : "Building project visuals";
    }
    if (jsBuildMessage) {
      jsBuildMessage.textContent = status?.message
        || (status?.framework ? `Detected ${status.framework}. Installing and building…` : "Installing dependencies and building…");
    }
    renderJsBuildProgress(status);
    if (jsBuildLog) {
      if (status?.logTail) {
        jsBuildLog.hidden = false;
        jsBuildLog.textContent = status.logTail;
        jsBuildLog.scrollTop = jsBuildLog.scrollHeight;
      } else {
        jsBuildLog.hidden = true;
        jsBuildLog.textContent = "";
      }
    }
    if (jsBuildRetry) jsBuildRetry.hidden = state !== "failed";
    if (jsBuildSkip) jsBuildSkip.hidden = !(state === "failed" || state === "pending" || state === "running");
  }

  async function pollJsBuildStatus() {
    if (!config.buildStatusUrl) return null;
    const response = await fetch(config.buildStatusUrl, { headers: { Accept: "application/json" } });
    const status = await response.json();
    if (!response.ok) throw new Error(status.error || "Could not read build status.");
    renderJsBuildStatus(status);
    return status;
  }

  function looksLikeMissingHtmlButSsrBuild(status) {
    const message = String(status?.message || "").toLowerCase();
    const log = String(status?.logTail || "").toLowerCase();
    return (
      message.includes("no html was found")
      || log.includes("dist/nitro.json")
      || log.includes("[nitro]")
      || log.includes("npx vite preview")
    );
  }

  async function startJsBuildAndWait(options = {}) {
    if (!config.buildStartUrl) return null;
    const preferReuse = Boolean(options.reuseExisting);
    setStatus(preferReuse ? "Starting SSR preview…" : "Building JS project…", "saving");
    jsBuildShownProgress = preferReuse ? 90 : 0;
    renderJsBuildStatus({
      ...(config.jsBuild || {}),
      status: "running",
      needsBuild: true,
      progress: preferReuse ? 90 : 2,
      phase: preferReuse ? "preview" : "queued",
      message: preferReuse ? "Starting SSR preview from existing build… 90%" : "Build queued… 2%",
    });

    async function postStart(reuseExisting) {
      const startResponse = await fetch(config.buildStartUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: JSON.stringify({ reuseExisting: Boolean(reuseExisting) }),
      });
      const status = await startResponse.json();
      if (!startResponse.ok) throw new Error(status.error || "Could not start build.");
      return status;
    }

    let status = await postStart(preferReuse);
    // If a previous Nitro build failed only because HTML was missing, reuse dist/server.
    if (
      !preferReuse
      && status.status === "failed"
      && looksLikeMissingHtmlButSsrBuild(status)
    ) {
      status = await postStart(true);
    }
    renderJsBuildStatus(status);

    while (status.status === "running" || status.status === "pending") {
      await new Promise((resolve) => {
        jsBuildPollTimer = window.setTimeout(resolve, 800);
      });
      status = await pollJsBuildStatus();
    }

    if (status.status === "succeeded") {
      setStatus(status.previewMode === "ssr" ? "SSR preview ready" : "Build succeeded", "saved");
      // Vite/JS/SSR builds open as a live website preview (not empty-shell Safe Edit).
      window.location.href = config.previewUrl || window.location.href;
      return status;
    }
    if (status.status === "failed") {
      // One more recovery attempt for older failed Nitro imports.
      if (!preferReuse && looksLikeMissingHtmlButSsrBuild(status)) {
        return startJsBuildAndWait({ reuseExisting: true });
      }
      setStatus("Build failed", "error");
    }
    return status;
  }

  async function ensureJsBuildReady() {
    const initial = config.jsBuild || {};
    if (jsBuildSkipped) return true;
    if (!initial.needsBuild && initial.status !== "pending" && initial.status !== "running") {
      return true;
    }
    renderJsBuildStatus(initial);
    jsBuildRetry?.addEventListener("click", () => {
      void startJsBuildAndWait();
    });
    jsBuildSkip?.addEventListener("click", async () => {
      if (jsBuildPollTimer) window.clearTimeout(jsBuildPollTimer);
      if (config.buildSkipUrl) {
        await fetch(config.buildSkipUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken(),
          },
          body: "{}",
        });
      }
      jsBuildSkipped = true;
      if (jsBuildOverlay) jsBuildOverlay.hidden = true;
      setStatus("Continuing without build", "dirty");
      window.location.reload();
    });
    if (initial.status === "failed") {
      if (looksLikeMissingHtmlButSsrBuild(initial)) {
        await startJsBuildAndWait({ reuseExisting: true });
        return false;
      }
      return false;
    }
    await startJsBuildAndWait();
    return false;
  }

  async function start() {
    initPanelChrome();
    try {
      const buildReady = await ensureJsBuildReady();
      if (!buildReady && !jsBuildSkipped) {
        // Waiting for build reload or user action.
        if ((config.jsBuild || {}).status === "failed") {
          bindInterface();
        }
        return;
      }

      const response = await fetch(config.dataUrl, { headers: { Accept: "application/json" } });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Project data could not be loaded.");
      loadedData = data;
      renderFileTree(Array.isArray(data.files) ? data.files : [], data.entryFile || config.entryFile);
      renderPagesManager(
        data.compatibility?.pages || (data.files || []).filter((item) => isHtmlPath(item)),
        data.entryFile || config.entryFile,
        data.compatibility?.pageDetails,
      );
      void refreshTreeManagers();
      void renderSnapshotsManager();

      if (data.mode === "code" || config.editorMode === "code") {
        showCodeEditor(data.entryFile || config.entryFile, data.content || "");
        codeEditor?.addEventListener("input", () => {
          dirty = true;
          setStatus("Unsaved changes", "dirty");
          clearTimeout(autosaveTimer);
          autosaveTimer = setTimeout(() => saveProject({ silent: true }), 25000);
        });
        bindInterface();
        if (previewBtn && data.canPreview === false) {
          previewBtn.style.opacity = "0.45";
          previewBtn.title = "Live preview needs an HTML entry file.";
        }
        if (safeModeBtn) safeModeBtn.disabled = true;
        if (interactiveModeBtn) interactiveModeBtn.disabled = true;
        codeEditorReady = true;
        editorReady = true;
        dirty = false;
        setStatus("All changes saved", "saved");
        return;
      }

      showVisualEditorShell();
      capturedComponents = Array.isArray(data.projectData?.siawCaptures) ? data.projectData.siawCaptures.slice(0, 30) : [];
      const preferLive = Boolean(
        data.preferLivePreview
        || data.compatibility?.preferLivePreview
        || data.compatibility?.spaShell?.isSpaShell
        || config.preferLivePreview
      );
      const params = new URLSearchParams(window.location.search);
      const requestedMode = (params.get("mode") || config.defaultViewMode || "").toLowerCase();
      const forceSafe = requestedMode === "safe" || params.get("edit") === "1";
      if (preferLive && notice) {
        notice.innerHTML = `<strong>Live website mode:</strong> This entry is a JS/Vite app shell. Interactive mode shows the real site. Use <em>Capture this page</em> before Safe Edit. <a href="${config.previewUrl || "#"}" style="color:inherit;font-weight:700;margin-left:6px">Open full preview</a> <button type="button" aria-label="Close notice">×</button>`;
        notice.classList.remove("hidden");
        notice.querySelector("button")?.addEventListener("click", () => notice.classList.add("hidden"));
      }

      let editorRef = null;
      editor = grapesjs.init({
        container: "#gjs",
        height: "100%",
        width: "auto",
        storageManager: false,
        panels: { defaults: [] },
        blockManager: { appendTo: "#blocks" },
        layerManager: { appendTo: "#layers" },
        traitManager: { appendTo: "#traits" },
        selectorManager: { appendTo: "#selectors", componentFirst: true },
        styleManager: { appendTo: "#styles", sectors: styleSectors() },
        deviceManager: {
          devices: [
            { id: "Desktop", name: "Desktop", width: "" },
            { id: "Tablet", name: "Tablet", width: "768px", widthMedia: "992px" },
            { id: "Mobile", name: "Mobile", width: "390px", widthMedia: "575px" },
          ],
        },
        canvas: {
          styles: (() => {
            const styleUrls = buildCanvasStyles(data);
            data._canvasStyleUrls = styleUrls;
            return styleUrls;
          })(),
          frameStyle: "body{min-height:100vh;} .gjs-selected{outline:2px solid #ff4545!important}",
        },
        assetManager: {
          assets: data.assets,
          multiUpload: true,
          autoAdd: true,
          uploadFile: async (event) => {
            try {
              const uploaded = await uploadAssets(event);
              const first = uploaded?.[0]?.src;
              if (first) applyUploadedSrcToPendingOrSelected(first);
              try { editor.AssetManager.close(); } catch (_error) { /* ignore */ }
            } catch (error) {
              console.error(error);
              await siawAlert(error.message);
            }
          },
        },
        parser: {
          optionsHtml: {
            allowScripts: false,
            allowUnsafeAttr: false,
          },
        },
      });
      editorRef = editor;

      registerProtectedComponents(editor);
      registerLayoutComponents(editor);
      bindAssetManagerOverride();
      bindImageSwapEditing();
      bindEditorShortcuts();
      try {
        const imageType = editor.DomComponents.getType("image");
        const ImageModel = imageType?.model;
        const ImageView = imageType?.view;
        if (ImageModel) {
          const imageTypeConfig = {
            model: ImageModel.extend({
              defaults: {
                ...ImageModel.prototype.defaults,
                traits: [
                  { type: "text", name: "alt", label: "Alt text" },
                  { type: "text", name: "src", label: "Image source" },
                  {
                    type: "button",
                    text: "Swap image…",
                    full: true,
                    command: "open-assets",
                  },
                ],
              },
            }),
          };
          if (ImageView) {
            imageTypeConfig.view = ImageView.extend({
              onActive(ev) {
                if (ev) {
                  ev.preventDefault?.();
                  ev.stopPropagation?.();
                }
                const selected = this.model;
                const context = findHeroCarouselContext(selected);
                pendingSlideshowAction = context
                  ? { type: "swap", image: selected, slide: context.slide }
                  : { type: "swap", image: selected };
                openImageAssetPicker({
                  title: context ? "Swap slideshow image" : "Swap image",
                  onSelect: (src) => {
                    pendingSlideshowAction = null;
                    selected.addAttributes({ src: toEditorAssetUrl(src) });
                    markDirty();
                    if (context) renderSlideshowManager(context.slide || selected);
                  },
                });
              },
            });
          }
          editor.DomComponents.addType("image", imageTypeConfig);
          editor.Commands.add("open-assets", {
            run(ed, _sender, options = {}) {
              const selected = options.target || ed.getSelected?.();
              const context = findHeroCarouselContext(selected);
              pendingSlideshowAction = context
                ? { type: "swap", image: selected, slide: context.slide }
                : (selected?.get?.("type") === "image" ? { type: "swap", image: selected } : null);
              openImageAssetPicker({
                title: context ? "Swap slideshow image" : "Swap image",
                onSelect: (src) => {
                  const absolute = toEditorAssetUrl(src);
                  pendingSlideshowAction = null;
                  if (selected?.get?.("type") === "image") {
                    selected.addAttributes({ src: absolute });
                    markDirty();
                    if (context) renderSlideshowManager(context.slide || selected);
                  }
                },
              });
            },
          });
        }
      } catch (error) {
        console.warn("Could not extend GrapesJS image traits; Content image panel still works.", error);
        editor.Commands.add("open-assets", {
          run(ed, _sender, options = {}) {
            const selected = options.target || ed.getSelected?.();
            pendingSlideshowAction =
              selected?.get?.("type") === "image" ? { type: "swap", image: selected } : null;
            openImageAssetPicker({
              title: "Swap image",
              onSelect: (src) => {
                const absolute = toEditorAssetUrl(src);
                pendingSlideshowAction = null;
                if (selected?.get?.("type") === "image") {
                  selected.addAttributes({ src: absolute });
                  markDirty();
                  renderImageManager(selected);
                }
              },
            });
          },
        });
      }
      registerBlocks(editor, data);
      try {
        editor.BlockManager.getCategories().each((category) => {
          const id = category.get("id") || category.id;
          if (id === "Layout") category.set("open", true);
        });
      } catch (_error) {
        // Categories API differs slightly across GrapesJS builds.
      }

      const canvasReady = new Promise((resolve) => {
        let resolved = false;
        const finish = () => {
          if (resolved) return;
          resolved = true;
          injectCanvasSafety(data);
          resolve();
        };
        editor.on("load", finish);
        window.setTimeout(finish, 300);
      });
      editor.on("canvas:frame:load", () => {
        injectCanvasSafety(data);
        window.setTimeout(() => injectEditorOnlyHelpers(data), 100);
      });
      await canvasReady;

      if (data.projectData) {
        editor.loadProjectData(data.projectData);
      } else {
        editor.setComponents(data.html);
      }
      repairEditorMediaUrls(data);

      // setComponents / loadProjectData can rebuild the canvas frame and drop styles.
      const reapplySiteCss = () => {
        injectCanvasSafety(data);
        injectEditorOnlyHelpers(data);
      };
      window.setTimeout(reapplySiteCss, 50);
      window.setTimeout(reapplySiteCss, 250);
      window.setTimeout(() => {
        reapplySiteCss();
        capturedComponents.forEach(registerCapturedBlock);
        renderSmartManager(data);
        renderCompatibilityReport(data);
        renderCaptureManager();
        renderPagesManager(
          data.compatibility?.pages || [],
          data.entryFile || config.entryFile,
          data.compatibility?.pageDetails,
        );
        void renderSnapshotsManager();
      }, 500);

      editor.on("update", markDirty);
      editor.on("component:selected", (component) => {
        protectedHint.hidden = !componentIsInsideProtected(component);
        renderLinkManager(component);
        renderImageManager(component);
        renderSlideshowManager(component);
        renderResponsiveManager(component);
      });
      editor.on("component:deselected", () => {
        protectedHint.hidden = true;
        renderLinkManager(null);
        renderImageManager(null);
        renderSlideshowManager(null);
        renderResponsiveManager(null);
      });
      editor.on("asset:add", markDirty);
      editor.on("component:update:attributes", (component) => {
        if (!smartServiceAvailable || component?.get?.("type") !== "image") return;
        const card = component.closest ? component.closest(".service-card") : null;
        if (!card) return;
        const key = serviceKey(card);
        const state = smartServiceState.get(key);
        if (state) state.image = componentImage(card);
        const preview = document.getElementById("smartImagePreview");
        if (preview && key === selectedSmartServiceKey) preview.src = state?.image || "";
      });

      bindInterface();
      if (preferLive && !forceSafe) {
        setEditorMode("interactive");
        setStatus("Interactive live preview", "saved");
      } else if (requestedMode === "interactive") {
        setEditorMode("interactive");
      }
      editorReady = true;
      dirty = false;
      editor.clearDirtyCount();
      if (!(preferLive && !forceSafe)) {
        setStatus("All changes saved", "saved");
      }
    } catch (error) {
      console.error(error);
      setStatus("Load failed", "error");
      document.getElementById("gjs").innerHTML = `<div style="padding:30px;font-family:sans-serif;color:#8d2727"><h2>Editor could not load</h2><p>${error.message}</p></div>`;
    }
  }

  start();
})();
