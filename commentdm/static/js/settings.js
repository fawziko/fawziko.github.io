/* CommentDM — settings page: credentials, webhook subscription, token refresh. */
(() => {
  "use strict";

  const App = window.App;
  const root = document.querySelector("[data-settings-page]");
  if (!root) return;

  const $ = (id) => document.getElementById(id);
  const form = $("settings-form");
  const tokenInput = $("access-token");
  const accountInput = $("instagram-account-id");
  const pageInput = $("page-id");
  const saveBtn = $("save-settings");
  const saveLabel = saveBtn.querySelector("span");
  const removeBtn = $("remove-token");
  const connectionResult = $("connection-result");
  const webhookResult = $("webhook-result");
  const refreshResult = $("refresh-result");
  const refreshBtn = $("refresh-token");
  const subscribeBtn = $("subscribe-webhooks");
  const webhookUrl = $("webhook-url");
  const toggleToken = $("toggle-token-visibility");
  const testButtons = Array.from(document.querySelectorAll(".js-test-connection"));

  const EYE_ICON =
    '<svg class="icon" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
  const EYE_OFF_ICON =
    '<svg class="icon" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m3 3 18 18M10.6 5.7A9.8 9.8 0 0 1 12 5.5c6.4 0 10 6.5 10 6.5a17.4 17.4 0 0 1-3.4 4M6.5 6.9A17.4 17.4 0 0 0 2 12s3.6 6.5 10 6.5a10 10 0 0 0 4.2-.9M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';

  const showResult = (element, type, title, message) => {
    if (!element) return;
    element.hidden = false;
    element.className = `inline-result${type ? ` is-${type}` : ""}`;
    element.replaceChildren();
    if (title) {
      const strong = document.createElement("strong");
      strong.textContent = title;
      element.append(strong);
    }
    if (message) {
      if (title) element.append(document.createTextNode(" "));
      element.append(document.createTextNode(message));
    }
  };

  const hideResult = (element) => {
    if (!element) return;
    element.hidden = true;
    element.textContent = "";
  };

  const busy = (button, label, text) => {
    const original = label ? label.textContent : button.textContent;
    button.disabled = true;
    if (label) label.textContent = text;
    return () => {
      button.disabled = false;
      if (label) label.textContent = original;
    };
  };

  /* ------------------------------------------------------------- webhook URL */
  const computeWebhookUrl = () => {
    if (webhookUrl && !webhookUrl.value) {
      webhookUrl.value = `${window.location.origin}/webhook/instagram`;
    }
  };
  computeWebhookUrl();

  /* --------------------------------------------------------------- token eye */
  toggleToken?.addEventListener("click", () => {
    const showing = tokenInput.type === "text";
    tokenInput.type = showing ? "password" : "text";
    toggleToken.setAttribute("aria-pressed", String(!showing));
    toggleToken.setAttribute("aria-label", showing ? "Show token" : "Hide token");
    toggleToken.innerHTML = showing ? EYE_ICON : EYE_OFF_ICON;
    tokenInput.focus();
  });

  [tokenInput, accountInput, pageInput].forEach((input) => {
    input?.addEventListener("input", () => {
      hideResult(connectionResult);
    });
  });

  /* ------------------------------------------------------------------- save */
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    hideResult(connectionResult);
    if (!form.checkValidity()) {
      form.reportValidity();
      return;
    }

    if (!tokenInput.value.trim() && root.dataset.hasToken !== "true") {
      showResult(connectionResult, "error", "Access token required", "Paste a long-lived User Access Token to connect Instagram.");
      tokenInput.focus();
      return;
    }

    const payload = {
      page_id: pageInput.value.trim(),
      instagram_business_account_id: accountInput.value.trim(),
    };
    const token = tokenInput.value.trim();
    if (token) payload.access_token = token;

    const restore = busy(saveBtn, saveLabel, "Saving…");
    try {
      await App.api("/api/config", { method: "PUT", body: payload });
      window.location.assign("/dashboard/settings?flash=settings_saved");
    } catch (error) {
      restore();
      showResult(connectionResult, "error", "Could not save", error.message);
      App.toast(error.message, { type: "error", title: "Could not save settings" });
    }
  });

  /* ------------------------------------------------------------------- test */
  testButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      if (tokenInput.value.trim()) {
        showResult(
          connectionResult,
          "",
          "Unsaved token",
          "Save credentials first — the connection test uses the stored token."
        );
        App.toast("Save the new token before testing the connection.", {
          type: "info",
          title: "Save first",
        });
        return;
      }
      testButtons.forEach((item) => (item.disabled = true));
      showResult(connectionResult, "", "Testing…", "Calling the Instagram Graph API.");
      try {
        const data = await App.api("/api/config/test", { method: "POST" });
        const account = data.account || {};
        const bits = [];
        if (account.username) bits.push(`@${account.username}`);
        if (account.followers_count !== null && account.followers_count !== undefined) {
          bits.push(`${App.formatNumber(account.followers_count)} followers`);
        }
        if (account.id) bits.push(`ID ${account.id}`);
        showResult(
          connectionResult,
          "success",
          "Connection verified.",
          bits.length ? bits.join(" · ") : "The Graph API accepted the stored credentials."
        );
        App.toast("Instagram credentials are valid.", { type: "success", title: "Connected" });
        document.querySelectorAll(".summary-card h3").forEach((heading) => {
          if (account.username) heading.textContent = `@${account.username}`;
        });
      } catch (error) {
        showResult(connectionResult, "error", "Connection failed.", error.message);
        App.toast(error.message, { type: "error", title: "Connection failed" });
      } finally {
        testButtons.forEach((item) => (item.disabled = false));
      }
    });
  });

  /* ------------------------------------------------------------- remove token */
  removeBtn?.addEventListener("click", async () => {
    const confirmed = await App.confirm({
      title: "Remove the access token?",
      message:
        "Campaigns stay saved, but no comment can be answered or DM'd until a new token is added. The Instagram account and Page IDs remain.",
      confirmLabel: "Remove token",
    });
    if (!confirmed) return;
    removeBtn.disabled = true;
    try {
      await App.api("/api/config", { method: "PUT", body: { clear_access_token: true } });
      window.location.assign("/dashboard/settings?flash=settings_saved");
    } catch (error) {
      removeBtn.disabled = false;
      App.toast(error.message, { type: "error", title: "Could not remove token" });
    }
  });

  /* --------------------------------------------------------------- subscribe */
  subscribeBtn?.addEventListener("click", async () => {
    hideResult(webhookResult);
    if (tokenInput.value.trim()) {
      showResult(webhookResult, "", "Save first", "Save the new token before subscribing.");
      return;
    }
    subscribeBtn.disabled = true;
    try {
      const data = await App.api("/api/config/subscribe", { method: "POST" });
      const fields = Array.isArray(data.subscribed_fields)
        ? data.subscribed_fields.join(", ")
        : "comments";
      showResult(
        webhookResult,
        "success",
        "Subscription active.",
        `This app now receives ${fields} events for the account. Make sure the callback URL and verify token are configured in the Meta app dashboard too.`
      );
      App.toast("Comment webhooks are subscribed for the account.", {
        type: "success",
        title: "Webhooks enabled",
      });
    } catch (error) {
      showResult(webhookResult, "error", "Subscription failed.", error.message);
      App.toast(error.message, { type: "error", title: "Subscription failed" });
    } finally {
      subscribeBtn.disabled = false;
    }
  });

  /* ------------------------------------------------------------ refresh token */
  refreshBtn?.addEventListener("click", async () => {
    if (refreshBtn.disabled) return;
    hideResult(refreshResult);
    refreshBtn.disabled = true;
    try {
      const data = await App.api("/api/config/refresh-token", { method: "POST" });
      const days = data.expires_in_days ? ` Valid for about ${data.expires_in_days} days.` : "";
      showResult(
        refreshResult,
        "success",
        "Token refreshed.",
        `A new long-lived token was saved.${days}`
      );
      App.toast("A fresh 60-day token has been saved.", {
        type: "success",
        title: "Token refreshed",
      });
      setTimeout(() => window.location.assign("/dashboard/settings?flash=token_refreshed"), 1400);
    } catch (error) {
      showResult(refreshResult, "error", "Refresh failed.", error.message);
      App.toast(error.message, { type: "error", title: "Token refresh failed" });
    } finally {
      refreshBtn.disabled = false;
    }
  });
})();
