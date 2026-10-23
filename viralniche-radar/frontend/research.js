"use strict";

const formatNumber = (value) => value == null ? "—" : new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value);
const formatPercent = (value) => value == null ? "—" : `${(value * 100).toFixed(1)}%`;

function researchMessage(text, error = false) {
  $("page-message").textContent = text;
  $("page-message").className = error ? "error" : "helper";
}

function renderMetrics(id, entries) {
  $(id).replaceChildren(...entries.map(([label, value]) => {
    const metric = node("dl", null, "metric");
    metric.append(node("dt", label), node("dd", value));
    return metric;
  }));
}

function externalLink(text, kind, id) {
  const link = node("a", text);
  link.href = kind === "channel" ? `https://www.youtube.com/channel/${encodeURIComponent(id)}` : `https://www.youtube.com/watch?v=${encodeURIComponent(id)}`;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function barChart(containerId, entries, title) {
  const container = $(containerId);
  container.replaceChildren();
  if (!entries.length) { container.append(node("p", "No data in this sample.", "empty")); return; }
  const svgElement = (tag, attributes = {}, text) => {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    // SVG defaults to black when chart styles are unavailable or still cached.
    // Presentation attributes keep charts readable without inline CSS.
    if (tag === "text") element.setAttribute("fill", attributes.class === "chart-value" ? "#f1f1f4" : "#c5c5cf");
    if (tag === "rect") element.setAttribute("fill", "#f46b7e");
    for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
    if (text != null) element.textContent = text;
    return element;
  };
  const width = 660, left = 175, plotWidth = 390, height = entries.length * 35 + 36;
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": title, class: "bar-chart" });
  svg.append(svgElement("title", {}, title));
  const maximum = Math.max(1, ...entries.map((entry) => entry.value));
  svg.append(svgElement("text", { x: left, y: 14, class: "chart-label" }, "0"));
  svg.append(svgElement("text", { x: left + plotWidth, y: 14, "text-anchor": "end", class: "chart-label" }, formatNumber(maximum)));
  entries.forEach((entry, index) => {
    const y = index * 35 + 26;
    const label = entry.label.length > 23 ? `${entry.label.slice(0, 21)}…` : entry.label;
    svg.append(svgElement("text", { x: left - 12, y: y + 16, "text-anchor": "end", class: "chart-label" }, label));
    const bar = svgElement("rect", { x: left, y, width: entry.value / maximum * plotWidth, height: 23, rx: 3, class: "chart-bar" });
    bar.append(svgElement("title", {}, `${entry.label}: ${entry.value.toLocaleString()}`));
    svg.append(bar, svgElement("text", { x: left + plotWidth + 12, y: y + 16, class: "chart-value" }, formatNumber(entry.value)));
  });
  container.append(svg);
  const details = node("details", null, "chart-data");
  details.append(node("summary", "View chart data"));
  const list = node("dl");
  for (const entry of entries) list.append(node("dt", entry.label), node("dd", entry.value.toLocaleString()));
  details.append(list);
  container.append(details);
}

async function initializeResearchPage(onSnapshot) {
  let snapshot = null;
  let generation = 0;
  let refreshing = false;
  const selector = $("saved-search");
  const refresh = $("refresh-search");
  const populate = (history, selectedId) => {
    selector.replaceChildren(...history.map((item) => {
      const option = node("option", `${item.query} · ${item.days} days · ${new Date(item.searched_at).toLocaleString()} · #${item.id}`);
      option.value = item.id;
      return option;
    }));
    if (selectedId != null) selector.value = String(selectedId);
    selector.disabled = !history.length;
  };
  async function load(id, provided) {
    const request = ++generation;
    snapshot = null;
    refresh.disabled = true;
    $("analysis-content").hidden = true;
    researchMessage("Loading research…");
    try {
      const data = provided || await api(`/api/searches/${encodeURIComponent(id)}`);
      if (request !== generation) return;
      snapshot = data;
      const url = new URL(location.href);
      url.searchParams.set("search", data.id);
      history.replaceState(null, "", url);
      $("related-page").href = `${location.pathname === "/channels" ? "/stats" : "/channels"}?search=${data.id}`;
      $("snapshot-meta").textContent = `${data.query} · ${data.days}-day window · ${data.format || "all"} formats · captured ${new Date(data.searched_at).toLocaleString()}`;
      await onSnapshot(data, () => request === generation);
      if (request !== generation) return;
      snapshot = data;
      $("analysis-content").hidden = false;
      researchMessage(data.scoring_version === 2 ? "" : "Older scoring snapshot. Refresh to use the updated method and channel histories.");
    } catch (error) {
      if (request === generation) researchMessage(error.message, true);
    } finally { if (request === generation) refresh.disabled = !snapshot || refreshing; }
  }
  selector.addEventListener("change", () => load(selector.value));
  refresh.addEventListener("click", async () => {
    if (!snapshot || refreshing) return;
    refreshing = true;
    refresh.disabled = selector.disabled = true;
    refresh.textContent = "Refreshing…";
    researchMessage("Collecting a new snapshot. This uses YouTube API quota…");
    try {
      const data = await api("/api/search", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: snapshot.query, days: snapshot.days, format: snapshot.format || "all" }) });
      await load(data.id, data);
      populate(await api("/api/searches"), data.id);
    } catch (error) { researchMessage(error.message, true); }
    finally { refreshing = false; refresh.disabled = !snapshot; selector.disabled = !selector.options.length; refresh.textContent = "Refresh research"; }
  });
  try {
    const items = await api("/api/searches");
    populate(items);
    if (!items.length) { researchMessage("Run a niche search on the dashboard first. Saved research will appear here."); return; }
    const requested = new URLSearchParams(location.search).get("search");
    const id = requested && /^\d+$/.test(requested) ? Number(requested) : items[0].id;
    if (!items.some((item) => item.id === id)) {
      const option = node("option", `Saved research #${id}`);
      option.value = id;
      selector.append(option);
    }
    selector.value = String(id);
    await load(id);
  } catch (error) { researchMessage(error.message, true); }
}
