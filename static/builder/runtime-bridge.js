(() => {
  "use strict";

  const script = document.currentScript;
  const projectId = script?.dataset.projectId || "";
  let captureActive = false;
  let hovered = null;
  let previousOutline = "";
  let previousCursor = "";

  const meaningfulSelector = "article,section,nav,header,footer,main,aside,form,ul,ol,table,[role='navigation'],[data-component],.card,.panel,.modal,.hero";

  function labelFor(element) {
    const heading = element.querySelector?.("h1,h2,h3,h4,h5,h6,[aria-label]");
    const headingText = heading?.getAttribute?.("aria-label") || heading?.textContent || "";
    const own = element.getAttribute?.("aria-label") || element.getAttribute?.("title") || "";
    const text = (headingText || own || element.textContent || element.tagName || "Component").replace(/\s+/g, " ").trim();
    return text.slice(0, 90) || "Captured component";
  }

  function selectorFor(element) {
    if (element.id) return `#${CSS.escape(element.id)}`;
    const classes = Array.from(element.classList || []).filter(Boolean).slice(0, 3);
    if (classes.length) return `${element.tagName.toLowerCase()}.${classes.map((name) => CSS.escape(name)).join(".")}`;
    const parent = element.parentElement;
    if (!parent) return element.tagName.toLowerCase();
    const siblings = Array.from(parent.children).filter((item) => item.tagName === element.tagName);
    const index = Math.max(1, siblings.indexOf(element) + 1);
    return `${element.tagName.toLowerCase()}:nth-of-type(${index})`;
  }

  function sanitisedOuterHTML(element) {
    const clone = element.cloneNode(true);
    clone.querySelectorAll("script,link[rel='preload'][as='script'],[data-siaw-runtime-bridge]").forEach((item) => item.remove());
    [clone, ...clone.querySelectorAll("*")].forEach((item) => {
      Array.from(item.attributes || []).forEach((attribute) => {
        const name = attribute.name.toLowerCase();
        if (name.startsWith("on") || name === "contenteditable") item.removeAttribute(attribute.name);
      });
      item.removeAttribute?.("data-siaw-capture-hover");
    });
    return clone.outerHTML.slice(0, 350000);
  }

  function navigationSnapshot() {
    const candidates = Array.from(document.querySelectorAll("nav,[role='navigation'],.nav-links,.desktop-nav,.mobile-menu,.mobile-panel"));
    return candidates.slice(0, 12).map((nav, index) => ({
      index,
      selector: selectorFor(nav),
      label: nav.getAttribute("aria-label") || nav.id || nav.className || `Navigation ${index + 1}`,
      items: Array.from(nav.querySelectorAll("a,button")).slice(0, 40).map((item) => ({
        label: (item.textContent || "").replace(/\s+/g, " ").trim().slice(0, 120),
        destination: item.getAttribute("href") || item.dataset.go || item.dataset.goto || item.dataset.view || item.dataset.page || "",
        tag: item.tagName.toLowerCase(),
      })).filter((item) => item.label),
    })).filter((nav) => nav.items.length);
  }

  function dynamicSnapshot() {
    const selectors = ["[data-product-category]", "[data-review]", ".review-card", ".testimonial", ".carousel", ".slider", ".trip", ".catalog-card", ".modal", "dialog", "[data-generated]"];
    const seen = new Set();
    const regions = [];
    selectors.forEach((selector) => {
      document.querySelectorAll(selector).forEach((element) => {
        if (seen.has(element) || regions.length >= 40) return;
        seen.add(element);
        regions.push({selector: selectorFor(element), label: labelFor(element), tag: element.tagName.toLowerCase()});
      });
    });
    return regions;
  }

  function postSnapshot() {
    window.parent.postMessage({
      type: "siaw:runtime:snapshot",
      projectId,
      title: document.title,
      url: location.href,
      navigation: navigationSnapshot(),
      dynamicRegions: dynamicSnapshot(),
    }, "*");
  }

  function clearHover() {
    if (!hovered) return;
    hovered.style.outline = previousOutline;
    hovered.style.cursor = previousCursor;
    hovered.removeAttribute("data-siaw-capture-hover");
    hovered = null;
  }

  function chooseElement(target) {
    if (!(target instanceof Element)) return null;
    return target.closest(meaningfulSelector) || target;
  }

  function onPointerMove(event) {
    if (!captureActive) return;
    const candidate = chooseElement(event.target);
    if (!candidate || candidate === hovered || candidate === script) return;
    clearHover();
    hovered = candidate;
    previousOutline = hovered.style.outline;
    previousCursor = hovered.style.cursor;
    hovered.style.outline = "3px solid #ff4545";
    hovered.style.cursor = "crosshair";
    hovered.setAttribute("data-siaw-capture-hover", "true");
  }

  function stopCapture(message = true) {
    captureActive = false;
    clearHover();
    document.removeEventListener("pointermove", onPointerMove, true);
    document.removeEventListener("click", onCaptureClick, true);
    document.removeEventListener("keydown", onKeyDown, true);
    if (message) window.parent.postMessage({type: "siaw:capture:stopped", projectId}, "*");
  }

  function onCaptureClick(event) {
    if (!captureActive) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const element = chooseElement(event.target);
    if (!element) return;
    const component = {
      id: `capture-${Date.now()}`,
      name: labelFor(element),
      selector: selectorFor(element),
      tag: element.tagName.toLowerCase(),
      html: sanitisedOuterHTML(element),
      text: (element.textContent || "").replace(/\s+/g, " ").trim().slice(0, 500),
      sourceUrl: location.href,
      capturedAt: new Date().toISOString(),
    };
    stopCapture(false);
    window.parent.postMessage({type: "siaw:capture:result", projectId, component}, "*");
  }

  function onKeyDown(event) {
    if (event.key === "Escape") stopCapture();
  }

  function startCapture() {
    if (captureActive) return;
    captureActive = true;
    document.addEventListener("pointermove", onPointerMove, true);
    document.addEventListener("click", onCaptureClick, true);
    document.addEventListener("keydown", onKeyDown, true);
    window.parent.postMessage({type: "siaw:capture:ready", projectId}, "*");
  }

  window.addEventListener("message", (event) => {
    const data = event.data || {};
    if (data.projectId && String(data.projectId) !== String(projectId)) return;
    if (data.type === "siaw:capture:start") startCapture();
    if (data.type === "siaw:capture:cancel") stopCapture();
    if (data.type === "siaw:runtime:snapshot:request") postSnapshot();
  });

  window.addEventListener("load", () => {
    window.setTimeout(postSnapshot, 350);
    window.setTimeout(postSnapshot, 1400);
  });
})();
