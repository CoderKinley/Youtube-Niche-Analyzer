"use strict";

let statistics = null;

function renderTimeline() {
  if (!statistics) return;
  const metric = $("timeline-metric").value;
  barChart("timeline-chart", statistics.uploads_by_date.map((entry) => ({ label: entry.date, value: entry[metric] })),
    metric === "uploads" ? "Sample upload count by publication date" : "Current total views grouped by publication date");
}

$("timeline-metric").addEventListener("change", renderTimeline);
initializeResearchPage(async (snapshot, isCurrent) => {
  const result = await api(`/api/searches/${snapshot.id}/stats`);
  if (!isCurrent()) return;
  statistics = result;
  renderMetrics("stats-metrics", [
    ["Sampled videos", formatNumber(result.video_count)], ["Discovered creators", formatNumber(result.channel_count)],
    ["Combined public views", formatNumber(result.total_views)], ["Top creator view share", formatPercent(result.top_channel_share)],
    ["5+ baseline uploads", `${result.baseline_supported} / ${result.video_count}`],
  ]);
  barChart("creator-chart", result.channel_views.slice(0, 10).map((entry) => ({ label: entry.title, value: entry.views })), "Sampled video views by creator, top ten");
  const labels = { short: "Short candidates ≤3 min", long: "Long videos >3 min", unknown: "Unknown duration" };
  barChart("format-chart", result.formats.map((entry) => ({ label: labels[entry.format], value: entry.videos })), "Sample video count by duration class");
  renderTimeline();
  $("stats-note").textContent = result.note;
  $("growth-empty").hidden = result.growth.length > 0;
  $("growth-rows").replaceChildren(...result.growth.map((entry) => {
    const row = node("tr");
    const title = node("td", null, "wrap-cell");
    title.append(externalLink(entry.title, "video", entry.video_id));
    row.append(title, node("td", new Date(entry.previous_at).toLocaleString()), node("td", `${entry.interval_hours.toFixed(1)}h`),
      node("td", formatNumber(entry.views_gained)), node("td", entry.count_correction ? "Count correction" : formatNumber(entry.views_per_hour)));
    return row;
  }));
});
