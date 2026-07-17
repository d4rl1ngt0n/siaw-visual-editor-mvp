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
  const safeModeBtn = document.getElementById("safeModeBtn");
  const interactiveModeBtn = document.getElementById("interactiveModeBtn");
  const interactiveMode = document.getElementById("interactiveMode");
  const interactiveFrame = document.getElementById("interactiveFrame");
  const canvasArea = document.querySelector(".canvas-area");

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

  function registerBlocks(instance, data) {
    const blocks = instance.BlockManager;
    const firstAsset = data.assets.length ? data.assets[0].src : "";

    blocks.add("heading", {
      label: blockLabel("H", "Heading"),
      category: "Basic",
      content: '<h2>New heading</h2>',
    });
    blocks.add("paragraph", {
      label: blockLabel("¶", "Paragraph"),
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
      content: '<a href="#contact" class="btn btn-primary">New Button</a>',
    });
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
      label: blockLabel("▥", "Two Columns"),
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
    blocks.add("spacer", {
      label: blockLabel("↕", "Spacer"),
      category: "Basic",
      content: '<div style="height:48px" aria-hidden="true"></div>',
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

  function injectInlineStyles(doc, styles = []) {
    doc.querySelectorAll("style[data-siaw-imported-style]").forEach((node) => node.remove());
    styles.forEach((cssText, index) => {
      const style = doc.createElement("style");
      style.setAttribute("data-siaw-imported-style", String(index));
      style.textContent = cssText;
      doc.head.appendChild(style);
    });
  }

  function injectCanvasSafety(data) {
    const doc = editor.Canvas.getDocument();
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


  function injectEditorOnlyHelpers(data = loadedData || {}) {
    const doc = editor?.Canvas?.getDocument();
    if (!doc) return;
    forceRevealAnimationElements();
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

  function renderCompatibilityReport(data) {
    if (!compatibilityReport) return;
    const report = data.compatibility || {};
    const score = Math.max(0, Math.min(100, Number(report.compatibilityScore || 0)));
    const runtimeRegions = Array.isArray(report.runtimeRegions) ? report.runtimeRegions : [];
    const missing = Array.isArray(report.missingResources) ? report.missingResources : [];
    const recommendations = Array.isArray(report.recommendations) ? report.recommendations : [];
    const pages = Array.isArray(report.pages) ? report.pages : [];

    const regionMarkup = runtimeRegions.length
      ? runtimeRegions.slice(0, 18).map((region) => `<div class="report-region"><code>${escapeHtml(region.selector || `#${region.id}`)}</code><span>${escapeHtml(region.reason || "JavaScript-generated")}</span></div>`).join("")
      : '<p class="smart-help">No empty JavaScript-generated regions were detected in the original HTML.</p>';
    const missingMarkup = missing.length
      ? `<div class="report-section report-danger"><strong>Missing local resources (${missing.length})</strong><ul class="report-list">${missing.slice(0, 12).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`
      : '<div class="report-section"><strong>Local resources</strong><p class="smart-help">No missing local files were detected.</p></div>';
    const pageMarkup = pages.length > 1
      ? `<div class="report-section"><strong>HTML pages (${pages.length})</strong><ul class="report-list">${pages.slice(0, 10).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`
      : "";

    compatibilityReport.innerHTML = `
      <div class="report-score">
        <div class="report-score-row"><strong>Compatibility</strong><div class="report-score-number">${score}<small>/100</small></div></div>
        <div class="report-type">${escapeHtml(report.websiteType || "Imported HTML website")}</div>
        <div class="report-meter"><span style="width:${score}%"></span></div>
      </div>
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
    compatibilityReport.querySelector("[data-open-interactive]")?.addEventListener("click", () => setEditorMode("interactive"));
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

  function setEditorMode(mode) {
    if (!interactiveMode || !interactiveFrame || !canvasArea) return;
    activeEditorMode = mode === "interactive" ? "interactive" : "safe";
    const interactive = activeEditorMode === "interactive";
    safeModeBtn?.classList.toggle("active", !interactive);
    interactiveModeBtn?.classList.toggle("active", interactive);
    canvasArea.classList.toggle("interactive-active", interactive);
    interactiveMode.hidden = !interactive;
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
    regions.forEach((region) => {
      const selector = region.selector || (region.id ? `#${region.id}` : "");
      if (!selector) return;
      let targets = [];
      try { targets = Array.from(doc.querySelectorAll(selector)); } catch (_error) { return; }
      targets.forEach((target) => {
        if (target.querySelector("[data-siaw-editor-runtime-note]")) return;
        const meaningful = Array.from(target.children).some((child) => !child.hasAttribute("data-siaw-editor-only"));
        if (meaningful || target.textContent.trim()) return;
        const note = doc.createElement("div");
        note.dataset.siawEditorOnly = "true";
        note.dataset.siawEditorRuntimeNote = "true";
        note.className = "siaw-editor-runtime-note";
        note.innerHTML = `<strong>JavaScript-generated content</strong><br>This region is filled by the original website script and appears in Interactive mode and Live Preview. Selector: <code>${escapeHtml(selector)}</code>`;
        target.appendChild(note);
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
      button.addEventListener("click", () => handleNavigationAction(button.dataset.navAction));
    });
  }

  function handleNavigationAction(action) {
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
      if (!window.confirm(`Delete the menu item “${item.label}”?`)) return;
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
      button.addEventListener("click", () => handleSmartAction(button.dataset.smartAction, data));
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

  function handleSmartAction(action, data) {
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
        window.alert("At least one service must remain.");
        return;
      }
      if (!window.confirm(`Delete ${componentText(component, "h3") || "this service"}?`)) return;
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

    captureManager.innerHTML = `
      <div class="capture-summary">
        <strong>${runtimeSnapshot ? "Interactive page detected" : "Waiting for Interactive mode"}</strong>
        <span>${runtimeSnapshot ? `${navigationCount} menu items and ${dynamicCount} dynamic regions found.` : "The capture bridge will analyse the running website after Interactive mode opens."}</span>
      </div>
      <button type="button" id="capturePanelStart" class="capture-panel-start">${captureWaiting ? "Click a component in the website…" : "Start component capture"}</button>
      <div class="capture-warning"><strong>Static-copy safety</strong><span>A captured JavaScript component becomes editable HTML. Its original live behaviour is not copied automatically, so use it as a new static section or reusable design block.</span></div>
      <div class="capture-list">${cards}</div>
    `;
    captureManager.querySelector("#capturePanelStart")?.addEventListener("click", startInteractiveCapture);
    captureManager.querySelectorAll("[data-capture-action]").forEach((button) => {
      button.addEventListener("click", () => {
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
          window.alert("The captured component is now available in the left Blocks panel under Captured.");
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
    }
  }

  function projectDataForSave() {
    const data = editor.getProjectData();
    data.siawCaptures = capturedComponents;
    return data;
  }

  async function uploadAssets(event) {
    const files = Array.from(event.dataTransfer?.files || event.target?.files || []);
    if (!files.length) return;

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
      editor.AssetManager.add(result.data || []);
    }
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
        window.alert(result.error || "Could not open that HTML file.");
        return;
      }
      window.location.reload();
      return;
    }
    if (isHtmlPath(path) && !codeMode && editor) {
      activeSourcePath = path;
      renderFileTree(loadedData?.files || [], path);
      return;
    }
    const response = await fetch(sourceFileUrl(path), { headers: { Accept: "application/json" } });
    const result = await response.json();
    if (!response.ok) {
      window.alert(result.error || "Could not open that file.");
      return;
    }
    showCodeEditor(path, result.content || "");
    dirty = false;
    codeEditorReady = true;
    editorReady = true;
    setStatus("All changes saved", "saved");
  }

  async function saveProject({ silent = false } = {}) {
    if (codeMode) {
      if (!codeEditorReady && !codeEditor) return false;
      if (savingPromise) return savingPromise;
      if (!dirty && silent) return true;
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
          if (!silent) window.alert(error.message);
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
    if (!dirty && silent) return true;

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
            html: editor.getHtml(),
            css: editor.getCss(),
            projectData: projectDataForSave(),
            smartServices: collectSmartServices(),
            smartNavigation: collectSmartNavigation(),
          }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "The project could not be saved.");
        dirty = false;
        editor.clearDirtyCount();
        const synced = Array.isArray(result.synced) ? result.synced : [];
        setStatus(synced.length ? "Saved + smart components synced" : "Saved", "saved");
        window.setTimeout(() => {
          if (!dirty) setStatus("All changes saved", "saved");
        }, synced.length ? 2200 : 1200);
        return true;
      } catch (error) {
        console.error(error);
        setStatus("Save failed", "error");
        if (!silent) window.alert(error.message);
        return false;
      } finally {
        saveBtn.disabled = false;
        savingPromise = null;
      }
    })();

    return savingPromise;
  }

  function bindInterface() {
    document.querySelectorAll(".panel-tab").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".panel-tab").forEach((item) => item.classList.remove("active"));
        document.querySelectorAll(".panel-content").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
        document.getElementById(button.dataset.target).classList.add("active");
      });
    });

    document.querySelectorAll(".right-tab").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".right-tab").forEach((item) => item.classList.remove("active"));
        document.querySelectorAll(".right-content").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
        document.getElementById(button.dataset.target).classList.add("active");
      });
    });

    safeModeBtn?.addEventListener("click", () => setEditorMode("safe"));
    interactiveModeBtn?.addEventListener("click", () => setEditorMode("interactive"));
    captureStartBtn?.addEventListener("click", startInteractiveCapture);
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
      const saved = await saveProject();
      if (saved) window.location.assign(config.exportUrl);
    });

    notice.querySelector("button").addEventListener("click", () => notice.classList.add("hidden"));

    document.getElementById("restoreForm").addEventListener("submit", (event) => {
      const confirmed = window.confirm("Restore the original uploaded website? All visual-editor changes will be removed.");
      if (!confirmed) event.preventDefault();
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

  async function start() {
    try {
      const response = await fetch(config.dataUrl, { headers: { Accept: "application/json" } });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Project data could not be loaded.");
      loadedData = data;
      renderFileTree(Array.isArray(data.files) ? data.files : [], data.entryFile || config.entryFile);

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
          styles: data.canvasStyles,
          frameStyle: "body{min-height:100vh;} .gjs-selected{outline:2px solid #ff4545!important}",
        },
        assetManager: {
          assets: data.assets,
          multiUpload: true,
          uploadFile: async (event) => {
            try {
              await uploadAssets(event);
            } catch (error) {
              console.error(error);
              window.alert(error.message);
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
      registerBlocks(editor, data);

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

      window.setTimeout(() => {
        injectCanvasSafety(data);
        injectEditorOnlyHelpers(data);
        capturedComponents.forEach(registerCapturedBlock);
        renderSmartManager(data);
        renderCompatibilityReport(data);
        renderCaptureManager();
      }, 120);

      editor.on("update", markDirty);
      editor.on("component:selected", (component) => {
        protectedHint.hidden = !componentIsInsideProtected(component);
      });
      editor.on("component:deselected", () => {
        protectedHint.hidden = true;
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
      editorReady = true;
      dirty = false;
      editor.clearDirtyCount();
      setStatus("All changes saved", "saved");
    } catch (error) {
      console.error(error);
      setStatus("Load failed", "error");
      document.getElementById("gjs").innerHTML = `<div style="padding:30px;font-family:sans-serif;color:#8d2727"><h2>Editor could not load</h2><p>${error.message}</p></div>`;
    }
  }

  start();
})();
