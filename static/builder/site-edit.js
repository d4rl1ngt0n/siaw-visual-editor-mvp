(() => {
  if (!document.body?.dataset.siteEdit) return;

  const saveUrl = document.body.dataset.siteEditSaveUrl || "";
  const uploadUrl = document.body.dataset.siteEditUploadUrl || "";
  const readCookie = (name) => {
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : "";
  };
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value
    || readCookie("csrftoken")
    || "";

  const originals = new Map();
  const parentOrders = new Map();
  let editing = false;
  let dragEl = null;
  let activeImage = null;

  const VOID_TAGS = new Set(["IMG", "BR", "HR", "INPUT", "META", "LINK", "SOURCE"]);

  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = "image/jpeg,image/png,image/webp,image/gif,image/svg+xml,.jpg,.jpeg,.png,.webp,.gif,.svg";
  fileInput.hidden = true;
  document.body.appendChild(fileInput);

  const bar = document.createElement("div");
  bar.className = "site-edit-bar";
  bar.innerHTML = `
    <div class="site-edit-bar-copy">
      <strong>Local edit mode</strong>
      <span data-site-edit-status>Drag any handle to move headings, images, buttons, or sections.</span>
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

  const editRoot = () => document.querySelector("main") || document.body;

  const targets = () => [...editRoot().querySelectorAll("[data-site-edit]")];

  const isMovable = (el) => {
    if (!el || el.nodeType !== 1) return false;
    if (el.classList?.contains("site-edit-handle")) return false;
    if (el.closest?.(".site-edit-bar")) return false;
    return el.hasAttribute("data-site-block") || el.hasAttribute("data-site-edit");
  };

  const movables = () => [...editRoot().querySelectorAll("[data-site-block], [data-site-edit]")].filter((el) => {
    // Prefer the outermost marked node when a marked parent wraps a marked child
    // only for collecting sibling lists; both still get handles.
    return isMovable(el);
  });

  const itemRef = (el) => {
    if (el.hasAttribute("data-site-block")) {
      return { attr: "data-site-block", key: el.getAttribute("data-site-block") };
    }
    if (el.hasAttribute("data-site-edit")) {
      return { attr: "data-site-edit", key: el.getAttribute("data-site-edit") };
    }
    return null;
  };

  const parentId = (parent) => {
    if (!parent) return "";
    if (parent.hasAttribute("data-site-block")) return `block:${parent.getAttribute("data-site-block")}`;
    if (parent.id) return `id:${parent.id}`;
    if (parent.hasAttribute("data-site-edit")) return `edit:${parent.getAttribute("data-site-edit")}`;
    const index = parent.parentElement
      ? [...parent.parentElement.children].indexOf(parent)
      : 0;
    return `tag:${parent.tagName}:${index}:${parent.className || ""}`;
  };

  const siblingMovables = (parent) => [...(parent?.children || [])].filter(isMovable);

  const readableText = (el) => {
    const clone = el.cloneNode(true);
    clone.querySelectorAll(".site-edit-handle").forEach((node) => node.remove());
    return (clone.innerText || "").replace(/\u00a0/g, " ").trimEnd();
  };

  const captureParentOrders = () => {
    const map = new Map();
    const parents = new Set(movables().map((el) => el.parentElement).filter(Boolean));
    parents.forEach((parent) => {
      const kids = siblingMovables(parent);
      if (kids.length < 2) return;
      map.set(parentId(parent), kids.map((el) => itemRef(el)).filter(Boolean));
    });
    return map;
  };

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
        originals.set(key, { kind: "text", value: readableText(el) });
      }
    });
    parentOrders.clear();
    captureParentOrders().forEach((order, id) => {
      parentOrders.set(id, JSON.stringify(order));
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
      const value = readableText(el);
      const previous = String(prev.value || "").replace(/\u00a0/g, " ").trimEnd();
      if (value !== previous) edits.push({ key, kind: "text", value });
    });

    captureParentOrders().forEach((order, id) => {
      const prev = parentOrders.get(id);
      if (!prev || prev === JSON.stringify(order) || order.length < 2) return;
      edits.push({ kind: "reorder_items", items: order });
    });
    return edits;
  };

  const stopHeroDemo = () => {
    document.body.classList.add("site-edit-active");
    document.querySelectorAll("[data-hero-edit]").forEach((node) => {
      node.setAttribute("data-hero-edit-paused", "1");
    });
  };

  const ensureHandle = (el) => {
    if (el.previousElementSibling?.classList?.contains("site-edit-handle")
      && el.previousElementSibling._siteDragTarget === el) {
      return;
    }
    const handle = document.createElement("button");
    handle.type = "button";
    handle.className = VOID_TAGS.has(el.tagName)
      ? "site-edit-handle site-edit-handle-media"
      : "site-edit-handle";
    handle.title = "Drag to move";
    handle.setAttribute("aria-label", "Drag to move");
    handle.innerHTML = "<span></span><span></span><span></span>";
    handle.draggable = true;
    handle._siteDragTarget = el;
    el.insertAdjacentElement("beforebegin", handle);
    el.parentElement?.classList.add("is-site-move-parent");
  };

  const clearHandles = () => {
    document.querySelectorAll(".site-edit-handle").forEach((node) => node.remove());
  };

  const startEditing = () => {
    editing = true;
    snapshot();
    stopHeroDemo();
    targets().forEach((el) => {
      if (el.tagName === "IMG") {
        el.classList.add("is-site-editable-media");
        el.title = "Drop an image, or click to choose a file";
      } else {
        el.contentEditable = "true";
        el.spellcheck = true;
        el.classList.add("is-site-editable");
      }
    });
    movables().forEach((el) => {
      el.classList.add("is-site-movable");
      ensureHandle(el);
    });
    document.body.classList.add("is-site-editing");
    toggleBtn.hidden = true;
    cancelBtn.hidden = false;
    saveBtn.hidden = false;
    setStatus("Drag handles to move any element. Drop files on images. Edit text inline.");
  };

  const restoreOrders = () => {
    parentOrders.forEach((joined, id) => {
      let order;
      try {
        order = JSON.parse(joined);
      } catch (_) {
        return;
      }
      if (!Array.isArray(order) || order.length < 2) return;
      const nodes = order.map((item) => {
        if (!item?.attr || !item?.key) return null;
        return editRoot().querySelector(`[${item.attr}="${item.key}"]`);
      }).filter(Boolean);
      if (nodes.length < 2) return;
      const parent = nodes[0].parentElement;
      if (!parent || parentId(parent) !== id) return;
      if (nodes.some((node) => node.parentElement !== parent)) return;
      const marker = document.createComment("site-edit-restore");
      parent.insertBefore(marker, nodes[0]);
      order.forEach((item) => {
        const node = editRoot().querySelector(`[${item.attr}="${item.key}"]`);
        if (node) parent.insertBefore(node, marker);
      });
      marker.remove();
    });
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
      restoreOrders();
    }
    targets().forEach((el) => {
      el.removeAttribute("contenteditable");
      el.classList.remove("is-site-editable", "is-site-editable-media", "is-site-movable", "is-site-dragging");
      el.removeAttribute("title");
    });
    document.querySelectorAll(".is-site-movable").forEach((el) => {
      el.classList.remove("is-site-movable", "is-site-dragging");
    });
    document.querySelectorAll(".is-site-move-parent").forEach((el) => {
      el.classList.remove("is-site-move-parent");
    });
    clearHandles();
    editing = false;
    dragEl = null;
    activeImage = null;
    document.body.classList.remove("is-site-editing");
    toggleBtn.hidden = false;
    cancelBtn.hidden = true;
    saveBtn.hidden = true;
    setStatus("Drag any handle to move headings, images, buttons, or sections.");
  };

  const getDragAfterElement = (container, y) => {
    const items = siblingMovables(container).filter((child) => child !== dragEl);
    return items.reduce((closest, child) => {
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) {
        return { offset, element: child };
      }
      return closest;
    }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
  };

  const handleFor = (el) => {
    const prev = el.previousElementSibling;
    if (prev?.classList?.contains("site-edit-handle") && prev._siteDragTarget === el) return prev;
    return null;
  };

  const placeElement = (parent, el, beforeNode) => {
    const handle = handleFor(el);
    let anchor = beforeNode;
    if (anchor) {
      const anchorHandle = handleFor(anchor);
      if (anchorHandle) anchor = anchorHandle;
    }
    if (anchor) parent.insertBefore(el, anchor);
    else parent.appendChild(el);
    if (handle) parent.insertBefore(handle, el);
  };

  const uploadImage = async (file) => {
    if (!uploadUrl) throw new Error("Image upload is unavailable.");
    const body = new FormData();
    body.append("image", file);
    const response = await fetch(uploadUrl, {
      method: "POST",
      headers: { "X-CSRFToken": csrf },
      body,
      credentials: "same-origin",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "Image upload failed.");
    return payload.url;
  };

  const applyImageFile = async (img, file) => {
    if (!file || !String(file.type || "").startsWith("image/")) {
      setStatus("Drop an image file (JPG, PNG, WebP, GIF, or SVG).");
      return;
    }
    setStatus(`Uploading ${file.name || "image"}…`);
    try {
      const url = await uploadImage(file);
      img.setAttribute("src", url);
      setStatus("Image updated. Save to code when ready.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not replace image.");
    }
  };

  toggleBtn?.addEventListener("click", () => startEditing());
  cancelBtn?.addEventListener("click", () => stopEditing({ restore: true }));

  document.addEventListener("dragstart", (event) => {
    if (!editing) return;
    const handle = event.target.closest(".site-edit-handle");
    if (!handle) return;
    const target = handle._siteDragTarget || handle.parentElement;
    if (!isMovable(target)) return;
    dragEl = target;
    target.classList.add("is-site-dragging");
    event.dataTransfer.effectAllowed = "move";
    const ref = itemRef(target);
    event.dataTransfer.setData("text/plain", ref ? `${ref.attr}:${ref.key}` : "move");
    try {
      event.dataTransfer.setDragImage(target, 24, 24);
    } catch (_) {
      /* ignore */
    }
  });

  document.addEventListener("dragend", () => {
    if (!dragEl) return;
    dragEl.classList.remove("is-site-dragging");
    dragEl = null;
  });

  document.addEventListener("dragover", (event) => {
    if (!editing || !dragEl) return;
    const parent = dragEl.parentElement;
    if (!parent || !editRoot().contains(parent)) return;
    // Keep moves among siblings so template saves stay reliable.
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    const after = getDragAfterElement(parent, event.clientY);
    if (!after) placeElement(parent, dragEl, null);
    else if (after !== dragEl) placeElement(parent, dragEl, after);
  });

  document.addEventListener("dragover", (event) => {
    if (!editing || dragEl) return;
    const img = event.target.closest("img[data-site-edit]");
    if (!img) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    img.classList.add("is-site-image-drop");
  });

  document.addEventListener("dragleave", (event) => {
    const img = event.target.closest("img[data-site-edit]");
    if (img) img.classList.remove("is-site-image-drop");
  });

  document.addEventListener("drop", async (event) => {
    if (!editing) return;
    if (dragEl) {
      event.preventDefault();
      return;
    }
    const img = event.target.closest("img[data-site-edit]");
    if (!img) return;
    event.preventDefault();
    event.stopPropagation();
    img.classList.remove("is-site-image-drop");
    const file = event.dataTransfer?.files?.[0];
    if (file) await applyImageFile(img, file);
  });

  document.addEventListener("click", (event) => {
    if (!editing) return;
    if (event.target.closest(".site-edit-handle")) {
      event.preventDefault();
      return;
    }
    const img = event.target.closest("img[data-site-edit]");
    if (!img) return;
    event.preventDefault();
    event.stopPropagation();
    activeImage = img;
    fileInput.value = "";
    fileInput.click();
  }, true);

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files?.[0];
    if (!file || !activeImage) return;
    await applyImageFile(activeImage, file);
    activeImage = null;
  });

  document.addEventListener("click", (event) => {
    if (!editing) return;
    const link = event.target.closest("a");
    if (!link || link.closest(".site-edit-bar")) return;
    if (link.hasAttribute("data-site-edit") || link.closest("[data-site-block]")) {
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
