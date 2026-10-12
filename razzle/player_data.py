"""Assemble player tear-sheet data from screener packs, engine, and Sleeper."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class PlayerSheetContext:
    kind: str  # nfl_skill | nfl_other | college | missing
    name: str
    pos: str = ""
    team: str = ""
    gsis_id: str = ""
    sleeper_id: str = ""
    season: int = 0
    bio: dict[str, Any] = field(default_factory=dict)
    engine_summary: dict[str, Any] | None = None
    engine_detail: dict[str, Any] | None = None
    season_stats: dict[str, Any] | None = None
    career_rows: list[dict[str, Any]] = field(default_factory=list)
    game_log: list[dict[str, Any]] = field(default_factory=list)
    weekly_chart: list[dict[str, Any]] = field(default_factory=list)
    season_chart: list[dict[str, Any]] = field(default_factory=list)
    comps: list[dict[str, Any]] = field(default_factory=list)
    league_owners: list[str] = field(default_factory=list)
    source_url: str = ""
    notes: list[str] = field(default_factory=list)


def _height_fmt(inches_raw: str | int | None) -> str:
    if inches_raw in (None, ""):
        return ""
    try:
        total = int(float(inches_raw))
    except (TypeError, ValueError):
        return str(inches_raw)
    feet, inches = divmod(total, 12)
    return f"{feet}'{inches}\""


def load_player_meta() -> dict[str, dict[str, Any]]:
    path = ROOT / "screener" / "data" / "nfl" / "player-meta.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload.get("players") or {}


def load_engine_details() -> dict[str, dict[str, Any]]:
    path = ROOT / "screener" / "data" / "engine" / "player-details.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload.get("players") or {}


def engine_comps(gsis: str, pos: str, index: dict[str, dict], summary: dict[str, dict], limit: int = 6) -> list[dict]:
    if gsis not in summary:
        return []
    target = summary[gsis].get("titleOddsPp")
    if target is None:
        return []
    peers = []
    for pid, row in summary.items():
        if row.get("pos") != pos or pid == gsis:
            continue
        val = row.get("titleOddsPp")
        if val is None:
            continue
        peers.append((abs(val - target), pid, row))
    peers.sort(key=lambda item: (item[0], item[2].get("name") or ""))
    out = []
    for _, pid, row in peers[:limit]:
        out.append(
            {
                "gsisId": pid,
                "name": row.get("name"),
                "team": row.get("team"),
                "titleOddsPp": row.get("titleOddsPp"),
                "ros": row.get("ros"),
            }
        )
    return out


def career_for_gsis(gsis: str, years: set[int], loader: Callable[[int], dict | None]) -> list[dict[str, Any]]:
    rows = []
    for year in sorted(years):
        pack = loader(year)
        if not pack:
            continue
        for player in pack.get("players") or []:
            if (player.get("gsisId") or "") == gsis:
                rows.append({"year": year, **player})
                break
    return rows


def game_log_for_gsis(gsis: str, year: int, week_loader: Callable[[int], dict | None]) -> list[dict[str, Any]]:
    pack = week_loader(year)
    if not pack:
        return []
    weeks = pack.get("weeks") or {}
    log = []
    for week in sorted(weeks, key=lambda w: int(w)):
        for row in weeks[week]:
            if (row.get("gsisId") or "") == gsis:
                log.append({"week": int(week), **row})
    log.sort(key=lambda r: r["week"])
    return log


def weekly_actuals_chart(game_log: list[dict], engine_weekly: list[dict] | None, projection_week: int) -> list[dict]:
    eng_by_week = {row["week"]: row for row in (engine_weekly or [])}
    points = []
    for row in game_log:
        wk = row["week"]
        eng = eng_by_week.get(wk) or {}
        points.append(
            {
                "week": wk,
                "actual": row.get("ppr"),
                "proj": eng.get("mean"),
                "sd": eng.get("sd"),
                "forecast": wk >= projection_week,
            }
        )
    return points


def league_roster_owners(gsis: str, sleeper_id: str, snapshot: dict | None, names: dict | None) -> list[str]:
    if not snapshot:
        return []
    owners = []
    for team in snapshot.get("teams") or []:
        label = team.get("label") or f"Roster {team.get('roster_id')}"
        for entry in (team.get("starters") or []) + (team.get("bench") or []):
            pid, name = entry if isinstance(entry, tuple) else (None, str(entry))
            if sleeper_id and pid and str(pid) == str(sleeper_id):
                owners.append(label)
                break
            if gsis and names:
                # names only by id — gsis match needs sleeper index
                pass
    return owners


def percentile_rank(value: float | None, population: list[float]) -> int | None:
    if value is None or not population:
        return None
    below = sum(1 for v in population if v < value)
    return int(round(100 * below / len(population)))
