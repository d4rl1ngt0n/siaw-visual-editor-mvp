(() => {
  if (!document.body?.dataset.siteEdit) return;

  const saveUrl = document.body.dataset.siteEditSaveUrl || "";
  const readCookie = (name) => {
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : "";
  };
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value
    || readCookie("csrftoken")
    || "";

  const originals = new Map();
  let editing = false;

  const bar = document.createElement("div");
  bar.className = "site-edit-bar";
  bar.innerHTML = `
    <div class="site-edit-bar-copy">
      <strong>Local edit mode</strong>
      <span data-site-edit-status>Click Edit to change copy on this page. Saves write into template files.</span>
    </div>
    <div class="site-edit-bar-actions">
      <button type="button" class="site-edit-btn" data-site-edit-toggle>Edit page</button>
      <button type="button" class="site-edit-btn site-edit-btn-ghost" data-site-edit-cancel hidden>Cancel</button>
      <button type="button" class="site-edit-btn site-edit-btn-primary" data-site-edit-save hidden>Save to code</button>
    </div>
  `;
  document.body.appendChild(bar);

  const status = bar.querySelector("[data-site-edit-status]");
  const toggleBtn = bar.querySelector("[data-site-edit-toggle]");
  const cancelBtn = bar.querySelector("[data-site-edit-cancel]");
  const saveBtn = bar.querySelector("[data-site-edit-save]");

  const targets = () => [...document.querySelectorAll("[data-site-edit]")];

  const setStatus = (text) => {
    if (status) status.textContent = text;
  };

  const snapshot = () => {
    originals.clear();
    targets().forEach((el) => {
      const key = el.getAttribute("data-site-edit");
      if (!key) return;
      if (el.tagName === "IMG") {
        originals.set(key, { kind: "src", value: el.getAttribute("src") || "" });
      } else {
        originals.set(key, { kind: "text", value: el.innerText || "" });
      }
    });
  };

  const collectEdits = () => {
    const edits = [];
    targets().forEach((el) => {
      const key = el.getAttribute("data-site-edit");
      if (!key || !originals.has(key)) return;
      const prev = originals.get(key);
      if (el.tagName === "IMG") {
        const value = el.getAttribute("src") || "";
        if (value !== prev.value) edits.push({ key, kind: "src", value });
        return;
      }
      const value = (el.innerText || "").replace(/\u00a0/g, " ").trimEnd();
      const previous = String(prev.value || "").replace(/\u00a0/g, " ").trimEnd();
      if (value !== previous) edits.push({ key, kind: "text", value });
    });
    return edits;
  };

  const stopHeroDemo = () => {
    document.body.classList.add("site-edit-active");
    document.querySelectorAll("[data-hero-edit]").forEach((node) => {
      node.setAttribute("data-hero-edit-paused", "1");
    });
  };

  const startEditing = () => {
    editing = true;
    snapshot();
    stopHeroDemo();
    targets().forEach((el) => {
      if (el.tagName === "IMG") {
        el.classList.add("is-site-editable-media");
        el.title = "Click to change image URL";
        return;
      }
      el.contentEditable = "true";
      el.spellcheck = true;
      el.classList.add("is-site-editable");
    });
    document.body.classList.add("is-site-editing");
    toggleBtn.hidden = true;
    cancelBtn.hidden = false;
    saveBtn.hidden = false;
    setStatus("Editing. Changes save into templates/ for your next commit.");
  };

  const stopEditing = ({ restore = false } = {}) => {
    if (restore) {
      targets().forEach((el) => {
        const key = el.getAttribute("data-site-edit");
        if (!key || !originals.has(key)) return;
        const prev = originals.get(key);
        if (el.tagName === "IMG") el.setAttribute("src", prev.value);
        else el.innerText = prev.value;
      });
    }
    targets().forEach((el) => {
      el.removeAttribute("contenteditable");
      el.classList.remove("is-site-editable", "is-site-editable-media");
      el.removeAttribute("title");
    });
    editing = false;
    document.body.classList.remove("is-site-editing");
    toggleBtn.hidden = false;
    cancelBtn.hidden = true;
    saveBtn.hidden = true;
    setStatus("Click Edit to change copy on this page. Saves write into template files.");
  };

  toggleBtn?.addEventListener("click", () => startEditing());
  cancelBtn?.addEventListener("click", () => stopEditing({ restore: true }));

  document.addEventListener("click", (event) => {
    if (!editing) return;
    const img = event.target.closest("img[data-site-edit]");
    if (!img) return;
    event.preventDefault();
    event.stopPropagation();
    const next = window.prompt("Image URL", img.getAttribute("src") || "");
    if (next == null) return;
    const trimmed = next.trim();
    if (trimmed) img.setAttribute("src", trimmed);
  }, true);

  document.addEventListener("click", (event) => {
    if (!editing) return;
    const link = event.target.closest("a");
    if (!link || link.closest(".site-edit-bar")) return;
    // Allow editing link label text without navigating away.
    if (link.hasAttribute("data-site-edit") || link.querySelector("[data-site-edit]")) {
      event.preventDefault();
    }
  }, true);

  saveBtn?.addEventListener("click", async () => {
    const edits = collectEdits();
    if (!edits.length) {
      setStatus("No changes to save.");
      return;
    }
    saveBtn.disabled = true;
    setStatus(`Saving ${edits.length} change${edits.length === 1 ? "" : "s"}…`);
    try {
      const response = await fetch(saveUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrf,
        },
        body: JSON.stringify({ edits }),
        credentials: "same-origin",
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || "Save failed.");
      }
      snapshot();
      stopEditing({ restore: false });
      setStatus(`Saved ${payload.count || edits.length} change(s) to templates. Commit when ready.`);
      if (window.siawAlert) {
        await window.siawAlert(
          `Saved ${payload.count || edits.length} change(s) into your template files. Review the diff, then commit when you are ready.`,
          { title: "Saved to code", okLabel: "Done" },
        );
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not save.");
      if (window.siawAlert) {
        await window.siawAlert(error instanceof Error ? error.message : "Could not save.", {
          title: "Save failed",
        });
      }
    } finally {
      saveBtn.disabled = false;
    }
  });
})();
