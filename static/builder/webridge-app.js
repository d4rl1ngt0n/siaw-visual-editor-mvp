(() => {
  const THEME_KEY = "wb-theme";
  const root = document.documentElement;
  const toggles = document.querySelectorAll("[data-wb-theme-toggle]");

  const applyTheme = (theme) => {
    root.setAttribute("data-wb-theme", theme);
    toggles.forEach((btn) => {
      btn.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
      btn.setAttribute(
        "aria-label",
        theme === "dark" ? "Switch to light mode" : "Switch to dark mode"
      );
    });
  };

  // The head bootstrap already set the attribute pre-paint; sync button state.
  applyTheme(root.getAttribute("data-wb-theme") === "dark" ? "dark" : "light");

  toggles.forEach((btn) => {
    btn.addEventListener("click", () => {
      const next = root.getAttribute("data-wb-theme") === "dark" ? "light" : "dark";
      applyTheme(next);
      try {
        window.localStorage.setItem(THEME_KEY, next);
      } catch (_) {
        /* ignore storage failures */
      }
    });
  });

  // Follow the OS while the user has not chosen explicitly.
  try {
    if (!window.localStorage.getItem(THEME_KEY) && window.matchMedia) {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (event) => {
        if (!window.localStorage.getItem(THEME_KEY)) {
          applyTheme(event.matches ? "dark" : "light");
        }
      });
    }
  } catch (_) {
    /* ignore */
  }

  const nav = document.querySelector("[data-wb-nav]");
  const toggle = document.querySelector("[data-wb-nav-toggle]");
  if (nav && toggle) {
    const setOpen = (open) => {
      nav.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    };
    toggle.addEventListener("click", () => {
      setOpen(!nav.classList.contains("is-open"));
    });
    nav.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => setOpen(false));
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") setOpen(false);
    });
    window.addEventListener("resize", () => {
      if (window.matchMedia("(min-width: 901px)").matches) setOpen(false);
    });
  }

  const guidance = document.querySelector("[data-wb-guidance]");
  const dismiss = document.querySelector("[data-wb-guidance-dismiss]");
  const storageKey = "wb-pre-editor-guidance-dismissed";
  if (guidance) {
    try {
      if (window.localStorage.getItem(storageKey) === "1") {
        guidance.hidden = true;
      }
    } catch (_) {
      /* ignore storage failures */
    }
  }
  if (guidance && dismiss) {
    dismiss.addEventListener("click", () => {
      guidance.hidden = true;
      try {
        window.localStorage.setItem(storageKey, "1");
      } catch (_) {
        /* ignore */
      }
    });
  }

  /* Hero product demo video: respect reduced motion, keep autoplay muted loop. */
  const demo = document.querySelector("[data-wb-demo]");
  if (demo) {
    const video = demo.querySelector("[data-wb-demo-video]");
    const still = demo.querySelector("[data-wb-demo-still]");
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (reduceMotion) {
      if (video) {
        video.pause();
        video.removeAttribute("autoplay");
        video.hidden = true;
      }
      if (still) still.hidden = false;
    } else if (video) {
      const tryPlay = () => {
        const playPromise = video.play();
        if (playPromise && typeof playPromise.catch === "function") {
          playPromise.catch(() => {
            /* Autoplay blocked: keep poster visible. */
          });
        }
      };
      if (video.readyState >= 2) {
        tryPlay();
      } else {
        video.addEventListener("loadeddata", tryPlay, { once: true });
      }
    }
  }
})();
