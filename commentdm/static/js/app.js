/* CommentDM — shared dashboard utilities (no dependencies). */
(() => {
  "use strict";

  const App = {};

  App.qs = (selector, root = document) => root.querySelector(selector);
  App.qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  App.escapeHtml = (value) =>
    String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");

  const TOAST_ICONS = {
    success:
      '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7"/></svg>',
    error:
      '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 8v5M12 17h.01"/><path d="M10.3 4 2.7 17a2 2 0 0 0 1.7 3h15.2a2 2 0 0 0 1.7-3L13.7 4a2 2 0 0 0-3.4 0Z"/></svg>',
    info:
      '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5h.01"/></svg>',
  };

  /* ---------------------------------------------------------------- network */
  App.api = async (url, options = {}) => {
    const opts = { credentials: "same-origin", ...options };
    opts.headers = { Accept: "application/json", ...(options.headers || {}) };

    if (opts.body && typeof opts.body !== "string") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }

    let response;
    try {
      response = await fetch(url, opts);
    } catch (error) {
      throw new Error("Network error — check your connection and try again.");
    }

    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = null;
      }
    }

    if (!response.ok) {
      let message = data && data.detail ? data.detail : `Request failed (HTTP ${response.status}).`;
      if (Array.isArray(message)) {
        message = message[0] && message[0].msg ? message[0].msg : "Please check the form.";
      }
      if (response.status === 401) {
        message = "Authentication required. Reload the page to sign in.";
      }
      const error = new Error(String(message));
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  };

  /* ------------------------------------------------------------------ toast */
  App.toast = (message, options = {}) => {
    const stack = App.qs("#toast-stack");
    if (!stack) return;

    const type = options.type === "error" ? "error" : options.type === "success" ? "success" : "info";
    const title = options.title || (type === "error" ? "Something went wrong" : type === "success" ? "Done" : "Heads up");

    const toast = document.createElement("div");
    toast.className = `toast is-${type}`;
    toast.setAttribute("role", type === "error" ? "alert" : "status");

    const icon = document.createElement("span");
    icon.className = "toast-icon";
    icon.innerHTML = TOAST_ICONS[type];

    const copy = document.createElement("div");
    copy.className = "toast-copy";
    const strong = document.createElement("strong");
    strong.textContent = title;
    const span = document.createElement("span");
    span.textContent = message;
    copy.append(strong, span);

    const close = document.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.setAttribute("aria-label", "Dismiss notification");
    close.innerHTML =
      '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';

    let timer;
    const dismiss = () => {
      clearTimeout(timer);
      if (toast.classList.contains("is-leaving")) return;
      toast.classList.add("is-leaving");
      setTimeout(() => toast.remove(), 200);
    };
    const arm = () => {
      clearTimeout(timer);
      timer = setTimeout(dismiss, options.duration || 5200);
    };
    close.addEventListener("click", dismiss);
    toast.addEventListener("mouseenter", () => clearTimeout(timer));
    toast.addEventListener("mouseleave", arm);

    toast.append(icon, copy, close);
    stack.append(toast);
    while (stack.children.length > 4) stack.firstElementChild.remove();
    arm();
    return toast;
  };

  App.deferToast = (type, title, message) => {
    try {
      sessionStorage.setItem("commentdm:toast", JSON.stringify({ type, title, message }));
    } catch {
      /* sessionStorage can be unavailable in private modes. */
    }
  };

  /* ---------------------------------------------------------------- confirm */
  App.confirm = ({ title, message, confirmLabel = "Confirm", danger = true } = {}) =>
    new Promise((resolve) => {
      const dialog = App.qs("#confirm-dialog");
      if (!dialog || typeof dialog.showModal !== "function") {
        resolve(window.confirm(`${title || "Are you sure?"}\n\n${message || ""}`));
        return;
      }

      App.qs("#confirm-title").textContent = title || "Are you sure?";
      App.qs("#confirm-message").textContent = message || "This action cannot be undone.";
      const ok = App.qs("#confirm-ok");
      ok.textContent = confirmLabel;
      ok.className = `btn ${danger ? "btn-danger" : "btn-primary"}`;

      const cancel = App.qs("#confirm-cancel");
      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        ok.removeEventListener("click", onOk);
        cancel.removeEventListener("click", onCancel);
        dialog.removeEventListener("cancel", onCancel);
        if (dialog.open) dialog.close();
        resolve(value);
      };
      const onOk = () => finish(true);
      const onCancel = (event) => {
        if (event && event.type === "cancel") event.preventDefault();
        finish(false);
      };
      ok.addEventListener("click", onOk);
      cancel.addEventListener("click", onCancel);
      dialog.addEventListener("cancel", onCancel);
      dialog.showModal();
      cancel.focus();
    });

  /* ------------------------------------------------------------------- copy */
  App.copy = async (text) => {
    const value = String(text ?? "");
    if (!value) return false;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
        return true;
      }
    } catch {
      /* fall through to the legacy path */
    }
    try {
      const area = document.createElement("textarea");
      area.value = value;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      area.remove();
      return ok;
    } catch {
      return false;
    }
  };

  App.debounce = (fn, wait = 250) => {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), wait);
    };
  };

  App.formatNumber = (value) => {
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString() : "0";
  };

  App.initials = (value, fallback = "f") => {
    const clean = String(value || "").replace(/^@/, "").trim();
    return clean ? clean.slice(0, 1).toLowerCase() : fallback;
  };

  /* --------------------------------------------------------------- init bits */
  const initFlash = () => {
    const el = App.qs("#flash-data");
    if (el && el.dataset.message) {
      App.toast(el.dataset.message, {
        type: el.dataset.type || "success",
        title: el.dataset.title || "Done",
      });
    }
    try {
      const deferred = sessionStorage.getItem("commentdm:toast");
      if (deferred) {
        sessionStorage.removeItem("commentdm:toast");
        const payload = JSON.parse(deferred);
        if (payload && payload.message) {
          App.toast(payload.message, { type: payload.type, title: payload.title });
        }
      }
    } catch {
      /* ignore malformed deferred toasts */
    }
  };

  const initDialogs = () => {
    document.addEventListener("click", async (event) => {
      const closer = event.target.closest("[data-close-dialog]");
      if (closer) {
        const dialog = closer.closest("dialog");
        if (dialog) dialog.close();
        return;
      }

      const dialog = event.target.closest("dialog[open]");
      if (dialog && event.target === dialog) {
        // A click on the backdrop is outside the dialog's content box.
        const rect = dialog.getBoundingClientRect();
        const outside =
          event.clientX < rect.left ||
          event.clientX > rect.right ||
          event.clientY < rect.top ||
          event.clientY > rect.bottom;
        if (outside) dialog.close();
      }

      const copyBtn = event.target.closest("[data-copy-target]");
      if (copyBtn) {
        const input = document.getElementById(copyBtn.dataset.copyTarget);
        if (input) {
          const ok = await App.copy(input.value);
          App.toast(ok ? "Copied to clipboard." : "Copy failed — select and copy manually.", {
            type: ok ? "success" : "error",
            title: ok ? "Copied" : "Copy failed",
            duration: 2400,
          });
        }
      }
    });
  };

  const initImageFallbacks = () => {
    document.addEventListener(
      "error",
      (event) => {
        const img = event.target;
        if (!(img instanceof HTMLImageElement)) return;
        if (img.closest(".campaign-thumb")) {
          img.closest(".campaign-thumb").classList.add("is-broken");
        }
        if (img.closest(".preview-thumb")) {
          img.hidden = true;
        }
      },
      true
    );
  };

  const initCharCounters = () => {
    App.qsa("[data-count-for]").forEach((counter) => {
      const source = document.getElementById(counter.dataset.countFor);
      if (!source) return;
      const max = Number(source.getAttribute("maxlength")) || 1000;
      const update = () => {
        const length = source.value.length;
        counter.textContent = `${length} / ${max}`;
        counter.classList.toggle("is-near-limit", length >= max * 0.9 && length < max);
        counter.classList.toggle("is-over", length >= max);
      };
      source.addEventListener("input", update);
      update();
    });
  };

  const init = () => {
    initFlash();
    initDialogs();
    initImageFallbacks();
    initCharCounters();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }

  window.App = App;
})();
