// Dependency-free DOM smoke tests. These exercise page behavior, not browser layout.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.attrs = {}; this._text = ""; this._value = ""; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
  set value(value) { this._value = String(value); }
  get value() { return this._value; }
  append(...children) { this.children.push(...children); if (this.tag === "select" && !this.value) this.value = this.children[0]?.value || ""; }
  replaceChildren(...children) { this.children = []; this._text = ""; if (this.tag === "select") this.value = ""; this.append(...children); }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  addEventListener(name, handler) { this.events[name] = handler; }
  get options() { return this.children; }
  get selectedOptions() { return this.children.filter((child) => child.value === this.value); }
  focus() {}
  scrollIntoView() {}
}

const snapshot = (id = 1) => ({ id, query: `niche ${id}`, days: 30, format: "short", scoring_version: 2, searched_at: "2026-10-23T12:00:00+00:00" });
const channel = (id, subscribers) => ({ channel_id: id, title: `<script>${id}</script>`, subscribers, matched_videos: 2,
  upload_count: 5, measured_count: 5, median_views: 1000, median_views_per_hour: 20, median_views_to_subscribers: 2,
  top_video_share: .2, supported: true, evidence: "Developing sample", performance_pattern: "Spread across uploads",
  uploads_per_week: 1, upload_history_available: true, history_limit_reached: false,
  videos: [{ video_id: "v1", title: "Example", views: 1000, duration_seconds: 30, age_hours: 48, published_at: "2026-10-21T12:00:00Z" }] });
const channelReport = { available: true, channels: [channel("known", 500), channel("hidden", null)],
  coverage: { discovered_channels: 2, supported_channels: 2, small_channels: 1, unknown_subscribers: 1 }, note: "Sample only" };
const stats = { video_count: 2, channel_count: 1, total_views: 1000, top_channel_share: 1, baseline_supported: 1,
  channel_views: [{ title: "Creator", views: 1000 }], formats: [{ format: "short", videos: 2 }],
  uploads_by_date: [{ date: "2026-10-21", uploads: 2, views: 1000 }], growth: [], note: "Sample only" };

function page(name, override = () => undefined) {
  const frontend = path.join(__dirname, "..", "frontend");
  const html = fs.readFileSync(path.join(frontend, `${name}.html`), "utf8");
  const elements = new Map();
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const element = new Element(match[1]);
    element.hidden = /\bhidden\b/.test(match[0]);
    element.disabled = /\bdisabled\b/.test(match[0]);
    elements.set(match[2], element);
  }
  for (const match of html.matchAll(/<select\b[^>]*id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)) {
    const element = elements.get(match[1]);
    for (const option of match[2].matchAll(/<option([^>]*)>([^<]*)<\/option>/g)) {
      const item = new Element("option");
      item.value = /value="([^"]*)"/.exec(option[1])?.[1] || option[2];
      item.textContent = option[2];
      element.append(item);
      if (/\bselected\b/.test(option[1])) element.value = item.value;
    }
  }
  const calls = [];
  const location = new URL(`http://localhost/${name}`);
  const context = vm.createContext({ URL, URLSearchParams, Intl, console, location,
    history: { replaceState(_state, _title, url) { location.href = url.href; } },
    document: { getElementById: (id) => { assert.ok(elements.has(id), `Missing ${id}`); return elements.get(id); },
      createElement: (tag) => new Element(tag), createElementNS: (_ns, tag) => new Element(tag),
      addEventListener() {}, querySelectorAll: () => [] },
    fetch: async (url, options) => {
      calls.push({ url, options });
      let data = await override(url, options);
      if (data === undefined) {
        if (url === "/api/searches") data = [snapshot(1), snapshot(2)];
        else if (url.endsWith("/stats")) data = stats;
        else if (url.includes("/channels?")) data = channelReport;
        else if (/\/api\/searches\/\d+$/.test(url)) data = snapshot(Number(url.split("/").at(-1)));
        else if (url === "/api/search") data = snapshot(3);
        else throw new Error(`Unexpected request: ${url}`);
      }
      return { ok: true, json: async () => data };
    },
  });
  for (const script of ["common.js", "research.js", `${name}.js`]) vm.runInContext(fs.readFileSync(path.join(frontend, script), "utf8"), context, { filename: script });
  return { elements, context, calls, get: (id) => elements.get(id) };
}

async function loaded(app) {
  for (let i = 0; i < 30; i++) {
    await new Promise(setImmediate);
    if (!app.get("analysis-content").hidden) return;
  }
  assert.fail(`Page did not load: ${app.get("page-message").textContent}`);
}

test("channel filters, safe titles, upload drilldown and format changes", async () => {
  const app = page("channels");
  await loaded(app);
  assert.equal(app.get("channel-rows").children.length, 1);
  const button = app.get("channel-rows").children[0].children[0].children[0];
  assert.equal(button.textContent, "<script>known</script>");
  await button.events.click();
  assert.equal(app.get("channel-detail").hidden, false);
  assert.equal(app.get("channel-upload-rows").children.length, 1);
  assert.equal(app.get("channel-chart").children[0].tag, "svg");
  app.get("subscriber-limit").value = "0";
  await app.get("subscriber-limit").events.change();
  assert.equal(app.get("channel-rows").children.length, 2);
  app.get("channel-format").value = "long";
  await app.get("channel-format").events.change();
  assert.ok(app.calls.some((call) => call.url.endsWith("format=long")));
});

test("stats charts switch measures and distinguish missing growth", async () => {
  const app = page("stats");
  await loaded(app);
  assert.equal(app.get("creator-chart").children[0].tag, "svg");
  assert.equal(app.get("growth-empty").hidden, false);
  app.get("timeline-metric").value = "views";
  await app.get("timeline-metric").events.change();
  assert.match(app.get("timeline-chart").textContent, /1,000/);
  assert.equal(app.get("related-page").href, "/channels?search=1");
});

test("a failed refresh restores controls and keeps current research", async () => {
  const app = page("channels", (url) => { if (url === "/api/search") throw new Error("Quota reached"); });
  await loaded(app);
  await app.get("refresh-search").events.click();
  assert.equal(app.get("refresh-search").disabled, false);
  assert.equal(app.get("saved-search").disabled, false);
  assert.match(app.get("page-message").textContent, /Quota reached/);
  assert.equal(app.get("channel-rows").children.length, 1);
});

test("late channel response cannot overwrite a newly selected snapshot", async () => {
  let release;
  const slow = new Promise((resolve) => { release = resolve; });
  const app = page("channels", (url) => url.startsWith("/api/searches/1/channels") ? slow : undefined);
  for (let i = 0; i < 30 && !app.calls.some((call) => call.url.includes("/1/channels")); i++) await new Promise(setImmediate);
  app.get("saved-search").value = "2";
  await app.get("saved-search").events.change();
  release({ ...channelReport, channels: [channel("stale", 1000)] });
  await loaded(app);
  await new Promise(setImmediate);
  assert.match(app.get("channel-rows").textContent, /known/);
  assert.doesNotMatch(app.get("channel-rows").textContent, /stale/);
  assert.match(app.get("snapshot-meta").textContent, /niche 2/);
});

const libraryFixture = { channels: [{ ...channel("UC" + "a".repeat(22), 500), niches: ["robot"], topics: ["tiny", "robot"],
  search_id: 1, captured_at: "2026-10-23T12:00:00Z", window_days: 30 }], reports: [] };

async function libraryLoaded(app) {
  for (let i = 0; i < 30; i++) {
    await new Promise(setImmediate);
    if (app.get("library-rows").children.length) return;
  }
  assert.fail(`Library did not load: ${app.get("similar-message").textContent}`);
}

test("similar page browsing, filtering and reference selection never start discovery", async () => {
  const app = page("similar", (url) => {
    if (url === "/api/channel-library") return libraryFixture;
    throw new Error(`Unexpected API use: ${url}`);
  });
  await libraryLoaded(app);
  assert.equal(app.calls.length, 1);
  const button = app.get("library-rows").children[0].children.at(-1).children[0];
  await button.events.click();
  assert.equal(app.get("channel-reference").value, libraryFixture.channels[0].channel_id);
  app.get("library-filter").value = "robot";
  await app.get("library-filter").events.input();
  assert.equal(app.calls.length, 1);
  assert.equal(app.get("library-rows").children.length, 1);
});

test("similar discovery runs only on submit, requires channel selection, and restores controls on failure", async () => {
  let discoveryCount = 0;
  const app = page("similar", (url, options) => {
    if (url === "/api/channel-library") return libraryFixture;
    if (url === "/api/related-channels") {
      discoveryCount++;
      assert.equal(options.method, "POST");
      if (discoveryCount === 1) return { choices: [{ channel_id: libraryFixture.channels[0].channel_id, title: "Robot Lab", description: "Example" }] };
      throw new Error("Quota reached");
    }
    throw new Error(url);
  });
  await libraryLoaded(app);
  app.get("channel-reference").value = "Robot Lab";
  app.get("refresh-related").checked = false;
  await app.get("similar-form").events.submit({ preventDefault() {} });
  assert.equal(discoveryCount, 1);
  assert.equal(app.get("channel-choices").hidden, false);
  assert.equal(app.get("find-similar").disabled, false);
  await app.get("choice-list").children[0].children.at(-1).events.click();
  for (let i = 0; i < 20 && app.get("find-similar").disabled; i++) await new Promise(setImmediate);
  assert.equal(discoveryCount, 2);
  assert.match(app.get("similar-message").textContent, /Quota reached/);
  assert.equal(app.get("find-similar").disabled, false);
});

test("opening a saved similarity report only reads local data", async () => {
  const cid = libraryFixture.channels[0].channel_id;
  const app = page("similar", (url, options) => {
    assert.ok(!options?.method || options.method === "GET");
    if (url === "/api/channel-library") return { ...libraryFixture, reports: [{ channel_id: cid, title: "Robot Lab", format: "short", searched_at: "2026-10-23T12:00:00Z" }] };
    if (url.startsWith("/api/related-channels/")) return { reference: { channel_id: cid, title: "Robot Lab", subscribers: 500 },
      channels: [], format: "short", examined_channels: 12, searched_at: "2026-10-23T12:00:00Z", warnings: [], note: "Title evidence only" };
    throw new Error(url);
  });
  await libraryLoaded(app);
  app.get("saved-report").value = `${cid}|short`;
  await app.get("saved-report").events.change();
  assert.equal(app.get("similar-results").hidden, false);
  assert.match(app.get("similar-message").textContent, /No YouTube requests/);
  assert.equal(app.calls.length, 2);
});
