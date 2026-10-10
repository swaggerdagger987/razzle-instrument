#!/usr/bin/env python3
"""Razzle shell. Stdlib only. python3 app.py serves port 8080."""

import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB_PATH = DATA / "razzle.db"
HOST = "0.0.0.0"
PORT = 8080
PBKDF2_ROUNDS = 200_000
STATIC_EXT = {".html", ".css", ".js", ".json", ".md", ".txt"}
PLAYER_CSS = ROOT / "player.css"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}
KEY_MISSING = "The key is not set."
POS_NFL_STATS = {
    "QB": ("gp", "ppr", "ppg", "py", "ptd", "ry", "rtd", "td"),
    "RB": ("gp", "ppr", "ppg", "ry", "rtd", "rec", "rey", "retd", "tgt"),
    "WR": ("gp", "ppr", "ppg", "rec", "rey", "retd", "tgt", "td"),
    "TE": ("gp", "ppr", "ppg", "rec", "rey", "retd", "tgt", "td"),
}
SAMPLE_VERDICT = {
    "QB": "Start him if the rushing floor is still there — passing volume carries the week.",
    "RB": "Start him. Touch share is sitting on the starter line.",
    "WR": "Start him. Targets are the whole story until the box adjusts.",
    "TE": "Flex him. Red-zone looks are the edge; everything else is noise.",
}
SAMPLE_LEVERAGE = (
    "Leverage read (sample): rostered in most leagues, "
    "but the trade market still sleeps on this usage curve."
)
ODDS_MISSING = "Championship odds are not computed yet."
ENGINE_NOTE = (
    "Four-team playoff sandbox from the valuation engine (fixed bracket assumptions). "
    "Not your Sleeper league bracket yet."
)
NFL_SKILL = frozenset({"QB", "RB", "WR", "TE"})
MODEL_URL_DEFAULT = "https://api.openai.com/v1/chat/completions"
MODEL_NAME_DEFAULT = "gpt-4o-mini"
SYSTEM = (
    "You are the Razzle War Room, film-room staff that already has this league. "
    "Use only the league context given. If it is not in the context, say you do not have it. "
    "Do not invent records, scores, injuries, or roster spots. "
    "Speak in short, confident football language. "
    "Do not describe how you are implemented."
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  salt TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sleeper_links (
  user_id INTEGER PRIMARY KEY,
  username TEXT,
  sleeper_user_id TEXT,
  league_id TEXT,
  league_name TEXT
);
CREATE TABLE IF NOT EXISTS league_choices (
  user_id INTEGER NOT NULL,
  league_id TEXT NOT NULL,
  name TEXT NOT NULL,
  PRIMARY KEY (user_id, league_id)
);
CREATE TABLE IF NOT EXISTS war_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""

_DB_LOCK = threading.Lock()
_PLAYERS_LOCK = threading.Lock()
_SLEEPER = None
_CATALOG = None
_NFL_PACKS = {}
_NFL_GSIS = {}
_COLLEGE_PACKS = {}
_ENGINE_SNAPSHOT = None
_ENGINE_LOCK = threading.Lock()


class SleeperError(Exception):
    def __init__(self, code):
        super().__init__(f"sleeper {code}")
        self.code = code


def h(value):
    return html.escape("" if value is None else str(value), quote=True)


def sample_badge():
    return '<span class="badge sample">Sample</span>'


def roster_entry_parts(entry):
    if isinstance(entry, tuple):
        return entry[0], str(entry[1])
    return None, str(entry)


def pos_for_roster_entry(pid, name):
    if pid:
        try:
            rec = (load_sleeper_index() or {}).get(str(pid))
        except SleeperError:
            rec = None
        if rec and rec.get("position"):
            return str(rec["position"])
    if name and not str(name).startswith("id "):
        stats_season, on_disk = nfl_stats_season()
        if on_disk:
            found, _ = find_players_by_name(name, stats_season)
            if found:
                return str(found[0].get("pos") or "")
    return ""


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    with _DB_LOCK:
        conn.executescript(SCHEMA)
    return conn


class DB:
    def __enter__(self):
        self.conn = connect()
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.conn.close()


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS
    ).hex()
    return salt, digest


def verify_password(password, salt, hashed):
    _, digest = hash_password(password, salt)
    return hmac.compare_digest(digest, hashed)


def clean_email(raw):
    email = (raw or "").strip().lower()
    if not email or len(email) > 200 or " " in email or "/" in email:
        return None
    local, sep, domain = email.partition("@")
    if not sep or not local or "." not in domain:
        return None
    return email


def clean_username(raw):
    name = (raw or "").strip()
    if not name or len(name) > 50:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
        return None
    return name


def clean_league_id(raw):
    league_id = (raw or "").strip()
    if not re.fullmatch(r"\d{1,20}", league_id):
        return None
    return league_id


def sleeper_bytes(path, timeout):
    url = "https://api.sleeper.app/v1" + path
    req = urllib.request.Request(url, headers={"User-Agent": "razzle-instrument/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise SleeperError(exc.code) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SleeperError(0) from exc


def sleeper_json(path, timeout=20):
    try:
        return json.loads(sleeper_bytes(path, timeout).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SleeperError(0) from exc


def normalize_gsis(value):
    return (value or "").strip()


def load_engine_snapshot():
    global _ENGINE_SNAPSHOT
    with _ENGINE_LOCK:
        if _ENGINE_SNAPSHOT is not None:
            return _ENGINE_SNAPSHOT
        path = ROOT / "screener" / "data" / "engine" / "screener.json"
        if not path.is_file():
            _ENGINE_SNAPSHOT = {}
            return _ENGINE_SNAPSHOT
        try:
            _ENGINE_SNAPSHOT = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _ENGINE_SNAPSHOT = {}
        return _ENGINE_SNAPSHOT


def engine_players_index():
    snap = load_engine_snapshot()
    return (snap.get("players") or {}) if isinstance(snap, dict) else {}


def run_engine_for_form(form):
    try:
        from razzle.engine.service import config_from_form, run_with_config
    except ImportError:
        return None
    try:
        config = config_from_form(form or {})
        return run_with_config(config)
    except (ValueError, TypeError, KeyError):
        return None


def load_catalog():
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    path = ROOT / "screener" / "data" / "catalog.json"
    try:
        _CATALOG = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _CATALOG = {"nfl": {"seasons": [], "defaultSeason": None}, "college": {"seasons": []}}
    return _CATALOG


def nfl_catalog_years():
    catalog = load_catalog()
    seasons = catalog.get("nfl", {}).get("seasons") or []
    return {int(row["year"]) for row in seasons if isinstance(row, dict) and "year" in row}


def sleeper_league_season():
    """NFL season Sleeper uses for league pulls and the in-season calendar."""
    state = _safe_state()
    if isinstance(state, dict) and state.get("season") is not None:
        try:
            return int(state["season"])
        except (TypeError, ValueError):
            pass
    return datetime.now().year


def nfl_stats_season():
    """Season year for nflverse screener files tied to the current league season."""
    want = sleeper_league_season()
    if want in nfl_catalog_years():
        return want, True
    return want, False


def load_nfl_pack(year):
    year = int(year)
    if year in _NFL_PACKS:
        return _NFL_PACKS[year]
    path = ROOT / "screener" / "data" / "nfl" / f"{year}.json"
    if not path.is_file():
        _NFL_PACKS[year] = None
        return None
    with path.open(encoding="utf-8") as handle:
        pack = json.load(handle)
    _NFL_PACKS[year] = pack
    return pack


def nfl_by_gsis(year):
    year = int(year)
    if year in _NFL_GSIS:
        return _NFL_GSIS[year]
    pack = load_nfl_pack(year)
    index = {}
    if isinstance(pack, dict):
        for player in pack.get("players") or []:
            gsis = normalize_gsis(player.get("gsisId"))
            if gsis:
                index[gsis] = player
    _NFL_GSIS[year] = index
    return index


def load_college_pack(year):
    year = int(year)
    if year in _COLLEGE_PACKS:
        return _COLLEGE_PACKS[year]
    path = ROOT / "screener" / "data" / "college" / f"{year}.json"
    if not path.is_file():
        _COLLEGE_PACKS[year] = None
        return None
    with path.open(encoding="utf-8") as handle:
        pack = json.load(handle)
    _COLLEGE_PACKS[year] = pack
    return pack


def find_college_player(year, cid):
    pack = load_college_pack(year)
    if not pack or not cid:
        return None
    want = str(cid).strip()
    for player in pack.get("players") or []:
        if str(player.get("cid") or "") == want:
            return player
    return None


def load_sleeper_index():
    """Sleeper player id -> record. None if the player file did not load."""
    global _SLEEPER
    with _PLAYERS_LOCK:
        if _SLEEPER is not None:
            return _SLEEPER
        path = DATA / "sleeper_players_nfl.json"
        data = None
        if path.exists():
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                data = None
        if not isinstance(data, dict):
            raw = sleeper_bytes("/players/nfl", timeout=90)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_bytes(raw)
            tmp.replace(path)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SleeperError(0) from exc
        index = {}
        if isinstance(data, dict):
            for pid, rec in data.items():
                if not isinstance(rec, dict):
                    continue
                name = rec.get("full_name")
                if not name:
                    first = rec.get("first_name") or ""
                    last = rec.get("last_name") or ""
                    name = f"{first} {last}".strip()
                if not name and rec.get("position") == "DEF":
                    team = str(rec.get("team") or pid or "").strip()
                    name = f"{team} Defense" if team else f"Defense {pid}"
                if name:
                    index[str(pid)] = {
                        "name": str(name),
                        "position": str(rec.get("position") or ""),
                        "team": str(rec.get("team") or ""),
                        "gsis_id": normalize_gsis(rec.get("gsis_id")),
                        "injury_status": str(rec.get("injury_status") or ""),
                        "status": str(rec.get("status") or ""),
                    }
        _SLEEPER = index
        return index


def load_player_names():
    """Sleeper id -> display name. None if the player file did not load."""
    index = load_sleeper_index()
    if index is None:
        return None
    return {pid: rec["name"] for pid, rec in index.items()}


def sleeper_display_name(rec, pid):
    if rec and rec.get("name"):
        return rec["name"]
    return f"id {pid}"


def find_players_by_name(name, year):
    want = (name or "").strip().casefold()
    if not want:
        return [], None
    pack = load_nfl_pack(year)
    if not pack:
        return [], pack
    found = []
    for player in pack.get("players") or []:
        if str(player.get("name") or "").strip().casefold() == want:
            found.append(player)
    return found, pack


def roster_pf(settings):
    if not isinstance(settings, dict) or "fpts" not in settings:
        return None
    try:
        whole = float(settings.get("fpts") or 0)
        dec = float(settings.get("fpts_decimal") or 0)
    except (TypeError, ValueError):
        return None
    return whole + dec / 100.0


def regular_weeks(league):
    settings = league.get("settings") if isinstance(league, dict) else None
    if not isinstance(settings, dict):
        return []
    try:
        start = int(settings.get("playoff_week_start"))
    except (TypeError, ValueError):
        return []
    if start < 2 or start > 18:
        return []
    return list(range(1, start))


def complete_through(state, league_season, last_regular_week):
    """Regular-season weeks fully in the past. None if the calendar is unknown."""
    if not isinstance(state, dict):
        return None
    try:
        season = int(state.get("season"))
        week = int(state.get("week") or 0)
    except (TypeError, ValueError):
        return None
    stype = str(state.get("season_type") or "")
    if season > league_season or (season == league_season and stype in ("post", "off")):
        return last_regular_week
    if season < league_season or stype == "pre":
        return 0
    if season == league_season and stype == "regular":
        return max(0, min(last_regular_week, week - 1))
    return None


def weeks_expected(league, state):
    weeks = regular_weeks(league)
    if not weeks:
        return []
    if str(league.get("status") or "") == "complete":
        return weeks
    done = complete_through(state, sleeper_league_season(), weeks[-1])
    if done is None:
        return []
    return [week for week in weeks if week <= done]


def classify_week(games, roster_ids):
    """('pairs', pairs) when the week has real scores, ('skip',) when it does not, ('bad',) if malformed."""
    if not isinstance(games, list):
        return ("bad",)
    wanted = set(roster_ids)
    paired = {}
    seen = set()
    scores = []
    for game in games:
        if not isinstance(game, dict) or "roster_id" not in game:
            return ("bad",)
        try:
            rid = int(game["roster_id"])
        except (TypeError, ValueError):
            return ("bad",)
        seen.add(rid)
        if game.get("matchup_id") is None:
            continue
        if game.get("points") is None:
            return ("bad",)
        try:
            pts = float(game["points"])
            mid = int(game["matchup_id"])
        except (TypeError, ValueError):
            return ("bad",)
        paired.setdefault(mid, []).append((rid, pts))
        scores.append(pts)
    if seen != wanted:
        return ("bad",)
    if not scores or max(scores) <= 0:
        return ("skip",)
    pairs = []
    for rows in paired.values():
        if len(rows) != 2:
            return ("bad",)
        pairs.append((rows[0], rows[1]))
    if not pairs:
        return ("skip",)
    return ("pairs", pairs)


def standings_from_weeks(roster_ids, week_games):
    """None unless every supplied week has a complete scored slate."""
    if not week_games:
        return None
    folded = []
    for games in week_games:
        kind = classify_week(games, roster_ids)
        if kind[0] != "pairs":
            return None
        folded.append(kind[1])
    rows = {rid: {"w": 0, "l": 0, "t": 0, "pf": 0.0} for rid in roster_ids}
    for pairs in folded:
        for (rid_a, pts_a), (rid_b, pts_b) in pairs:
            rows[rid_a]["pf"] += pts_a
            rows[rid_b]["pf"] += pts_b
            if pts_a > pts_b:
                rows[rid_a]["w"] += 1
                rows[rid_b]["l"] += 1
            elif pts_b > pts_a:
                rows[rid_b]["w"] += 1
                rows[rid_a]["l"] += 1
            else:
                rows[rid_a]["t"] += 1
                rows[rid_b]["t"] += 1
    return rows


def standings_from_settings(rosters):
    rows = {}
    for roster in rosters:
        settings = roster.get("settings") if isinstance(roster, dict) else None
        if not isinstance(settings, dict):
            return None
        if "wins" not in settings or "losses" not in settings:
            return None
        points = roster_pf(settings)
        if points is None:
            return None
        try:
            rid = int(roster["roster_id"])
            wins = int(settings.get("wins") or 0)
            losses = int(settings.get("losses") or 0)
            ties = int(settings.get("ties") or 0)
        except (TypeError, ValueError, KeyError):
            return None
        rows[rid] = {"w": wins, "l": losses, "t": ties, "pf": points}
    return rows or None


def thin_share(standings):
    if not standings:
        return None
    weights = {}
    for rid, row in standings.items():
        weights[rid] = row["w"] * 10000 + row["pf"]
    total = sum(weights.values())
    if total <= 0:
        return None
    return {rid: 100.0 * weight / total for rid, weight in weights.items()}


def _winner_id(game):
    if not isinstance(game, dict) or game.get("w") is None:
        return None
    try:
        return int(game["w"])
    except (TypeError, ValueError):
        return None


def champion_from_bracket(bracket):
    """Roster id that won the title game. Sleeper marks that game with p=1.

    If no game carries a placement, use the lowest matchup id in the last round.
    """
    if not isinstance(bracket, list) or not bracket:
        return None
    games = [game for game in bracket if isinstance(game, dict)]
    for game in games:
        try:
            place = int(game["p"]) if "p" in game and game["p"] is not None else None
        except (TypeError, ValueError):
            place = None
        if place == 1:
            return _winner_id(game)
    parsed = []
    for game in games:
        if "r" not in game:
            continue
        try:
            rnd = int(game["r"])
            mid = int(game.get("m") or 0)
        except (TypeError, ValueError):
            continue
        parsed.append((rnd, mid, game))
    if not parsed:
        return None
    last = max(rnd for rnd, _, _ in parsed)
    finals = [game for rnd, mid, game in sorted(parsed, key=lambda item: (item[0], item[1])) if rnd == last]
    return _winner_id(finals[0]) if finals else None


def record_text(row):
    if row["t"]:
        return f"{row['w']}-{row['l']}-{row['t']}"
    return f"{row['w']}-{row['l']}"


def team_label(user, roster_id):
    if isinstance(user, dict):
        meta = user.get("metadata") if isinstance(user.get("metadata"), dict) else {}
        name = str(meta.get("team_name") or "").strip()
        if name:
            return name
        display = str(user.get("display_name") or "").strip()
        if display:
            return display
    return f"Roster {roster_id}"


def slot_ids(roster, key):
    ids = []
    for pid in roster.get(key) or []:
        if pid is None or str(pid) == "0":
            continue
        ids.append(str(pid))
    return ids


def describe_ids(pids, names):
    """Names actually on the player file, otherwise the Sleeper id. Never a guessed name."""
    lines = []
    for pid in pids:
        if names is None:
            lines.append(f"id {pid} (player file did not load)")
            continue
        name = names.get(str(pid))
        if name:
            lines.append(name)
        else:
            lines.append(f"id {pid} (name not on the player file)")
    return lines


def fetch_matchups(league_id, weeks):
    from concurrent.futures import ThreadPoolExecutor

    found = {}
    errors = []

    def one(week):
        return week, sleeper_json(f"/league/{league_id}/matchups/{week}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(one, week) for week in weeks]
        for future in futures:
            try:
                week, payload = future.result()
            except SleeperError as exc:
                errors.append(exc)
                continue
            found[week] = payload
    return found, errors


def build_snapshot(link):
    league_id = link["league_id"]
    league = sleeper_json(f"/league/{league_id}")
    rosters = sleeper_json(f"/league/{league_id}/rosters")
    users = sleeper_json(f"/league/{league_id}/users")
    if not isinstance(league, dict) or not isinstance(rosters, list) or not isinstance(users, list):
        raise SleeperError(0)
    roster_ids = []
    for roster in rosters:
        if not isinstance(roster, dict) or "roster_id" not in roster:
            raise SleeperError(0)
        roster_ids.append(int(roster["roster_id"]))
    users_by_id = {}
    for user in users:
        if isinstance(user, dict) and user.get("user_id"):
            users_by_id[str(user["user_id"])] = user
    try:
        names = load_player_names()
    except SleeperError:
        names = None
    bracket = None
    try:
        bracket = sleeper_json(f"/league/{league_id}/winners_bracket")
    except SleeperError as exc:
        if exc.code != 404:
            bracket = None
        else:
            bracket = []
    champion = champion_from_bracket(bracket)
    if champion not in roster_ids:
        champion = None
    standings = None
    source = None
    counted = []
    weeks = weeks_expected(league, _safe_state())
    if weeks:
        payloads, errors = fetch_matchups(league_id, weeks)
        if not errors and all(week in payloads for week in weeks):
            ordered = [payloads[week] for week in weeks]
            standings = standings_from_weeks(roster_ids, ordered)
            if standings is not None:
                source = "matchups"
                counted = list(weeks)
    if standings is None:
        standings = standings_from_settings(rosters)
        if standings is not None:
            source = "settings"
            counted = []
    shares = None
    share_kind = None
    share_note = None
    if champion is not None:
        shares = {rid: (100.0 if rid == champion else 0.0) for rid in roster_ids}
        share_kind = "bracket"
        share_note = (
            "From the Sleeper winners bracket. The final already has a winner, "
            "so this is the result, not a projection."
        )
    else:
        thin = thin_share(standings)
        if thin is not None:
            shares = thin
            share_kind = "thin"
            if source == "matchups":
                week_list = ", ".join(str(week) for week in counted)
                share_note = (
                    "Thin read from completed Sleeper matchups only "
                    f"(weeks {week_list}). Share of wins, then points scored. "
                    "Remaining games are not simulated."
                )
            else:
                share_note = (
                    "Thin read from Sleeper roster settings (wins and points on the roster payload). "
                    "Share of wins, then points scored. Remaining games are not simulated."
                )
    mine = []
    sleeper_user_id = str(link.get("sleeper_user_id") or "")
    teams = []
    for roster in rosters:
        rid = int(roster["roster_id"])
        owners = [str(roster.get("owner_id"))]
        for co in roster.get("co_owners") or []:
            owners.append(str(co))
        if sleeper_user_id and sleeper_user_id in owners:
            mine.append(rid)
        user = users_by_id.get(str(roster.get("owner_id")))
        row = standings.get(rid) if standings else None
        starters = roster_entries(slot_ids(roster, "starters"), names)
        bench_ids = [pid for pid in slot_ids(roster, "players") if pid not in set(slot_ids(roster, "starters"))]
        bench = roster_entries(bench_ids, names)
        teams.append({
            "roster_id": rid,
            "label": team_label(user, rid),
            "record": record_text(row) if row else None,
            "pf": row["pf"] if row else None,
            "starters": starters,
            "bench": bench,
            "share": None if shares is None else shares.get(rid),
        })
    teams.sort(key=lambda team: (-(team["pf"] or 0), team["label"]))
    return {
        "league": league,
        "names_loaded": names is not None,
        "teams": teams,
        "mine": mine,
        "shares": shares,
        "share_kind": share_kind,
        "share_note": share_note,
        "champion": champion,
    }


def _safe_state():
    try:
        state = sleeper_json("/state/nfl")
    except SleeperError:
        return None
    return state if isinstance(state, dict) else None


def context_from(snapshot, link):
    league = snapshot["league"]
    name = str(league.get("name") or "").strip() or "unnamed"
    lines = [f"League: {name} (id {link['league_id']}), season {sleeper_league_season()}"]
    if snapshot["mine"]:
        lines.append("Your roster ids: " + ", ".join(str(rid) for rid in snapshot["mine"]))
    else:
        lines.append("Your Sleeper user is not an owner on this league.")
    if not snapshot["names_loaded"]:
        lines.append("Player names did not load. Ids below are from the roster payload.")
    lines.append("Teams:")
    for team in snapshot["teams"]:
        bits = [f"{team['label']} (roster {team['roster_id']})"]
        if team["record"] is not None and team["pf"] is not None:
            bits.append(f"{team['record']}, {team['pf']:.1f} points")
        lines.append("- " + ", ".join(bits))
        if team["starters"]:
            lines.append("  Starters: " + ", ".join(name for _, name in team["starters"]))
        if team["bench"]:
            lines.append("  Bench: " + ", ".join(name for _, name in team["bench"]))
    text = "\n".join(lines)
    if len(text) > 12000:
        text = text[:12000] + "\nContext truncated."
    return text


def ask_model(question, context):
    key = (os.environ.get("RAZZLE_MODEL_KEY") or "").strip()
    if not key:
        return KEY_MISSING, False
    url = (os.environ.get("RAZZLE_MODEL_URL") or MODEL_URL_DEFAULT).strip()
    model = (os.environ.get("RAZZLE_MODEL_NAME") or MODEL_NAME_DEFAULT).strip()
    payload = json.dumps({
        "model": model,
        "temperature": 0.4,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": context + "\n\nQuestion:\n" + question},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return "The room could not get a reply.", True
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return "The room sent nothing back.", True
    text = str(content or "").strip()
    if not text:
        return "The room sent nothing back.", True
    return text[:4000], True


def shell_nav(user, active=None):
    if not user:
        screener_cls = ' class="nav-on"' if active == "screener" else ""
        return (
            '<nav class="rooms" aria-label="Rooms">'
            f'<a href="/screener/"{screener_cls}>Screener</a>'
            '<a href="/">Sign in</a>'
            "</nav>"
        )

    def item(href, label, key):
        cls = ' class="nav-on"' if active == key else ""
        return f'<a href="{href}"{cls}>{label}</a>'

    war_cls = ' class="nav-on"' if active == "war" else ""
    return (
        '<nav class="rooms" aria-label="Rooms">'
        + item("/home", "Home", "home")
        + item("/screener/", "Screener", "screener")
        + f'<a href="/war-room"{war_cls}>War Room <span class="nav-preview">Preview</span></a>'
        + '<form method="post" action="/logout"><button type="submit">Sign out</button></form>'
        + "</nav>"
    )


def layout(title, body, *, user=None, war=False, active=None, tagline=None, page="", extra_head=""):
    logo_href = "/home" if user else "/"
    body_class = " ".join(part for part in (page, "war" if war else "") if part)
    tagline_html = f'<p class="page-kicker">{h(tagline)}</p>' if tagline else ""
    doc_title = f"{title} · Razzle" if title != "Razzle" else "Razzle"
    if user:
        room_heading = f'<p class="screen-label">{h(title)}</p>'
    else:
        room_heading = f"<h1>{h(title)}</h1>"
    extra_css = extra_head
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{h(doc_title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@600&family=Luckiest+Guy&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/design/tokens.css">
<link rel="stylesheet" href="/shell.css">
{extra_css}
</head>
<body class="{h(body_class)}">
<header>
  <a class="logo" href="{logo_href}" aria-label="Razzle home">
    <span class="logo-mark" aria-hidden="true">&#x1F42F;</span>
    <span class="logo-text">Razzle</span>
  </a>
  {room_heading}
  {shell_nav(user, active)}
</header>
{tagline_html}
<main>
{body}
<p class="watermark">razzle.lol — let's razzle dazzle em baby</p>
</main>
</body>
</html>
"""


def page_auth(error=None):
    err = f'<p class="error">{h(error)}</p>' if error else ""
    body = f"""
{err}
<div class="grid">
  <section class="card">
    <p class="kicker">Sign in</p>
    <form method="post" action="/login">
      <label for="login-email">Email</label>
      <input id="login-email" name="email" type="email" autocomplete="username" required>
      <label for="login-password">Password</label>
      <input id="login-password" name="password" type="password" autocomplete="current-password" required>
      <div class="row"><button class="primary" type="submit">Sign in</button></div>
    </form>
  </section>
  <section class="card">
    <p class="kicker">Register</p>
    <form method="post" action="/register">
      <label for="reg-email">Email</label>
      <input id="reg-email" name="email" type="email" autocomplete="username" required>
      <label for="reg-password">Password</label>
      <input id="reg-password" name="password" type="password" autocomplete="new-password" required>
      <div class="row"><button class="primary" type="submit">Create account</button></div>
    </form>
  </section>
</div>
<p class="aside">The screener is open. <a href="/screener/">Go to the screener</a></p>
"""
    return layout(
        "Sign in",
        body,
        user=None,
        active="signin",
        tagline="The fantasy football research lab. Forever free.",
    )


def render_engine_odds_hero(engine_result, thesis_form=None):
    """Four-team sandbox title odds (valuation engine)."""
    bits = [
        '<section class="home-hero card stripe-orange">',
        '<p class="kicker">Championship odds (sandbox)</p>',
    ]
    if engine_result is None or not engine_result.simulation:
        bits.append(f'<p class="hero-missing">{h(ODDS_MISSING)}</p>')
        bits.append("</section>")
        return "".join(bits)
    sim = engine_result.simulation
    pct = 100.0 * sim.thesis_wins / sim.draws
    bits.append(
        f'<p class="hero-number" aria-label="Sandbox title odds">{pct:.1f}'
        '<span class="hero-unit">%</span></p>'
    )
    bits.append(f'<p class="hero-note">{h(ENGINE_NOTE)}</p>')
    contrib = sim.contribution_pp
    bits.append(
        f'<p class="hero-note">Title-odds edge vs replacement at the playoff slot: '
        f'<strong>{h(f"{contrib:+.1f}")}</strong> pp (paired SE {sim.paired_se_pp:.2f} pp).</p>'
    )
    shares = sim.title_shares
    bits.append(
        '<p class="hero-note">Sim shares — You '
        f'{shares.get("you", 0)}/{sim.draws}, A {shares.get("A", 0)}, '
        f'B {shares.get("B", 0)}, C {shares.get("C", 0)}.</p>'
    )
    bits.append(render_odds_builder(thesis_form or {}))
    bits.append("</section>")
    return "".join(bits)


def render_odds_builder(form):
    team = h(form.get("team") or "HOU")
    off = h(form.get("off_z") or "")
    deff = h(form.get("def_z") or "2")
    lean = h(form.get("pass_z") or "")
    gut_team = h(form.get("gut_team") or "")
    gut_week = h(form.get("gut_week") or "5")
    gut_factor = h(form.get("gut_factor") or "Defense")
    gut_strength = h(form.get("gut_strength") or "Very good")
    draws = h(form.get("draws") or "10000")
    return f"""
<section class="odds-builder card">
  <p class="kicker">Formula builder (σ knobs)</p>
  <form method="post" action="/engine/thesis" class="odds-form">
    <div class="odds-grid">
      <label>Team <input name="team" value="{team}" maxlength="3" autocomplete="off"></label>
      <label>Off σ <input name="off_z" value="{off}" inputmode="decimal" autocomplete="off"></label>
      <label>Def σ <input name="def_z" value="{deff}" inputmode="decimal" autocomplete="off"></label>
      <label>Pass-lean σ <input name="pass_z" value="{lean}" inputmode="decimal" autocomplete="off"></label>
      <label>Draws <input name="draws" value="{draws}" inputmode="numeric" autocomplete="off"></label>
    </div>
    <p class="group-label">Gut call</p>
    <div class="odds-grid">
      <label>Team <input name="gut_team" value="{gut_team}" maxlength="3" autocomplete="off"></label>
      <label>Week <input name="gut_week" value="{gut_week}" autocomplete="off" placeholder="4-17 or All"></label>
      <label>Factor
        <select name="gut_factor">
          <option{" selected" if gut_factor == "Offense" else ""}>Offense</option>
          <option{" selected" if gut_factor == "Defense" else ""}>Defense</option>
          <option{" selected" if gut_factor == "Pass lean" else ""}>Pass lean</option>
        </select>
      </label>
      <label>Strength
        <select name="gut_strength">
          {''.join(f'<option{" selected" if gut_strength == label else ""}>{h(label)}</option>' for label in (
            "Very bad", "Bad", "Slightly worse", "Neutral", "Good", "Very good"
          ))}
        </select>
      </label>
    </div>
    <div class="row"><button class="primary" type="submit">Recompute odds</button></div>
  </form>
</section>
"""


def render_sleeper_share(snapshot, link):
    shares = snapshot.get("shares")
    mine = snapshot.get("mine") or []
    if not shares or not mine:
        return ""
    league_name = str(link.get("league_name") or "") if link else ""
    bits = ['<section class="card stripe-muted">', '<p class="kicker">Sleeper thin read</p>']
    if league_name:
        bits.append(f'<p class="league-pill">{h(league_name)}</p>')
    if any(rid not in shares for rid in mine):
        return ""
    if len(mine) == 1:
        bits.append(f'<p class="hero-note">Your roster: <strong>{shares[mine[0]]:.1f}%</strong> championship share (not simulated).</p>')
    else:
        roster_bits = [f"Roster {rid}: {shares[rid]:.1f}%" for rid in mine]
        bits.append(f'<p class="hero-note">{h(" · ".join(roster_bits))}</p>')
    if snapshot.get("share_note"):
        bits.append(f'<p class="hero-note">{h(snapshot["share_note"])}</p>')
    bits.append("</section>")
    return "".join(bits)


def render_roster_slot(entry):
    pid, name = roster_entry_parts(entry)
    pos = pos_for_roster_entry(pid, name)
    pos_html = ""
    if pos:
        pos_html = f'<span class="pos {h(pos)}">{h(pos)}</span>'
    if name.startswith("id "):
        return f'<li class="roster-row">{pos_html}<span class="roster-id">{h(name)}</span></li>'
    if pid:
        url = "/player?sleeper=" + urllib.parse.quote(str(pid))
    else:
        url = "/player?name=" + urllib.parse.quote(name)
    stripe = f" stripe-{pos.lower()}" if pos else ""
    return (
        f'<li class="roster-row{stripe}">{pos_html}'
        f'<a class="roster-name" href="{h(url)}">{h(name)}</a></li>'
    )


def render_roster_panel(team):
    starters = team.get("starters") or []
    bench = team.get("bench") or []
    if not starters and not bench:
        return ""
    starter_html = "".join(render_roster_slot(entry) for entry in starters)
    bench_html = "".join(render_roster_slot(entry) for entry in bench)
    return (
        '<section class="roster-board card">'
        f'<p class="kicker">Your roster · {h(team["label"])}</p>'
        '<div class="roster-groups">'
        '<div class="roster-group starters">'
        '<p class="group-label">Starters</p>'
        f'<ul class="roster">{starter_html or "<li class=\"roster-empty\">No starters listed.</li>"}</ul>'
        "</div>"
        '<div class="roster-group bench">'
        '<p class="group-label">Bench</p>'
        f'<ul class="roster">{bench_html or "<li class=\"roster-empty\">Bench is empty.</li>"}</ul>'
        "</div>"
        "</div></section>"
    )


def render_standings(snapshot):
    mine = set(snapshot.get("mine") or [])
    teams = list(snapshot.get("teams") or [])
    if not teams:
        return ""
    show_share = snapshot.get("shares") is not None
    teams_by_pf = sorted(teams, key=lambda team: (-(team.get("pf") or 0), team.get("label") or ""))
    rows = []
    for rank, team in enumerate(teams_by_pf, start=1):
        rec = team["record"] if team.get("record") is not None else "—"
        pf = f"{team['pf']:.1f}" if team.get("pf") is not None else "—"
        share = f"{team['share']:.1f}%" if team.get("share") is not None else "—"
        mine_cls = " mine" if team.get("roster_id") in mine else ""
        rank_cls = " rank-1" if rank == 1 else (" rank-2" if rank == 2 else (" rank-3" if rank == 3 else ""))
        share_cell = f'<td class="num">{h(share)}</td>' if show_share else ""
        rows.append(
            f'<tr class="{mine_cls.strip()}{rank_cls}">'
            f'<td class="rank">{rank}</td>'
            f'<td class="team">{h(team.get("label") or "")}</td>'
            f'<td class="num">{h(rec)}</td>'
            f'<td class="num">{h(pf)}</td>'
            f"{share_cell}</tr>"
        )
    head_share = '<th scope="col">Share</th>' if show_share else ""
    return (
        '<section class="standings-board card">'
        '<p class="kicker">Standings</p>'
        '<div class="standings-wrap">'
        '<table class="standings">'
        "<thead><tr>"
        '<th scope="col" class="rank">#</th>'
        '<th scope="col">Team</th>'
        '<th scope="col">Record</th>'
        '<th scope="col">PF</th>'
        f"{head_share}"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div></section>"
    )


def roster_entries(pids, names):
    lines = []
    for pid in pids:
        if names is None:
            lines.append((None, f"id {pid} (player file did not load)"))
            continue
        name = names.get(str(pid))
        if name:
            lines.append((str(pid), name))
        else:
            lines.append((str(pid), f"id {pid} (name not on the player file)"))
    return lines


def page_home(user, link, choices, snapshot, error=None, engine_result=None, thesis_form=None):
    err = f'<p class="error">{h(error)}</p>' if error else ""
    league_saved = bool(link and link.get("league_id"))
    setup_open = "" if league_saved else " open"
    saved_line = ""
    if link and link.get("username"):
        saved_line = f'<p class="saved-line">Sleeper <strong>{h(link["username"])}</strong>'
        if link.get("league_name"):
            saved_line += f' · league <strong>{h(link["league_name"])}</strong>'
        saved_line += "</p>"
    choice_html = ""
    if choices:
        items = []
        for choice in choices:
            on = link and link.get("league_id") == choice["league_id"]
            items.append(
                '<li class="' + ("on" if on else "") + '"><span>' + h(choice["name"]) + "</span>"
                '<form method="post" action="/sleeper/league">'
                '<input type="hidden" name="league_id" value="' + h(choice["league_id"]) + '">'
                "<button type=\"submit\">Save</button></form></li>"
            )
        choice_html = '<ul class="league-list">' + "".join(items) + "</ul>"
    season = sleeper_league_season()
    form = f"""
<form method="post" action="/sleeper/lookup">
  <label for="username">Sleeper username</label>
  <input id="username" name="username" autocomplete="off" required>
  <div class="row"><button class="primary" type="submit">Pull {h(str(season))} leagues</button></div>
</form>
"""
    setup = (
        f'<details class="setup-panel card"{setup_open}>'
        '<summary class="setup-summary">League setup</summary>'
        '<div class="setup-body">'
        + saved_line
        + form
        + choice_html
        + "</div></details>"
    )
    league_html = ""
    if snapshot:
        mine = set(snapshot.get("mine") or [])
        my_teams = [team for team in snapshot["teams"] if team["roster_id"] in mine]
        roster_blocks = "".join(render_roster_panel(team) for team in my_teams)
        if link and link.get("league_id") and not my_teams:
            roster_blocks = (
                '<section class="roster-board card"><p class="hero-note">'
                "No roster on this league is owned by that Sleeper user.</p></section>"
            )
        league_html = (
            render_engine_odds_hero(engine_result, thesis_form)
            + render_sleeper_share(snapshot, link)
            + render_standings(snapshot)
            + roster_blocks
        )
    else:
        league_html = render_engine_odds_hero(engine_result, thesis_form)
    if link and link.get("league_id") and snapshot is None and not league_html:
        league_html = render_engine_odds_hero(engine_result, thesis_form)
    body = "\n".join([
        err,
        '<div class="home-layout">',
        league_html or '<section class="home-empty card"><p class="hero-note">Pull a Sleeper league to see your board.</p></section>',
        setup,
        "</div>",
    ])
    return layout("Home", body, user=user, active="home", page="page-home")


NFL_STAT_FIELDS = [
    ("pos", "Pos"),
    ("team", "Team"),
    ("age", "Age"),
    ("gp", "GP"),
    ("ppr", "PPR"),
    ("ppg", "PPG"),
    ("py", "Pass Yds"),
    ("ptd", "Pass TD"),
    ("ry", "Rush Yds"),
    ("rtd", "Rush TD"),
    ("rec", "REC"),
    ("rey", "Rec Yds"),
    ("retd", "Rec TD"),
    ("tgt", "TGT"),
    ("td", "TD"),
]

COLLEGE_STAT_FIELDS = [
    ("pos", "Pos"),
    ("team", "Team"),
    ("conference", "Conference"),
    ("gp", "GP"),
    ("py", "Pass Yds"),
    ("ptd", "Pass TD"),
    ("ry", "Rush Yds"),
    ("rtd", "Rush TD"),
    ("rey", "Rec Yds"),
    ("retd", "Rec TD"),
    ("ty", "Total Yds"),
    ("td", "Total TD"),
]


def source_label(url):
    text = str(url or "")
    if "nflverse" in text and "stats_player" in text:
        return "nflverse player stats (regular season)"
    if "espn_cfb" in text or "sportsdataverse" in text:
        return "ESPN college play stats (sportsdataverse)"
    if text:
        return "Published data file"
    return ""


def labeled_source_for_season(season, url):
    if not url:
        return ""
    label = source_label(url)
    safe = h(url)
    prefix = f"{h(season)} · " if season else ""
    return (
        f'<p class="source-line">{prefix}Source: '
        f'<a href="{safe}">{h(label)}</a></p>'
    )


def labeled_sources(urls):
    if not urls:
        return ""
    if isinstance(urls, str):
        return labeled_source_for_season("", urls)
    lines = ['<p class="source-line">Sources:</p><ul class="roster">']
    for url in urls:
        label = source_label(url)
        safe = h(url)
        lines.append(f'<li><a href="{safe}">{h(label)}</a></li>')
    lines.append("</ul>")
    return "".join(lines)


def stat_rows(player, fields):
    pos = player.get("pos") or ""
    rows = []
    for key, label in fields:
        if key not in player or player[key] is None or player[key] == "":
            continue
        value = player[key]
        if isinstance(value, float):
            shown = f"{value:.1f}"
        else:
            shown = str(value)
        if key == "pos":
            shown_html = f'<span class="pos {h(pos)}">{h(shown)}</span>'
        else:
            shown_html = h(shown)
        rows.append(f"<tr><th>{h(label)}</th><td>{shown_html}</td></tr>")
    return rows


def stat_label(key):
    for field_key, label in NFL_STAT_FIELDS:
        if field_key == key:
            return label
    return key.upper()


def render_stat_grid(player, pos):
    keys = POS_NFL_STATS.get(pos, POS_NFL_STATS["WR"])
    cells = []
    for key in keys:
        if key not in player or player[key] is None or player[key] == "":
            continue
        value = player[key]
        if isinstance(value, float):
            shown = f"{value:.1f}"
        else:
            shown = str(value)
        cells.append(
            f'<div class="stat-cell"><span class="label">{h(stat_label(key))}</span>'
            f'<span class="value">{h(shown)}</span></div>'
        )
    if not cells:
        return ""
    return '<div class="stat-grid">' + "".join(cells) + "</div>"


def render_engine_tear_block(gsis, season):
    row = engine_players_index().get(gsis)
    if not row:
        return (
            '<p class="tear-verdict">Valuation engine has no row for this player yet. '
            f'{sample_badge()}</p>'
        )
    wk = load_engine_snapshot().get("meta", {}).get("projectionWeek", 4)
    lines = [
        '<div class="stat-grid engine-grid">',
        f'<div class="stat-cell"><span class="label">Proj W{wk}</span>'
        f'<span class="value">{h(f"{row["proj"]:.1f}")}</span></div>',
        f'<div class="stat-cell"><span class="label">Weekly SD</span>'
        f'<span class="value">{h(f"{row["sd"]:.1f}")}</span></div>',
        f'<div class="stat-cell"><span class="label">ROS value</span>'
        f'<span class="value">{h(f"{row["ros"]:.1f}")}</span></div>',
        f'<div class="stat-cell"><span class="label">Title odds Δ</span>'
        f'<span class="value">{h(f"{row["titleOddsPp"]:+.1f}")} pp</span></div>',
        "</div>",
        f'<p class="tear-verdict">Engine projection (PPR, week {wk}): '
        f'<strong>{row["proj"]:.1f}</strong> pts, σ {row["sd"]:.1f}. '
        f'Rest-of-season weighted value <strong>{row["ros"]:.1f}</strong>. '
        f'Title-odds impact vs replacement <strong>{row["titleOddsPp"]:+.1f} pp</strong>.</p>',
    ]
    return "".join(lines)


def render_nfl_stat_card(player, season, source):
    pos = player.get("pos") or "WR"
    team = player.get("team") or ""
    age = player.get("age")
    meta_bits = [bit for bit in (team, f"Age {age}" if age is not None else "") if bit]
    verdict = SAMPLE_VERDICT.get(pos, SAMPLE_VERDICT["WR"])
    stripe = f" card-pos-{pos}" if pos in POS_NFL_STATS else ""
    gsis = player.get("gsisId") or ""
    engine_html = render_engine_tear_block(gsis, season) if gsis else ""
    return (
        f'<section class="card card-stripe{stripe}">'
        '<div class="tear-head">'
        f'<p class="player-name">{h(player.get("name"))}</p>'
        f'<span class="pos {h(pos)}">{h(pos)}</span>'
        f'<span class="tear-meta">{h(" · ".join(meta_bits))}</span>'
        "</div>"
        + engine_html
        + f'<p class="tear-leverage">{h(SAMPLE_LEVERAGE)} <span class="sample-badge">Sample</span></p>'
        + render_stat_grid(player, pos)
        + labeled_source_for_season(f"{season} NFL regular season", source)
        + "</section>"
    )


def render_college_stat_card(player, season, sources):
    rows = stat_rows(player, COLLEGE_STAT_FIELDS)
    return (
        "<section class=\"card\">"
        f"<p class=\"player-name\">{h(player.get('name'))}</p>"
        f"<table>{''.join(rows)}</table>"
        f"<p class=\"aside\">{h(season)} college season totals.</p>"
        + labeled_sources(sources)
        + "</section>"
    )


def render_empty_card(title, lines):
    body = "".join(f"<p>{h(line)}</p>" for line in lines)
    return f"<section class=\"card\"><p class=\"player-name\">{h(title)}</p>{body}</section>"


def missing_nfl_season_message(want):
    built = sorted(nfl_catalog_years())
    if built:
        span = f"{built[0]}–{built[-1]}"
        newest = built[-1]
        return (
            f"No NFL screener file for the {want} season is in this build. "
            f"Published nflverse regular-season stats on disk run {span}. "
            f"Newest season: {newest}."
        )
    return (
        f"No NFL screener file for the {want} season is in this build. "
        "No nflverse seasons downloaded yet."
    )


def _engine_summary_for_gsis(gsis: str):
    row = engine_players_index().get(gsis)
    if not row:
        return None
    full = engine_players_index()
    return {**row, "__full_index__": full}


def _week_pack_loader(year):
    def loader(y):
        if y != year:
            return None
        path = ROOT / "screener" / "data" / "nfl" / f"{y}-weeks.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    return loader


def _render_skill_tear_sheet(
    player,
    season,
    source,
    *,
    sleeper_id="",
    sleeper_rec=None,
    league_snapshot=None,
):
    from razzle.player_sheet import build_nfl_skill_context, render_tear_sheet

    gsis = player.get("gsisId") or ""
    try:
        sidx = load_sleeper_index()
    except SleeperError:
        sidx = None
    ctx = build_nfl_skill_context(
        gsis=gsis,
        season=season,
        name=player.get("name") or "",
        pos=player.get("pos") or "",
        team=player.get("team") or "",
        season_player=player,
        source=source,
        engine_summary=_engine_summary_for_gsis(gsis) if gsis else None,
        sleeper_id=sleeper_id,
        sleeper_rec=sleeper_rec,
        league_snapshot=league_snapshot,
        sleeper_index=sidx,
        load_pack=load_nfl_pack,
        catalog_years=nfl_catalog_years(),
        week_pack_loader=_week_pack_loader(season),
    )
    return render_tear_sheet(ctx, h, sample_badge())


def page_player(query, user=None):
    from razzle.player_sheet import (
        build_nfl_skill_context,
        render_college_tear,
        render_sparse_card,
        render_tear_sheet,
    )

    sleeper_id = (query.get("sleeper") or "").strip()
    cid = (query.get("cid") or "").strip()
    season_q = (query.get("season") or "").strip()
    legacy_name = (query.get("name") or "").strip()
    stats_season, stats_on_disk = nfl_stats_season()
    inner = ""
    league_snapshot = None
    if user:
        link = get_link(user["id"])
        if link and link.get("league_id"):
            try:
                league_snapshot = build_snapshot(link)
            except (SleeperError, OSError, ValueError, TypeError, KeyError):
                league_snapshot = None

    if sleeper_id:
        try:
            index = load_sleeper_index()
        except SleeperError:
            index = None
        rec = (index or {}).get(str(sleeper_id))
        if not rec:
            inner = "<p>That player is not on the Sleeper NFL player file.</p>"
        else:
            title = rec["name"]
            pos = rec.get("position") or ""
            team = rec.get("team") or ""
            header_bits = [bit for bit in (pos, team) if bit]
            if pos in ("DEF", "K"):
                inner = render_sparse_card(
                    title,
                    [
                        " · ".join(header_bits) if header_bits else ("Team defense" if pos == "DEF" else "Kicker"),
                        "The NFL screener only includes QB, RB, WR, and TE counting stats from nflverse. "
                        + (
                            "Team defense scoring is not in that source."
                            if pos == "DEF"
                            else "Kicker scoring is not in that source."
                        ),
                    ],
                    h,
                )
            elif pos in NFL_SKILL:
                if not stats_on_disk:
                    inner = render_empty_card(title, [missing_nfl_season_message(stats_season)])
                else:
                    gsis = rec.get("gsis_id") or ""
                    pack = load_nfl_pack(stats_season)
                    source = (pack or {}).get("source") or ""
                    player = nfl_by_gsis(stats_season).get(gsis) if gsis else None
                    if player:
                        inner = _render_skill_tear_sheet(
                            player,
                            stats_season,
                            source,
                            sleeper_id=sleeper_id,
                            sleeper_rec=rec,
                            league_snapshot=league_snapshot,
                        )
                    elif not gsis:
                        inner = render_empty_card(
                            title,
                            [
                                " · ".join(header_bits) if header_bits else "",
                                "Sleeper has no nflverse player id for this roster slot, so there is no stat join.",
                            ],
                        )
                    else:
                        inner = render_empty_card(
                            title,
                            [
                                " · ".join(header_bits) if header_bits else "",
                                f"No published {stats_season} regular-season skill stats for this player in nflverse yet. "
                                "Blank where the source has no row — nothing invented here.",
                            ],
                        )
            else:
                inner = render_empty_card(
                    title,
                    [
                        " · ".join(header_bits) if header_bits else pos or "Player",
                        "No screener stats for this position in the published sources.",
                    ],
                )
    elif (query.get("gsis") or "").strip():
        gsis = normalize_gsis(query.get("gsis"))
        try:
            year = int(season_q) if season_q else stats_season
        except (TypeError, ValueError):
            year = stats_season
        if year not in nfl_catalog_years():
            inner = render_empty_card(
                gsis,
                [missing_nfl_season_message(year)],
            )
        else:
            pack = load_nfl_pack(year)
            source = (pack or {}).get("source") or ""
            player = nfl_by_gsis(year).get(gsis)
            if player:
                inner = _render_skill_tear_sheet(
                    player,
                    year,
                    source,
                    league_snapshot=league_snapshot,
                )
            else:
                meta = load_engine_snapshot()
                eng = (meta.get("players") or {}).get(gsis)
                if eng:
                    stub = {
                        "gsisId": gsis,
                        "name": eng.get("name") or gsis,
                        "pos": eng.get("pos") or "",
                        "team": eng.get("team") or "",
                    }
                    inner = _render_skill_tear_sheet(stub, year, source, league_snapshot=league_snapshot)
                else:
                    inner = render_empty_card(
                        gsis,
                        [
                            f"No published {year} regular-season skill stats for nflverse id {gsis}.",
                            "Blank where the source has no row — nothing invented here.",
                        ],
                    )
    elif cid:
        try:
            year = int(season_q) if season_q else int(load_catalog().get("college", {}).get("defaultSeason") or 0)
        except (TypeError, ValueError):
            year = 0
        if year <= 0:
            inner = "<p>Pick a college season from the screener.</p>"
        elif year not in (load_catalog().get("college", {}).get("seasons") or []):
            inner = render_empty_card(
                "College player",
                [f"No college screener file for {year} is in this build."],
            )
        else:
            pack = load_college_pack(year)
            player = find_college_player(year, cid)
            if player:
                from razzle.player_data import PlayerSheetContext
                from razzle.player_sheet import render_college_tear

                ctx = PlayerSheetContext(
                    kind="college",
                    name=player.get("name") or "College player",
                    pos=player.get("pos") or "",
                    team=player.get("team") or "",
                    season=year,
                    season_stats=player,
                    source_url=((pack or {}).get("source") or [""])[0] if isinstance((pack or {}).get("source"), list) else (pack or {}).get("source") or "",
                )
                inner = render_college_tear(ctx, h, sample_badge())
            else:
                inner = render_empty_card(
                    "College player",
                    [
                        f"No row for player id {cid} in the {year} college screener file.",
                        "Blank where the source has no row — nothing invented here.",
                    ],
                )
    elif legacy_name:
        if not stats_on_disk:
            inner = render_empty_card(legacy_name, [missing_nfl_season_message(stats_season)])
        else:
            found, pack = find_players_by_name(legacy_name, stats_season)
            if not found:
                inner = render_empty_card(
                    legacy_name,
                    [
                        f"No published {stats_season} regular-season skill stats under this name in nflverse.",
                        "Try opening the player from your roster or the screener so Sleeper ids can join the file.",
                    ],
                )
            else:
                source = (pack or {}).get("source") or ""
                inner = "".join(
                    _render_skill_tear_sheet(player, stats_season, source, league_snapshot=league_snapshot)
                    for player in found
                )
    else:
        inner = "<p>Open a player from the screener or your roster.</p>"

    body = inner + '<p class="back-link"><a href="/screener/">← Screener</a></p>'
    return layout(
        "Player",
        body,
        user=user,
        active="player",
        page="page-player",
        extra_head='<link rel="stylesheet" href="/player.css">',
    )


def war_preview_messages(link, snapshot):
    messages = [
        {
            "staff": "Razzle",
            "tone": "razzle",
            "body": "Film room's open. This is a preview thread — staff voice, sample intel.",
            "sample": True,
            "urgent": False,
        },
        {
            "staff": "Hawkeye",
            "tone": "hawk",
            "body": "Screener's loaded. I'm cross-checking usage before anyone gets cute in trade chat.",
            "sample": True,
            "urgent": False,
        },
    ]
    if link and link.get("league_id") and snapshot:
        mine = set(snapshot.get("mine") or [])
        my_team = next(
            (team for team in snapshot.get("teams") or [] if team.get("roster_id") in mine),
            None,
        )
        if my_team:
            starters = []
            for entry in my_team.get("starters") or []:
                _, name = roster_entry_parts(entry)
                if not str(name).startswith("id "):
                    starters.append(name)
            focus = starters[0] if starters else my_team.get("label")
            messages.append({
                "staff": "Razzle",
                "tone": "razzle",
                "body": f"Heads up — {focus} is your pivot this week. Don't die on the wrong hill.",
                "sample": True,
                "urgent": True,
            })
        else:
            messages.append({
                "staff": "Razzle",
                "tone": "razzle",
                "body": "League's on file. I don't see your roster as an owner yet — fix that in Home setup.",
                "sample": True,
                "urgent": False,
            })
    else:
        messages.append({
            "staff": "Dr. Dolphin",
            "tone": "dolphin",
            "body": "Save a Sleeper league on Home and this thread picks up your roster context.",
            "sample": True,
            "urgent": False,
        })
    messages.append({
        "staff": "Razzle",
        "tone": "razzle",
        "body": "Live replies ship later. For now, read the room and poke the screener.",
        "sample": True,
        "urgent": False,
    })
    return messages


def render_war_bubble(message):
    staff = message.get("staff") or "Staff"
    tone = message.get("tone") or "staff"
    urgent = message.get("urgent")
    sample = message.get("sample")
    badges = []
    if sample:
        badges.append(sample_badge())
    if urgent:
        badges.append('<span class="badge urgent">Urgent</span>')
    badge_html = (" ".join(badges) + " ") if badges else ""
    tone_class = " ".join(h(part) for part in str(tone).split())
    return (
        f'<article class="war-msg {tone_class}{" urgent" if urgent else ""}">'
        f'<p class="war-who">{h(staff)}</p>'
        f'<p class="war-text">{badge_html}{h(message.get("body") or "")}</p>'
        "</article>"
    )


def page_war(user, preview, live_messages=None, banner=None):
    parts = [
        '<div class="war-phone">',
        '<div class="war-phone-notch" aria-hidden="true"></div>',
        '<div class="war-phone-header">',
        '<p class="war-phone-title">War Room</p>',
        '<p class="war-phone-sub">Staff thread · preview</p>',
        "</div>",
        '<div class="war-thread" role="log" aria-live="polite">',
    ]
    if banner:
        parts.append(f'<p class="banner">{h(banner)}</p>')
    for message in preview:
        parts.append(render_war_bubble(message))
    for message in live_messages or []:
        if message.get("role") == "you":
            parts.append(
                '<article class="war-msg you"><p class="war-who">You</p>'
                f'<p class="war-text">{h(message.get("body") or "")}</p></article>'
            )
        elif message.get("body") and message.get("body") != KEY_MISSING:
            parts.append(
                '<article class="war-msg room"><p class="war-who">War Room</p>'
                f'<p class="war-text">{h(message.get("body") or "")}</p></article>'
            )
    parts.extend([
        "</div>",
        '<div class="war-compose-bar">',
        '<div class="war-compose-faux" aria-hidden="true">'
        '<span class="war-compose-placeholder">Message the staff…</span>'
        "</div>",
        "</div>",
        "</div>",
    ])
    return layout("War Room", "\n".join(parts), user=user, war=True, active="war", page="page-war")


def screener_html(user):
    path = ROOT / "screener" / "index.html"
    template = path.read_text(encoding="utf-8")
    nav = shell_nav(user, active="screener")
    html_doc = template.replace("__SHELL_NAV__", nav)
    return html_doc


def cookies_of(handler):
    jar = {}
    raw = handler.headers.get("Cookie") or ""
    for part in raw.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            jar[key.strip()] = value.strip()
    return jar


def current_user(handler):
    token = cookies_of(handler).get("razzle_session")
    if not token or len(token) > 200:
        return None
    with DB() as conn:
        row = conn.execute(
            """
            SELECT users.id, users.email FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ?
            """,
            (token,),
        ).fetchone()
    return dict(row) if row else None


def read_form(handler):
    length = int(handler.headers.get("Content-Length") or 0)
    if length < 0 or length > 100_000:
        return None
    raw = handler.rfile.read(length).decode("utf-8", errors="replace")
    parsed = urllib.parse.parse_qs(raw, keep_blank_values=False)
    return {key: values[0] for key, values in parsed.items() if values}


def get_link(user_id):
    with DB() as conn:
        row = conn.execute("SELECT * FROM sleeper_links WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_choices(user_id):
    with DB() as conn:
        rows = conn.execute(
            "SELECT league_id, name FROM league_choices WHERE user_id = ? ORDER BY name",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args), flush=True)

    def send_html(self, code, body, extra=None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for key, value in extra or []:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location, extra=None):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        for key, value in extra or []:
            self.send_header(key, value)
        self.end_headers()

    def session_cookie(self, token):
        return ("Set-Cookie", f"razzle_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000")

    def clear_cookie(self):
        return ("Set-Cookie", "razzle_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        user = current_user(self)
        if path.startswith("/design") or path in ("/shell.css", "/player.css"):
            self.serve_static(path)
            return
        if path in ("/screener", "/screener/", "/screener/index.html"):
            self.send_html(200, screener_html(user))
            return
        if path.startswith("/screener"):
            self.serve_static(path)
            return
        if path == "/":
            if user:
                self.redirect("/home")
            else:
                self.send_html(200, page_auth())
            return
        if path == "/home":
            if not user:
                self.redirect("/")
                return
            self.send_html(200, self.home_html(user))
            return
        if path == "/player":
            query = urllib.parse.parse_qs(parsed.query)
            params = {key: values[0] for key, values in query.items() if values}
            self.send_html(200, page_player(params, user=user))
            return
        if path == "/war-room":
            if not user:
                self.redirect("/")
                return
            self.send_html(200, self.war_html(user))
            return
        self.send_html(404, layout("Missing", "<p>That page is not here.</p>", user=user))

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        form = read_form(self)
        if form is None:
            self.send_html(400, layout("Razzle", "<p>That form is too large.</p>"))
            return
        user = current_user(self)
        if path == "/register":
            self.post_register(form)
            return
        if path == "/login":
            self.post_login(form)
            return
        if path == "/logout":
            token = cookies_of(self).get("razzle_session")
            if token:
                with DB() as conn:
                    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            self.redirect("/", [self.clear_cookie()])
            return
        if not user:
            self.redirect("/")
            return
        if path == "/sleeper/lookup":
            self.post_lookup(user, form)
            return
        if path == "/sleeper/league":
            self.post_league(user, form)
            return
        if path == "/war-room":
            self.post_war(user, form)
            return
        if path == "/engine/thesis":
            self.post_engine_thesis(user, form)
            return
        self.send_html(404, layout("Missing", "<p>That page is not here.</p>", user=user))

    def post_engine_thesis(self, user, form):
        self.send_html(200, self.home_html(user, thesis_form=form))

    def post_register(self, form):
        email = clean_email(form.get("email"))
        password = form.get("password") or ""
        if not email:
            self.send_html(400, page_auth("Enter an email address."))
            return
        if len(password) < 8 or len(password) > 200:
            self.send_html(400, page_auth("Use a longer password (8 or more)."))
            return
        salt, digest = hash_password(password)
        try:
            with DB() as conn:
                cur = conn.execute(
                    "INSERT INTO users (email, salt, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (email, salt, digest, now()),
                )
                user_id = cur.lastrowid
                token = secrets.token_urlsafe(32)
                conn.execute(
                    "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                    (token, user_id, now()),
                )
        except sqlite3.IntegrityError:
            self.send_html(400, page_auth("That email is already registered."))
            return
        self.redirect("/home", [self.session_cookie(token)])

    def post_login(self, form):
        email = clean_email(form.get("email"))
        password = form.get("password") or ""
        row = None
        if email:
            with DB() as conn:
                row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row or not verify_password(password, row["salt"], row["password_hash"]):
            self.send_html(400, page_auth("Email or password does not match."))
            return
        token = secrets.token_urlsafe(32)
        with DB() as conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                (token, row["id"], now()),
            )
        self.redirect("/home", [self.session_cookie(token)])

    def post_lookup(self, user, form):
        username = clean_username(form.get("username"))
        if not username:
            self.send_html(400, self.home_html(user, error="Enter a Sleeper username."))
            return
        try:
            payload = sleeper_json("/user/" + urllib.parse.quote(username))
            if not isinstance(payload, dict) or not payload.get("user_id"):
                raise SleeperError(404)
            sleeper_user_id = str(payload["user_id"])
            canonical = clean_username(payload.get("username") or username) or username
            season = sleeper_league_season()
            leagues = sleeper_json(f"/user/{urllib.parse.quote(sleeper_user_id)}/leagues/nfl/{season}")
            if not isinstance(leagues, list):
                raise SleeperError(0)
        except SleeperError as exc:
            message = "Sleeper has no user by that name." if exc.code == 404 else "Sleeper did not answer."
            self.send_html(400, self.home_html(user, error=message))
            return
        choices = []
        for league in leagues:
            if not isinstance(league, dict):
                continue
            league_id = clean_league_id(str(league.get("league_id") or ""))
            name = str(league.get("name") or "").strip() or ("League " + league_id)
            if league_id:
                choices.append((league_id, name))
        with DB() as conn:
            existing = conn.execute(
                "SELECT league_id FROM sleeper_links WHERE user_id = ?", (user["id"],)
            ).fetchone()
            keep = existing["league_id"] if existing else None
            if keep not in {item[0] for item in choices}:
                keep = None
            kept_name = None
            if keep:
                for league_id, name in choices:
                    if league_id == keep:
                        kept_name = name
            conn.execute("DELETE FROM league_choices WHERE user_id = ?", (user["id"],))
            conn.execute(
                """
                INSERT INTO sleeper_links (user_id, username, sleeper_user_id, league_id, league_name)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                  username = excluded.username,
                  sleeper_user_id = excluded.sleeper_user_id,
                  league_id = excluded.league_id,
                  league_name = excluded.league_name
                """,
                (user["id"], canonical, sleeper_user_id, keep, kept_name),
            )
            conn.executemany(
                "INSERT INTO league_choices (user_id, league_id, name) VALUES (?, ?, ?)",
                [(user["id"], league_id, name) for league_id, name in choices],
            )
        if not choices:
            self.send_html(
                200,
                self.home_html(
                    user,
                    error=f"No {sleeper_league_season()} NFL leagues on that Sleeper user.",
                ),
            )
            return
        self.redirect("/home")

    def post_league(self, user, form):
        league_id = clean_league_id(form.get("league_id"))
        if not league_id:
            self.send_html(400, self.home_html(user, error="That league id is not valid."))
            return
        with DB() as conn:
            choice = conn.execute(
                "SELECT name FROM league_choices WHERE user_id = ? AND league_id = ?",
                (user["id"], league_id),
            ).fetchone()
            if not choice:
                self.send_html(400, self.home_html(user, error="Pull leagues before saving one."))
                return
            conn.execute(
                """
                UPDATE sleeper_links
                SET league_id = ?, league_name = ?
                WHERE user_id = ?
                """,
                (league_id, choice["name"], user["id"]),
            )
        self.redirect("/home")

    def home_html(self, user, error=None, thesis_form=None):
        link = get_link(user["id"])
        choices = get_choices(user["id"])
        snapshot = None
        if link and link.get("league_id") and not error:
            try:
                snapshot = build_snapshot(link)
            except SleeperError:
                error = "Sleeper did not return this league. " + ODDS_MISSING
            except (OSError, ValueError, TypeError, KeyError):
                error = "Sleeper did not return this league. " + ODDS_MISSING
        default_form = thesis_form or {"team": "HOU", "def_z": "2", "draws": "10000"}
        engine_result = run_engine_for_form(default_form)
        return page_home(
            user,
            link,
            choices,
            snapshot,
            error=error,
            engine_result=engine_result,
            thesis_form=default_form,
        )

    def war_messages(self, user_id):
        with DB() as conn:
            rows = conn.execute(
                """
                SELECT role, body FROM war_messages
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 50
                """,
                (user_id,),
            ).fetchall()
        return list(reversed([dict(row) for row in rows]))

    def war_html(self, user, banner=None):
        link = get_link(user["id"])
        snapshot = None
        if link and link.get("league_id"):
            try:
                snapshot = build_snapshot(link)
            except (SleeperError, OSError, ValueError, TypeError, KeyError):
                snapshot = None
        preview = war_preview_messages(link, snapshot)
        key = (os.environ.get("RAZZLE_MODEL_KEY") or "").strip()
        live = self.war_messages(user["id"]) if key else []
        return page_war(user, preview, live_messages=live, banner=banner)

    def post_war(self, user, form):
        question = (form.get("question") or "").strip()
        if not question:
            self.redirect("/war-room")
            return
        question = question[:2000]
        key = (os.environ.get("RAZZLE_MODEL_KEY") or "").strip()
        if not key:
            self.redirect("/war-room")
            return
        link = get_link(user["id"])
        if not link or not link.get("league_id"):
            context = "No Sleeper league is saved for this account."
            reply, ok = ask_model(question, context)
        else:
            try:
                snapshot = build_snapshot(link)
            except SleeperError:
                self.send_html(
                    200,
                    self.war_html(user, banner="The league did not load, so the room did not answer."),
                )
                return
            reply, ok = ask_model(question, context_from(snapshot, link))
        if not ok and reply == KEY_MISSING:
            reply = KEY_MISSING
        with DB() as conn:
            conn.execute(
                "INSERT INTO war_messages (user_id, role, body, created_at) VALUES (?, ?, ?, ?)",
                (user["id"], "you", question, now()),
            )
            conn.execute(
                "INSERT INTO war_messages (user_id, role, body, created_at) VALUES (?, ?, ?, ?)",
                (user["id"], "room", reply, now()),
            )
        self.redirect("/war-room")

    def serve_static(self, path):
        target = resolve_static(path)
        if target is None:
            self.send_html(404, layout("Missing", "<p>That file is not here.</p>"))
            return
        data = target.read_bytes()
        ctype = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)


def resolve_static(path):
    if path == "/shell.css":
        candidate = (ROOT / "shell.css").resolve()
        return candidate if candidate.is_file() else None
    if path == "/player.css":
        candidate = (ROOT / "player.css").resolve()
        return candidate if candidate.is_file() else None
    roots = (("/screener", ROOT / "screener"), ("/design", ROOT / "design"))
    for prefix, folder in roots:
        if path != prefix and not path.startswith(prefix + "/"):
            continue
        rel = path[len(prefix):].lstrip("/") or "index.html"
        base = folder.resolve()
        candidate = (base / rel).resolve()
        if candidate != base and base not in candidate.parents:
            return None
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.is_file():
            return None
        if candidate.suffix.lower() not in STATIC_EXT:
            return None
        return candidate
    return None


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    with DB():
        pass
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Razzle shell on http://127.0.0.1:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
