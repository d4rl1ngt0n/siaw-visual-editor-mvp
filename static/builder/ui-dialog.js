(() => {
  const TITLE = {
    alert: "Notice",
    confirm: "Confirm",
    prompt: "Enter a value",
    danger: "Please confirm",
  };

  let root = null;
  let activeResolver = null;
  let previousFocus = null;

  function ensureRoot() {
    if (root) return root;
    root = document.createElement("div");
    root.className = "siaw-dialog-root";
    root.hidden = true;
    root.setAttribute("role", "presentation");
    root.innerHTML = `
      <div class="siaw-dialog-card" role="dialog" aria-modal="true" aria-labelledby="siawDialogTitle" aria-describedby="siawDialogMessage">
        <p class="siaw-dialog-eyebrow" data-dialog-eyebrow>Notice</p>
        <h2 class="siaw-dialog-title" id="siawDialogTitle" data-dialog-title>Notice</h2>
        <p class="siaw-dialog-message" id="siawDialogMessage" data-dialog-message></p>
        <input class="siaw-dialog-input" data-dialog-input type="text" hidden>
        <div class="siaw-dialog-actions" data-dialog-actions></div>
      </div>
    `;
    document.body.appendChild(root);

    root.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && activeResolver) {
        event.preventDefault();
        close(activeResolver.escapeValue);
      }
    });
    root.addEventListener("click", (event) => {
      if (event.target === root && activeResolver) {
        close(activeResolver.escapeValue);
      }
    });
    return root;
  }

  function close(value) {
    if (!activeResolver) return;
    const resolver = activeResolver;
    activeResolver = null;
    const node = ensureRoot();
    node.hidden = true;
    document.body.style.overflow = "";
    if (previousFocus && typeof previousFocus.focus === "function") {
      previousFocus.focus();
    }
    previousFocus = null;
    resolver.resolve(value);
  }

  function openDialog(options) {
    const node = ensureRoot();
    const eyebrow = node.querySelector("[data-dialog-eyebrow]");
    const title = node.querySelector("[data-dialog-title]");
    const message = node.querySelector("[data-dialog-message]");
    const input = node.querySelector("[data-dialog-input]");
    const actions = node.querySelector("[data-dialog-actions]");

    eyebrow.textContent = options.eyebrow || options.title || TITLE.alert;
    title.textContent = options.title || TITLE.alert;
    message.textContent = options.message || "";

    if (options.mode === "prompt") {
      input.hidden = false;
      input.value = options.defaultValue || "";
      input.placeholder = options.placeholder || "";
    } else {
      input.hidden = true;
      input.value = "";
    }

    actions.innerHTML = "";
    (options.buttons || []).forEach((button) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = `siaw-dialog-btn ${button.className || ""}`.trim();
      el.textContent = button.label;
      el.addEventListener("click", () => {
        if (options.mode === "prompt" && button.value === true) {
          close(input.value);
          return;
        }
        close(button.value);
      });
      actions.appendChild(el);
    });

    previousFocus = document.activeElement;
    node.hidden = false;
    document.body.style.overflow = "hidden";

    window.setTimeout(() => {
      if (options.mode === "prompt") {
        input.focus();
        input.select();
      } else {
        const primary = actions.querySelector(".siaw-dialog-btn-primary, .siaw-dialog-btn-danger") || actions.querySelector("button");
        primary?.focus();
      }
    }, 0);

    return new Promise((resolve) => {
      activeResolver = {
        resolve,
        escapeValue: options.escapeValue,
      };
    });
  }

  async function alert(message, options = {}) {
    await openDialog({
      mode: "alert",
      title: options.title || TITLE.alert,
      eyebrow: options.eyebrow || "Notice",
      message: String(message ?? ""),
      escapeValue: undefined,
      buttons: [
        { label: options.okLabel || "OK", value: undefined, className: "siaw-dialog-btn-primary" },
      ],
    });
  }

  async function confirm(message, options = {}) {
    const danger = Boolean(options.danger);
    return openDialog({
      mode: "confirm",
      title: options.title || (danger ? TITLE.danger : TITLE.confirm),
      eyebrow: options.eyebrow || (danger ? "Confirm" : "Confirm"),
      message: String(message ?? ""),
      escapeValue: false,
      buttons: [
        { label: options.cancelLabel || "Cancel", value: false },
        {
          label: options.confirmLabel || (danger ? "Delete" : "Continue"),
          value: true,
          className: danger ? "siaw-dialog-btn-danger" : "siaw-dialog-btn-primary",
        },
      ],
    });
  }

  async function prompt(message, defaultValue = "", options = {}) {
    return openDialog({
      mode: "prompt",
      title: options.title || TITLE.prompt,
      eyebrow: options.eyebrow || "Input",
      message: String(message ?? ""),
      defaultValue: defaultValue == null ? "" : String(defaultValue),
      placeholder: options.placeholder || "",
      escapeValue: null,
      buttons: [
        { label: options.cancelLabel || "Cancel", value: null },
        { label: options.okLabel || "OK", value: true, className: "siaw-dialog-btn-primary" },
      ],
    });
  }

  window.SiawDialog = { alert, confirm, prompt };

  // Convenience aliases used across editor/dashboard scripts.
  window.siawAlert = alert;
  window.siawConfirm = confirm;
  window.siawPrompt = prompt;
})();
