/* Screener. Season files live under screener/data/nfl and screener/data/college. */

const NFL_COLS = [
  { key: "posRank", label: "Pos Rank" },
  { key: "ppr", label: "PPR", digits: 1 },
  { key: "ppg", label: "PPG", digits: 1 },
  { key: "gp", label: "GP" },
  { key: "py", label: "Pass Yds" },
  { key: "ptd", label: "Pass TD" },
  { key: "ry", label: "Rush Yds" },
  { key: "rtd", label: "Rush TD" },
  { key: "rec", label: "REC" },
  { key: "rey", label: "Rec Yds" },
  { key: "retd", label: "Rec TD" },
  { key: "tgt", label: "TGT" },
  { key: "td", label: "TD" },
];

const COLLEGE_COLS = [
  { key: "gp", label: "GP" },
  { key: "py", label: "Pass Yds" },
  { key: "ptd", label: "Pass TD" },
  { key: "ry", label: "Rush Yds" },
  { key: "rtd", label: "Rush TD" },
  { key: "rey", label: "Rec Yds" },
  { key: "retd", label: "Rec TD" },
  { key: "ty", label: "Total Yds" },
  { key: "td", label: "Total TD" },
];

const state = {
  universe: "nfl",
  pos: "ALL",
  query: "",
  sortKey: "ppr",
  sortDir: "desc",
  season: null,
  week: "",
};

const cache = {
  nfl: new Map(),
  weeks: new Map(),
  college: new Map(),
};

let catalog = null;
let view = null;
let loadId = 0;

const head = document.getElementById("head");
const body = document.getElementById("body");
const empty = document.getElementById("empty");
const count = document.getElementById("count");
const caption = document.getElementById("caption");
const seasonSelect = document.getElementById("season-select");
const weekSelect = document.getElementById("week-select");
const weekControl = document.getElementById("week-control");

function cols() {
  return state.universe === "nfl" ? NFL_COLS : COLLEGE_COLS;
}

function missing(value) {
  return value === undefined || value === null || value === "";
}

function format(value, digits) {
  if (missing(value)) return "";
  const n = Number(value);
  if (!Number.isFinite(n)) return "";
  if (digits == null) return n.toLocaleString("en-US");
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function addPosRank(players) {
  const groups = new Map();
  for (const player of players) {
    if (!groups.has(player.pos)) groups.set(player.pos, []);
    groups.get(player.pos).push(player);
  }
  for (const list of groups.values()) {
    list.sort((a, b) => (b.ppr ?? -Infinity) - (a.ppr ?? -Infinity) || a.name.localeCompare(b.name));
    let rank = 0;
    let prev = null;
    list.forEach((player, index) => {
      if (missing(player.ppr)) {
        player.posRank = null;
        return;
      }
      if (prev === null || player.ppr !== prev) rank = index + 1;
      player.posRank = rank;
      prev = player.ppr;
    });
  }
}

function nflSeason(year) {
  return catalog.nfl.seasons.find((row) => row.year === year);
}

function yearsForUniverse() {
  if (state.universe === "nfl") {
    return catalog.nfl.seasons.map((row) => row.year).slice().reverse();
  }
  return catalog.college.seasons.slice().reverse();
}

function fillSeason() {
  seasonSelect.replaceChildren();
  for (const year of yearsForUniverse()) {
    const option = document.createElement("option");
    option.value = String(year);
    option.textContent = String(year);
    if (year === state.season) option.selected = true;
    seasonSelect.appendChild(option);
  }
}

function fillWeeks() {
  if (state.universe !== "nfl") {
    weekControl.hidden = true;
    return;
  }
  weekControl.hidden = false;
  const meta = nflSeason(state.season);
  weekSelect.replaceChildren();
  const seasonOption = document.createElement("option");
  seasonOption.value = "";
  seasonOption.textContent = "Season";
  weekSelect.appendChild(seasonOption);
  const disabled = new Set((meta && meta.disabledWeeks) || []);
  const present = (meta && meta.weeks) || [];
  const last = Math.max(0, ...present, ...disabled);
  for (let week = 1; week <= last; week += 1) {
    const option = document.createElement("option");
    option.value = String(week);
    option.textContent = "Week " + week;
    if (disabled.has(week) || present.indexOf(week) === -1) {
      option.disabled = true;
    }
    if (state.week === String(week)) option.selected = true;
    weekSelect.appendChild(option);
  }
  if (!state.week) seasonOption.selected = true;
}

function visible() {
  if (!view || !view.players) return [];
  const q = state.query.trim().toLowerCase();
  const rows = view.players.filter((player) => {
    if (state.pos !== "ALL" && player.pos !== state.pos) return false;
    if (q && !player.name.toLowerCase().includes(q)) return false;
    return true;
  });
  const key = state.sortKey;
  const dir = state.sortDir === "asc" ? 1 : -1;
  rows.sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    const aMissing = missing(av);
    const bMissing = missing(bv);
    if (aMissing && bMissing) return a.name.localeCompare(b.name);
    if (aMissing) return 1;
    if (bMissing) return -1;
    if (typeof av === "string" || typeof bv === "string") {
      return String(av).localeCompare(String(bv)) * dir;
    }
    if (av === bv) return a.name.localeCompare(b.name);
    return av < bv ? -dir : dir;
  });
  return rows;
}

function meta(player) {
  if (state.universe === "nfl") {
    const bits = [player.team, player.pos];
    if (!missing(player.age)) bits.push(String(player.age));
    return bits.filter(Boolean).join(" · ");
  }
  return [player.team, player.conference, player.pos].filter(Boolean).join(" · ");
}

function renderHead() {
  const row = document.createElement("tr");
  const rank = document.createElement("th");
  rank.className = "ident rank";
  rank.textContent = "#";
  rank.scope = "col";
  row.appendChild(rank);

  const player = document.createElement("th");
  player.className = "ident player";
  player.textContent = "Player";
  player.scope = "col";
  row.appendChild(player);

  for (const col of cols()) {
    const th = document.createElement("th");
    th.scope = "col";
    th.dataset.key = col.key;
    const on = state.sortKey === col.key;
    th.className = on ? "sorted" : "";
    th.setAttribute("aria-sort", on ? (state.sortDir === "asc" ? "ascending" : "descending") : "none");
    const mark = on ? (state.sortDir === "asc" ? " ▲" : " ▼") : "";
    th.textContent = col.label + mark;
    th.addEventListener("click", () => {
      if (state.sortKey === col.key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = col.key;
        state.sortDir = "desc";
      }
      render();
    });
    row.appendChild(th);
  }
  head.replaceChildren(row);
}

function scopeLabel() {
  const league = state.universe === "nfl" ? "NFL" : "College";
  if (!state.season) return league + " player screener";
  if (state.universe === "nfl" && state.week) {
    return league + " " + state.season + " week " + state.week + " player screener";
  }
  return league + " " + state.season + " player screener";
}

function render() {
  renderHead();
  caption.textContent = scopeLabel();
  if (!view) {
    body.replaceChildren();
    empty.hidden = false;
    empty.textContent = "pulling film...";
    count.textContent = "";
    return;
  }
  if (view.error) {
    body.replaceChildren();
    empty.hidden = false;
    empty.textContent = view.error;
    count.textContent = "";
    return;
  }
  const rows = visible();
  count.textContent = rows.length + (rows.length === 1 ? " player" : " players");
  if (!view.players.length) {
    body.replaceChildren();
    empty.hidden = false;
    empty.textContent = "No players in this file.";
    return;
  }
  empty.hidden = rows.length > 0;
  empty.textContent = rows.length ? "" : "No players match.";
  const frag = document.createDocumentFragment();
  const columns = cols();
  rows.forEach((player, index) => {
    const tr = document.createElement("tr");
    tr.className = player.pos || "";
    const rank = document.createElement("td");
    rank.className = "ident rank";
    rank.textContent = String(index + 1);
    tr.appendChild(rank);
    const who = document.createElement("td");
    who.className = "ident player";
    const badge = document.createElement("span");
    badge.className = "pos " + (player.pos || "");
    badge.textContent = player.pos || "";
    const name = document.createElement("a");
    name.className = "name";
    if (state.universe === "college" && player.cid) {
      name.href =
        "/player?cid=" +
        encodeURIComponent(player.cid) +
        "&season=" +
        encodeURIComponent(String(state.season));
    } else if (player.gsisId) {
      name.href =
        "/player?gsis=" +
        encodeURIComponent(player.gsisId) +
        "&season=" +
        encodeURIComponent(String(state.season));
    } else {
      name.href = "/player?name=" + encodeURIComponent(player.name);
    }
    name.textContent = player.name;
    const sub = document.createElement("span");
    sub.className = "meta";
    sub.textContent = meta(player);
    who.appendChild(badge);
    who.appendChild(name);
    who.appendChild(sub);
    tr.appendChild(who);
    for (const col of columns) {
      const td = document.createElement("td");
      td.textContent = format(player[col.key], col.digits);
      tr.appendChild(td);
    }
    frag.appendChild(tr);
  });
  body.replaceChildren(frag);
}

async function load(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

function loadNfl(year) {
  if (!cache.nfl.has(year)) {
    cache.nfl.set(year, load("data/nfl/" + year + ".json"));
  }
  return cache.nfl.get(year);
}

function loadWeeks(year) {
  if (!cache.weeks.has(year)) {
    cache.weeks.set(year, load("data/nfl/" + year + "-weeks.json"));
  }
  return cache.weeks.get(year);
}

function loadCollege(year) {
  if (!cache.college.has(year)) {
    cache.college.set(year, load("data/college/" + year + ".json"));
  }
  return cache.college.get(year);
}

async function refresh() {
  const id = ++loadId;
  const universe = state.universe;
  const season = state.season;
  const week = state.week;
  view = null;
  render();
  try {
    let data;
    if (universe === "nfl" && week) {
      const pack = await loadWeeks(season);
      const players = (pack.weeks && pack.weeks[week]) || [];
      data = { season: pack.season, players: players.slice() };
      addPosRank(data.players);
    } else if (universe === "nfl") {
      const pack = await loadNfl(season);
      data = { season: pack.season, players: pack.players.slice() };
      addPosRank(data.players);
    } else {
      const pack = await loadCollege(season);
      data = { season: pack.season, players: pack.players.slice() };
    }
    if (id !== loadId) return;
    view = data;
  } catch (err) {
    if (id !== loadId) return;
    cache.nfl.delete(season);
    cache.weeks.delete(season);
    cache.college.delete(season);
    view = {
      error: "That file did not load. Expected data for " + universe + " " + season + ".",
      players: [],
    };
  }
  render();
}

function setUniverse(next) {
  state.universe = next;
  state.pos = "ALL";
  state.week = "";
  state.sortKey = next === "nfl" ? "ppr" : "ty";
  state.sortDir = "desc";
  state.season = next === "nfl" ? catalog.nfl.defaultSeason : catalog.college.defaultSeason;
  document.body.classList.toggle("college", next === "college");
  document.getElementById("tab-nfl").setAttribute("aria-selected", next === "nfl" ? "true" : "false");
  document.getElementById("tab-college").setAttribute("aria-selected", next === "college" ? "true" : "false");
  for (const chip of document.querySelectorAll(".chip")) {
    chip.classList.toggle("on", chip.dataset.pos === "ALL");
  }
  fillSeason();
  fillWeeks();
  refresh();
}

document.getElementById("tab-nfl").addEventListener("click", () => setUniverse("nfl"));
document.getElementById("tab-college").addEventListener("click", () => setUniverse("college"));

for (const chip of document.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => {
    state.pos = chip.dataset.pos;
    for (const other of document.querySelectorAll(".chip")) {
      other.classList.toggle("on", other === chip);
    }
    render();
  });
}

document.getElementById("search").addEventListener("input", (event) => {
  state.query = event.target.value;
  render();
});

seasonSelect.addEventListener("change", () => {
  state.season = Number(seasonSelect.value);
  const meta = state.universe === "nfl" ? nflSeason(state.season) : null;
  if (!meta || (state.week && meta.weeks.indexOf(Number(state.week)) === -1)) {
    state.week = "";
  }
  fillWeeks();
  refresh();
});

weekSelect.addEventListener("change", () => {
  state.week = weekSelect.value;
  refresh();
});

load("data/catalog.json").then((data) => {
  catalog = data;
  state.season = data.nfl.defaultSeason;
  state.week = "";
  fillSeason();
  fillWeeks();
  refresh();
}).catch(() => {
  view = { error: "The season list did not load. Expected data/catalog.json.", players: [] };
  render();
});
