"use strict";

let library = [];
let relatedReport = null;
let relatedBusy = false;

function similarMessage(text, error = false) {
  $("similar-message").textContent = text;
  $("similar-message").className = error ? "error" : "helper";
}

function busyRelated(value) {
  relatedBusy = value;
  for (const id of ["find-similar", "channel-reference", "similar-format", "refresh-related", "saved-report"]) $(id).disabled = value;
  $("find-similar").textContent = value ? "Working…" : "Find similar";
}

function chooseReference(channel) {
  if (relatedBusy) return;
  $("channel-reference").value = channel.channel_id;
  $("refresh-related").checked = false;
  $("channel-choices").hidden = true;
  similarMessage(`${channel.title} selected. Click Find similar when ready.`);
  $("channel-reference").focus();
  $("similar-form").scrollIntoView({ behavior: "auto", block: "center" });
}

function renderLibrary() {
  const query = $("library-filter").value.trim().toLocaleLowerCase();
  const rows = library.filter((channel) => [channel.title, ...channel.niches, ...channel.topics].join(" ").toLocaleLowerCase().includes(query));
  $("library-count").textContent = `${rows.length} of ${library.length} saved channels · no YouTube requests`;
  $("library-empty").hidden = rows.length > 0;
  $("library-empty").textContent = library.length ? "No saved channels match this filter." : "Run a niche search on the dashboard to build your channel library.";
  $("library-rows").replaceChildren(...rows.map((channel) => {
    const row = node("tr");
    const title = node("td", null, "wrap-cell");
    title.append(externalLink(channel.title, "channel", channel.channel_id), node("span", channel.topics.join(" · "), "subtext"));
    const niche = node("td", null, "wrap-cell");
    const source = node("a", channel.niches.join(", "));
    source.href = `/channels?search=${channel.search_id}`;
    niche.append(source, node("span", `${channel.window_days}-day sample`, "subtext"));
    const action = node("td");
    const button = node("button", "Use as reference", "secondary");
    button.type = "button";
    button.addEventListener("click", () => chooseReference(channel));
    action.append(button);
    row.append(title, niche, node("td", channel.subscribers == null ? "Unknown" : formatNumber(channel.subscribers)),
      node("td", formatNumber(channel.median_views)), node("td", new Date(channel.captured_at).toLocaleDateString()), action);
    return row;
  }));
}

async function loadLibrary() {
  const result = await api("/api/channel-library");
  library = result.channels;
  renderLibrary();
  const placeholder = node("option", "Choose a saved report");
  placeholder.value = "";
  $("saved-report").replaceChildren(placeholder, ...result.reports.map((report) => {
    const option = node("option", `${report.title} · ${report.format} · ${new Date(report.searched_at).toLocaleString()}`);
    option.value = `${report.channel_id}|${report.format}`;
    return option;
  }));
}

function renderRelated() {
  if (!relatedReport) return;
  const size = $("related-size").value;
  const referenceSize = relatedReport.reference.subscribers;
  const rows = relatedReport.channels.filter((row) => size === "all" || row.subscribers != null &&
    (size === "small" ? row.subscribers < 100000 : referenceSize != null && row.subscribers < referenceSize));
  $("similar-results").hidden = false;
  $("similar-heading").textContent = `Similar to ${relatedReport.reference.title}`;
  $("similar-meta").textContent = `${relatedReport.format} formats · ${rows.length} matches · ${relatedReport.examined_channels} channels examined · saved ${new Date(relatedReport.searched_at).toLocaleString()}`;
  $("related-empty").hidden = rows.length > 0;
  $("related-empty").textContent = size === "smaller" && referenceSize == null ? "The reference channel's subscriber count is unknown. Choose All matches." : "No matches in this selection. Try another size filter, All formats, or another reference.";
  $("related-note").textContent = relatedReport.note;
  $("related-warnings").replaceChildren(...relatedReport.warnings.map((warning) => node("p", warning)));
  $("related-warnings").hidden = !relatedReport.warnings.length;
  $("related-rows").replaceChildren(...rows.map((channel) => {
    const row = node("tr");
    const title = node("td", null, "wrap-cell");
    title.append(externalLink(channel.title, "channel", channel.channel_id));
    const reason = node("td", null, "wrap-cell");
    reason.append(node("span", channel.shared_topics.join(" · ")));
    for (const video of channel.examples) {
      const example = node("div", null, "subtext");
      example.append(externalLink(video.title, "video", video.video_id));
      reason.append(example);
    }
    const evidence = node("td", `${channel.matching_uploads} / ${channel.sampled_uploads} titles overlap`);
    evidence.append(node("span", channel.match_evidence, "subtext"), node("span", channel.performance_pattern, "subtext"));
    row.append(title, node("td", `${channel.similarity.toFixed(1)} / 100`), reason,
      node("td", channel.subscribers == null ? "Unknown" : formatNumber(channel.subscribers)), node("td", formatNumber(channel.median_views)), evidence);
    return row;
  }));
}

async function findSimilar(reference, format, refresh) {
  if (relatedBusy) return;
  busyRelated(true);
  $("channel-choices").hidden = true;
  $("similar-results").hidden = true;
  similarMessage("Checking saved reports, then discovering related channels if needed…");
  try {
    const result = await api("/api/related-channels", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference, format, refresh }) });
    if (result.choices) {
      $("channel-choices").hidden = false;
      $("choice-list").replaceChildren(...result.choices.map((choice) => {
        const card = node("div", null, "choice-card");
        card.append(externalLink(choice.title, "channel", choice.channel_id), node("p", choice.description, "helper"));
        const button = node("button", "Find similar to this channel", "secondary");
        button.type = "button";
        button.addEventListener("click", () => {
          if (!relatedBusy) { $("channel-reference").value = choice.channel_id; findSimilar(choice.channel_id, format, refresh); }
        });
        card.append(button);
        return card;
      }));
      similarMessage("Choose the correct channel below.");
    } else {
      relatedReport = result;
      $("related-size").value = "all";
      renderRelated();
      $("refresh-related").checked = false;
      similarMessage(result.cached ? (result.requests_this_action ? "Saved report loaded after a channel lookup." : "Saved report loaded. No YouTube requests.") : "Related-channel report saved. Reopening it uses no quota.");
      await loadLibrary();
    }
  } catch (error) { similarMessage(error.message, true); }
  finally { busyRelated(false); }
}

$("similar-form").addEventListener("submit", (event) => {
  event.preventDefault();
  return findSimilar($("channel-reference").value.trim(), $("similar-format").value, $("refresh-related").checked);
});
$("library-filter").addEventListener("input", renderLibrary);
$("related-size").addEventListener("change", renderRelated);
$("saved-report").addEventListener("change", async () => {
  if (relatedBusy || !$("saved-report").value) return;
  const [channelId, format] = $("saved-report").value.split("|");
  busyRelated(true);
  $("channel-choices").hidden = true;
  try {
    relatedReport = await api(`/api/related-channels/${encodeURIComponent(channelId)}?format=${encodeURIComponent(format)}`);
    $("channel-reference").value = channelId;
    $("similar-format").value = format;
    $("refresh-related").checked = false;
    $("related-size").value = "all";
    renderRelated();
    similarMessage("Saved report loaded. No YouTube requests.");
  } catch (error) { similarMessage(error.message, true); }
  finally { busyRelated(false); }
});

async function initializeSimilar() {
  const reference = new URLSearchParams(location.search).get("reference");
  if (reference) $("channel-reference").value = reference.slice(0, 200);
  try { await loadLibrary(); }
  catch (error) { $("library-count").textContent = "Saved channels unavailable"; similarMessage(error.message, true); }
}
initializeSimilar();
