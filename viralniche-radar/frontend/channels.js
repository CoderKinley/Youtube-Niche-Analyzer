"use strict";

let channelSnapshot = null;
let channelAnalysis = null;
let channelRequest = 0;
let currentSnapshotRequest = () => true;

function showChannel(channel) {
  $("channel-detail").hidden = false;
  $("channel-detail-title").textContent = channel.title;
  $("channel-detail-meta").textContent = `${channel.upload_count} sampled uploads · ${channel.uploads_per_week.toFixed(1)}/week in window · ${channel.performance_pattern}${channel.history_limit_reached ? " · Latest-50 limit reached; history may be incomplete" : ""}`;
  $("youtube-channel").href = `https://www.youtube.com/channel/${encodeURIComponent(channel.channel_id)}`;
  const chronological = [...channel.videos].sort((a, b) => a.published_at.localeCompare(b.published_at));
  barChart("channel-chart", chronological.map((v) => ({ label: `${new Date(v.published_at).toLocaleDateString()} · ${v.title}`, value: v.views })), "Current views per sampled upload, oldest first");
  $("channel-upload-rows").replaceChildren(...channel.videos.map((video) => {
    const row = node("tr");
    const title = node("td", null, "wrap-cell");
    title.append(externalLink(video.title, "video", video.video_id));
    row.append(title, node("td", new Date(video.published_at).toLocaleDateString()), node("td", formatNumber(video.views)),
      node("td", `${Math.floor(video.duration_seconds / 60)}:${String(video.duration_seconds % 60).padStart(2, "0")}`),
      node("td", !channel.upload_history_available ? "History unavailable" : video.age_hours >= 24 ? "Yes" : "Too recent"));
    return row;
  }));
  $("channel-detail").focus({ preventScroll: true });
  $("channel-detail").scrollIntoView({ behavior: "auto", block: "start" });
}

function renderChannels() {
  if (!channelAnalysis) return;
  $("channel-detail").hidden = true;
  const limit = Number($("subscriber-limit").value);
  const minimum = Number($("minimum-uploads").value);
  const sort = $("channel-sort").value;
  const rows = channelAnalysis.channels.filter((row) => (!limit || row.subscribers != null && row.subscribers < limit) && row.measured_count >= minimum);
  rows.sort((a, b) => sort === "evidence" ? Number(b.supported) - Number(a.supported) || (b.median_views ?? -1) - (a.median_views ?? -1) : (b[sort] ?? -1) - (a[sort] ?? -1));
  const coverage = channelAnalysis.coverage;
  renderMetrics("channel-metrics", [
    ["Discovered", formatNumber(coverage.discovered_channels)], ["5+ measured uploads", formatNumber(coverage.supported_channels)],
    ["Under 100K subscribers", formatNumber(coverage.small_channels)], ["Subscriber count unknown", formatNumber(coverage.unknown_subscribers)], ["Shown after filters", String(rows.length)],
  ]);
  $("channel-count").textContent = `${rows.length} shown · ${$("channel-format").selectedOptions[0].textContent}`;
  $("channel-note").textContent = channelAnalysis.note;
  $("channel-empty").hidden = rows.length > 0;
  $("channel-empty").textContent = channelAnalysis.available ? "No channels match these filters. Try all channel sizes or a smaller minimum sample." : channelAnalysis.note;
  $("channel-rows").replaceChildren(...rows.map((channel) => {
    const row = node("tr");
    const title = node("td", null, "wrap-cell");
    const button = node("button", channel.title, "text-button");
    button.type = "button";
    button.addEventListener("click", () => showChannel(channel));
    title.append(button, node("span", `${channel.matched_videos} keyword matches · inspect uploads ↓`, "subtext"));
    const similar = node("a", "Find similar channels", "subtext");
    similar.href = `/similar?reference=${encodeURIComponent(channel.channel_id)}`;
    title.append(similar);
    const typical = node("td", formatNumber(channel.median_views));
    if (channel.median_views_to_subscribers != null) typical.append(node("span", `${channel.median_views_to_subscribers.toFixed(1)}× views/subscriber`, "subtext"));
    const evidence = node("td", channel.evidence);
    evidence.append(node("span", channel.performance_pattern, "subtext"));
    if (channel.history_limit_reached) evidence.append(node("span", "Latest-50 cap reached", "subtext"));
    row.append(title, node("td", channel.subscribers == null ? "Unknown" : formatNumber(channel.subscribers)), typical,
      node("td", formatNumber(channel.median_views_per_hour)), node("td", `${channel.measured_count} / ${channel.upload_count}`),
      node("td", formatPercent(channel.top_video_share)), evidence);
    return row;
  }));
}

async function loadChannels(snapshot, isCurrent = currentSnapshotRequest) {
  const request = ++channelRequest;
  const result = await api(`/api/searches/${snapshot.id}/channels?format=${encodeURIComponent($("channel-format").value)}`);
  if (request !== channelRequest || !isCurrent()) return;
  channelAnalysis = result;
  renderChannels();
}

$("channel-format").addEventListener("change", async () => {
  if (!channelSnapshot) return;
  $("channel-rows").replaceChildren();
  $("channel-detail").hidden = true;
  channelAnalysis = null;
  researchMessage("Loading duration class…");
  try { await loadChannels(channelSnapshot); researchMessage(""); }
  catch (error) { researchMessage(error.message, true); }
});
for (const id of ["subscriber-limit", "minimum-uploads", "channel-sort"]) $(id).addEventListener("change", renderChannels);
initializeResearchPage(async (snapshot, isCurrent) => {
  channelSnapshot = snapshot;
  currentSnapshotRequest = isCurrent;
  if (snapshot.format === "short" || snapshot.format === "long") $("channel-format").value = snapshot.format;
  await loadChannels(snapshot, isCurrent);
});
