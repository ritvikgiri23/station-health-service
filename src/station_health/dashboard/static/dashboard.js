// The dashboard: fleet summary tiles, the 24-hour trend and the Poor Hygiene list, from
// the `read` endpoints only. Plain browser JavaScript, no build step and no libraries.
"use strict";

const REFRESH_SECONDS = 30;
const LIST_LIMIT = 50;
const KEY_STORAGE = "station-health-read-key";
const SVG_NS = "http://www.w3.org/2000/svg";

const keyHeader = document.querySelector('meta[name="api-key-header"]').content;
const demoKey = document.querySelector('meta[name="demo-api-key"]').content;

function storedKey() {
  try {
    return sessionStorage.getItem(KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

let apiKey = demoKey || storedKey();

class AuthError extends Error {}

async function getJson(path) {
  const response = await fetch(path, { headers: { [keyHeader]: apiKey } });
  if (response.status === 401 || response.status === 403) {
    throw new AuthError("This key cannot read the dashboard's data. Enter a read API key.");
  }
  if (!response.ok) {
    throw new Error(`${path} answered ${response.status}`);
  }
  return response.json();
}

// --- Formatting ---------------------------------------------------------------

// A dash for a value that is null: nothing was measured.
function orDash(value, format) {
  return value === null || value === undefined ? "–" : format(value);
}

function fixed(value, digits = 0) {
  return orDash(value, (v) => v.toFixed(digits));
}

function percent(fraction) {
  return orDash(fraction, (f) => `${(f * 100).toFixed(1)}%`);
}

function ago(iso) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

function withAttributes(node, attributes) {
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  return node;
}

// API data only ever goes in as text, never as HTML.
function el(tag, attributes = {}, text) {
  const node = withAttributes(document.createElement(tag), attributes);
  if (text !== undefined) node.textContent = text;
  return node;
}

// --- Tiles --------------------------------------------------------------------

function renderTiles(snapshot) {
  const overall = snapshot.overall;
  const tiles = [
    ["Stations", fixed(overall.station_count), null],
    ["Poor Hygiene", fixed(overall.poor_hygiene_count),
      overall.poor_hygiene_percentage === null ? null : `${fixed(overall.poor_hygiene_percentage, 1)}% of Stations`],
    ["Silent", fixed(overall.silent_count), null],
    ["Unverified Stations", fixed(overall.unverified_count), null],
    ["Avg Hygiene Score", fixed(overall.average_hygiene_score, 1), null],
    ["Avg Availability", percent(overall.average_availability), null],
    ["Avg p95 latency", orDash(overall.average_p95_latency_ms, (ms) => `${ms.toFixed(0)} ms`), null],
  ];
  const container = document.getElementById("tiles");
  container.replaceChildren(
    ...tiles.map(([label, value, note]) => {
      const tile = el("div", { class: "tile" });
      tile.append(el("div", { class: "tile-label" }, label), el("div", { class: "tile-value" }, value));
      if (note) tile.append(el("div", { class: "tile-note" }, note));
      return tile;
    }),
  );
  document.getElementById("freshness").textContent = snapshot.scored_at
    ? `Scored ${ago(snapshot.scored_at)} · refreshes every ${REFRESH_SECONDS} s`
    : "Not scored yet: the worker has not completed a scoring run.";
}

// --- Trend chart --------------------------------------------------------------

function svg(tag, attributes) {
  return withAttributes(document.createElementNS(SVG_NS, tag), attributes);
}

function hourLabel(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// A line over the hours: gaps where the value is null (no Station reported that hour).
function lineChart(target, points, value, { max, format }) {
  const width = 480, height = 180, left = 36, right = 8, top = 10, bottom = 24;
  const values = points.map(value);
  const ceiling = max ?? Math.max(1, ...values.filter((v) => v !== null));
  const x = (i) => left + (points.length < 2 ? 0 : (i * (width - left - right)) / (points.length - 1));
  const y = (v) => top + (1 - v / ceiling) * (height - top - bottom);

  target.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const children = [];
  for (const tick of [0, ceiling / 2, ceiling]) {
    children.push(svg("line", { class: "grid", x1: left, x2: width - right, y1: y(tick), y2: y(tick) }));
    const label = svg("text", { class: "axis", x: left - 6, y: y(tick) + 4, "text-anchor": "end" });
    label.textContent = format(tick);
    children.push(label);
  }
  points.forEach((point, i) => {
    if (i % 6 !== 0 && i !== points.length - 1) return;
    const anchor = i === 0 ? "start" : i === points.length - 1 ? "end" : "middle";
    const label = svg("text", { class: "axis", x: x(i), y: height - 6, "text-anchor": anchor });
    label.textContent = hourLabel(point.hour);
    children.push(label);
  });

  let path = "";
  values.forEach((v, i) => {
    if (v === null) return;
    path += `${i > 0 && values[i - 1] !== null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
  });
  children.push(svg("path", { class: "series", d: path }));
  values.forEach((v, i) => {
    if (v === null) return;
    const dot = svg("circle", { class: "dot", cx: x(i), cy: y(v), r: 2.5 });
    const title = svg("title", {});
    title.textContent = `${hourLabel(points[i].hour)}: ${format(v)}`;
    dot.append(title);
    children.push(dot);
  });
  target.replaceChildren(...children);
}

function renderTrend(trend) {
  lineChart(document.getElementById("trend-score"), trend.points, (p) => p.average_hygiene_score, {
    max: 100,
    format: (v) => v.toFixed(0),
  });
  lineChart(document.getElementById("trend-below"), trend.points, (p) => p.below_flag_threshold_count, {
    format: (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1)),
  });
}

// --- Poor Hygiene list ----------------------------------------------------------

function renderList(page) {
  const shown = page.items.length;
  document.getElementById("list-total").textContent =
    page.total > shown ? `(${page.total}, worst ${shown} shown)` : `(${page.total})`;
  const rows = page.items.map((station) => {
    const row = el("tr");
    const id = el("td", {}, station.station_id);
    if (!station.verified) id.append(" ", el("span", { class: "badge unverified" }, "Unverified Station"));
    const reason = el("td");
    reason.append(el("span", { class: `badge reason-${station.flag_reason}` }, station.flag_reason));
    const since = el("td", { title: station.flagged_since ?? "" },
      orDash(station.flagged_since, ago));
    row.append(
      id,
      el("td", {}, station.region ?? "unassigned"),
      el("td", { class: "num" }, station.silent ? "Silent" : fixed(station.score)),
      reason,
      since,
    );
    return row;
  });
  if (rows.length === 0) {
    const empty = el("tr");
    empty.append(el("td", { colspan: 5, class: "muted" }, "No Station has Poor Hygiene."));
    rows.push(empty);
  }
  document.getElementById("list-body").replaceChildren(...rows);
}

// --- Loading --------------------------------------------------------------------

function showError(message) {
  const error = document.getElementById("error");
  error.textContent = message;
  error.hidden = !message;
}

async function refresh() {
  if (!apiKey) {
    document.getElementById("key-form").hidden = false;
    document.getElementById("freshness").textContent = "Enter a read API key to load the dashboard.";
    return;
  }
  try {
    const [snapshot, trend, page] = await Promise.all([
      getJson("/metrics"),
      getJson("/metrics/trend?hours=24"),
      getJson(`/poor-hygiene?sort=score&limit=${LIST_LIMIT}`),
    ]);
    renderTiles(snapshot);
    renderTrend(trend);
    renderList(page);
    showError("");
  } catch (error) {
    if (error instanceof AuthError) document.getElementById("key-form").hidden = false;
    showError(error.message);
  }
}

document.getElementById("key-form").addEventListener("submit", (event) => {
  event.preventDefault();
  apiKey = document.getElementById("key-input").value.trim();
  try {
    sessionStorage.setItem(KEY_STORAGE, apiKey);
  } catch {
    // Without storage the key lasts until the page is reloaded.
  }
  document.getElementById("key-form").hidden = true;
  refresh();
});

refresh();
setInterval(refresh, REFRESH_SECONDS * 1000);
