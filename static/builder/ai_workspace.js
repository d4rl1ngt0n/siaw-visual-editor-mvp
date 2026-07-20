(() => {
  const wizard = document.getElementById("wizard");
  const form = document.getElementById("briefForm");
  // Browser refresh should start clean, not restore the autosaved draft.
  const nav = performance.getEntriesByType("navigation")[0];
  if (nav && nav.type === "reload" && wizard?.dataset.freshUrl) {
    window.location.replace(wizard.dataset.freshUrl);
    return;
  }
  const state = window.SIAW_BRIEF || {};
  state.starting_point = "new";
  const TOTAL_STEPS = 2;
  const MAX_GOALS = 3;
  const OTHER_GOAL = "other";
  const MIN_OTHER_CHARS = 3;
  const MIN_DESCRIPTION_CHARS = Number(wizard?.dataset.minDescriptionChars || 40);

  const GOAL_CATALOG = {
    leads: { title: "Generate enquiries", desc: "Turn visitors into qualified leads." },
    book: { title: "Book appointments", desc: "Make scheduling the natural next step." },
    sell: { title: "Sell products", desc: "Show products and encourage purchases." },
    services: { title: "Present services", desc: "Explain expertise with clarity." },
    credibility: { title: "Build credibility", desc: "Establish trust and authority." },
    event: { title: "Promote an event", desc: "Drive registrations and attendance." },
    community: { title: "Grow a community", desc: "Invite people to participate." },
    portfolio: { title: "Display a portfolio", desc: "Let excellent work lead the story." },
    reserve: { title: "Take reservations", desc: "Make booking a table or visit effortless." },
    hire: { title: "Attract talent", desc: "Help the right people join your team." },
    donate: { title: "Drive donations", desc: "Make supporting the cause simple." },
    educate: { title: "Explain the offer", desc: "Help people understand what you teach." },
    menu: { title: "Show the menu", desc: "Highlight dishes, drinks, and what to order." },
    membership: { title: "Sell memberships", desc: "Make joining or renewing feel simple." },
    trial: { title: "Start free trials", desc: "Get people into the product quickly." },
    listings: { title: "Showcase listings", desc: "Help people browse and enquire on properties." },
    quote: { title: "Request a quote", desc: "Make getting a price the clear next step." },
  };

  const INDUSTRY_GOALS = {
    "Restaurants and hospitality": ["reserve", "menu", "event", "sell", "community"],
    "Health and wellness": ["book", "services", "educate", "credibility", "leads"],
    "Fitness and sports": ["membership", "book", "community", "sell", "credibility"],
    "Beauty and personal care": ["book", "services", "sell", "credibility", "leads"],
    "Professional services": ["leads", "quote", "services", "credibility", "book"],
    "Legal and accounting": ["leads", "book", "services", "credibility", "educate"],
    "Finance and insurance": ["leads", "educate", "services", "credibility", "book"],
    "Real estate": ["listings", "leads", "book", "credibility", "portfolio"],
    "Construction and trades": ["quote", "leads", "portfolio", "services", "credibility"],
    "Ecommerce and retail": ["sell", "community", "credibility", "event", "leads"],
    "Fashion and lifestyle": ["sell", "portfolio", "community", "event", "credibility"],
    "Technology and SaaS": ["trial", "leads", "educate", "hire", "credibility"],
    "Creative agencies and studios": ["portfolio", "leads", "services", "hire", "credibility"],
    "Education and coaching": ["educate", "book", "sell", "community", "leads"],
    "Nonprofit and community": ["donate", "community", "event", "credibility", "leads"],
    "Events and entertainment": ["event", "sell", "community", "leads", "credibility"],
    "Travel and tourism": ["book", "sell", "event", "community", "credibility"],
    "Automotive and mobility": ["sell", "book", "quote", "services", "leads"],
    "Home services": ["quote", "book", "leads", "services", "credibility"],
    Other: ["leads", "services", "credibility", "sell", "book"],
  };

  try {
    const ctaNode = document.getElementById("initial-primary-cta");
    state.primary_cta = ctaNode ? JSON.parse(ctaNode.textContent) : {};
  } catch (_) {
    state.primary_cta = {};
  }
  try {
    const redesignNode = document.getElementById("initial-redesign");
    state.redesign_json = redesignNode ? JSON.parse(redesignNode.textContent) : {};
  } catch (_) {
    state.redesign_json = {};
  }

  state.goals = Array.isArray(state.primary_cta?.goals)
    ? state.primary_cta.goals.filter(Boolean).slice(0, MAX_GOALS)
    : state.primary_goal
      ? [state.primary_goal]
      : [];
  state.customGoal = String(state.primary_cta?.other || "").trim();
  if (state.customGoal && !state.goals.includes(OTHER_GOAL)) {
    state.goals = [OTHER_GOAL, ...state.goals].slice(0, MAX_GOALS);
  } else if (state.goals.includes(OTHER_GOAL)) {
    state.goals = [OTHER_GOAL, ...state.goals.filter((value) => value !== OTHER_GOAL)].slice(
      0,
      MAX_GOALS
    );
  }

  let goalsQuestion = null;
  try {
    const questionNode = document.getElementById("initial-goals-question");
    goalsQuestion = questionNode ? JSON.parse(questionNode.textContent) : null;
  } catch (_) {
    goalsQuestion = null;
  }

  let step = Math.min(TOTAL_STEPS, Math.max(1, Number(document.body.dataset.step) || 1));
  if (step > TOTAL_STEPS) step = TOTAL_STEPS;
  let timer;

  function csrf() {
    return form.querySelector("[name=csrfmiddlewaretoken]").value;
  }

  function setSave(text, busy = false) {
    const el = document.getElementById("saveState");
    el.textContent = text;
    el.classList.toggle("busy", busy);
  }

  function collect() {
    const result = {};
    form.querySelectorAll("[data-field]").forEach((el) => {
      result[el.dataset.field] = el.value;
    });
    form.querySelectorAll("[data-json-group]").forEach((el) => {
      const group = el.dataset.jsonGroup;
      result[group] = result[group] || structuredClone(state[group] || {});
      result[group][el.dataset.jsonKey] = el.value;
    });
    result.starting_point = state.starting_point || "";
    const customGoal = String(state.customGoal || "").trim().slice(0, 160);
    // Keep Other selected even before the user finishes typing. Stripping it here
    // was hiding the input as soon as autosave ran.
    let goals = prioritizeOther([...state.goals]);
    if (customGoal && !goals.includes(OTHER_GOAL)) {
      goals = prioritizeOther([OTHER_GOAL, ...goals]);
    }
    state.goals = goals;
    result.primary_goal = goals[0] || "";
    result.primary_cta = {
      ...(state.primary_cta || {}),
      goals,
      other: customGoal,
    };
    state.primary_cta = result.primary_cta;
    result.redesign_json = state.redesign_json || {};
    return result;
  }

  async function save(extra = {}) {
    clearTimeout(timer);
    setSave("Saving…", true);
    const payload = { ...collect(), ...extra };
    try {
      const response = await fetch(wizard.dataset.saveUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf(), Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      const raw = await response.text();
      let data = {};
      try {
        data = raw ? JSON.parse(raw) : {};
      } catch {
        // login_required / CSRF failures return HTML, which used to surface as Unexpected token '<'
        if (
          response.status === 401 ||
          response.status === 403 ||
          response.redirected ||
          /^\s*<!doctype/i.test(raw) ||
          /<\s*html/i.test(raw)
        ) {
          setSave("Session expired. Sign in to continue…");
          const next = encodeURIComponent(window.location.pathname + window.location.search);
          window.location.href = `/login/?next=${next}`;
          return false;
        }
        throw new Error("Could not save. Try again.");
      }
      if (!response.ok) {
        throw new Error(Object.values(data.fields || {})[0] || data.error || "Could not save");
      }
      if (data.goalsQuestion && typeof data.goalsQuestion === "object") {
        goalsQuestion = data.goalsQuestion;
        applyGoalsQuestion();
        // Do not rebuild the goals grid while the custom outcome field is focused.
        const otherInput = document.getElementById("goalOtherInput");
        const editingOther = Boolean(otherInput && document.activeElement === otherInput);
        if (step === 2 && !editingOther) renderGoals();
        else if (step === 2) syncOtherPanel();
      }
      const prefetch = data.prefetch || {};
      if (prefetch.ready) {
        setSave("Saved · site ready");
      } else if (prefetch.building || prefetch.prefetchStarted) {
        const pct = Number(prefetch.progressPct || 0);
        setSave(pct > 0 ? `Saved · building ${pct}%` : "Saved · building in background…");
      } else if (prefetch.promptChars > 0) {
        setSave("Saved · prompt updated");
      } else {
        setSave("All changes saved");
      }
      return true;
    } catch (error) {
      setSave(error.message);
      return false;
    }
  }

  function queueSave() {
    clearTimeout(timer);
    timer = setTimeout(() => save(), 650);
    setSave("Unsaved changes", true);
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }
  function escapeAttr(value) {
    return escapeHtml(value).replace(/"/g, "&quot;");
  }

  function industryGoals() {
    const industry = (document.getElementById("industrySelect")?.value || state.industry || "").trim();
    if (
      goalsQuestion &&
      Array.isArray(goalsQuestion.goals) &&
      goalsQuestion.goals.length &&
      (!goalsQuestion.industry || goalsQuestion.industry === industry)
    ) {
      return goalsQuestion.goals
        .map((item) => ({
          value: item.value,
          title: item.title || GOAL_CATALOG[item.value]?.title,
          desc: item.desc || GOAL_CATALOG[item.value]?.desc,
        }))
        .filter((item) => item.value && item.title);
    }
    const keys = INDUSTRY_GOALS[industry] || INDUSTRY_GOALS.Other;
    return keys.map((value) => ({ value, ...GOAL_CATALOG[value] })).filter((item) => item.title);
  }

  function applyGoalsQuestion() {
    const headline = document.getElementById("goalsHeadline");
    const lead = document.getElementById("goalsLead");
    if (!goalsQuestion) return;
    if (headline && goalsQuestion.headline) headline.textContent = goalsQuestion.headline;
    if (lead && goalsQuestion.lead) lead.textContent = goalsQuestion.lead;
  }

  function prioritizeOther(goals) {
    const list = Array.isArray(goals) ? goals : [];
    const next = list.filter((value) => value !== OTHER_GOAL);
    if (list.includes(OTHER_GOAL)) {
      return [OTHER_GOAL, ...next].slice(0, MAX_GOALS);
    }
    return next.slice(0, MAX_GOALS);
  }

  function syncOtherPanel() {
    const panel = document.getElementById("goalOtherPanel");
    const input = document.getElementById("goalOtherInput");
    const selected = state.goals.includes(OTHER_GOAL);
    if (panel) panel.hidden = !selected;
    if (input && document.activeElement !== input) {
      input.value = state.customGoal || "";
    }
  }

  function selectOtherGoal() {
    const rest = state.goals.filter((value) => value !== OTHER_GOAL);
    if (rest.length >= MAX_GOALS) {
      rest.pop();
    }
    state.goals = [OTHER_GOAL, ...rest].slice(0, MAX_GOALS);
  }

  function renderGoals() {
    const grid = document.getElementById("goalGrid");
    const hint = document.getElementById("goalHint");
    const count = document.getElementById("goalCount");
    const industryLabel = document.getElementById("goalIndustryLabel");
    const industry = (document.getElementById("industrySelect")?.value || state.industry || "").trim();
    applyGoalsQuestion();
    const options = industryGoals();
    const allowed = new Set(options.map((item) => item.value));
    state.goals = prioritizeOther(
      state.goals.filter((value) => value === OTHER_GOAL || allowed.has(value))
    );

    hint.hidden = Boolean(industry);
    if (industryLabel) {
      industryLabel.hidden = !industry;
      industryLabel.textContent =
        (goalsQuestion && goalsQuestion.industryLabel) ||
        (industry ? `Goals for ${industry}` : "");
    }
    count.textContent = `${state.goals.length} of ${MAX_GOALS} selected`;
    grid.innerHTML = "";
    grid.dataset.industry = industry || "";

    if (!industry) {
      grid.innerHTML = '<p class="goal-empty">Choose an industry on the Idea step to unlock goals.</p>';
      syncOtherPanel();
      return;
    }

    const allOptions = [
      ...options,
      {
        value: OTHER_GOAL,
        title: "Other",
        desc: "Type your own outcome. We will treat it as the top priority.",
        isOther: true,
      },
    ];

    allOptions.forEach((option) => {
      const selected = state.goals.includes(option.value);
      const atLimit = !selected && state.goals.length >= MAX_GOALS;
      const button = document.createElement("button");
      button.type = "button";
      button.className = `choice compact${option.isOther ? " is-other" : ""}${selected ? " selected" : ""}${atLimit ? " is-disabled" : ""}`;
      button.dataset.value = option.value;
      button.setAttribute("aria-pressed", String(selected));
      button.innerHTML = `<strong>${escapeHtml(option.title)}</strong><span>${escapeHtml(option.desc)}</span>`;
      button.addEventListener("click", () => {
        if (option.value === OTHER_GOAL) {
          if (selected) {
            state.goals = state.goals.filter((value) => value !== OTHER_GOAL);
          } else {
            selectOtherGoal();
            window.setTimeout(() => document.getElementById("goalOtherInput")?.focus(), 0);
          }
        } else if (selected) {
          state.goals = state.goals.filter((value) => value !== option.value);
        } else if (state.goals.length < MAX_GOALS) {
          state.goals = prioritizeOther([...state.goals, option.value]);
        } else {
          return;
        }
        renderGoals();
        queueSave();
      });
      grid.append(button);
    });
    syncOtherPanel();
  }

  function showStep() {
    document.querySelectorAll("[data-step-panel]").forEach((el) => {
      el.classList.toggle("active", Number(el.dataset.stepPanel) === step);
    });
    document.querySelectorAll("[data-nav-step]").forEach((el) => {
      const nav = Number(el.dataset.navStep);
      el.classList.toggle("active", nav === step);
      el.classList.toggle("done", nav < step);
    });
    document.getElementById("progressBar").style.width = `${(step / TOTAL_STEPS) * 100}%`;
    document.getElementById("backBtn").disabled = step === 1;
    document.getElementById("nextBtn").textContent =
      step === TOTAL_STEPS ? "Continue →" : "Continue →";
    document.body.dataset.step = step;
    if (step === 2) renderGoals();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function validate() {
    const message = document.getElementById("validation");
    let error = "";
    if (step === 1) {
      const missing = [...document.querySelectorAll('[data-step-panel="1"] [required]')].find(
        (el) => !String(el.value || "").trim()
      );
      if (missing) {
        error = "Complete the required idea details.";
        missing.focus();
      } else {
        const description = document.querySelector('[data-field="description"]');
        const text = String(description?.value || "").trim();
        if (text.length < MIN_DESCRIPTION_CHARS) {
          error = `Add a bit more detail about your idea (at least ${MIN_DESCRIPTION_CHARS} characters).`;
          description?.focus();
        }
      }
    }
    if (step === 2) {
      if (!document.getElementById("industrySelect")?.value) {
        error = "Select an industry first, then choose up to three goals.";
      } else if (!state.goals.length) {
        error = "Select at least one goal (up to three).";
      } else if (state.goals.includes(OTHER_GOAL)) {
        const custom = String(state.customGoal || "").trim();
        if (custom.length < MIN_OTHER_CHARS) {
          error = "Type your custom outcome, or deselect Other.";
          document.getElementById("goalOtherInput")?.focus();
        }
      }
    }
    message.textContent = error;
    return !error;
  }

  document.getElementById("nextBtn").onclick = async () => {
    if (!validate()) return;
    if (!(await save({ current_step: Math.min(TOTAL_STEPS + 1, step + 1) }))) return;
    if (step === TOTAL_STEPS) {
      location.href = wizard.dataset.reviewUrl;
      return;
    }
    step += 1;
    showStep();
  };

  document.getElementById("backBtn").onclick = () => {
    if (step > 1) {
      step -= 1;
      showStep();
      save({ current_step: step });
    }
  };

  form.addEventListener("input", (e) => {
    if (!e.target.matches("input,textarea,select")) return;
    if (e.target.id === "goalOtherInput") {
      state.customGoal = String(e.target.value || "").slice(0, 160);
      if (!state.goals.includes(OTHER_GOAL)) {
        selectOtherGoal();
        renderGoals();
        window.setTimeout(() => document.getElementById("goalOtherInput")?.focus(), 0);
      } else {
        const count = document.getElementById("goalCount");
        if (count) count.textContent = `${state.goals.length} of ${MAX_GOALS} selected`;
      }
      queueSave();
      return;
    }
    if (e.target.id === "industrySelect" || e.target.dataset.field === "industry") {
      state.industry = e.target.value;
      state.goals = state.goals.includes(OTHER_GOAL) ? [OTHER_GOAL] : [];
      if (step === 2) renderGoals();
    }
    queueSave();
  });
  form.addEventListener("change", (e) => {
    if (e.target?.id === "industrySelect" || e.target?.dataset?.field === "industry") {
      state.industry = e.target.value;
      state.goals = state.goals.includes(OTHER_GOAL) ? [OTHER_GOAL] : [];
      if (step === 2) renderGoals();
    }
  });

  document.getElementById("goalOtherInput")?.addEventListener("focus", () => {
    if (!state.goals.includes(OTHER_GOAL)) {
      selectOtherGoal();
      renderGoals();
    }
  });

  let assets = [];
  try {
    const assetsNode = document.getElementById("initial-assets");
    assets = assetsNode ? JSON.parse(assetsNode.textContent) : [];
  } catch (_) {
    assets = [];
  }
  if (!Array.isArray(assets)) assets = [];

  function assetDetailUrl(assetId) {
    const template = wizard.dataset.assetUrlTemplate || "";
    return template.replace(/\/0\/?$/, `/${assetId}/`).replace("/0/", `/${assetId}/`);
  }

  function renderAssets() {
    const gallery = document.getElementById("assetGallery");
    if (!gallery) return;
    if (!assets.length) {
      gallery.innerHTML = '<p class="asset-empty">No files uploaded yet. Add a logo so it can brand the generated site.</p>';
      return;
    }
    gallery.innerHTML = "";
    assets.forEach((asset) => {
      const card = document.createElement("figure");
      card.className = `asset-card${asset.type === "logo" ? " is-logo" : ""}`;
      const preview = asset.isImage
        ? `<img src="${asset.url}" alt="${escapeAttr(asset.name)}" loading="lazy">`
        : `<div class="asset-file-fallback" aria-hidden="true">PDF</div>`;
      card.innerHTML = `
        ${preview}
        <figcaption>
          <strong>${escapeHtml(asset.name)}</strong>
          <span>${asset.type === "logo" ? "Logo" : asset.type === "document" ? "Document" : "Image"}</span>
        </figcaption>
        <div class="asset-card-actions">
          ${
            asset.isImage && asset.type !== "logo"
              ? `<button type="button" data-asset-logo="${asset.id}">Use as logo</button>`
              : asset.type === "logo"
                ? `<span class="asset-logo-badge">Logo</span>`
                : ""
          }
          <button type="button" class="is-danger" data-asset-delete="${asset.id}" aria-label="Remove ${escapeAttr(asset.name)}">Remove</button>
        </div>
      `;
      gallery.append(card);
    });
  }

  document.getElementById("assetGallery")?.addEventListener("click", async (event) => {
    const logoBtn = event.target.closest("[data-asset-logo]");
    const deleteBtn = event.target.closest("[data-asset-delete]");
    const status = document.getElementById("assetStatus");
    if (logoBtn) {
      const id = logoBtn.getAttribute("data-asset-logo");
      const response = await fetch(assetDetailUrl(id), {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ asset_type: "logo" }),
      });
      const data = await response.json();
      if (!response.ok) {
        status.textContent = data.error || "Could not set logo.";
        return;
      }
      assets = assets.map((item) => ({
        ...item,
        type: String(item.id) === String(id) ? "logo" : item.type === "logo" ? "image" : item.type,
      }));
      renderAssets();
      status.textContent = "Logo updated. This file will brand the generated site.";
      return;
    }
    if (deleteBtn) {
      const id = deleteBtn.getAttribute("data-asset-delete");
      const response = await fetch(assetDetailUrl(id), {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ action: "delete" }),
      });
      const data = await response.json();
      if (!response.ok) {
        status.textContent = data.error || "Could not remove file.";
        return;
      }
      assets = assets.filter((item) => String(item.id) !== String(id));
      renderAssets();
      status.textContent = "File removed.";
    }
  });

  const assetInput = document.getElementById("assetInput");
  assetInput?.addEventListener("change", async () => {
    const status = document.getElementById("assetStatus");
    const typeSelect = document.getElementById("assetTypeSelect");
    for (const file of assetInput.files) {
      status.textContent = `Uploading ${file.name}…`;
      const body = new FormData();
      body.append("file", file);
      let assetType = typeSelect?.value || "image";
      if (file.type === "application/pdf") assetType = "document";
      else if (/logo/i.test(file.name) && assetType === "image") assetType = "logo";
      body.append("asset_type", assetType);
      const response = await fetch(wizard.dataset.uploadUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrf() },
        body,
      });
      const data = await response.json();
      if (!response.ok) {
        status.textContent = data.error || "Upload failed";
        continue;
      }
      if (data.asset) {
        if (data.asset.type === "logo") {
          assets = assets.map((item) => (item.type === "logo" ? { ...item, type: "image" } : item));
        }
        assets = [data.asset, ...assets.filter((item) => item.id !== data.asset.id)];
        renderAssets();
      }
      status.textContent =
        data.asset?.type === "logo"
          ? `${file.name} uploaded as logo.`
          : `${file.name} uploaded.`;
    }
    assetInput.value = "";
  });

  renderAssets();

  const industrySelect = document.getElementById("industrySelect");
  if (industrySelect && state.industry) {
    const match = [...industrySelect.options].find((opt) => opt.value === state.industry || opt.textContent === state.industry);
    if (match) industrySelect.value = match.value || match.textContent;
    else if (state.industry) {
      const custom = document.createElement("option");
      custom.value = state.industry;
      custom.textContent = state.industry;
      industrySelect.append(custom);
      industrySelect.value = state.industry;
    }
  }

  const languageField = form.querySelector('[data-field="language"]');
  if (languageField) languageField.value = state.language || "English";
  showStep();
})();
