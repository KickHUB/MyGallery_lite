(() => {
  const AppUtils = window.AppUtils || {};

  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const byId = (id) => document.getElementById(id);
  const SAFE_HTTP_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
  const nativeFetch = window.fetch.bind(window);

  const getCsrfToken = () => {
    const meta = qs('meta[name="csrf-token"]');
    return meta ? (meta.getAttribute("content") || "").trim() : "";
  };

  const isSameOriginUrl = (value) => {
    try {
      return new URL(String(value), window.location.href).origin === window.location.origin;
    } catch {
      return false;
    }
  };

  const buildProtectedHeaders = (requestHeaders, initHeaders) => {
    const headers = new Headers(requestHeaders || {});
    const overrides = new Headers(initHeaders || {});
    overrides.forEach((value, key) => headers.set(key, value));

    const csrfToken = getCsrfToken();
    if (csrfToken && !headers.has("X-CSRF-Token")) {
      headers.set("X-CSRF-Token", csrfToken);
    }
    if (!headers.has("X-Requested-With")) {
      headers.set("X-Requested-With", "XMLHttpRequest");
    }
    return headers;
  };

  window.fetch = (input, init = {}) => {
    const request = input instanceof Request ? input : null;
    const method = String(init.method || request?.method || "GET").toUpperCase();
    const url = request ? request.url : input;

    if (SAFE_HTTP_METHODS.has(method) || !isSameOriginUrl(url)) {
      return nativeFetch(input, init);
    }

    const headers = buildProtectedHeaders(request?.headers, init.headers);
    if (request) {
      return nativeFetch(new Request(request, { ...init, headers }));
    }
    return nativeFetch(input, { ...init, headers });
  };

  const ensureToastContainer = () => byId("toast-container");

  const showToast = (message, type = "success", options = {}) => {
    const container = ensureToastContainer();
    if (!container) return;

    const toast = document.createElement("div");
    const kind = type === "error" || type === "warning" || type === "info" ? type : "success";
    toast.className = `toast toast-${kind}`;
    toast.textContent = message;
    container.appendChild(toast);

    const duration = Number.isFinite(options.duration) ? options.duration : 3000;
    requestAnimationFrame(() => toast.classList.add("is-visible"));
    window.setTimeout(() => {
      toast.classList.remove("is-visible");
      toast.addEventListener("transitionend", () => toast.remove(), { once: true });
    }, duration);
  };

  const fetchJSON = async (url, options = {}) => {
    const res = await fetch(url, options);
    const raw = await res.text();
    let data;
    try {
      data = raw ? JSON.parse(raw) : {};
    } catch {
      data = { text: raw };
    }
    if (!res.ok) {
      const error = new Error(data?.error || res.statusText || "Request failed");
      error.status = res.status;
      error.data = data;
      throw error;
    }
    return data;
  };

  const postForm = (url, payload = {}, options = {}) => {
    const body = new URLSearchParams();
    Object.entries(payload || {}).forEach(([key, value]) => {
      if (Array.isArray(value)) {
        value.forEach((item) => body.append(key, item));
      } else if (value !== undefined && value !== null) {
        body.append(key, value);
      }
    });
    return fetchJSON(url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", ...(options.headers || {}) },
      body: body.toString(),
      ...options,
    });
  };

  const postJSON = (url, payload = {}, options = {}) => {
    return fetchJSON(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      body: JSON.stringify(payload || {}),
      ...options,
    });
  };

  const THEME_STORAGE_KEY = "mygallery-theme";

  const resolveTheme = () => {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  };

  const applyTheme = (theme) => {
    document.documentElement.dataset.theme = theme;
  };

  const updateThemeToggles = (theme) => {
    qsa("[data-theme-toggle]").forEach((toggle) => {
      const iconEl = toggle.querySelector("[data-theme-icon]");
      const labelEl = toggle.querySelector("[data-theme-label]");
      const labelLight = toggle.dataset.labelLight || "Light";
      const labelDark = toggle.dataset.labelDark || "Dark";
      const iconLight = toggle.dataset.iconLight || "L";
      const iconDark = toggle.dataset.iconDark || "D";
      const nextTheme = theme === "dark" ? "light" : "dark";
      const nextLabel = nextTheme === "dark" ? labelDark : labelLight;
      const nextIcon = nextTheme === "dark" ? iconDark : iconLight;

      if (iconEl) iconEl.textContent = nextIcon;
      if (labelEl) labelEl.textContent = nextLabel;
      toggle.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
      toggle.setAttribute("aria-label", `Theme toggle: ${nextLabel}`);
      toggle.dataset.nextTheme = nextTheme;
    });
  };

  const setTheme = (theme, persist = true) => {
    applyTheme(theme);
    if (persist) {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    }
    updateThemeToggles(theme);
  };

  const initThemeToggle = () => {
    const theme = resolveTheme();
    setTheme(theme, false);

    qsa("[data-theme-toggle]").forEach((toggle) => {
      toggle.addEventListener("click", () => {
        const nextTheme = toggle.dataset.nextTheme || (document.documentElement.dataset.theme === "dark" ? "light" : "dark");
        setTheme(nextTheme, true);
      });
    });

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = (event) => {
      const stored = localStorage.getItem(THEME_STORAGE_KEY);
      if (stored === "light" || stored === "dark") return;
      setTheme(event.matches ? "dark" : "light", false);
    };
    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", handleChange);
    } else if (typeof mediaQuery.addListener === "function") {
      mediaQuery.addListener(handleChange);
    }
  };

  const initProfileMenu = () => {
    const root = byId("profile-menu");
    const toggle = byId("profile-menu-toggle");
    const panel = byId("profile-menu-panel");
    if (!root || !toggle || !panel) return;
    if (root.dataset.menuBound === "1") return;
    root.dataset.menuBound = "1";

    let open = false;
    const setOpen = (nextOpen) => {
      open = !!nextOpen;
      root.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    };

    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      setOpen(!open);
    });

    panel.addEventListener("click", (event) => {
      if (event.target.closest(".profile-menu-item")) {
        setOpen(false);
      }
    });

    document.addEventListener("click", (event) => {
      if (!open) return;
      if (!root.contains(event.target)) {
        setOpen(false);
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && open) {
        setOpen(false);
      }
    });
  };

  const openSettingsModal = () => {
    const modal = byId("settings-modal");
    if (!modal) return false;
    if (typeof window.initSettingsTabs === "function" && document.body.dataset.settingsTabsInit !== "1") {
      document.body.dataset.settingsTabsInit = "1";
      window.initSettingsTabs();
    } else if (document.body.dataset.settingsTabsFallbackInit !== "1") {
      document.body.dataset.settingsTabsFallbackInit = "1";
      const tabButtons = qsa(".settings-tab-button");
      const tabPanels = qsa(".settings-tab-panel");
      tabButtons.forEach((button) => {
        button.addEventListener("click", () => {
          const target = button.dataset.tabTarget;
          tabButtons.forEach((item) => {
            const isActive = item === button;
            item.classList.toggle("active", isActive);
            item.setAttribute("aria-selected", isActive ? "true" : "false");
          });
          tabPanels.forEach((panel) => {
            panel.classList.toggle("active", panel.id === target);
          });
        });
      });
    }
    if (typeof window.initEnvModeTabs === "function" && document.body.dataset.envTabsInit !== "1") {
      document.body.dataset.envTabsInit = "1";
      window.initEnvModeTabs();
    }
    modal.style.display = "block";
    document.body.style.overflow = "hidden";
    if (typeof window.loadEnvBasic === "function") {
      window.loadEnvBasic();
    }
    return true;
  };

  const closeSettingsModal = () => {
    const modal = byId("settings-modal");
    if (!modal) return;
    modal.style.display = "none";
    document.body.style.overflow = "";
  };

  const initGlobalSettingsModal = () => {
    const settingsBtn = byId("settings-btn");
    if (settingsBtn && settingsBtn.dataset.settingsBound !== "1") {
      settingsBtn.dataset.settingsBound = "1";
      settingsBtn.addEventListener("click", (event) => {
        event.preventDefault();
        const profileRoot = byId("profile-menu");
        const profileToggle = byId("profile-menu-toggle");
        if (profileRoot) profileRoot.classList.remove("open");
        if (profileToggle) profileToggle.setAttribute("aria-expanded", "false");
        openSettingsModal();
      });
    }

    const closeBtn = byId("settings-close");
    if (closeBtn && closeBtn.dataset.settingsBound !== "1") {
      closeBtn.dataset.settingsBound = "1";
      closeBtn.addEventListener("click", closeSettingsModal);
    }

    const modal = byId("settings-modal");
    if (modal && modal.dataset.settingsBound !== "1") {
      modal.dataset.settingsBound = "1";
      modal.addEventListener("click", (event) => {
        if (event.target === modal) {
          closeSettingsModal();
        }
      });
    }

    if (document.body.dataset.settingsBound !== "1") {
      document.body.dataset.settingsBound = "1";
      document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        const settingsModal = byId("settings-modal");
        if (!settingsModal || settingsModal.style.display !== "block") return;
        closeSettingsModal();
      });
    }
  };

  AppUtils.qs = qs;
  AppUtils.qsa = qsa;
  AppUtils.byId = byId;
  AppUtils.showToast = showToast;
  AppUtils.fetchJSON = fetchJSON;
  AppUtils.postForm = postForm;
  AppUtils.postJSON = postJSON;
  AppUtils.initThemeToggle = initThemeToggle;
  AppUtils.initProfileMenu = initProfileMenu;
  AppUtils.openSettingsModal = openSettingsModal;
  AppUtils.closeSettingsModal = closeSettingsModal;
  AppUtils.initGlobalSettingsModal = initGlobalSettingsModal;

  window.AppUtils = AppUtils;

  const initGlobalUi = () => {
    initThemeToggle();
    initProfileMenu();
    initGlobalSettingsModal();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initGlobalUi);
  } else {
    initGlobalUi();
  }
})();
