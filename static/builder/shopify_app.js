(() => {
  const root = document.body;
  if (!root || !root.classList.contains("siaw-shopify-app")) return;

  const statusEl = root.querySelector("[data-shopify-status]");
  const buildBtn = root.querySelector("[data-shopify-build]");
  const catalogPanel = root.querySelector("[data-catalog-panel]");
  const productList = root.querySelector("[data-product-list]");
  const sessionUrl = root.getAttribute("data-session-url") || "";
  const buildUrl = root.getAttribute("data-build-url") || "";
  const productsUrl = root.getAttribute("data-products-url") || "";
  const host = root.getAttribute("data-host") || "";
  const apiKeyMeta = document.querySelector('meta[name="shopify-api-key"]');
  const apiKey = apiKeyMeta ? apiKeyMeta.getAttribute("content") || "" : "";

  const setStatus = (text, kind = "") => {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.classList.toggle("is-error", kind === "error");
    statusEl.classList.toggle("is-ok", kind === "ok");
  };

  const getSessionToken = async () => {
    if (window.shopify && typeof window.shopify.idToken === "function") {
      return window.shopify.idToken();
    }
    const bridge = window["app-bridge"];
    if (bridge && apiKey && host) {
      const createApp = bridge.default || bridge.createApp || bridge;
      const app = typeof createApp === "function" ? createApp({ apiKey, host, forceRedirect: true }) : null;
      const utilities = bridge.utilities || (bridge.actions && bridge.actions.utilities) || {};
      if (app && typeof utilities.getSessionToken === "function") {
        return utilities.getSessionToken(app);
      }
    }
    throw new Error("Open this page from Shopify Admin (Apps → Siaw) so App Bridge can issue a session token.");
  };

  const authedFetch = async (url, options = {}) => {
    const token = await getSessionToken();
    const headers = new Headers(options.headers || {});
    headers.set("Authorization", `Bearer ${token}`);
    if (options.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(url, { ...options, headers, credentials: "same-origin" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `Request failed (${response.status})`);
    }
    return data;
  };

  const renderProducts = (products) => {
    if (!catalogPanel || !productList) return;
    productList.innerHTML = "";
    (products || []).slice(0, 8).forEach((product) => {
      const li = document.createElement("li");
      const img = document.createElement("img");
      img.alt = "";
      img.src = product.image_url || "";
      if (!product.image_url) img.style.visibility = "hidden";
      const copy = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = product.title || "Product";
      const meta = document.createElement("small");
      const price = [product.price_amount, product.price_currency].filter(Boolean).join(" ");
      meta.textContent = price || product.handle || "";
      copy.append(title, meta);
      const badge = document.createElement("small");
      badge.textContent = product.status || "";
      li.append(img, copy, badge);
      productList.append(li);
    });
    catalogPanel.hidden = !(products && products.length);
  };

  const boot = async () => {
    if (!sessionUrl) {
      setStatus("Session endpoint missing.", "error");
      return;
    }
    try {
      setStatus("Connecting to your Shopify session…");
      const session = await authedFetch(sessionUrl, { method: "POST", body: "{}" });
      const name = session.shop?.name || session.shop?.domain || "your store";
      setStatus(`Connected to ${name}.`, "ok");
      if (productsUrl) {
        const catalog = await authedFetch(`${productsUrl}?limit=8`);
        renderProducts(catalog.products || []);
      }
    } catch (err) {
      setStatus(err.message || "Could not connect Shopify session.", "error");
    }
  };

  if (buildBtn) {
    buildBtn.addEventListener("click", async () => {
      buildBtn.disabled = true;
      setStatus("Generating site brief from your catalog…");
      try {
        const result = await authedFetch(buildUrl, { method: "POST", body: "{}" });
        setStatus(`Brief ready for ${result.shop || "your store"}. Opening wizard…`, "ok");
        if (result.wizard_url) {
          window.open(result.wizard_url, "_top");
        }
      } catch (err) {
        setStatus(err.message || "Could not build from catalog.", "error");
        buildBtn.disabled = false;
      }
    });
  }

  boot();
})();
