"use strict";

const number = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
const selected = new Set();
let current = null;
let saved = [];

function compact(value) { return value === null || value === undefined ? "—" : number.format(value); }
function multiplier(value) { return value === null || value === undefined ? "—" : `${value.toFixed(1)}×`; }
function age(hours) { return hours < 1 ? "<1h" : hours < 48 ? `${Math.floor(hours)}h` : `${Math.floor(hours / 24)}d`; }
function duration(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds / 60) % 60;
  return `${hours ? `${hours}:` : ""}${hours ? String(minutes).padStart(2, "0") : minutes}:${String(seconds % 60).padStart(2, "0")}`;
}
function message(text, error = false) {
  $("message").hidden = !text;
  $("message").textContent = text;
  $("message").className = error ? "error" : "";
}

function renderKeyStatus(ready) {
  $("connection").textContent = ready ? "Key saved" : "Add a key";
  $("setup").hidden = ready;
}

function renderVideos() {
  if (!current) return;
  const field = $("sort").value;
  const rows = [...current.videos].sort((a, b) => (b[field] ?? -1) - (a[field] ?? -1));
  $("videos").replaceChildren();
  $("no-videos").hidden = rows.length > 0;
  for (const video of rows) {
    const row = node("tr");
    const scoreCell = node("td");
    const score = node("span", video.breakout_score.toFixed(1), `score${video.is_breakout ? "" : " muted"}`);
    score.title = video.score_label;
    scoreCell.append(score, node("span", video.is_breakout ? "Breakout" : video.score_label, "subtext"));
    if (video.evidence_note) scoreCell.append(node("span", video.evidence_note, "subtext"));
    const titleCell = node("td");
    const content = node("div", null, "video-cell");
    if (video.thumbnail_url) {
      try {
        const url = new URL(video.thumbnail_url);
        if (url.protocol === "https:" && ["i.ytimg.com", "img.youtube.com"].includes(url.hostname)) {
          const img = node("img");
          img.src = url.href;
          img.alt = "";
          img.loading = "lazy";
          img.width = 104;
          img.height = 59;
          content.append(img);
        }
      } catch { /* An unavailable thumbnail does not prevent video research. */ }
    }
    const text = node("div");
    const link = node("a", video.title);
    link.href = `https://www.youtube.com/watch?v=${encodeURIComponent(video.video_id)}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const channel = node("a", video.channel_title, "channel");
    channel.href = `https://www.youtube.com/channel/${encodeURIComponent(video.channel_id)}`;
    channel.target = "_blank";
    channel.rel = "noopener noreferrer";
    text.append(link, channel, node("span", duration(video.duration_seconds), "subtext"));
    content.append(text);
    titleCell.append(content);
    const outlier = node("td", multiplier(video.outlier_multiplier), "outlier");
    outlier.append(node("span", video.baseline_count ? `${video.baseline_count} earlier ${current.scoring_version === 2 ? "same-class " : ""}uploads` : "No baseline", "subtext"));
    outlier.title = `Channel median: ${compact(video.channel_baseline)} views. ${video.baseline_count < 10 ? "Weak baseline: fewer than 10 uploads." : ""}`;
    const subscribers = node("td", video.subscriber_count === null ? "Unknown" : compact(video.subscriber_count));
    subscribers.append(node("span", video.small_channel_breakout ? "Small-channel hit" : video.small_channel ? "Small channel" : video.subscribers_hidden ? "Not disclosed" : "", "subtext"));
    if (video.views_to_subscribers !== null) subscribers.title = `${video.views_to_subscribers.toFixed(1)}× views/subscribers`;
    const engagement = node("td", `${(video.engagement * 100).toFixed(2)}%`);
    engagement.title = `${compact(video.likes)} likes; ${compact(video.comments)} comments. Comments weighted 3×.`;
    if (video.engagement_incomplete) engagement.append(node("span", "Partial counts", "subtext"));
    row.append(scoreCell, titleCell, node("td", age(video.age_hours)), node("td", compact(video.views)),
      node("td", compact(video.avg_views_per_hour)), outlier, subscribers, engagement);
    $("videos").append(row);
  }
}

function renderResearch(result) {
  current = result;
  $("video-format").value = result.format || "all";
  $("research").hidden = false;
  $("research-heading").textContent = result.query;
  $("research-meta").textContent = `${result.videos.length} videos · ${result.summary.channel_count} creators · ${result.days} days · ${result.format || "all"} formats · ${new Date(result.searched_at).toLocaleDateString()}${result.scoring_version === 2 ? "" : " · Older scoring — rerun to update"}`;
  $("channel-link").href = `/channels?search=${result.id}`;
  $("stats-link").href = `/stats?search=${result.id}`;
  $("research-meta").title = `Saved ${new Date(result.searched_at).toLocaleString()}`;
  $("export").href = `/api/searches/${result.id}/export`;
  $("export").hidden = result.videos.length === 0;
  $("warnings").replaceChildren(...result.warnings.map((warning) => node("p", warning)));
  $("sample-notes").hidden = !result.warnings.length;
  const summary = result.summary;
  const metrics = [
    ["Median views", compact(summary.median_recent_views)],
    ["Median views/hour", compact(summary.median_views_per_hour)],
    ["Median outlier", multiplier(summary.median_outlier_multiplier)],
    ["Small-channel hits", String(summary.small_channel_breakouts)],
    ["Breakout creators", String(summary.independent_breakout_channels)],
  ];
  $("summary").replaceChildren(...metrics.map(([label, value]) => {
    const metric = node("dl", null, "metric");
    metric.append(node("dt", label), node("dd", value));
    return metric;
  }));
  $("phrases").replaceChildren();
  if (!result.phrases.length) $("phrases").append(node("p", "No recurring phrases in this sample.", "empty"));
  for (const phrase of result.phrases) {
    const card = node("div", null, "phrase");
    card.append(node("strong", phrase.phrase), node("span", `${phrase.video_count} videos · ${phrase.channel_count} creators · ${phrase.breakout_lift.toFixed(1)}× lift`));
    card.title = `${phrase.breakout_count} breakout videos`;
    $("phrases").append(card);
  }
  renderVideos();
}

function renderHistory() {
  $("history").replaceChildren();
  if (!saved.length) $("history").append(node("p", "Your searches will appear here.", "empty"));
  for (const search of saved) {
    const item = node("div", null, `history-item${selected.has(search.id) ? " selected" : ""}`);
    const checkbox = node("input");
    checkbox.type = "checkbox";
    checkbox.checked = selected.has(search.id);
    checkbox.setAttribute("aria-label", `Compare ${search.query}, last ${search.days} days, search ${search.id}`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked && selected.size >= 5) {
        checkbox.checked = false;
        $("compare-message").textContent = "Select at most 5 niches.";
        $("compare-message").hidden = false;
        return;
      }
      if (checkbox.checked) selected.add(search.id); else selected.delete(search.id);
      $("comparison").hidden = true;
      $("compare-message").hidden = true;
      renderHistory();
    });
    const open = node("button", search.query);
    open.type = "button";
    open.append(node("small", `${search.days} days · ${new Date(search.searched_at).toLocaleDateString()} · #${search.id}`));
    open.addEventListener("click", async () => {
      try {
        const result = await api(`/api/searches/${search.id}`);
        $("query").value = result.query;
        $("days").value = String(result.days);
        renderResearch(result);
        message("Saved research loaded.");
      } catch (error) { message(error.message, true); }
    });
    item.append(checkbox, open);
    $("history").append(item);
  }
  $("compare").disabled = selected.size < 2;
  $("compare").textContent = `Compare (${selected.size})`;
}

$("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = $("query").value.trim();
  if (query.length < 2) { message("Enter at least two characters for the niche keyword.", true); return; }
  $("analyze").disabled = true;
  $("analyze").textContent = "Analyzing…";
  $("research").setAttribute("aria-busy", "true");
  message("Analyzing videos and channels. This may take a minute…");
  $("message").className = "loading";
  try {
    const result = await api("/api/search", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, days: Number($("days").value), format: $("video-format").value }),
    });
    renderResearch(result);
    const history = await api("/api/searches");
    for (const search of saved) {
      if (search.query.toLowerCase() === query.toLowerCase()) selected.delete(search.id);
    }
    saved = history;
    const visible = new Set(saved.map((search) => search.id));
    for (const id of selected) if (!visible.has(id)) selected.delete(id);
    if (selected.size < 5 && result.videos.length) selected.add(result.id);
    $("comparison").hidden = true;
    renderHistory();
    message(result.videos.length ? "Analysis saved." : "No videos found. Try another keyword.");
  } catch (error) { message(error.message || "Could not reach the server.", true); }
  finally {
    $("analyze").disabled = false;
    $("analyze").textContent = "Analyze";
    $("research").setAttribute("aria-busy", "false");
  }
});
$("sort").addEventListener("change", renderVideos);
$("compare").addEventListener("click", async () => {
  $("compare").disabled = true;
  $("compare-message").hidden = true;
  try {
    const result = await api(`/api/compare?ids=${[...selected].join(",")}`);
    $("niches").replaceChildren(...result.niches.map((niche, index) => {
      const summary = niche.summary;
      const row = node("tr", null, index === 0 ? "winner" : "");
      const title = node("td", `${index + 1}. ${niche.query}`);
      title.append(node("span", `${summary.video_count} videos · ${niche.days} days`, "subtext"));
      row.append(title, node("td", niche.opportunity_score.toFixed(1)), node("td", compact(summary.median_views_per_hour)),
        node("td", multiplier(summary.median_outlier_multiplier)), node("td", summary.breakout_videos),
        node("td", summary.small_channel_breakouts), node("td", summary.independent_breakout_channels),
        node("td", `${(summary.top_phrase_concentration * 100).toFixed(0)}%`));
      return row;
    }));
    $("comparison-note").textContent = result.note;
    $("comparison-note").title = result.note;
    $("comparison").hidden = false;
  } catch (error) {
    $("comparison").hidden = true;
    $("compare-message").hidden = false;
    $("compare-message").textContent = error.message;
  } finally { $("compare").disabled = selected.size < 2; }
});

async function initialize() {
  const results = await Promise.allSettled([api("/api/health"), api("/api/searches")]);
  if (results[0].status === "fulfilled") {
    renderKeyStatus(results[0].value.youtube_key_configured);
  } else {
    $("connection").textContent = "Server unavailable";
    message(results[0].reason.message, true);
  }
  if (results[1].status === "fulfilled") {
    saved = results[1].value;
    renderHistory();
    if (saved.length) {
      try { renderResearch(await api(`/api/searches/${saved[0].id}`)); }
      catch (error) { message(error.message, true); }
    }
  } else { message(`Could not load saved searches: ${results[1].reason.message}`, true); }
}
initialize();
