#!/usr/bin/env python3
"""Build compact screener JSON from public nflverse and sportsdataverse files.

No API key. Counting stats are copied. Derived fields are PPR, PPG, and
total touchdowns. A category with no source row is omitted, not filled with 0.
"""

import csv
import gzip
import io
import json
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

NFL_STATS = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_2025.csv.gz"
NFL_ROSTER = "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2025.csv"
CFB_PASS = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_2026.csv"
CFB_RUSH = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_2026.csv"
CFB_REC = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_2026.csv"
CFB_ROSTER = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_2026.csv.gz"

SKILL = ("QB", "RB", "WR", "TE")
AGE_ON = date(2025, 9, 1)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "razzle-screener-build"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
    if url.endswith(".gz"):
        raw = gzip.decompress(raw)
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


def num(value):
    if value is None or value == "":
        return None
    return float(value)


def whole(value):
    n = num(value)
    if n is None:
        return None
    return int(round(n))


def age_on(birth, on):
    year, month, day = (int(part) for part in birth.split("-"))
    born = date(year, month, day)
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def ppr(row):
    """Standard PPR from counting stats. Matches nflverse fantasy_points_ppr."""
    fumbles = (
        num(row["sack_fumbles_lost"])
        + num(row["rushing_fumbles_lost"])
        + num(row["receiving_fumbles_lost"])
    )
    points = (
        num(row["passing_yards"]) * 0.04
        + num(row["passing_tds"]) * 4
        + num(row["passing_interceptions"]) * -2
        + num(row["rushing_yards"]) * 0.1
        + num(row["rushing_tds"]) * 6
        + num(row["receptions"]) * 1
        + num(row["receiving_yards"]) * 0.1
        + num(row["receiving_tds"]) * 6
        + num(row["special_teams_tds"]) * 6
        + num(row["passing_2pt_conversions"]) * 2
        + num(row["rushing_2pt_conversions"]) * 2
        + num(row["receiving_2pt_conversions"]) * 2
        + fumbles * -2
    )
    return round(points + 1e-9, 1)


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def build_nfl():
    stats = fetch(NFL_STATS)
    roster = fetch(NFL_ROSTER)
    birth = {}
    for row in roster:
        gsis = row.get("gsis_id") or ""
        born = row.get("birth_date") or ""
        if gsis and born and gsis not in birth:
            birth[gsis] = born

    players = []
    for row in stats:
        pos = row.get("position") or ""
        if pos not in SKILL:
            continue
        games = whole(row["games"])
        points = ppr(row)
        published = round(num(row["fantasy_points_ppr"]) + 1e-9, 1)
        if points != published:
            raise SystemExit(
                f"PPR mismatch for {row['player_display_name']}: {points} vs {published}"
            )
        player = {
            "name": row["player_display_name"],
            "team": row["recent_team"],
            "pos": pos,
            "gp": games,
            "ppr": points,
            "py": whole(row["passing_yards"]),
            "ptd": whole(row["passing_tds"]),
            "ry": whole(row["rushing_yards"]),
            "rtd": whole(row["rushing_tds"]),
            "rec": whole(row["receptions"]),
            "rey": whole(row["receiving_yards"]),
            "retd": whole(row["receiving_tds"]),
            "tgt": whole(row["targets"]),
            "td": whole(row["passing_tds"]) + whole(row["rushing_tds"]) + whole(row["receiving_tds"]),
        }
        if games:
            player["ppg"] = round(num(row["fantasy_points_ppr"]) / games + 1e-9, 1)
        born = birth.get(row["player_id"])
        if born:
            player["age"] = age_on(born, AGE_ON)
        players.append(player)

    players.sort(key=lambda p: (-(p["ppr"]), p["name"]))
    write_json(
        DATA / "nfl.json",
        {
            "universe": "nfl",
            "season": 2025,
            "seasonType": "REG",
            "source": NFL_STATS,
            "players": players,
        },
    )
    return len(players)


def build_college():
    passing = {row["player_id"]: row for row in fetch(CFB_PASS)}
    rushing = {row["player_id"]: row for row in fetch(CFB_RUSH)}
    receiving = {row["player_id"]: row for row in fetch(CFB_REC)}
    roster = {}
    for row in fetch(CFB_ROSTER):
        roster[row["athlete_id"]] = row

    players = []
    for player_id in set(passing) | set(rushing) | set(receiving):
        parts = [table[player_id] for table in (passing, rushing, receiving) if player_id in table]
        stat_pos = next(
            (row["position_group"] for row in parts if row.get("position_group") in SKILL),
            "",
        )
        roster_row = roster.get(player_id)
        roster_pos = (roster_row or {}).get("position_abbreviation") or ""
        if roster_pos in SKILL:
            pos = roster_pos
        elif not roster_row and stat_pos in SKILL:
            pos = stat_pos
        else:
            continue

        home = max(parts, key=lambda row: whole(row.get("plays")) or 0)
        name = home.get("passer_player_name") or home.get("rusher_player_name") or home.get("receiver_player_name")
        if roster_row and roster_row.get("full_name"):
            name = roster_row["full_name"]
        if not name:
            continue

        player = {
            "name": name,
            "team": home.get("pos_team") or "",
            "conference": home.get("conference") or "",
            "pos": pos,
            "gp": max(whole(row.get("games")) or 0 for row in parts),
        }
        if player_id in passing:
            player["py"] = whole(passing[player_id]["yards"])
            player["ptd"] = whole(passing[player_id]["passing_td"])
        if player_id in rushing:
            player["ry"] = whole(rushing[player_id]["yards"])
            player["rtd"] = whole(rushing[player_id]["rushing_td"])
        if player_id in receiving:
            # The receiving file names the score column passing_td. It is the
            # receiving touchdown count for that player.
            player["rey"] = whole(receiving[player_id]["yards"])
            player["retd"] = whole(receiving[player_id]["passing_td"])

        yards = [player[key] for key in ("py", "ry", "rey") if key in player]
        tds = [player[key] for key in ("ptd", "rtd", "retd") if key in player]
        if yards:
            player["ty"] = sum(yards)
        if tds:
            player["td"] = sum(tds)
        players.append(player)

    players.sort(key=lambda p: (-(p.get("ty") or 0), p["name"]))
    write_json(
        DATA / "college.json",
        {
            "universe": "college",
            "season": 2026,
            "source": [CFB_PASS, CFB_RUSH, CFB_REC, CFB_ROSTER],
            "players": players,
        },
    )
    return len(players)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    nfl_n = build_nfl()
    college_n = build_college()
    print(f"nfl {nfl_n}")
    print(f"college {college_n}")


if __name__ == "__main__":
    main()
