/* CommentDM — activity log filters and destructive actions. */
(() => {
  "use strict";

  const App = window.App;
  const table = document.getElementById("activity-table");
  if (!table) return;

  const rows = Array.from(table.querySelectorAll("tbody tr"));
  const search = document.getElementById("activity-search");
  const statusFilter = document.getElementById("activity-status");
  const campaignFilter = document.getElementById("activity-campaign");
  const count = document.getElementById("activity-count");
  const noResults = document.getElementById("activity-no-results");
  const resetButtons = Array.from(document.querySelectorAll("#reset-filters, [data-reset-filters]"));
  const tableCard = table.closest(".table-card");
  const clearButton = document.getElementById("clear-activity");
  const refreshButton = document.getElementById("refresh-activity");

  const applyFilters = () => {
    const query = (search?.value || "").trim().toLowerCase();
    const status = statusFilter?.value || "";
    const campaign = campaignFilter?.value || "";
    let visible = 0;

    rows.forEach((row) => {
      const matchesQuery = !query || (row.dataset.search || "").includes(query);
      const matchesStatus = !status || row.dataset.status === status;
      const matchesCampaign = !campaign || row.dataset.campaignId === campaign;
      const matches = matchesQuery && matchesStatus && matchesCampaign;
      row.hidden = !matches;
      if (matches) visible += 1;
    });

    if (count) count.textContent = `${visible} entr${visible === 1 ? "y" : "ies"}`;
    if (tableCard) tableCard.hidden = rows.length > 0 && visible === 0;
    if (noResults) noResults.hidden = visible !== 0;
  };

  const reset = () => {
    if (search) search.value = "";
    if (statusFilter) statusFilter.value = "";
    if (campaignFilter) campaignFilter.value = "";
    applyFilters();
  };

  search?.addEventListener("input", App.debounce(applyFilters, 100));
  statusFilter?.addEventListener("change", applyFilters);
  campaignFilter?.addEventListener("change", applyFilters);
  resetButtons.forEach((button) => button.addEventListener("click", reset));

  refreshButton?.addEventListener("click", () => window.location.reload());

  clearButton?.addEventListener("click", async () => {
    if (clearButton.disabled) return;
    const confirmed = await App.confirm({
      title: "Clear the activity log?",
      message:
        "This deletes every processed-comment record, including the deduplication ledger. Meta could re-deliver an old event and fire the same campaign again. Campaigns and credentials are untouched.",
      confirmLabel: "Clear log",
    });
    if (!confirmed) return;

    clearButton.disabled = true;
    try {
      await App.api("/api/activity", { method: "DELETE" });
      window.location.assign("/dashboard/activity?flash=activity_cleared");
    } catch (error) {
      clearButton.disabled = false;
      App.toast(error.message, { type: "error", title: "Could not clear the log" });
    }
  });
})();
