/* CommentDM — campaigns page interactions. */
(() => {
  "use strict";

  const App = window.App;
  const dialog = document.getElementById("campaign-dialog");
  if (!dialog) return;

  const $ = (id) => document.getElementById(id);

  const form = $("campaign-form");
  const list = $("campaign-list");
  const idInput = $("campaign-id");
  const nameInput = $("campaign-name");
  const postInput = $("post-id");
  const keywordsInput = $("keywords");
  const replyInput = $("comment-reply");
  const dmInput = $("dm-message");
  const activeInput = $("campaign-active");
  const previewBtn = $("preview-btn");
  const postPreview = $("post-preview");
  const previewImage = $("preview-image");
  const previewStatus = $("preview-status");
  const previewCaption = $("preview-caption");
  const previewLink = $("preview-link");
  const keywordPreview = $("keyword-preview");
  const modeLabel = $("campaign-mode-label");
  const dialogTitle = $("campaign-dialog-title");
  const saveBtn = $("save-campaign");
  const saveLabel = saveBtn.querySelector("span");
  const formError = $("form-error");

  const simulateDialog = $("simulate-dialog");
  const simulateForm = $("simulate-form");
  const simulateTitle = $("simulate-title");
  const simulateLead = $("simulate-lead");
  const simulateComment = $("simulate-comment");
  const simulateUsername = $("simulate-username");
  const simulateKeywords = $("simulate-keywords");
  const simulateResult = $("simulate-result");
  const simulateKeyword = $("simulate-keyword");
  const simulateReply = $("simulate-reply");
  const simulateDm = $("simulate-dm");
  const simulateError = $("simulate-error");
  const runBtn = $("run-simulation");
  const runLabel = runBtn.querySelector("span");

  const state = {
    campaignId: null,
    previewId: null,
    previewRequest: 0,
    simulateId: null,
    simulateKeywords: [],
  };

  /* --------------------------------------------------------------- helpers */
  const splitKeywords = (raw) => {
    const seen = new Set();
    return String(raw || "")
      .split(/[,\n]/)
      .map((part) => part.trim().replace(/\s+/g, " "))
      .filter((keyword) => {
        if (!keyword) return false;
        const key = keyword.toLowerCase();
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
  };

  const makeChip = (text, extraClass = "") => {
    const chip = document.createElement("span");
    chip.className = `chip ${extraClass}`.trim();
    chip.textContent = text;
    return chip;
  };

  const setPreviewState = (name, message) => {
    postPreview.dataset.state = name;
    previewStatus.textContent = message;
  };

  const clearPreview = (message = "Paste a post ID, then preview it.") => {
    state.previewId = null;
    previewImage.hidden = true;
    previewImage.removeAttribute("src");
    previewCaption.hidden = true;
    previewCaption.textContent = "";
    previewLink.hidden = true;
    previewLink.removeAttribute("href");
    setPreviewState("empty", message);
  };

  const renderPreview = (data) => {
    postPreview.dataset.state = "ready";
    previewImage.hidden = true;
    previewImage.removeAttribute("src");
    if (data.thumbnail_url) {
      previewImage.src = data.thumbnail_url;
      previewImage.hidden = false;
    }
    previewStatus.textContent = data.cached
      ? `Showing a cached preview.${data.warning ? ` ${data.warning}` : ""}`
      : "Post loaded — the thumbnail and caption are cached with the campaign.";
    previewCaption.textContent = data.caption || "";
    previewCaption.hidden = !data.caption;
    if (data.permalink) {
      previewLink.href = data.permalink;
      previewLink.hidden = false;
    } else {
      previewLink.hidden = true;
    }
  };

  const describePreviewError = (message) =>
    `${message || "Could not load this post."} You can still save the campaign.`;

  const previewPost = async (force = false) => {
    const postId = postInput.value.trim();
    if (!postId) {
      clearPreview("Paste a post ID, then preview it.");
      return;
    }
    if (!/^\d{5,30}$/.test(postId)) {
      setPreviewState("error", "Post IDs are numeric. Copy the media ID from the Graph API Explorer.");
      return;
    }
    if (!force && state.previewId === postId && postPreview.dataset.state === "ready") return;

    const request = ++state.previewRequest;
    previewBtn.disabled = true;
    previewBtn.classList.add("is-loading");
    setPreviewState("loading", "Fetching the post from Instagram…");

    try {
      const data = await App.api("/api/posts/preview", {
        method: "POST",
        body: { post_id: postId },
      });
      if (request !== state.previewRequest) return;
      state.previewId = postId;
      renderPreview(data);
    } catch (error) {
      if (request !== state.previewRequest) return;
      state.previewId = null;
      previewImage.hidden = true;
      previewCaption.hidden = true;
      previewLink.hidden = true;
      setPreviewState("error", describePreviewError(error.message));
    } finally {
      if (request === state.previewRequest) {
        previewBtn.disabled = false;
        previewBtn.classList.remove("is-loading");
      }
    }
  };

  const renderKeywordPreview = () => {
    const keywords = splitKeywords(keywordsInput.value);
    keywordPreview.replaceChildren();
    if (!keywords.length) {
      const hint = document.createElement("span");
      hint.className = "keyword-empty";
      hint.textContent = "Keywords appear here as you type.";
      keywordPreview.append(hint);
      return;
    }
    keywords.slice(0, 10).forEach((keyword) => keywordPreview.append(makeChip(keyword)));
    if (keywords.length > 10) {
      keywordPreview.append(makeChip(`+${keywords.length - 10} more`, "chip-more"));
    }
  };

  const updateConversation = () => {
    const keywords = splitKeywords(keywordsInput.value);
    const sample = keywords.length
      ? `${keywords[0]} please! 🙌`
      : "Comment with a keyword…";
    $("chat-comment-text").textContent = sample;
    $("chat-reply-text").textContent =
      replyInput.value.trim() || "Your public reply appears here.";
    $("chat-dm-text").textContent = dmInput.value.trim() || "Your DM appears here.";
    $("chat-avatar").textContent = App.initials("follower");
  };

  const syncCounters = () => {
    [replyInput, dmInput].forEach((field) => field.dispatchEvent(new Event("input")));
  };

  const setDialogMode = (campaign) => {
    if (campaign) {
      state.campaignId = campaign.id;
      idInput.value = String(campaign.id);
      nameInput.value = campaign.raw_name || "";
      postInput.value = campaign.post_id || "";
      keywordsInput.value = (campaign.keyword_list || []).join(", ");
      replyInput.value = campaign.comment_reply || "";
      dmInput.value = campaign.dm_message || "";
      activeInput.checked = Boolean(campaign.is_active);
      modeLabel.textContent = "Editing automation";
      dialogTitle.textContent = "Edit campaign";
      saveLabel.textContent = "Save changes";

      if (campaign.post_thumbnail_url || campaign.post_caption) {
        state.previewId = campaign.post_id;
        postPreview.dataset.state = "ready";
        previewImage.hidden = true;
        previewImage.removeAttribute("src");
        if (campaign.post_thumbnail_url) {
          previewImage.src = campaign.post_thumbnail_url;
          previewImage.hidden = false;
        }
        previewStatus.textContent = "Cached preview from your last save. Click Preview to refresh.";
        previewCaption.textContent = campaign.post_caption || "";
        previewCaption.hidden = !campaign.post_caption;
        if (campaign.post_permalink) {
          previewLink.href = campaign.post_permalink;
          previewLink.hidden = false;
        } else {
          previewLink.hidden = true;
        }
      } else {
        clearPreview("Click Preview to fetch this post's details.");
      }
    } else {
      state.campaignId = null;
      idInput.value = "";
      nameInput.value = "";
      postInput.value = "";
      keywordsInput.value = "";
      replyInput.value = "";
      dmInput.value = "";
      activeInput.checked = true;
      modeLabel.textContent = "New automation";
      dialogTitle.textContent = "Create campaign";
      saveLabel.textContent = "Save campaign";
      clearPreview();
    }
    formError.hidden = true;
    formError.textContent = "";
    renderKeywordPreview();
    updateConversation();
    syncCounters();
  };

  const openForm = (campaign = null) => {
    setDialogMode(campaign);
    if (!dialog.open) dialog.showModal();
    setTimeout(() => (campaign ? nameInput : postInput).focus(), 60);
  };

  const setBusy = (button, label, text) => {
    if (!button || !label) return () => {};
    const original = label.textContent;
    button.disabled = true;
    button.classList.add("is-loading");
    label.textContent = text;
    return () => {
      button.disabled = false;
      button.classList.remove("is-loading");
      label.textContent = original;
    };
  };

  /* ---------------------------------------------------------------- events */
  document.addEventListener("click", async (event) => {
    const newButton = event.target.closest(".js-new-campaign");
    if (newButton) {
      event.preventDefault();
      openForm();
      return;
    }

    const demoButton = event.target.closest("#load-demo");
    if (demoButton) {
      const originalText = demoButton.textContent.trim();
      demoButton.disabled = true;
      demoButton.textContent = "Loading sample data…";
      try {
        await App.api("/api/demo/seed", { method: "POST" });
        window.location.assign("/dashboard?flash=demo_loaded");
      } catch (error) {
        demoButton.disabled = false;
        demoButton.textContent = originalText;
        App.toast(error.message, { type: "error", title: "Could not load sample data" });
      }
      return;
    }

    if (!list) return;
    const card = event.target.closest(".campaign-card");
    if (!card) return;
    const campaignId = card.dataset.campaignId;
    const action = event.target.closest("[data-action]")?.dataset.action;

    if (action === "toggle") {
      event.preventDefault();
      await toggleCampaign(card, campaignId);
      return;
    }
    if (action === "edit") {
      event.preventDefault();
      await openEdit(campaignId);
      return;
    }
    if (action === "delete") {
      event.preventDefault();
      await deleteCampaign(card, campaignId);
      return;
    }
    if (action === "simulate") {
      event.preventDefault();
      await openSimulate(campaignId);
      return;
    }
    if (event.target.closest("button, a")) return;
    await openEdit(campaignId);
  });

  const openEdit = async (campaignId) => {
    try {
      const campaign = await App.api(`/api/campaigns/${campaignId}`);
      openForm(campaign);
    } catch (error) {
      App.toast(error.message, { type: "error", title: "Could not open campaign" });
    }
  };

  const toggleCampaign = async (card, campaignId) => {
    const button = card.querySelector(".switch");
    if (!button || button.disabled) return;
    button.disabled = true;
    try {
      const result = await App.api(`/api/campaigns/${campaignId}/toggle`, { method: "POST" });
      const active = Boolean(result.is_active);
      button.setAttribute("aria-checked", String(active));
      card.classList.toggle("is-paused", !active);
      card.dataset.active = String(active);

      const badge = card.querySelector('[data-role="status-badge"]');
      const text = card.querySelector('[data-role="status-text"]');
      if (badge) {
        badge.classList.toggle("badge-live", active);
        badge.classList.toggle("badge-paused", !active);
      }
      if (text) text.textContent = active ? "Active" : "Paused";

      document.querySelectorAll('[data-stat="campaigns_active"]').forEach((node) => {
        node.textContent = App.formatNumber(result.stats.campaigns_active);
      });
      const navCount = document.querySelector(".nav-count");
      if (navCount) navCount.textContent = String(result.stats.campaigns_active);

      App.toast(active ? "New comments will be handled automatically." : "Existing activity stays, new comments are ignored.", {
        type: "success",
        title: active ? "Campaign activated" : "Campaign paused",
        duration: 3000,
      });
    } catch (error) {
      App.toast(error.message, { type: "error", title: "Could not update campaign" });
    } finally {
      button.disabled = false;
    }
  };

  const deleteCampaign = async (card, campaignId) => {
    const name = card.querySelector(".campaign-name")?.textContent?.trim() || "this campaign";
    const confirmed = await App.confirm({
      title: "Delete this campaign?",
      message: `“${name}” will stop replying to comments. Its activity history stays in the log, and processed comments will not fire again.`,
      confirmLabel: "Delete campaign",
    });
    if (!confirmed) return;
    try {
      await App.api(`/api/campaigns/${campaignId}`, { method: "DELETE" });
      card.classList.add("is-removing");
      setTimeout(() => window.location.assign("/dashboard?flash=campaign_deleted"), 220);
    } catch (error) {
      App.toast(error.message, { type: "error", title: "Could not delete campaign" });
    }
  };

  const openSimulate = async (campaignId) => {
    try {
      const campaign = await App.api(`/api/campaigns/${campaignId}`);
      state.simulateId = campaignId;
      state.simulateKeywords = campaign.keyword_list || [];
      simulateTitle.textContent = "Test this campaign";
      simulateLead.textContent = `Dry-run “${campaign.name}” with a sample comment. Nothing is sent to Instagram.`;
      simulateComment.value = state.simulateKeywords.length
        ? `${state.simulateKeywords[0]} please!`
        : "";
      simulateUsername.value = "";
      simulateResult.hidden = true;
      simulateError.hidden = true;
      simulateError.textContent = "";
      renderSimulateKeywords();
      if (!simulateDialog.open) simulateDialog.showModal();
      setTimeout(() => simulateComment.focus(), 60);
    } catch (error) {
      App.toast(error.message, { type: "error", title: "Could not open test" });
    }
  };

  const renderSimulateKeywords = () => {
    simulateKeywords.replaceChildren();
    state.simulateKeywords.forEach((keyword) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip chip-button";
      chip.textContent = keyword;
      chip.title = `Use “${keyword}” in the test comment`;
      simulateKeywords.append(chip);
    });
  };

  simulateKeywords?.addEventListener("click", (event) => {
    const chip = event.target.closest(".chip-button");
    if (!chip) return;
    simulateComment.value = `${chip.textContent} please!`;
    simulateComment.focus();
    simulateError.hidden = true;
  });

  postInput.addEventListener("blur", () => previewPost(false));
  previewBtn.addEventListener("mousedown", (event) => event.preventDefault());
  previewBtn.addEventListener("click", () => previewPost(true));
  keywordsInput.addEventListener("input", () => {
    renderKeywordPreview();
    updateConversation();
  });
  replyInput.addEventListener("input", updateConversation);
  dmInput.addEventListener("input", updateConversation);
  nameInput.addEventListener("input", () => {
    if (nameInput.value.trim().length > 120) nameInput.value = nameInput.value.slice(0, 120);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    formError.hidden = true;
    formError.textContent = "";

    if (!form.checkValidity()) {
      form.reportValidity();
      return;
    }

    const payload = {
      name: nameInput.value.trim(),
      post_id: postInput.value.trim(),
      keywords: splitKeywords(keywordsInput.value).join(", "),
      comment_reply: replyInput.value.trim(),
      dm_message: dmInput.value.trim(),
      is_active: activeInput.checked,
    };

    if (!payload.keywords) {
      formError.textContent = "Add at least one trigger keyword.";
      formError.hidden = false;
      keywordsInput.focus();
      return;
    }
    if (!payload.comment_reply || !payload.dm_message) {
      formError.textContent = "Both the public reply and the DM message are required.";
      formError.hidden = false;
      return;
    }

    const restore = setBusy(saveBtn, saveLabel, "Saving…");
    try {
      const editing = Boolean(state.campaignId);
      const result = await App.api(editing ? `/api/campaigns/${state.campaignId}` : "/api/campaigns", {
        method: editing ? "PUT" : "POST",
        body: payload,
      });
      if (result && result.preview_warning) {
        App.deferToast("info", "Saved — preview unavailable", result.preview_warning);
      }
      window.location.assign("/dashboard?flash=campaign_saved");
    } catch (error) {
      restore();
      formError.textContent = error.message;
      formError.hidden = false;
      formError.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  });

  simulateForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    simulateError.hidden = true;
    simulateError.textContent = "";
    const text = simulateComment.value.trim();
    if (!text) {
      simulateError.textContent = "Write a sample comment first.";
      simulateError.hidden = false;
      simulateComment.focus();
      return;
    }
    if (!state.simulateId) return;

    const restore = setBusy(runBtn, runLabel, "Testing…");
    try {
      const result = await App.api(`/api/campaigns/${state.simulateId}/simulate`, {
        method: "POST",
        body: {
          comment_text: text,
          commenter_username: simulateUsername.value.trim() || null,
        },
      });
      simulateKeyword.textContent = `“${result.matched_keyword}”`;
      simulateReply.textContent = result.comment_reply;
      simulateDm.textContent = result.dm_message;
      simulateResult.hidden = false;
      App.toast("The dry run was logged as simulated — no Instagram API call was made.", {
        type: "success",
        title: "Test complete",
        duration: 4000,
      });
      simulateResult.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
      simulateError.textContent = error.message;
      simulateError.hidden = false;
    } finally {
      restore();
    }
  });

  /* ------------------------------------------------------------- searching */
  const search = $("campaign-search");
  const noResults = $("campaign-no-results");
  if (search) {
    search.addEventListener(
      "input",
      App.debounce(() => {
        const query = search.value.trim().toLowerCase();
        let visible = 0;
        document.querySelectorAll(".campaign-card").forEach((card) => {
          const matches = !query || (card.dataset.search || "").includes(query);
          card.hidden = !matches;
          if (matches) visible += 1;
        });
        if (noResults) noResults.hidden = visible !== 0;
      }, 120)
    );
  }

  updateConversation();
  renderKeywordPreview();
})();
