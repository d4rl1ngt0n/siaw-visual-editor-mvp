(() => {
  const TITLE = {
    alert: "Notice",
    confirm: "Please confirm",
    prompt: "Enter a value",
    danger: "Please confirm",
  };

  let root = null;
  let activeResolver = null;
  let previousFocus = null;
  let focusTrapHandler = null;

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
      if (!activeResolver) return;
      if (event.key === "Escape") {
        event.preventDefault();
        close(activeResolver.escapeValue);
        return;
      }
      if (event.key === "Enter" && activeResolver.mode !== "prompt") {
        const target = event.target;
        if (target && target.tagName === "BUTTON") return;
        event.preventDefault();
        close(activeResolver.enterValue);
      }
    });
    root.addEventListener("click", (event) => {
      if (event.target === root && activeResolver) {
        close(activeResolver.escapeValue);
      }
    });
    return root;
  }

  function getFocusable(container) {
    return [...container.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]):not([hidden]), select, textarea, [tabindex]:not([tabindex="-1"])'
    )].filter((el) => !el.hasAttribute("hidden") && el.offsetParent !== null);
  }

  function armFocusTrap(card) {
    disarmFocusTrap();
    focusTrapHandler = (event) => {
      if (event.key !== "Tab" || !root || root.hidden) return;
      const items = getFocusable(card);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", focusTrapHandler);
  }

  function disarmFocusTrap() {
    if (!focusTrapHandler) return;
    document.removeEventListener("keydown", focusTrapHandler);
    focusTrapHandler = null;
  }

  function close(value) {
    if (!activeResolver) return;
    const resolver = activeResolver;
    activeResolver = null;
    const node = ensureRoot();
    node.hidden = true;
    document.body.style.overflow = "";
    disarmFocusTrap();
    if (previousFocus && typeof previousFocus.focus === "function") {
      previousFocus.focus();
    }
    previousFocus = null;
    resolver.resolve(value);
  }

  function openDialog(options) {
    const node = ensureRoot();
    const card = node.querySelector(".siaw-dialog-card");
    const eyebrow = node.querySelector("[data-dialog-eyebrow]");
    const title = node.querySelector("[data-dialog-title]");
    const message = node.querySelector("[data-dialog-message]");
    const input = node.querySelector("[data-dialog-input]");
    const actions = node.querySelector("[data-dialog-actions]");

    const titleText = options.title || TITLE.alert;
    eyebrow.textContent = options.eyebrow || titleText;
    title.textContent = titleText;
    message.textContent = options.message || "";
    message.hidden = !options.message;

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
    armFocusTrap(card);

    window.setTimeout(() => {
      if (options.mode === "prompt") {
        input.focus();
        input.select();
      } else {
        const primary = actions.querySelector(".siaw-dialog-btn-primary, .siaw-dialog-btn-danger")
          || actions.querySelector("button");
        primary?.focus();
      }
    }, 0);

    return new Promise((resolve) => {
      activeResolver = {
        resolve,
        escapeValue: options.escapeValue,
        enterValue: options.enterValue,
        mode: options.mode,
      };
    });
  }

  async function alert(message, options = {}) {
    const text = String(message ?? "");
    await openDialog({
      mode: "alert",
      title: options.title || TITLE.alert,
      eyebrow: options.eyebrow || "Notice",
      message: options.message != null ? String(options.message) : text,
      escapeValue: undefined,
      enterValue: undefined,
      buttons: [
        { label: options.okLabel || "OK", value: undefined, className: "siaw-dialog-btn-primary" },
      ],
    });
  }

  async function confirm(message, options = {}) {
    const danger = Boolean(options.danger);
    const text = String(message ?? "");
    return openDialog({
      mode: "confirm",
      title: options.title || (danger ? TITLE.danger : TITLE.confirm),
      eyebrow: options.eyebrow || (danger ? "Destructive action" : "Confirm"),
      message: options.message != null ? String(options.message) : text,
      escapeValue: false,
      enterValue: true,
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
    const text = String(message ?? "");
    return openDialog({
      mode: "prompt",
      title: options.title || TITLE.prompt,
      eyebrow: options.eyebrow || "Input",
      message: options.message != null ? String(options.message) : text,
      defaultValue: defaultValue == null ? "" : String(defaultValue),
      placeholder: options.placeholder || "",
      escapeValue: null,
      enterValue: null,
      buttons: [
        { label: options.cancelLabel || "Cancel", value: null },
        { label: options.okLabel || "OK", value: true, className: "siaw-dialog-btn-primary" },
      ],
    });
  }

  window.SiawDialog = { alert, confirm, prompt };
  window.siawAlert = alert;
  window.siawConfirm = confirm;
  window.siawPrompt = prompt;

  // Route any leftover native calls through the styled dialog.
  // confirm/prompt stay async-only via siawConfirm/siawPrompt; sync window.confirm cannot be replaced safely.
  window.alert = (message) => {
    void alert(message);
  };
})();
