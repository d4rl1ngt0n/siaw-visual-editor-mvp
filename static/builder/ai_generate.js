(() => {
  const form = document.querySelector("[data-generate-form]");
  const overlay = document.querySelector("[data-generate-overlay]");
  if (!form || !overlay) return;

  const pctEl = overlay.querySelector("[data-generate-pct]");
  const fillEl = overlay.querySelector("[data-generate-fill]");
  const statusEl = overlay.querySelector("[data-generate-status]");
  const titleEl = overlay.querySelector("[data-generate-title]");
  const stageEls = [...overlay.querySelectorAll("[data-generate-stage]")];
  const submitBtn =
    form.querySelector("[data-generate-submit]") || form.querySelector('[type="submit"]');
  const nameInput = form.querySelector('[name="name"]');
  const prefetchHint = document.querySelector("[data-prefetch-hint]");
  const statusUrl = form.dataset.statusUrl || "";
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const defaultSubmitLabel = submitBtn?.textContent?.trim() || "Generate website ✦";

  const statuses = statusUrl
    ? [
        "Reading your creative brief…",
        "Mapping pages and sections…",
        "Writing homepage copy…",
        "Laying out the design system…",
        "Composing navigation and CTAs…",
        "Tuning spacing and typography…",
        "Polishing responsive layouts…",
        "Packing assets for the editor…",
        "Almost ready to open…",
      ]
    : [
        "Reading your prompt…",
        "Mapping pages and sections…",
        "Writing homepage copy…",
        "Laying out the design system…",
        "Composing navigation and CTAs…",
        "Tuning spacing and typography…",
        "Polishing responsive layouts…",
        "Packing assets for the editor…",
        "Almost ready to open…",
      ];

  let pct = 0;
  let statusIndex = 0;
  let raf = 0;
  let statusTimer = 0;
  let stageTimer = 0;
  let pollTimer = 0;
  let startedAt = 0;
  let submitting = false;

  function csrf() {
    return form.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  }

  function syncTitle() {
    if (!titleEl) return;
    const name = (nameInput?.value || "").trim();
    titleEl.textContent = name ? `Building ${name}` : "Building your website";
  }

  function setPct(value) {
    pct = Math.max(0, Math.min(99, value));
    if (pctEl) pctEl.textContent = `${Math.round(pct)}%`;
    if (fillEl) fillEl.style.width = `${pct}%`;
    overlay.style.setProperty("--generate-pct", String(pct / 100));
  }

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  function setStage(index) {
    stageEls.forEach((el, i) => {
      el.classList.toggle("is-done", i < index);
      el.classList.toggle("is-active", i === index);
    });
  }

  function tick() {
    const elapsed = Date.now() - startedAt;
    // Ease toward ~92% over a few minutes so long Codex builds still feel alive.
    const target = 92 * (1 - Math.exp(-elapsed / 45000));
    const next = pct + (target - pct) * (reduceMotion ? 0.35 : 0.08);
    setPct(next);
    raf = window.requestAnimationFrame(tick);
  }

  function startOverlay(initialStatus) {
    syncTitle();
    overlay.hidden = false;
    overlay.setAttribute("aria-hidden", "false");
    document.body.classList.add("is-generating");
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Building…";
    }
    const seededPct = Number(initialStatus?.progressPct || 0);
    startedAt = Date.now();
    // If a background build already ran for a while, continue from that estimate.
    if (initialStatus?.startedAt) {
      const startedMs = Date.parse(initialStatus.startedAt);
      if (!Number.isNaN(startedMs)) startedAt = startedMs;
    }
    statusIndex = 0;
    setPct(
      initialStatus?.ready
        ? 88
        : seededPct > 0
          ? seededPct
          : initialStatus?.building
            ? 35
            : 2
    );
    setStatus(
      initialStatus?.ready
        ? "Opening your website…"
        : seededPct > 0
          ? `Continuing from ${Math.round(seededPct)}%…`
          : statuses[0]
    );
    setStage(initialStatus?.ready ? stageEls.length - 1 : seededPct > 50 ? 2 : 0);

    if (!reduceMotion) {
      raf = window.requestAnimationFrame(tick);
    } else {
      setPct(initialStatus?.building ? 45 : 35);
    }

    statusTimer = window.setInterval(() => {
      statusIndex = Math.min(statuses.length - 1, statusIndex + 1);
      setStatus(statuses[statusIndex]);
      setPct(Math.min(90, pct + (reduceMotion ? 8 : 3)));
    }, reduceMotion ? 2200 : 4200);

    let stage = 0;
    stageTimer = window.setInterval(() => {
      stage = Math.min(stageEls.length - 1, stage + 1);
      setStage(stage);
    }, reduceMotion ? 2800 : 5500);
  }

  function stopOverlayTimers() {
    window.cancelAnimationFrame(raf);
    window.clearInterval(statusTimer);
    window.clearInterval(stageTimer);
    window.clearInterval(pollTimer);
  }

  function finishAndRedirect(url) {
    stopOverlayTimers();
    setPct(100);
    setStatus("Opening in the editor…");
    setStage(stageEls.length - 1);
    window.setTimeout(() => {
      window.location.href = url;
    }, 350);
  }

  function updatePrefetchHint(payload) {
    if (!prefetchHint) return;
    const pct = Math.round(Number(payload.progressPct || 0));
    if (payload.ready) {
      prefetchHint.hidden = false;
      prefetchHint.textContent = "Your website is ready (~100%). Generate opens it instantly.";
      prefetchHint.classList.add("is-ready");
      return;
    }
    if (payload.failed) {
      prefetchHint.hidden = false;
      prefetchHint.textContent =
        payload.error || "Background build stopped. Generate will start a fresh build.";
      prefetchHint.classList.remove("is-ready");
      return;
    }
    if (payload.building) {
      prefetchHint.hidden = false;
      prefetchHint.textContent =
        pct > 0
          ? `Building in the background: about ${pct}% done. Keep reviewing.`
          : "Building in the background while you review…";
      prefetchHint.classList.remove("is-ready");
      return;
    }
    if (payload.promptChars > 0 || pct > 0) {
      prefetchHint.hidden = false;
      prefetchHint.textContent = "Master prompt ready. Background build starts as soon as possible.";
      prefetchHint.classList.remove("is-ready");
      return;
    }
    prefetchHint.hidden = true;
  }

  async function fetchStatus() {
    if (!statusUrl) return null;
    const response = await fetch(statusUrl, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    if (!response.ok) return null;
    return response.json();
  }

  async function claimOrStart() {
    const response = await fetch(form.action, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "X-CSRFToken": csrf(),
      },
      credentials: "same-origin",
      body: new URLSearchParams({ csrfmiddlewaretoken: csrf() }),
    });
    const data = await response.json().catch(() => ({}));
    if (response.ok && data.redirectUrl) {
      return { ready: true, redirectUrl: data.redirectUrl };
    }
    if (!response.ok) {
      return {
        ...data,
        ready: false,
        failed: Boolean(data.failed) || response.status >= 400,
        error: data.error || "Could not start generation.",
        building: false,
      };
    }
    if (data.building || response.status === 202) {
      if (data.building) {
        return { ...data, ready: false, building: true };
      }
      return {
        ...data,
        ready: false,
        failed: true,
        building: false,
        error: data.error || "Could not start generation.",
      };
    }
    return data;
  }

  async function pollUntilReady() {
    const maxMs = 12 * 60 * 1000;
    const started = Date.now();
    let restartAttempted = false;
    while (Date.now() - started < maxMs) {
      const status = await fetchStatus();
      if (status?.progressPct) {
        setPct(Math.max(pct, Number(status.progressPct)));
      }
      if (status?.ready) {
        const claimed = await claimOrStart();
        if (claimed.redirectUrl) {
          finishAndRedirect(claimed.redirectUrl);
          return;
        }
        // Ready in status but claim failed: do not spin forever.
        if (claimed.failed || claimed.error) {
          throw new Error(claimed.error || "The prepared site could not be opened.");
        }
      }
      if (status?.failed) {
        if (!restartAttempted) {
          restartAttempted = true;
          setStatus("Previous build stopped. Starting a fresh build…");
          const restarted = await claimOrStart();
          if (restarted.redirectUrl) {
            finishAndRedirect(restarted.redirectUrl);
            return;
          }
          if (restarted.failed || restarted.error) {
            throw new Error(restarted.error || status.error || "Background build failed.");
          }
        } else {
          throw new Error(status.error || "Background build failed. Try Generate again.");
        }
      }
      if (!status?.building && !status?.ready && !status?.failed) {
        if (!restartAttempted) {
          restartAttempted = true;
          setStatus("Starting the website build…");
          const restarted = await claimOrStart();
          if (restarted.redirectUrl) {
            finishAndRedirect(restarted.redirectUrl);
            return;
          }
          if (restarted.failed || restarted.error || !restarted.building) {
            throw new Error(
              restarted.error || status?.error || "Could not start the website build."
            );
          }
        } else {
          throw new Error(status?.error || "Background build failed. Try Generate again.");
        }
      }
      await new Promise((resolve) => {
        pollTimer = window.setTimeout(resolve, 1500);
      });
    }
    throw new Error("The build is taking longer than expected. Refresh and try again.");
  }

  // Background status while the user reads the summary (wizard review only).
  async function watchBackground() {
    if (!statusUrl) return;
    const tickStatus = async () => {
      try {
        const status = await fetchStatus();
        if (status) updatePrefetchHint(status);
      } catch (_) {
        /* ignore */
      }
    };
    tickStatus();
    window.setInterval(tickStatus, 4000);
  }

  form.addEventListener("submit", async (event) => {
    // Compose / paste-prompt flow: normal blocking POST. Show overlay and let the browser submit.
    if (!statusUrl) {
      if (submitting) {
        event.preventDefault();
        return;
      }
      submitting = true;
      startOverlay({});
      return;
    }

    event.preventDefault();
    if (submitting) return;
    submitting = true;
    try {
      let status = (await fetchStatus()) || {};
      startOverlay(status);
      if (status.ready) {
        setStatus("Opening your prepared website…");
        setPct(90);
      } else if (status.building) {
        setStatus("Finishing the site we already started…");
      }
      const result = await claimOrStart();
      if (result.redirectUrl) {
        finishAndRedirect(result.redirectUrl);
        return;
      }
      if (result.failed || result.error) {
        throw new Error(result.error || "Could not generate the website.");
      }
      if (!result.building && !result.ready) {
        throw new Error(result.error || "Could not start generation.");
      }
      await pollUntilReady();
    } catch (error) {
      stopOverlayTimers();
      overlay.hidden = true;
      overlay.setAttribute("aria-hidden", "true");
      document.body.classList.remove("is-generating");
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = defaultSubmitLabel;
      }
      submitting = false;
      window.alert(error.message || "Could not generate the website.");
    }
  });

  window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
      overlay.hidden = true;
      document.body.classList.remove("is-generating");
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = defaultSubmitLabel;
      }
      stopOverlayTimers();
      submitting = false;
    }
  });

  watchBackground();
})();
