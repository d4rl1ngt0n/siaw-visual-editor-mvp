(() => {
  const tabs = document.querySelectorAll("[data-create-tab]");
  const panels = document.querySelectorAll("[data-create-panel]");
  const activateTab = (name) => {
    tabs.forEach((tab) => {
      const active = tab.getAttribute("data-create-tab") === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    panels.forEach((panel) => {
      panel.classList.toggle("is-hidden", panel.getAttribute("data-create-panel") !== name);
    });
  };
  window.siawActivateCreateTab = activateTab;
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => activateTab(tab.getAttribute("data-create-tab") || "ai"));
  });

  const generateForm = document.querySelector("[data-generate-form]");
  const generateSubmit = document.querySelector("[data-generate-submit]");
  generateForm?.addEventListener("submit", () => {
    if (!generateSubmit) return;
    generateSubmit.disabled = true;
    generateSubmit.textContent = "Generating website…";
  });
})();

(() => {
  const root = document.querySelector("[data-ai-builder]");
  if (!root) return;

  const steps = {
    gate: root.querySelector('[data-ai-step="gate"]'),
    help: root.querySelector('[data-ai-step="help"]'),
    compose: root.querySelector('[data-ai-step="compose"]'),
  };
  const page = document.querySelector(".ai-build-page");
  const lead = document.querySelector("[data-ai-heading-lead]");
  const composeNote = root.querySelector("[data-ai-compose-note]");
  const helpForm = root.querySelector("[data-ai-help-form]");
  const journey = root.querySelector("[data-ai-journey]");
  const slides = [...(root.querySelectorAll("[data-ai-slide]") || [])];
  const stageBoard = root.querySelector("[data-ai-journey-stage]");
  const stageCard = root.querySelector("[data-ai-stage-card]");
  const building = root.querySelector("[data-ai-building]");
  const buildingTitle = root.querySelector("[data-ai-building-title]");
  const buildingLead = root.querySelector("[data-ai-building-lead]");
  const buildingSteps = [...(root.querySelectorAll("[data-build-step]") || [])];
  const backBtn = root.querySelector("[data-ai-journey-back]");
  const progressLabel = root.querySelector("[data-ai-progress-label]");
  const progressPct = root.querySelector("[data-ai-progress-pct]");
  const progressBar = root.querySelector("[data-ai-progress-bar]");
  const progressFill = root.querySelector("[data-ai-progress-fill]");
  const sectorValue = root.querySelector("[data-ai-sector-value]");
  const sectorDisplay = root.querySelector("[data-ai-sector-display]");
  const mustInput = root.querySelector("[data-ai-must-input]");
  const floatCards = [...(root.querySelectorAll("[data-ai-float]") || [])];
  const answerTrail = root.querySelector("[data-ai-answer-trail]");
  const nameInput = root.querySelector('#generateForm input[name="name"]');
  const promptInput = root.querySelector('#generateForm textarea[name="prompt"]');
  const draftUrl = root.getAttribute("data-draft-prompt-url") || "/projects/draft-prompt/";
  const totalSlides = slides.length || 5;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let slideIndex = 0;
  let drafting = false;
  let buildTimer = null;

  const ANSWER_META = [
    { key: "brand", label: "Brand" },
    { key: "sector", label: "Industry" },
    { key: "market", label: "Audience" },
    { key: "goal_tone", label: "Goal & feel" },
    { key: "must_include", label: "Must include" },
  ];

  const FLOAT_BY_SLIDE = [
    [
      { value: "Harbor & Hearth", text: "A warm restaurant or cafe brand" },
      { value: "Northline Studio", text: "A clean agency or studio name" },
      { value: "Lumen Clinic", text: "A calm health or wellness brand" },
      { value: "Atlas Goods", text: "A product shop or ecommerce brand" },
    ],
    [
      { value: "restaurant / cafe", text: "Restaurant or cafe" },
      { value: "saas / software", text: "SaaS or software product" },
      { value: "beauty / wellness", text: "Beauty or wellness brand" },
      { value: "agency / services", text: "Agency or local services" },
    ],
    [
      { value: "Accra, couples booking weekend dinners", text: "Local diners booking a night out" },
      { value: "Online, founders launching a first product", text: "Founders launching something new" },
      { value: "London, busy professionals booking wellness", text: "Busy professionals nearby" },
      { value: "Global, creative freelancers finding clients", text: "Creatives looking for clients" },
    ],
    [
      { value: "Book a table. Warm, candlelit, premium but welcoming.", text: "Book a visit with a warm premium feel" },
      { value: "Start a free trial. Clear, modern, confident.", text: "Start a trial with a confident tone" },
      { value: "Enquire today. Calm, trustworthy, human.", text: "Enquire with a calm, human tone" },
      { value: "Shop the collection. Bold, editorial, playful.", text: "Shop with a bold editorial feel" },
    ],
    [
      { value: "Hero with clear CTA", text: "A strong hero and clear CTA" },
      { value: "Services or menu", text: "Services or menu section" },
      { value: "About / story", text: "About or brand story" },
      { value: "Contact form", text: "Contact or booking form" },
    ],
  ];

  const readCookie = (name) => {
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : "";
  };

  const csrfToken = () =>
    document.querySelector("[name=csrfmiddlewaretoken]")?.value || readCookie("csrftoken") || "";

  const showFlowStep = (name) => {
    Object.entries(steps).forEach(([key, el]) => {
      if (!el) return;
      el.hidden = key !== name;
    });
    page?.classList.toggle("is-journey", name === "help");
    page?.classList.toggle("is-compose", name === "compose");
    if (lead) {
      if (name === "gate") {
        lead.textContent = "Start with a short guided brief, or paste a prompt you already wrote.";
      } else if (name === "help") {
        lead.textContent = "One question at a time. Your answers stack into a brief.";
      } else if (name === "compose") {
        const start = (root.getAttribute("data-ai-start") || "").trim().toLowerCase();
        if (lead.dataset.fromJourney === "1") {
          lead.textContent = "Review the brief, then generate a full editable website.";
        } else if (start === "compose" || start === "prompt") {
          lead.textContent =
            "Advanced path: paste a finished prompt. For most sites, the guided brief is faster and more reliable.";
        } else {
          lead.textContent = "Paste or edit your prompt, then generate an editable site.";
        }
      }
    }
  };

  const fieldValue = (name) => {
    if (name === "sector") {
      const hidden = String(sectorValue?.value || "").trim();
      if (hidden) return hidden;
      return String(sectorDisplay?.value || "").trim();
    }
    const el = helpForm?.elements?.namedItem(name);
    if (!el) return "";
    return String(el.value || "").trim();
  };

  const syncSectorFromDisplay = () => {
    const typed = String(sectorDisplay?.value || "").trim();
    if (typed && sectorValue) sectorValue.value = typed;
  };

  const updateProgress = () => {
    const step = Math.min(slideIndex + 1, totalSlides);
    const pct = Math.round((step / totalSlides) * 100);
    if (progressLabel) progressLabel.textContent = `Question ${step} of ${totalSlides}`;
    if (progressPct) progressPct.textContent = `${pct}%`;
    if (progressFill) progressFill.style.width = `${pct}%`;
    if (progressBar) progressBar.setAttribute("aria-valuenow", String(step));
  };

  const renderAnswerTrail = () => {
    if (!answerTrail) return;
    const cards = ANSWER_META
      .slice(0, slideIndex)
      .map((item) => {
        const value = fieldValue(item.key);
        if (!value) return "";
        return `<article class="ai-answer-card" data-ai-answer-key="${item.key}">
          <span>${item.label}</span>
          <strong>${value.replace(/</g, "&lt;")}</strong>
        </article>`;
      })
      .filter(Boolean);
    answerTrail.innerHTML = cards.join("");
    answerTrail.hidden = cards.length === 0;
  };

  const renderFloatCards = () => {
    const options = FLOAT_BY_SLIDE[slideIndex] || [];
    floatCards.forEach((card, i) => {
      const option = options[i];
      if (!option) {
        card.hidden = true;
        card.removeAttribute("data-ai-float-value");
        return;
      }
      card.hidden = false;
      card.setAttribute("data-ai-float-value", option.value);
      const text = card.querySelector(".ai-float-text");
      if (text) text.textContent = option.text;
      card.classList.toggle("is-selected", fieldValue(slides[slideIndex]?.getAttribute("data-ai-field") || "") === option.value);
    });
  };

  const focusActive = () => {
    const active = slides[slideIndex];
    const target = active?.querySelector("[data-ai-autofocus], input, textarea");
    window.setTimeout(() => target?.focus?.(), reduceMotion ? 0 : 220);
  };

  const setSlide = (index, { animate = true } = {}) => {
    slideIndex = Math.max(0, Math.min(index, totalSlides - 1));
    slides.forEach((slide, i) => {
      const active = i === slideIndex;
      slide.hidden = !active;
      slide.classList.toggle("is-active", active);
      if (active && animate && !reduceMotion) {
        slide.classList.remove("is-enter");
        void slide.offsetWidth;
        slide.classList.add("is-enter");
      }
    });
    if (stageCard && animate && !reduceMotion) {
      stageCard.classList.remove("is-enter");
      void stageCard.offsetWidth;
      stageCard.classList.add("is-enter");
    }
    if (backBtn) backBtn.textContent = slideIndex === 0 ? "Start over" : "Back";
    if (slideIndex === 1 && sectorDisplay && sectorValue?.value && !sectorDisplay.value) {
      sectorDisplay.value = sectorValue.value;
    }
    updateProgress();
    renderAnswerTrail();
    renderFloatCards();
    focusActive();
  };

  const validateSlide = () => {
    if (slideIndex === 1) syncSectorFromDisplay();
    if (slideIndex === 0) return Boolean(fieldValue("brand"));
    if (slideIndex === 1) return Boolean(fieldValue("sector"));
    if (slideIndex === 2) return Boolean(fieldValue("market"));
    if (slideIndex === 3) return Boolean(fieldValue("goal_tone"));
    return true;
  };

  const shakeActive = () => {
    const target = stageCard || slides[slideIndex];
    if (!target) return;
    target.classList.remove("is-shake");
    void target.offsetWidth;
    target.classList.add("is-shake");
  };

  const setBuildingVisible = (visible) => {
    if (stageBoard) stageBoard.hidden = visible;
    if (answerTrail && visible) answerTrail.hidden = true;
    if (!visible) renderAnswerTrail();
    if (building) building.hidden = !visible;
    journey?.classList.toggle("is-building", visible);
    if (progressFill && visible) progressFill.style.width = "100%";
    if (progressLabel && visible) progressLabel.textContent = "Building your brief";
    if (progressPct && visible) progressPct.textContent = "100%";
  };

  const stopBuildAnimation = () => {
    if (buildTimer) {
      window.clearInterval(buildTimer);
      buildTimer = null;
    }
    buildingSteps.forEach((el) => el.classList.remove("is-active", "is-done"));
  };

  const startBuildAnimation = () => {
    stopBuildAnimation();
    let step = 0;
    const mark = () => {
      buildingSteps.forEach((el, i) => {
        el.classList.toggle("is-done", i < step);
        el.classList.toggle("is-active", i === step);
      });
    };
    mark();
    buildTimer = window.setInterval(() => {
      if (step < buildingSteps.length - 1) {
        step += 1;
        mark();
      }
    }, reduceMotion ? 900 : 700);
  };

  const applyDraft = (prompt, name, note) => {
    if (nameInput && !nameInput.value.trim() && name) nameInput.value = String(name).slice(0, 160);
    if (promptInput) promptInput.value = prompt;
    if (composeNote) {
      composeNote.hidden = false;
      composeNote.textContent = note;
    }
    if (lead) lead.dataset.fromJourney = "1";
    setBuildingVisible(false);
    stopBuildAnimation();
    showFlowStep("compose");
    promptInput?.focus();
  };

  const resetJourney = () => {
    drafting = false;
    stopBuildAnimation();
    setBuildingVisible(false);
    helpForm?.reset();
    if (sectorValue) sectorValue.value = "";
    if (sectorDisplay) sectorDisplay.value = "";
    setSlide(0, { animate: false });
  };

  const goNext = () => {
    if (drafting) return;
    if (!validateSlide()) {
      shakeActive();
      focusActive();
      return;
    }
    if (slideIndex >= totalSlides - 1) {
      void draftPrompt();
      return;
    }
    setSlide(slideIndex + 1);
  };

  const draftPrompt = async () => {
    syncSectorFromDisplay();
    const payload = {
      brand: fieldValue("brand"),
      sector: fieldValue("sector"),
      market: fieldValue("market"),
      goal_tone: fieldValue("goal_tone"),
      must_include: fieldValue("must_include"),
    };
    if (!payload.brand || !payload.sector || !payload.market || !payload.goal_tone) return;

    drafting = true;
    setBuildingVisible(true);
    startBuildAnimation();
    if (buildingTitle) buildingTitle.textContent = "Crafting your brief…";
    if (buildingLead) buildingLead.textContent = "Turning your answers into a clear website prompt.";

    try {
      const response = await fetch(draftUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
        },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.prompt) {
        throw new Error(data.error || "Could not draft the prompt.");
      }
      buildingSteps.forEach((el, i) => {
        el.classList.toggle("is-done", true);
        el.classList.toggle("is-active", i === buildingSteps.length - 1);
      });
      if (buildingTitle) buildingTitle.textContent = "Brief ready";
      if (buildingLead) buildingLead.textContent = "Opening the editor prompt so you can tweak anything.";
      await new Promise((resolve) => window.setTimeout(resolve, reduceMotion ? 120 : 480));
      const usedAi = Boolean(data.used_ai);
      const model = data.model ? ` (${data.model})` : "";
      const note = usedAi
        ? `Prompt drafted with AI${model}. Edit anything, then generate.`
        : "Prompt drafted from your answers. Edit anything, then generate.";
      applyDraft(data.prompt, data.name || payload.brand, note);
    } catch (err) {
      setBuildingVisible(false);
      stopBuildAnimation();
      if (typeof window.siawAlert === "function") {
        window.siawAlert({
          title: "Could not draft prompt",
          message: err?.message || "Could not reach the AI helper. Try again in a moment.",
        });
      } else {
        window.alert(err?.message || "Could not draft the prompt.");
      }
    } finally {
      drafting = false;
    }
  };

  root.querySelectorAll("[data-ai-have-prompt]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (composeNote) composeNote.hidden = true;
      showFlowStep("compose");
      promptInput?.focus();
    });
  });

  root.querySelectorAll("[data-ai-need-help]").forEach((btn) => {
    btn.addEventListener("click", () => {
      resetJourney();
      showFlowStep("help");
    });
  });

  root.querySelector("[data-ai-float-cards]")?.addEventListener("click", (event) => {
    const card = event.target.closest("[data-ai-float]");
    if (!card || drafting || card.hidden) return;
    const value = card.getAttribute("data-ai-float-value") || "";
    if (!value) return;
    const field = slides[slideIndex]?.getAttribute("data-ai-field");
    if (field === "brand") {
      const input = helpForm?.elements?.namedItem("brand");
      if (input) input.value = value;
    } else if (field === "sector") {
      if (sectorValue) sectorValue.value = value;
      if (sectorDisplay) sectorDisplay.value = value;
    } else if (field === "market") {
      const input = helpForm?.elements?.namedItem("market");
      if (input) input.value = value;
    } else if (field === "goal_tone") {
      const input = helpForm?.elements?.namedItem("goal_tone");
      if (input) input.value = value;
    } else if (field === "must_include" && mustInput) {
      const parts = mustInput.value
        .split(",")
        .map((part) => part.trim())
        .filter(Boolean);
      if (!parts.includes(value)) parts.push(value);
      mustInput.value = parts.join(", ");
      renderFloatCards();
      return;
    }
    renderFloatCards();
    window.setTimeout(() => {
      if (!drafting) goNext();
    }, reduceMotion ? 0 : 220);
  });

  answerTrail?.addEventListener("click", (event) => {
    const card = event.target.closest("[data-ai-answer-key]");
    if (!card || drafting) return;
    const key = card.getAttribute("data-ai-answer-key");
    const index = ANSWER_META.findIndex((item) => item.key === key);
    if (index >= 0) setSlide(index);
  });

  backBtn?.addEventListener("click", () => {
    if (drafting) return;
    if (slideIndex === 0) {
      showFlowStep("gate");
      return;
    }
    setSlide(slideIndex - 1);
  });

  root.querySelectorAll("[data-ai-journey-next]").forEach((btn) => {
    btn.addEventListener("click", goNext);
  });

  helpForm?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    if (event.target?.tagName === "TEXTAREA" && !event.metaKey && !event.ctrlKey) return;
    event.preventDefault();
    goNext();
  });

  helpForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    goNext();
  });

  window.siawShowAiCompose = () => {
    if (composeNote) composeNote.hidden = true;
    showFlowStep("compose");
  };

  setSlide(0, { animate: false });

  const startMode = (root.getAttribute("data-ai-start") || "").trim().toLowerCase();
  if (startMode === "help") {
    resetJourney();
    showFlowStep("help");
  } else if (startMode === "compose" || startMode === "prompt") {
    if (composeNote) composeNote.hidden = true;
    showFlowStep("compose");
  }
})();

(() => {
  const root = document.querySelector("[data-hero-edit]");
  if (!root) return;

  const headline = root.querySelector("[data-hero-headline]");
  const status = root.querySelector("[data-hero-edit-status]");
  const caret = root.querySelector("[data-hero-caret]");
  if (!headline) return;

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const lines = [
    "Prompt a site. Edit by hand.",
    "Click any line. Rewrite it live.",
  ];

  if (reduceMotion) {
    if (status) status.textContent = "Click to edit";
    return;
  }

  const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

  const typeText = async (el, text) => {
    el.textContent = "";
    el.classList.add("is-typing");
    if (caret) {
      caret.hidden = false;
      el.after(caret);
    }
    for (let i = 0; i < text.length; i += 1) {
      el.textContent = text.slice(0, i + 1);
      await sleep(42 + (text[i] === " " ? 28 : 0));
    }
    el.classList.remove("is-typing");
    if (caret) caret.hidden = true;
  };

  const rewriteHeadline = async (nextText) => {
    if (status) status.textContent = "Editing";
    headline.classList.add("is-selected");
    root.classList.add("is-editing");
    await sleep(900);

    headline.classList.remove("is-selected");
    headline.classList.add("is-clearing");
    await sleep(280);
    headline.classList.remove("is-clearing");
    await typeText(headline, nextText);
    if (status) status.textContent = "Saved";
    root.classList.remove("is-editing");
    await sleep(2600);
    if (status) status.textContent = "Click to edit";
  };

  const loop = async () => {
    let index = 0;
    while (document.body.contains(root)) {
      if (
        document.body.classList.contains("is-site-editing")
        || document.body.classList.contains("site-edit-active")
        || root.hasAttribute("data-hero-edit-paused")
      ) {
        await sleep(800);
        continue;
      }
      await sleep(3200);
      index = (index + 1) % lines.length;
      await rewriteHeadline(lines[index]);
    }
  };

  loop();
})();

(() => {
  const form = document.querySelector("#uploadForm");
  if (!form) return;

  const fileInput = form.querySelector('input[name="website_zip"]');
  const folderInput = form.querySelector("[data-folder-input]");
  const folderButton = form.querySelector("[data-pick-folder]");
  const entryInput = form.querySelector("[data-entry-file], input[name='entry_file']");
  const nameInput = form.querySelector('input[name="name"]');
  const dropLabel = form.querySelector(".file-drop");
  const dropTitle = dropLabel?.querySelector("strong");
  const dropHint = dropLabel?.querySelector("small");
  const preview = document.querySelector("[data-upload-preview]");
  if (!fileInput || !preview) return;

  const previewFrame = preview.querySelector("[data-preview-frame]");
  const previewFrameWrap = preview.querySelector("[data-preview-frame-wrap]");
  const previewCode = preview.querySelector("[data-preview-code]");
  const previewMeta = preview.querySelector("[data-preview-meta]");
  const previewFiles = preview.querySelector("[data-preview-files]");
  const previewStatus = preview.querySelector("[data-preview-status]");
  const clearButton = preview.querySelector("[data-preview-clear]");

  const sideImport = document.querySelector("[data-side-import]");
  const emptyDrop = document.querySelector("[data-empty-drop]");
  const sideReady = document.querySelector("[data-side-ready]");
  const sideMeta = document.querySelector("[data-side-preview-meta]");
  const sideStatus = document.querySelector("[data-side-preview-status]");
  const sideFiles = document.querySelector("[data-side-preview-files]");
  const sideFrame = document.querySelector("[data-side-preview-frame]");
  const sideFrameWrap = document.querySelector("[data-side-preview-frame-wrap]");
  const sideCode = document.querySelector("[data-side-preview-code]");
  const sideName = document.querySelector("[data-side-name]");
  const sideClear = document.querySelector("[data-side-clear]");

  let ingestSource = "left";

  const PREFERRED_ENTRY_NAMES = [
    "index.html", "index.htm", "default.html", "default.htm",
    "home.html", "home.htm", "main.html", "app.html",
    "main.tsx", "main.jsx", "main.ts", "main.js",
    "app.tsx", "app.jsx", "app.vue", "app.svelte",
    "manage.py", "package.json", "readme.md",
  ];

  const SKIP_DIR_NAMES = new Set([
    "node_modules", ".git", "__pycache__", ".venv", "venv", ".tox",
    ".mypy_cache", ".pytest_cache", ".next", ".nuxt", ".svelte-kit",
    ".turbo", ".parcel-cache", ".cache", "coverage", ".idea", ".vscode",
    ".cursor", "__macosx",
  ]);

  let activeObjectUrl = "";
  let selectedEntryPath = "";

  function revokePreviewUrl() {
    if (activeObjectUrl) {
      URL.revokeObjectURL(activeObjectUrl);
      activeObjectUrl = "";
    }
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function setEntryPath(path) {
    selectedEntryPath = path || "";
    if (entryInput) entryInput.value = selectedEntryPath;
  }

  function resetDropCopy() {
    if (dropTitle) dropTitle.textContent = "Select ZIP or HTML file";
    if (dropHint) dropHint.textContent = "Maximum 25 MB after packing.";
    dropLabel?.classList.remove("has-file");
  }

  function syncSideNameFromForm() {
    if (sideName && nameInput) sideName.value = nameInput.value;
  }

  function syncFormNameFromSide() {
    if (sideName && nameInput) nameInput.value = sideName.value;
  }

  function setSideReadyVisible(show) {
    if (!sideImport) return;
    if (emptyDrop) emptyDrop.hidden = show;
    if (sideReady) sideReady.hidden = !show;
  }

  function hidePreview() {
    revokePreviewUrl();
    preview.hidden = true;
    preview.classList.remove("is-visible");
    if (previewFrame) previewFrame.removeAttribute("src");
    if (sideFrame) sideFrame.removeAttribute("src");
    if (previewCode) {
      previewCode.hidden = true;
      previewCode.textContent = "";
    }
    if (sideCode) {
      sideCode.hidden = true;
      sideCode.textContent = "";
    }
    if (previewFrameWrap) previewFrameWrap.hidden = false;
    if (sideFrameWrap) sideFrameWrap.hidden = false;
    if (previewMeta) previewMeta.textContent = "";
    if (sideMeta) sideMeta.textContent = "";
    if (previewFiles) previewFiles.innerHTML = "";
    if (sideFiles) sideFiles.innerHTML = "";
    if (previewStatus) previewStatus.textContent = "";
    if (sideStatus) sideStatus.textContent = "";
    if (sideName) sideName.value = "";
    setEntryPath("");
    resetDropCopy();
    setSideReadyVisible(false);
    ingestSource = "left";
  }

  function showPreviewShell(label, sizeBytes, statusText) {
    const metaText = `${label} · ${formatBytes(sizeBytes)}`;
    dropLabel?.classList.add("has-file");
    if (dropTitle) dropTitle.textContent = label;
    if (dropHint) dropHint.textContent = `${formatBytes(sizeBytes)} ready to import`;
    if (previewMeta) previewMeta.textContent = metaText;
    if (sideMeta) sideMeta.textContent = metaText;
    if (previewStatus) previewStatus.textContent = statusText || "";
    if (sideStatus) sideStatus.textContent = statusText || "";

    if (nameInput && !nameInput.value.trim()) {
      nameInput.value = label.replace(/\.(zip|html|htm|js|ts|tsx|jsx|vue|svelte|py|json|md|txt)$/i, "").replace(/[-_]+/g, " ").trim();
    }
    syncSideNameFromForm();

    // When the empty projects panel exists, show the ready card there.
    // Keep the left form pickers, but put the main preview/import on the right.
    if (sideImport) {
      preview.hidden = true;
      preview.classList.remove("is-visible");
      setSideReadyVisible(true);
    } else {
      preview.hidden = false;
      preview.classList.add("is-visible");
    }
  }

  function showPreviewError(message) {
    showPreviewShell("Import issue", 0, "");
    if (previewMeta) previewMeta.textContent = message;
    if (sideMeta) sideMeta.textContent = message;
    if (previewStatus) previewStatus.textContent = "";
    if (sideStatus) sideStatus.textContent = "";
    if (previewFiles) previewFiles.innerHTML = "";
    if (sideFiles) sideFiles.innerHTML = "";
    if (previewCode) {
      previewCode.hidden = true;
      previewCode.textContent = "";
    }
    if (sideCode) {
      sideCode.hidden = true;
      sideCode.textContent = "";
    }
    if (previewFrameWrap) previewFrameWrap.hidden = true;
    if (sideFrameWrap) sideFrameWrap.hidden = true;
  }

  function setFrameHtml(htmlText) {
    revokePreviewUrl();
    if (previewFrameWrap) previewFrameWrap.hidden = false;
    if (sideFrameWrap) sideFrameWrap.hidden = false;
    if (previewCode) {
      previewCode.hidden = true;
      previewCode.textContent = "";
    }
    if (sideCode) {
      sideCode.hidden = true;
      sideCode.textContent = "";
    }
    const blob = new Blob([htmlText], { type: "text/html" });
    activeObjectUrl = URL.createObjectURL(blob);
    if (previewFrame) previewFrame.src = activeObjectUrl;
    if (sideFrame) sideFrame.src = activeObjectUrl;
  }

  function setCodePreview(text, path) {
    revokePreviewUrl();
    if (previewFrame) previewFrame.removeAttribute("src");
    if (sideFrame) sideFrame.removeAttribute("src");
    if (previewFrameWrap) previewFrameWrap.hidden = true;
    if (sideFrameWrap) sideFrameWrap.hidden = true;
    const clipped = text.length > 4000 ? `${text.slice(0, 4000)}\n…` : text;
    const content = clipped || `(empty file: ${path})`;
    if (previewCode) {
      previewCode.hidden = false;
      previewCode.textContent = content;
    }
    if (sideCode) {
      sideCode.hidden = false;
      sideCode.textContent = content;
    }
  }

  function preferredEntryScore(path) {
    const name = path.split("/").pop().toLowerCase();
    const preferred = PREFERRED_ENTRY_NAMES.indexOf(name);
    const depth = path.split("/").filter(Boolean).length;
    const htmlBoost = /\.(html|htm|xhtml)$/i.test(name) ? 0 : 50;
    return [preferred === -1 ? 100 + htmlBoost : preferred, depth, path.toLowerCase()];
  }

  function compareEntries(a, b) {
    const left = preferredEntryScore(a);
    const right = preferredEntryScore(b);
    for (let i = 0; i < left.length; i += 1) {
      if (left[i] < right[i]) return -1;
      if (left[i] > right[i]) return 1;
    }
    return 0;
  }

  function renderFileListInto(container, paths, entryPath) {
    if (!container) return;
    container.innerHTML = "";
    const unique = [...new Set(paths)].sort(compareEntries).slice(0, 12);
    unique.forEach((path) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = path;
      if (path === entryPath) item.classList.add("is-entry");
      button.addEventListener("click", () => {
        setEntryPath(path);
        [previewFiles, sideFiles].forEach((list) => {
          if (!list) return;
          [...list.children].forEach((child) => {
            const label = child.querySelector("button")?.textContent || "";
            child.classList.toggle("is-entry", label === path);
          });
        });
        const statusText = `Entry set to ${path}. Click import when ready.`;
        if (previewStatus) previewStatus.textContent = statusText;
        if (sideStatus) sideStatus.textContent = statusText;
      });
      item.appendChild(button);
      container.appendChild(item);
    });
    if (paths.length > unique.length) {
      const more = document.createElement("li");
      more.className = "is-more";
      more.textContent = `+${paths.length - unique.length} more files`;
      container.appendChild(more);
    }
  }

  function renderFileList(paths, entryPath) {
    renderFileListInto(previewFiles, paths, entryPath);
    renderFileListInto(sideFiles, paths, entryPath);
  }

  async function inflateRaw(bytes) {
    if (typeof DecompressionStream === "undefined") {
      throw new Error("This browser cannot preview compressed ZIP entries.");
    }
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
    const buffer = await new Response(stream).arrayBuffer();
    return new Uint8Array(buffer);
  }

  function readU16(view, offset) {
    return view.getUint16(offset, true);
  }

  function readU32(view, offset) {
    return view.getUint32(offset, true);
  }

  const CRC_TABLE = (() => {
    const table = new Uint32Array(256);
    for (let i = 0; i < 256; i += 1) {
      let value = i;
      for (let j = 0; j < 8; j += 1) {
        value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
      }
      table[i] = value >>> 0;
    }
    return table;
  })();

  function crc32(bytes) {
    let crc = 0xffffffff;
    for (let i = 0; i < bytes.length; i += 1) {
      crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
    }
    return (crc ^ 0xffffffff) >>> 0;
  }

  function concatBytes(chunks) {
    const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const output = new Uint8Array(total);
    let offset = 0;
    chunks.forEach((chunk) => {
      output.set(chunk, offset);
      offset += chunk.length;
    });
    return output;
  }

  function u16(value) {
    const bytes = new Uint8Array(2);
    new DataView(bytes.buffer).setUint16(0, value, true);
    return bytes;
  }

  function u32(value) {
    const bytes = new Uint8Array(4);
    new DataView(bytes.buffer).setUint32(0, value, true);
    return bytes;
  }

  async function createStoreZip(entries) {
    const localChunks = [];
    const centralChunks = [];
    let offset = 0;

    for (const entry of entries) {
      const nameBytes = new TextEncoder().encode(entry.name);
      const data = entry.data;
      const checksum = crc32(data);
      const local = concatBytes([
        u32(0x04034b50),
        u16(20),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(checksum),
        u32(data.length),
        u32(data.length),
        u16(nameBytes.length),
        u16(0),
        nameBytes,
        data,
      ]);
      localChunks.push(local);

      const central = concatBytes([
        u32(0x02014b50),
        u16(20),
        u16(20),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(checksum),
        u32(data.length),
        u32(data.length),
        u16(nameBytes.length),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(0),
        u32(offset),
        nameBytes,
      ]);
      centralChunks.push(central);
      offset += local.length;
    }

    const centralDirectory = concatBytes(centralChunks);
    const end = concatBytes([
      u32(0x06054b50),
      u16(0),
      u16(0),
      u16(entries.length),
      u16(entries.length),
      u32(centralDirectory.length),
      u32(offset),
      u16(0),
    ]);
    return concatBytes([...localChunks, centralDirectory, end]);
  }

  function shouldSkipRelativePath(relativePath) {
    return relativePath.split("/").some((part) => SKIP_DIR_NAMES.has(part.toLowerCase()) || part === ".DS_Store");
  }

  function normalizeFolderEntries(fileList) {
    // Accept FileList from <input webkitdirectory> or [{ relativePath, file }] from showDirectoryPicker.
    if (Array.isArray(fileList) && fileList[0] && fileList[0].relativePath) {
      return fileList.filter((item) => item.relativePath && !shouldSkipRelativePath(item.relativePath));
    }
    return [...fileList]
      .map((file) => ({
        relativePath: file.webkitRelativePath || file.name,
        file,
      }))
      .filter((item) => item.relativePath && !shouldSkipRelativePath(item.relativePath));
  }

  async function walkDirectoryHandle(dirHandle, prefix = "") {
    const collected = [];
    for await (const [name, handle] of dirHandle.entries()) {
      if (SKIP_DIR_NAMES.has(name.toLowerCase()) || name === ".DS_Store") continue;
      const relativePath = prefix ? `${prefix}/${name}` : name;
      if (handle.kind === "directory") {
        collected.push(...await walkDirectoryHandle(handle, relativePath));
        continue;
      }
      if (handle.kind === "file") {
        collected.push({ relativePath, file: await handle.getFile() });
      }
    }
    return collected;
  }

  async function zipFolderFiles(fileList, folderNameHint = "") {
    const items = normalizeFolderEntries(fileList);
    if (!items.length) throw new Error("That folder has no importable files.");

    // Strip the shared top-level folder name so archives match ZIP uploads.
    // showDirectoryPicker paths are already relative to the chosen folder (no prefix).
    const first = items[0].relativePath;
    const hasSharedRoot = items.every((item) => item.relativePath.includes("/"))
      && items.every((item) => item.relativePath.split("/")[0] === first.split("/")[0])
      && Boolean(items[0].file?.webkitRelativePath);
    const rootPrefix = hasSharedRoot ? `${first.split("/")[0]}/` : "";
    const entries = [];
    for (const item of items) {
      const relative = item.relativePath;
      const name = rootPrefix && relative.startsWith(rootPrefix) ? relative.slice(rootPrefix.length) : relative;
      if (!name) continue;
      entries.push({ name, data: new Uint8Array(await item.file.arrayBuffer()) });
    }
    if (!entries.length) throw new Error("That folder has no importable files.");

    const zipBytes = await createStoreZip(entries);
    if (zipBytes.length > 25 * 1024 * 1024) {
      throw new Error("Packed folder is larger than 25 MB. Remove node_modules/build output or zip a smaller subset.");
    }
    const folderName = folderNameHint || rootPrefix.replace(/\/$/, "") || "project";
    return {
      file: new File([zipBytes], `${folderName}.zip`, { type: "application/zip" }),
      paths: entries.map((entry) => entry.name),
    };
  }

  async function packSelectedFolder(fileList, folderNameHint = "") {
    showPreviewShell("Packing folder…", 0, "Skipping node_modules and other tooling folders…");
    const packed = await zipFolderFiles(fileList, folderNameHint);
    assignFileToInput(packed.file);
    await previewSelectedFile(packed.file, packed.paths);
    if (sideImport) {
      sideReady?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      sideName?.focus();
    } else {
      form.scrollIntoView({ behavior: "smooth", block: "nearest" });
      nameInput?.focus();
    }
  }

  function assignFileToInput(file) {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    fileInput.files = transfer.files;
    window.dispatchEvent(new CustomEvent("siaw:upload-selected", {
      detail: {
        file,
        name: nameInput?.value || "",
        entryFile: entryInput?.value || "",
      },
    }));
  }

  async function fileLooksLikeZip(file) {
    const header = new Uint8Array(await file.slice(0, 4).arrayBuffer());
    if (header.length < 4 || header[0] !== 0x50 || header[1] !== 0x4b) return false;
    const third = header[2];
    const fourth = header[3];
    return (
      (third === 0x03 && fourth === 0x04) ||
      (third === 0x05 && fourth === 0x06) ||
      (third === 0x07 && fourth === 0x08)
    );
  }

  async function extractZipEntry(bytes, entry) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const localOffset = entry.localHeaderOffset;
    if (readU32(view, localOffset) !== 0x04034b50) {
      throw new Error("Could not read the selected file from this ZIP.");
    }
    const localNameLength = readU16(view, localOffset + 26);
    const localExtraLength = readU16(view, localOffset + 28);
    const dataStart = localOffset + 30 + localNameLength + localExtraLength;
    const compressed = bytes.subarray(dataStart, dataStart + entry.compressedSize);
    if (entry.compression === 0) return compressed;
    if (entry.compression === 8) return inflateRaw(compressed);
    throw new Error("This ZIP uses a compression type the preview cannot open.");
  }

  async function readZipPreview(file) {
    const buffer = await file.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    const view = new DataView(buffer);

    let end = bytes.length - 22;
    while (end >= 0) {
      if (readU32(view, end) === 0x06054b50) break;
      end -= 1;
    }
    if (end < 0) throw new Error("This ZIP archive looks invalid.");

    const count = readU16(view, end + 10);
    let offset = readU32(view, end + 16);
    const entries = [];

    for (let i = 0; i < count; i += 1) {
      if (readU32(view, offset) !== 0x02014b50) break;
      const compression = readU16(view, offset + 10);
      const compressedSize = readU32(view, offset + 20);
      const nameLength = readU16(view, offset + 28);
      const extraLength = readU16(view, offset + 30);
      const commentLength = readU16(view, offset + 32);
      const localHeaderOffset = readU32(view, offset + 42);
      const nameStart = offset + 46;
      const name = new TextDecoder().decode(bytes.subarray(nameStart, nameStart + nameLength));
      offset = nameStart + nameLength + extraLength + commentLength;

      if (!name || name.endsWith("/") || shouldSkipRelativePath(name)) continue;
      entries.push({ name, compression, compressedSize, localHeaderOffset });
    }

    if (!entries.length) throw new Error("No files were found inside this ZIP.");

    const ranked = [...entries].map((entry) => entry.name).sort(compareEntries);
    const entryPath = ranked[0];
    const entry = entries.find((item) => item.name === entryPath);
    const raw = await extractZipEntry(bytes, entry);
    const text = new TextDecoder("utf-8", { fatal: false }).decode(raw);
    return {
      entryPath,
      paths: entries.map((item) => item.name),
      text,
      isHtml: /\.(html|htm|xhtml)$/i.test(entryPath),
    };
  }

  async function previewSelectedFile(file, extraPaths = null) {
    const lower = file.name.toLowerCase();
    const isHtml = /\.(html|htm|xhtml)$/i.test(lower);
    const isZip = lower.endsWith(".zip") || (await fileLooksLikeZip(file));
    const isText = /\.(css|js|mjs|cjs|jsx|ts|tsx|vue|svelte|py|json|md|txt|php|rb|yml|yaml|toml)$/i.test(lower);

    if (file.size > 25 * 1024 * 1024) {
      showPreviewError("File is larger than 25 MB.");
      return;
    }

    showPreviewShell(file.name, file.size, "Building preview…");
    if (previewFiles) previewFiles.innerHTML = "";

    try {
      if (isZip) {
        const zipPreview = await readZipPreview(file);
        setEntryPath(zipPreview.entryPath);
        if (zipPreview.isHtml) setFrameHtml(zipPreview.text);
        else setCodePreview(zipPreview.text, zipPreview.entryPath);
        renderFileList(extraPaths || zipPreview.paths, zipPreview.entryPath);
        if (previewStatus) {
          previewStatus.textContent = zipPreview.isHtml
            ? `Previewing ${zipPreview.entryPath}. Click a file below to change the entry, then import.`
            : `Source project detected. Entry: ${zipPreview.entryPath}. Visual canvas needs an HTML file; other files open in the code editor.`;
        }
        return;
      }

      if (isHtml) {
        const htmlText = await file.text();
        setEntryPath(file.name);
        setFrameHtml(htmlText);
        renderFileList([file.name], file.name);
        if (previewStatus) previewStatus.textContent = "HTML preview ready. Click import when it looks right.";
        return;
      }

      if (isText) {
        const text = await file.text();
        setEntryPath(file.name);
        setCodePreview(text, file.name);
        renderFileList([file.name], file.name);
        if (previewStatus) previewStatus.textContent = "Source file ready. It will open in the code editor after import.";
        return;
      }

      showPreviewError("Please choose a folder, .zip, HTML file, or common source file.");
    } catch (error) {
      revokePreviewUrl();
      if (previewFrame) previewFrame.removeAttribute("src");
      showPreviewError(error instanceof Error ? error.message : "Could not preview this file.");
    }
  }

  async function handleFileChange() {
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      hidePreview();
      window.dispatchEvent(new CustomEvent("siaw:upload-cleared"));
      return;
    }
    window.dispatchEvent(new CustomEvent("siaw:upload-selected", {
      detail: {
        file,
        name: nameInput?.value || "",
        entryFile: entryInput?.value || "",
      },
    }));
    await previewSelectedFile(file);
  }

  async function requestFolderPick(source = "left") {
    ingestSource = source;

    // Prefer File System Access API: avoids Chrome's "Upload N files to this site?" dialog.
    // That prompt only appears for <input webkitdirectory>, which we keep as a fallback.
    if (typeof window.showDirectoryPicker === "function") {
      try {
        const dirHandle = await window.showDirectoryPicker({ mode: "read" });
        showPreviewShell("Reading folder…", 0, "Skipping node_modules and other tooling folders…");
        const entries = await walkDirectoryHandle(dirHandle);
        await packSelectedFolder(entries, dirHandle.name || "project");
      } catch (error) {
        if (error && (error.name === "AbortError" || error.name === "SecurityError")) return;
        showPreviewError(error instanceof Error ? error.message : "Could not open that folder.");
      }
      return;
    }

    folderInput?.click();
  }

  folderButton?.addEventListener("click", () => {
    void requestFolderPick("left");
  });
  dropLabel?.addEventListener("click", () => {
    ingestSource = "left";
  });

  folderInput?.addEventListener("change", async () => {
    const list = folderInput.files;
    if (!list || !list.length) return;
    try {
      await packSelectedFolder(list);
    } catch (error) {
      showPreviewError(error instanceof Error ? error.message : "Could not pack that folder.");
    } finally {
      folderInput.value = "";
    }
  });

  fileInput.addEventListener("change", () => {
    void handleFileChange().then(() => {
      if (sideImport && fileInput.files?.length) {
        sideReady?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        sideName?.focus();
      }
    });
  });

  clearButton?.addEventListener("click", () => {
    fileInput.value = "";
    if (folderInput) folderInput.value = "";
    hidePreview();
    window.dispatchEvent(new CustomEvent("siaw:upload-cleared"));
  });

  async function ingestFiles(fileList, source = "left") {
    ingestSource = source;
    const files = [...(fileList || [])].filter(Boolean);
    if (!files.length) return;
    const looksLikeFolder = files.length > 1
      || files.some((file) => Boolean(file.webkitRelativePath && file.webkitRelativePath.includes("/")));
    try {
      if (looksLikeFolder) {
        await packSelectedFolder(files);
      } else {
        assignFileToInput(files[0]);
        await previewSelectedFile(files[0]);
        if (sideImport && (source === "right" || sideReady)) {
          sideReady?.scrollIntoView({ behavior: "smooth", block: "nearest" });
          sideName?.focus();
        } else {
          form.scrollIntoView({ behavior: "smooth", block: "nearest" });
          nameInput?.focus();
        }
      }
    } catch (error) {
      showPreviewError(error instanceof Error ? error.message : "Could not import that drop.");
      if (sideImport) sideReady?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      else form.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function bindDropTarget(target, { onClick, source = "left" } = {}) {
    if (!target) return;
    let dragDepth = 0;

    target.addEventListener("dragenter", (event) => {
      event.preventDefault();
      dragDepth += 1;
      target.classList.add("is-dragover");
    });
    target.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    });
    target.addEventListener("dragleave", (event) => {
      event.preventDefault();
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) target.classList.remove("is-dragover");
    });
    target.addEventListener("drop", (event) => {
      event.preventDefault();
      dragDepth = 0;
      target.classList.remove("is-dragover");
      void ingestFiles(event.dataTransfer?.files, source);
    });

    if (onClick) {
      target.addEventListener("click", (event) => {
        if (event.target.closest("button, a, input, label")) return;
        onClick(event);
      });
      target.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onClick(event);
        }
      });
    }
  }

  bindDropTarget(dropLabel, { source: "left" });

  const emptyPickFile = document.querySelector("[data-empty-pick-file]");
  const emptyPickFolder = document.querySelector("[data-empty-pick-folder]");
  bindDropTarget(emptyDrop, {
    source: "right",
    onClick: () => {
      ingestSource = "right";
      fileInput.click();
    },
  });
  emptyPickFile?.addEventListener("click", (event) => {
    event.stopPropagation();
    ingestSource = "right";
    fileInput.click();
  });
  emptyPickFolder?.addEventListener("click", (event) => {
    event.stopPropagation();
    void requestFolderPick("right");
  });

  sideName?.addEventListener("input", syncFormNameFromSide);
  nameInput?.addEventListener("input", syncSideNameFromForm);
  sideClear?.addEventListener("click", () => {
    fileInput.value = "";
    if (folderInput) folderInput.value = "";
    hidePreview();
    window.dispatchEvent(new CustomEvent("siaw:upload-cleared"));
  });
  form.addEventListener("submit", () => {
    syncFormNameFromSide();
    window.dispatchEvent(new CustomEvent("siaw:upload-cleared"));
  });

  window.siawRestoreUploadDraft = async ({ file, name, entryFile } = {}) => {
    if (!file) return;
    if (name && nameInput) nameInput.value = name;
    if (entryFile && entryInput) entryInput.value = entryFile;
    assignFileToInput(file);
    await previewSelectedFile(file);
    syncSideNameFromForm();
  };
})();

(() => {
  const AI_KEY = "siaw.draft.ai";
  const META_KEY = "siaw.draft.meta";
  const IDB_NAME = "siaw-drafts";
  const IDB_STORE = "blobs";
  const UPLOAD_KEY = "upload";

  const generateForm = document.querySelector("[data-generate-form]");
  const uploadForm = document.querySelector("#uploadForm");
  const nameAi = generateForm?.querySelector('input[name="name"]');
  const promptAi = generateForm?.querySelector('textarea[name="prompt"]');
  const nameUpload = uploadForm?.querySelector('input[name="name"]');
  const entryUpload = uploadForm?.querySelector('input[name="entry_file"]');

  const openDb = () => new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(IDB_STORE)) db.createObjectStore(IDB_STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error("Could not open draft storage."));
  });

  const idbPut = async (key, value) => {
    const db = await openDb();
    await new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, "readwrite");
      tx.objectStore(IDB_STORE).put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    db.close();
  };

  const idbGet = async (key) => {
    const db = await openDb();
    const value = await new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, "readonly");
      const req = tx.objectStore(IDB_STORE).get(key);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    db.close();
    return value;
  };

  const idbDelete = async (key) => {
    const db = await openDb();
    await new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, "readwrite");
      tx.objectStore(IDB_STORE).delete(key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    db.close();
  };

  const saveAiDraft = () => {
    const payload = {
      name: nameAi?.value || "",
      prompt: promptAi?.value || "",
      updatedAt: Date.now(),
    };
    if (!payload.name.trim() && !payload.prompt.trim()) {
      sessionStorage.removeItem(AI_KEY);
      return;
    }
    sessionStorage.setItem(AI_KEY, JSON.stringify(payload));
  };

  const saveMeta = (tab) => {
    sessionStorage.setItem(META_KEY, JSON.stringify({ tab, updatedAt: Date.now() }));
  };

  const readAiDraft = () => {
    try {
      return JSON.parse(sessionStorage.getItem(AI_KEY) || "null");
    } catch (_) {
      return null;
    }
  };

  const readMeta = () => {
    try {
      return JSON.parse(sessionStorage.getItem(META_KEY) || "null");
    } catch (_) {
      return null;
    }
  };

  nameAi?.addEventListener("input", saveAiDraft);
  promptAi?.addEventListener("input", saveAiDraft);
  nameUpload?.addEventListener("input", () => {
    const file = uploadForm?.querySelector('input[name="website_zip"]')?.files?.[0];
    if (!file) return;
    void idbPut(UPLOAD_KEY, {
      name: nameUpload.value || "",
      entryFile: entryUpload?.value || "",
      file,
      fileName: file.name,
      fileType: file.type,
      updatedAt: Date.now(),
    });
  });

  window.addEventListener("siaw:upload-selected", (event) => {
    const detail = event.detail || {};
    if (!detail.file) return;
    saveMeta("import");
    void idbPut(UPLOAD_KEY, {
      name: detail.name || nameUpload?.value || "",
      entryFile: detail.entryFile || entryUpload?.value || "",
      file: detail.file,
      fileName: detail.file.name,
      fileType: detail.file.type,
      updatedAt: Date.now(),
    });
  });

  window.addEventListener("siaw:upload-cleared", () => {
    void idbDelete(UPLOAD_KEY);
  });

  generateForm?.addEventListener("submit", () => {
    sessionStorage.removeItem(AI_KEY);
  });

  const flushDraftsBeforeAuth = async (tab) => {
    if (tab === "ai" || !tab) saveAiDraft();
    if (tab) saveMeta(tab);
    const fileInput = uploadForm?.querySelector('input[name="website_zip"]');
    const file = fileInput?.files?.[0];
    if (file) {
      await idbPut(UPLOAD_KEY, {
        name: nameUpload?.value || "",
        entryFile: entryUpload?.value || "",
        file,
        fileName: file.name,
        fileType: file.type,
        updatedAt: Date.now(),
      });
      saveMeta("import");
    }
  };

  document.querySelectorAll("[data-auth-continue]").forEach((link) => {
    link.addEventListener("click", (event) => {
      const tab = link.getAttribute("data-auth-continue") || "ai";
      event.preventDefault();
      void flushDraftsBeforeAuth(tab).finally(() => {
        window.location.href = link.href;
      });
    });
  });

  const showDraftNotice = async (message, restoredTab) => {
    if (document.documentElement.dataset.draftNoticeShown === "1") return;
    document.documentElement.dataset.draftNoticeShown = "1";
    const alertFn = typeof window.siawAlert === "function" ? window.siawAlert : null;
    if (alertFn) {
      await alertFn("", {
        eyebrow: "Draft restored",
        title: restoredTab === "import" ? "Your import is ready" : "Your AI prompt is ready",
        message,
        okLabel: restoredTab === "import" ? "Continue to import" : "Continue to generate",
      });
    }
    const panel = document.querySelector(
      restoredTab === "import" ? '[data-create-panel="import"]' : '[data-create-panel="ai"]'
    );
    const focusTarget =
      panel?.querySelector(restoredTab === "import" ? 'button[type="submit"], .primary-btn' : "[data-generate-submit], button[type='submit']")
      || panel?.querySelector("textarea, input:not([type='hidden'])");
    if (focusTarget && typeof focusTarget.focus === "function") {
      focusTarget.focus({ preventScroll: false });
      focusTarget.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  const DRAFT_MAX_AGE_MS = 24 * 60 * 60 * 1000;
  const isFresh = (stamp) => typeof stamp === "number" && (Date.now() - stamp) < DRAFT_MAX_AGE_MS;

  const restoreDrafts = async () => {
    let ai = readAiDraft();
    if (ai && !isFresh(ai.updatedAt)) {
      sessionStorage.removeItem(AI_KEY);
      ai = null;
    }
    let upload = await idbGet(UPLOAD_KEY).catch(() => null);
    if (upload && !isFresh(upload.updatedAt)) {
      await idbDelete(UPLOAD_KEY).catch(() => null);
      upload = null;
    }
    let meta = readMeta();
    if (meta && !isFresh(meta.updatedAt)) {
      sessionStorage.removeItem(META_KEY);
      meta = null;
    }

    let restoredTab = meta?.tab || null;
    let didRestore = false;

    if (ai && (ai.name || ai.prompt)) {
      if (nameAi && !nameAi.value) nameAi.value = ai.name || "";
      if (promptAi && !promptAi.value) promptAi.value = ai.prompt || "";
      restoredTab = restoredTab || "ai";
      didRestore = true;
    }

    if (upload?.file && typeof window.siawRestoreUploadDraft === "function") {
      await window.siawRestoreUploadDraft({
        file: upload.file,
        name: upload.name || "",
        entryFile: upload.entryFile || "",
      });
      restoredTab = "import";
      didRestore = true;
    }

    if (!didRestore) return;

    if (restoredTab && typeof window.siawActivateCreateTab === "function") {
      window.siawActivateCreateTab(restoredTab);
    }

    const fromAuth = /\/(login|signup)\/?/i.test(document.referrer || "");
    const workspace = document.querySelector("#workspace");
    const onPersonalWorkspace = /^\/workspace\/?$/i.test(window.location.pathname);
    if (workspace && (fromAuth || window.location.hash === "#workspace" || onPersonalWorkspace)) {
      if (!onPersonalWorkspace && window.location.hash !== "#workspace") {
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#workspace`);
      }
      if (!onPersonalWorkspace) {
        workspace.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    if (didRestore && restoredTab === "ai" && typeof window.siawShowAiCompose === "function") {
      window.siawShowAiCompose();
    }

    if (fromAuth) {
      if (restoredTab === "import") {
        void showDraftNotice(
          "We kept the file you selected before login. Review it in Import, then open it in the editor.",
          "import"
        );
      } else {
        void showDraftNotice(
          "We kept the prompt you wrote before login. Review it in AI Builder, then generate your site.",
          "ai"
        );
      }
    }
  };

  void restoreDrafts();
})();

(() => {
  // Surface form errors and error/warning flashes in a modal so they are not buried under Import.
  const flash = [...document.querySelectorAll(".messages .message.error, .messages .message.warning")]
    .map((el) => (el.textContent || "").trim())
    .filter(Boolean);
  const formErrors = [...document.querySelectorAll(".upload-form .error, .upload-form .errorlist li")]
    .map((el) => (el.textContent || "").trim())
    .filter(Boolean);
  const unique = [...new Set([...flash, ...formErrors])];
  if (!unique.length || typeof window.siawAlert !== "function") return;

  const combined = unique.join("\n\n");
  const needsUpgrade = /upgrade|plan allows|AI generations|active projects/i.test(combined);
  const accountUrl = document.body?.dataset?.accountUrl || "/account/#plan";

  document.querySelectorAll(".upload-form .error, .upload-form .errorlist li").forEach((el) => {
    el.setAttribute("data-dialog-handled", "1");
  });

  const importPanel = document.querySelector('[data-create-panel="import"]');
  const hasImportError = Boolean(
    [...(importPanel?.querySelectorAll(".error") || [])].some((el) => (el.textContent || "").trim())
  );
  if (hasImportError && typeof window.siawActivateCreateTab === "function") {
    window.siawActivateCreateTab("import");
  }

  void window.siawAlert("", {
    eyebrow: needsUpgrade ? "Plan limit" : "Needs attention",
    title: needsUpgrade ? "Upgrade to continue" : "Could not continue",
    message: needsUpgrade
      ? `${combined}\n\nUpgrade your plan to unlock more projects and AI generations.`
      : combined,
    buttons: needsUpgrade
      ? [
          { label: "Not now", value: "dismiss" },
          { label: "Upgrade plan", value: "upgrade", className: "siaw-dialog-btn-primary" },
        ]
      : [{ label: "Got it", value: "ok", className: "siaw-dialog-btn-primary" }],
  }).then((result) => {
    document.querySelectorAll(".messages .message.error, .messages .message.warning").forEach((el) => {
      el.setAttribute("hidden", "");
    });
    if (result === "upgrade") {
      window.location.href = accountUrl;
    }
  });
})();

(() => {
  document.querySelectorAll("[data-delete-project]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = form.getAttribute("data-project-name") || "this project";
      const confirmed = await siawConfirm("", {
        danger: true,
        confirmLabel: "Delete",
        cancelLabel: "Cancel",
        title: `Delete “${name}”?`,
        message: "This removes the project from your account. It cannot be undone.",
        eyebrow: "Delete project",
      });
      if (confirmed) form.submit();
    });
  });
})();
