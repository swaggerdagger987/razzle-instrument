#!/usr/bin/env python3
"""Build compact screener JSON from public nflverse and sportsdataverse files.

No API key. Counting stats are copied. Derived fields are PPR, PPG, and
total touchdowns. A category with no source value is omitted, not filled with 0.
NFL seasons 2015 through the latest published nflverse year, regular season, plus
the weekly file for each of those
seasons. College seasons are every year whose passing, rushing, receiving, and
roster files download.
"""

import csv
import gzip
import io
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
NFL_DIR = DATA / "nfl"
COLLEGE_DIR = DATA / "college"

NFL_YEARS = list(range(2015, 2027))
COLLEGE_YEARS = list(range(2015, 2027))
SKILL = ("QB", "RB", "WR", "TE")

NFL_REG = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_{year}.csv.gz"
NFL_WEEK = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{year}.csv.gz"
NFL_ROSTER = "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{year}.csv"
CFB_PASS = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_{year}.csv"
CFB_RUSH = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_{year}.csv"
CFB_REC = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_{year}.csv"
CFB_ROSTER = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_{year}.csv.gz"


def fetch(url):
    last = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "razzle-screener-build"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read()
            if url.endswith(".gz"):
                raw = gzip.decompress(raw)
            return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
    raise SystemExit(f"failed to fetch {url}: {last}")


def fetch_ok(url):
    try:
        return fetch(url), None
    except SystemExit as exc:
        return None, str(exc)


def num(value):
    if value is None or value == "":
        return None
    return float(value)


def whole(value):
    n = num(value)
    if n is None:
        return None
    return int(round(n))


def n0(value):
    n = num(value)
    return 0.0 if n is None else n


def age_on(birth, on):
    year, month, day = (int(part) for part in birth.split("-"))
    born = date(year, month, day)
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def ppr_from(stats):
    """Standard PPR from counting stats. Matches nflverse fantasy_points_ppr."""
    fumbles = (
        n0(stats.get("sack_fumbles_lost"))
        + n0(stats.get("rushing_fumbles_lost"))
        + n0(stats.get("receiving_fumbles_lost"))
    )
    points = (
        n0(stats.get("passing_yards")) * 0.04
        + n0(stats.get("passing_tds")) * 4
        + n0(stats.get("passing_interceptions")) * -2
        + n0(stats.get("rushing_yards")) * 0.1
        + n0(stats.get("rushing_tds")) * 6
        + n0(stats.get("receptions")) * 1
        + n0(stats.get("receiving_yards")) * 0.1
        + n0(stats.get("receiving_tds")) * 6
        + n0(stats.get("special_teams_tds")) * 6
        + n0(stats.get("passing_2pt_conversions")) * 2
        + n0(stats.get("rushing_2pt_conversions")) * 2
        + n0(stats.get("receiving_2pt_conversions")) * 2
        + fumbles * -2
    )
    return round(points + 1e-9, 1)


def check_ppr(label, computed, published):
    if published is None:
        return
    if computed != round(published + 1e-9, 1):
        raise SystemExit(f"PPR mismatch for {label}: {computed} vs {published}")


def put(player, key, value):
    if value is None or value == "":
        return
    player[key] = value


def norm_gsis(value):
    return (value or "").strip()


def build_player_meta(year):
    """Roster bio keyed by gsis id (latest season roster file)."""
    roster_url = NFL_ROSTER.format(year=year)
    roster, err = fetch_ok(roster_url)
    if roster is None:
        return {"year": year, "skipped": True, "error": err}
    players = {}
    for row in roster:
        gsis = norm_gsis(row.get("gsis_id"))
        if not gsis:
            continue
        entry = {"gsisId": gsis, "name": row.get("full_name") or ""}
        put(entry, "pos", row.get("position") or "")
        put(entry, "team", row.get("team") or "")
        if row.get("height") not in (None, ""):
            try:
                inches = int(float(row["height"]))
                entry["heightIn"] = inches
                entry["height"] = f"{inches // 12}'{inches % 12}\""
            except (TypeError, ValueError):
                put(entry, "height", row.get("height"))
        put(entry, "weight", whole(row.get("weight")))
        put(entry, "college", row.get("college") or "")
        put(entry, "yearsExp", whole(row.get("years_exp")))
        put(entry, "rookieYear", whole(row.get("rookie_year") or row.get("entry_year")))
        draft_num = whole(row.get("draft_number"))
        if draft_num is not None:
            entry["draftPick"] = draft_num
            rnd = whole(row.get("draft_round"))
            if rnd is not None:
                entry["draftRound"] = rnd
        players[gsis] = entry
    out = NFL_DIR / "player-meta.json"
    write_json(
        out,
        {"season": year, "source": roster_url, "players": players},
    )
    return {"year": year, "players": len(players), "skipped": False}


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


COUNT_FIELDS = (
    ("py", "passing_yards"),
    ("ptd", "passing_tds"),
    ("att", "attempts"),
    ("int", "passing_interceptions"),
    ("ry", "rushing_yards"),
    ("rtd", "rushing_tds"),
    ("car", "carries"),
    ("rec", "receptions"),
    ("rey", "receiving_yards"),
    ("retd", "receiving_tds"),
    ("tgt", "targets"),
)

NFL_TEAM_WEEK = "https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{year}.csv.gz"
NFL_GAMES = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"


def counting(row):
    out = {}
    for key, source in COUNT_FIELDS:
        value = whole(row.get(source)) if source in row else None
        if value is not None:
            out[key] = value
    tds = [out[key] for key in ("ptd", "rtd", "retd") if key in out]
    if tds:
        out["td"] = sum(tds)
    return out


def birth_map(roster_rows):
    birth = {}
    for row in roster_rows:
        gsis = row.get("gsis_id") or ""
        born = row.get("birth_date") or ""
        if gsis and born and gsis not in birth:
            birth[gsis] = born
    return birth


def skill_rows(rows, season_type=None):
    kept = []
    for row in rows:
        if (row.get("position") or "") not in SKILL:
            continue
        if season_type and (row.get("season_type") or "") != season_type:
            continue
        kept.append(row)
    return kept


def season_player(row, births, year):
    games = whole(row.get("games")) if "games" in row else None
    points = ppr_from(row)
    published = num(row.get("fantasy_points_ppr")) if "fantasy_points_ppr" in row else None
    check_ppr(row.get("player_display_name") or row.get("player_id"), points, published)
    player = {
        "name": row.get("player_display_name") or row.get("player_name") or "",
        "pos": row["position"],
        "ppr": points,
    }
    put(player, "gsisId", norm_gsis(row.get("player_id")))
    put(player, "team", row.get("recent_team") or "")
    put(player, "gp", games)
    player.update(counting(row))
    if games:
        player["ppg"] = round(points / games + 1e-9, 1)
    born = births.get(row.get("player_id") or "")
    if born:
        player["age"] = age_on(born, date(year, 9, 1))
    if not player["name"]:
        return None
    return player


def add_counts(total, row):
    keys = [source for _, source in COUNT_FIELDS] + [
        "sack_fumbles_lost",
        "rushing_fumbles_lost",
        "receiving_fumbles_lost",
        "special_teams_tds",
        "passing_interceptions",
        "passing_2pt_conversions",
        "rushing_2pt_conversions",
        "receiving_2pt_conversions",
        "fantasy_points_ppr",
    ]
    for key in keys:
        if key not in row:
            continue
        value = num(row.get(key))
        if value is None:
            continue
        total[key] = total.get(key, 0.0) + value


def week_player(rows, births, year):
    base = rows[0]
    total = {}
    for row in rows:
        add_counts(total, row)
    # Rebuild a dict the PPR helper can read. Summed floats stay floats.
    points = ppr_from(total)
    published = total.get("fantasy_points_ppr")
    check_ppr(
        f"{base.get('player_display_name')} {year} wk {base.get('week')}",
        points,
        published,
    )
    player = {
        "name": base.get("player_display_name") or base.get("player_name") or "",
        "pos": base["position"],
        "ppr": points,
    }
    put(player, "gsisId", norm_gsis(base.get("player_id")))
    put(player, "team", base.get("team") or "")
    put(player, "opp", base.get("opponent_team") or "")
    if base.get("game_id") not in (None, ""):
        put(player, "gameId", str(base.get("game_id")))
    home = base.get("home_away")
    if home in ("home", "away"):
        put(player, "home", home)
    summed = {source: total[source] for _, source in COUNT_FIELDS if source in total}
    player.update(counting(summed))
    born = births.get(base.get("player_id") or "")
    if born:
        player["age"] = age_on(born, date(year, 9, 1))
    if not player["name"]:
        return None
    return player


def build_nfl_year(year):
    reg_url = NFL_REG.format(year=year)
    week_url = NFL_WEEK.format(year=year)
    roster_url = NFL_ROSTER.format(year=year)
    reg_rows, reg_err = fetch_ok(reg_url)
    if reg_rows is None:
        return {
            "year": year,
            "players": 0,
            "weeks": [],
            "disabledWeeks": [],
            "weekRows": {},
            "regUrl": reg_url,
            "weekUrl": NFL_WEEK.format(year=year),
            "rosterUrl": roster_url,
            "rosterError": reg_err,
            "skipped": True,
            "errors": {"reg": reg_err},
        }
    week_rows, week_err = fetch_ok(week_url)
    if week_rows is None:
        return {
            "year": year,
            "players": 0,
            "weeks": [],
            "disabledWeeks": [],
            "weekRows": {},
            "regUrl": reg_url,
            "weekUrl": week_url,
            "rosterUrl": roster_url,
            "rosterError": None,
            "skipped": True,
            "errors": {"week": week_err},
        }
    reg = skill_rows(reg_rows)
    weeks_raw = skill_rows(week_rows, season_type="REG")
    roster, roster_err = fetch_ok(roster_url)
    births = birth_map(roster) if roster is not None else {}

    seen = set()
    players = []
    for row in reg:
        pid = row.get("player_id") or row.get("player_display_name")
        if pid in seen:
            raise SystemExit(f"duplicate season row {year} {pid}")
        seen.add(pid)
        player = season_player(row, births, year)
        if player:
            players.append(player)
    players.sort(key=lambda p: (-(p["ppr"]), p["name"]))

    grouped = {}
    for row in weeks_raw:
        week = whole(row.get("week"))
        if week is None:
            continue
        pid = row.get("player_id") or row.get("player_display_name")
        grouped.setdefault(week, {}).setdefault(pid, []).append(row)

    week_payload = {}
    for week, by_player in grouped.items():
        week_players = []
        for rows in by_player.values():
            player = week_player(rows, births, year)
            if player:
                week_players.append(player)
        week_players.sort(key=lambda p: (-(p["ppr"]), p["name"]))
        week_payload[str(week)] = week_players

    present = sorted(int(week) for week in week_payload)
    disabled = []
    if present:
        disabled = [week for week in range(1, present[-1] + 1) if week not in present]

    write_json(
        NFL_DIR / f"{year}.json",
        {
            "universe": "nfl",
            "season": year,
            "seasonType": "REG",
            "source": reg_url,
            "players": players,
        },
    )
    write_json(
        NFL_DIR / f"{year}-weeks.json",
        {
            "universe": "nfl",
            "season": year,
            "seasonType": "REG",
            "source": week_url,
            "weeks": week_payload,
        },
    )
    return {
        "year": year,
        "players": len(players),
        "weeks": present,
        "disabledWeeks": disabled,
        "weekRows": {str(week): len(rows) for week, rows in week_payload.items()},
        "regUrl": reg_url,
        "weekUrl": week_url,
        "rosterUrl": roster_url if roster is not None else None,
        "rosterError": roster_err,
        "skipped": False,
        "errors": {},
    }


def college_player(player_id, passing, rushing, receiving, roster):
    parts = [table[player_id] for table in (passing, rushing, receiving) if player_id in table]
    stat_pos = next(
        (row.get("position_group") for row in parts if row.get("position_group") in SKILL),
        "",
    )
    roster_row = roster.get(player_id)
    roster_pos = (roster_row or {}).get("position_abbreviation") or ""
    if roster_pos in SKILL:
        pos = roster_pos
    elif roster_pos in ("", "-") and stat_pos in SKILL:
        pos = stat_pos
    elif not roster_row and stat_pos in SKILL:
        pos = stat_pos
    else:
        return None

    home = max(parts, key=lambda row: whole(row.get("plays")) or 0)
    name = home.get("passer_player_name") or home.get("rusher_player_name") or home.get("receiver_player_name")
    if roster_row and roster_row.get("full_name"):
        name = roster_row["full_name"]
    if not name:
        return None

    player = {"name": name, "pos": pos, "cid": str(player_id)}
    put(player, "team", home.get("pos_team") or "")
    put(player, "conference", home.get("conference") or "")
    games = [whole(row.get("games")) for row in parts if "games" in row]
    games = [game for game in games if game is not None]
    if games:
        player["gp"] = max(games)
    if player_id in passing:
        put(player, "py", whole(passing[player_id].get("yards")))
        put(player, "ptd", whole(passing[player_id].get("passing_td")))
    if player_id in rushing:
        put(player, "ry", whole(rushing[player_id].get("yards")))
        put(player, "rtd", whole(rushing[player_id].get("rushing_td")))
    if player_id in receiving:
        # The receiving file names the score column passing_td. It is the
        # receiving touchdown count for that player.
        put(player, "rey", whole(receiving[player_id].get("yards")))
        put(player, "retd", whole(receiving[player_id].get("passing_td")))
    yards = [player[key] for key in ("py", "ry", "rey") if key in player]
    tds = [player[key] for key in ("ptd", "rtd", "retd") if key in player]
    if yards:
        player["ty"] = sum(yards)
    if tds:
        player["td"] = sum(tds)
    return player


def build_college_year(year):
    urls = {
        "pass": CFB_PASS.format(year=year),
        "rush": CFB_RUSH.format(year=year),
        "rec": CFB_REC.format(year=year),
        "roster": CFB_ROSTER.format(year=year),
    }
    loaded = {}
    errors = {}
    for key, url in urls.items():
        rows, err = fetch_ok(url)
        if err:
            errors[key] = err
        else:
            loaded[key] = rows
    needed = ("pass", "rush", "rec")
    if any(key not in loaded for key in needed):
        return {"year": year, "players": 0, "skipped": True, "urls": urls, "errors": errors}

    passing = {row["player_id"]: row for row in loaded["pass"] if row.get("player_id")}
    rushing = {row["player_id"]: row for row in loaded["rush"] if row.get("player_id")}
    receiving = {row["player_id"]: row for row in loaded["rec"] if row.get("player_id")}
    roster = {}
    if "roster" in loaded:
        for row in loaded["roster"]:
            roster[row.get("athlete_id") or ""] = row

    players = []
    for player_id in set(passing) | set(rushing) | set(receiving):
        player = college_player(player_id, passing, rushing, receiving, roster)
        if player:
            players.append(player)
    players.sort(key=lambda p: (-(p.get("ty") or 0), p["name"]))
    write_json(
        COLLEGE_DIR / f"{year}.json",
        {
            "universe": "college",
            "season": year,
            "source": [urls["pass"], urls["rush"], urls["rec"], urls["roster"]],
            "players": players,
        },
    )
    return {
        "year": year,
        "players": len(players),
        "skipped": False,
        "urls": urls,
        "roster": "roster" in loaded,
        "errors": errors,
    }


def write_sources(nfl, college):
    lines = ["# Screener sources", ""]
    lines.append(
        "NFL regular season, QB/RB/WR/TE only, one row per player per season. "
        "Seasons 2015 through the latest year that downloaded. Each season file is "
        "`screener/data/nfl/YEAR.json`, built from:"
    )
    lines.append("")
    for row in nfl:
        if row.get("skipped"):
            lines.append(f"- {row['year']}: not built ({row.get('errors')})")
        else:
            lines.append(f"- {row['year']}: {row['regUrl']} ({row['players']} players)")
    lines.append("")
    lines.append(
        "Age is years old on September 1 of that season, from `birth_date` in the roster file "
        "joined on `gsis_id` = `player_id`. A player with no birth date has no age."
    )
    lines.append("")
    for row in nfl:
        if row.get("skipped"):
            continue
        if row["rosterUrl"]:
            lines.append(f"- {row['year']} roster: {row['rosterUrl']}")
        else:
            lines.append(f"- {row['year']} roster: missing ({row['rosterError']})")
    lines.append("")
    lines.append(
        "PPR is computed from counting stats: pass yards × 0.04, pass TD × 4, interception × −2, "
        "rush yards × 0.1, rush TD × 6, reception × 1, rec yards × 0.1, rec TD × 6, "
        "special-teams TD × 6, two-point conversion × 2, and offensive fumbles lost "
        "(sack + rush + receiving) × −2. A blank component counts as 0 only inside that formula. "
        "That matches nflverse `fantasy_points_ppr` on every skill-position row, season and week. "
        "PPG is PPR divided by games, and only when the file has a games value. "
        "TD is pass TD + rush TD + rec TD. Pos Rank is within position by PPR and is computed in the page."
    )
    lines.append("")
    lines.append(
        "Weekly view uses the same positions and the same formula, one row per player per week, "
        "regular season only (`season_type` = REG). A week with more than one row for a player "
        "is summed. The week file has no `games` column, so GP and PPG are left blank in a week view. "
        "Files:"
    )
    lines.append("")
    for row in nfl:
        if row.get("skipped"):
            continue
        weeks = ", ".join(str(week) for week in row["weeks"]) or "none"
        disabled = ", ".join(str(week) for week in row["disabledWeeks"]) or "none"
        lines.append(
            f"- {row['year']}: {row['weekUrl']} — weeks present: {weeks}. "
            f"Disabled (inside 1 through the last present week, but with no skill-position rows): {disabled}."
        )
    lines.append("")
    lines.append(
        "The week control lists every week from 1 through the last week that has rows. "
        "A missing week in that span is disabled. Weeks that the file does not contain past that "
        "span are not shown. No week numbers were invented."
    )
    lines.append("")
    built = [row for row in college if not row["skipped"]]
    skipped = [row for row in college if row["skipped"]]
    if built:
        years = ", ".join(str(row["year"]) for row in built)
        lines.append(
            f"College seasons downloaded with no API key: {years}. "
            "Play-derived season stats, skill positions. One file per season at "
            "`screener/data/college/YEAR.json`."
        )
        lines.append("")
        for row in built:
            lines.append(
                f"- {row['year']} passing: {row['urls']['pass']}"
            )
            lines.append(
                f"- {row['year']} rushing: {row['urls']['rush']}"
            )
            lines.append(
                f"- {row['year']} receiving: {row['urls']['rec']}"
            )
            lines.append(
                f"- {row['year']} roster: {row['urls']['roster']}"
                + ("" if row["roster"] else " (not used; download failed)")
                + f" — {row['players']} players"
            )
        lines.append("")
        lines.append(
            "GP is the max `games` across the passing, rushing, and receiving files. "
            "A stat with no source row is left blank. Total yards and total TD sum only the "
            "categories that exist. Receiving TD is the `passing_td` column on the receiving file. "
            "Roster position wins when it is QB, RB, WR, or TE. A roster position of blank or `-` "
            "falls back to the stat file `position_group`. College files are season totals, not weeks, "
            "so the page has no college week control."
        )
    if skipped:
        lines.append("")
        lines.append("College seasons that did not download, and are not in the page:")
        lines.append("")
        for row in skipped:
            lines.append(f"- {row['year']}: {row['errors']}")
    lines.append("")
    lines.append(
        "Also fetched in an earlier pass, then not used as the table: "
        "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_player_box/player_box_2025.csv.gz "
        "(one row per player-game, no school, conference, or position)."
    )
    lines.append("")
    (DATA / "SOURCES.md").write_text("\n".join(lines), encoding="utf-8")


def build_engine_support(year):
    """Team-week totals and remaining schedule for the valuation engine."""
    out_dir = NFL_DIR / "engine"
    out_dir.mkdir(parents=True, exist_ok=True)
    team_url = NFL_TEAM_WEEK.format(year=year)
    team_rows, team_err = fetch_ok(team_url)
    games_rows, games_err = fetch_ok(NFL_GAMES)
    if team_rows is None or games_rows is None:
        return {"year": year, "skipped": True, "errors": {"team": team_err, "games": games_err}}
    team_week = []
    for row in team_rows:
        if (row.get("season_type") or "") != "REG":
            continue
        try:
            week = int(row.get("week"))
            season = int(row.get("season"))
        except (TypeError, ValueError):
            continue
        if season != year:
            continue
        team_week.append(
            {
                "team": row.get("team") or "",
                "week": week,
                "passAtt": whole(row.get("passing_attempts")),
                "sacks": whole(row.get("sacks_suffered")),
                "carries": whole(row.get("rushing_attempts")),
                "targets": whole(row.get("targets")),
                "pf": whole(row.get("points_for")),
                "pa": whole(row.get("points_against")),
            }
        )
    schedule = []
    for row in games_rows:
        try:
            season = int(row.get("season"))
            week = int(row.get("week"))
        except (TypeError, ValueError):
            continue
        if season != year or week < 4 or week > 17:
            continue
        if (row.get("game_type") or "REG") != "REG":
            continue
        gid = row.get("game_id") or ""
        for side, team_col, opp_col, ha in (
            ("home", "home_team", "away_team", 1),
            ("away", "away_team", "home_team", -1),
        ):
            team = row.get(team_col) or ""
            opp = row.get(opp_col) or ""
            if not team:
                continue
            schedule.append(
                {
                    "team": team,
                    "week": week,
                    "opponent": opp,
                    "homeSign": ha,
                    "gameId": str(gid),
                }
            )
    write_json(
        out_dir / f"{year}-team-week.json",
        {"season": year, "source": team_url, "rows": team_week},
    )
    write_json(
        out_dir / f"{year}-schedule.json",
        {"season": year, "source": NFL_GAMES, "rows": schedule},
    )
    return {"year": year, "skipped": False, "teamWeekRows": len(team_week), "scheduleRows": len(schedule)}


def main():
    NFL_DIR.mkdir(parents=True, exist_ok=True)
    COLLEGE_DIR.mkdir(parents=True, exist_ok=True)
    # The old single-file dumps are replaced by the per-season files.
    for stale in (DATA / "nfl.json", DATA / "college.json"):
        if stale.exists():
            stale.unlink()

    nfl = []
    college = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(build_nfl_year, year): ("nfl", year) for year in NFL_YEARS}
        futures.update({pool.submit(build_college_year, year): ("college", year) for year in COLLEGE_YEARS})
        for future in as_completed(futures):
            kind, year = futures[future]
            result = future.result()
            if kind == "nfl":
                nfl.append(result)
                if result.get("skipped"):
                    print(f"nfl {year} skipped {result.get('errors')}", flush=True)
                else:
                    print(
                        f"nfl {year} players {result['players']} weeks {result['weeks']} "
                        f"disabled {result['disabledWeeks']}",
                        flush=True,
                    )
            else:
                college.append(result)
                print(f"college {year} players {result['players']} skipped {result['skipped']}", flush=True)

    nfl.sort(key=lambda row: row["year"])
    college.sort(key=lambda row: row["year"])
    built_nfl = [row for row in nfl if not row.get("skipped")]
    catalog = {
        "nfl": {
            "defaultSeason": built_nfl[-1]["year"] if built_nfl else 2025,
            "seasons": [
                {
                    "year": row["year"],
                    "weeks": row["weeks"],
                    "disabledWeeks": row["disabledWeeks"],
                }
                for row in built_nfl
            ],
        },
        "college": {
            "defaultSeason": max(row["year"] for row in college if not row["skipped"]),
            "seasons": [row["year"] for row in college if not row["skipped"] and row["players"]],
        },
    }
    write_json(DATA / "catalog.json", catalog)
    write_sources(nfl, college)
    engine_year = catalog["nfl"]["defaultSeason"]
    try:
        eng = build_engine_support(engine_year)
        print(f"engine support {eng}", flush=True)
    except SystemExit as exc:
        print(f"engine support skipped: {exc}", flush=True)
    try:
        meta = build_player_meta(engine_year)
        print(f"player meta {meta}", flush=True)
    except SystemExit as exc:
        print(f"player meta skipped: {exc}", flush=True)
    try:
        from razzle.engine.snapshot import build_snapshot

        build_snapshot(ROOT / "data" / "engine", legacy_case3=False)
        print("engine screener snapshot rebuilt", flush=True)
    except Exception as exc:
        print(f"engine snapshot not rebuilt: {exc}", flush=True)

    other = next(row for row in built_nfl if row["year"] == 2018)
    week = other["weeks"][0]
    print(f"SANITY nfl {other['year']} season rows {other['players']}")
    print(f"SANITY nfl {other['year']} week {week} rows {other['weekRows'][str(week)]}")
    college_2020 = next(row for row in college if row["year"] == 2020)
    print(f"SANITY college 2020 rows {college_2020['players']}")
    print(f"SANITY college years {catalog['college']['seasons']}")
    print(f"SANITY nfl default {catalog['nfl']['defaultSeason']}")


if __name__ == "__main__":
    main()
