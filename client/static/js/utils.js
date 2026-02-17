(() => {
  const AppUtils = window.AppUtils || {};

  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const byId = (id) => document.getElementById(id);

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

  AppUtils.qs = qs;
  AppUtils.qsa = qsa;
  AppUtils.byId = byId;
  AppUtils.showToast = showToast;
  AppUtils.fetchJSON = fetchJSON;
  AppUtils.postForm = postForm;
  AppUtils.postJSON = postJSON;
  AppUtils.initThemeToggle = initThemeToggle;

  window.AppUtils = AppUtils;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initThemeToggle);
  } else {
    initThemeToggle();
  }
})();
