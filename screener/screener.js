/* Screener. Loads screener/data/nfl.json and screener/data/college.json. */

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
  sets: { nfl: null, college: null },
};

const head = document.getElementById("head");
const body = document.getElementById("body");
const empty = document.getElementById("empty");
const count = document.getElementById("count");
const season = document.getElementById("season");
const caption = document.getElementById("caption");

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

function current() {
  return state.sets[state.universe];
}

function visible() {
  const data = current();
  if (!data) return [];
  const q = state.query.trim().toLowerCase();
  const rows = data.players.filter((player) => {
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

function render() {
  const data = current();
  renderHead();
  if (!data) {
    body.replaceChildren();
    empty.hidden = false;
    empty.textContent = "Loading.";
    count.textContent = "";
    return;
  }
  if (data.error) {
    body.replaceChildren();
    empty.hidden = false;
    empty.textContent = data.error;
    count.textContent = "";
    season.textContent = "";
    return;
  }
  season.textContent = data.season ? String(data.season) : "";
  caption.textContent = (state.universe === "nfl" ? "NFL" : "College") + " player screener";
  const rows = visible();
  count.textContent = rows.length + (rows.length === 1 ? " player" : " players");
  if (!data.players.length) {
    body.replaceChildren();
    empty.hidden = false;
    empty.textContent = data.empty || "No players in this file.";
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
    const name = document.createElement("span");
    name.className = "name";
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

function setUniverse(next) {
  state.universe = next;
  state.pos = "ALL";
  state.sortKey = next === "nfl" ? "ppr" : "ty";
  state.sortDir = "desc";
  document.body.classList.toggle("college", next === "college");
  document.getElementById("tab-nfl").setAttribute("aria-selected", next === "nfl" ? "true" : "false");
  document.getElementById("tab-college").setAttribute("aria-selected", next === "college" ? "true" : "false");
  for (const chip of document.querySelectorAll(".chip")) {
    chip.classList.toggle("on", chip.dataset.pos === "ALL");
  }
  render();
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

async function load(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

const COLLEGE_EMPTY = "The college file is not in the repo yet. Tried https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_player_box/player_box_2025.csv.gz (game rows, no school or position), plus the 2026 passing, rushing, and receiving season files under espn_cfb_passing, espn_cfb_rushing, and espn_cfb_receiving.";

Promise.all([
  load("data/nfl.json").then((data) => {
    addPosRank(data.players || []);
    state.sets.nfl = data;
  }).catch(() => {
    state.sets.nfl = { error: "NFL stats did not load. Expected data/nfl.json.", players: [] };
  }),
  load("data/college.json").then((data) => {
    data.players = data.players || [];
    if (!data.players.length) data.empty = COLLEGE_EMPTY;
    state.sets.college = data;
  }).catch(() => {
    state.sets.college = { error: COLLEGE_EMPTY, players: [] };
  }),
]).then(() => render());
