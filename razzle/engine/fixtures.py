"""Load streamed Excel cell dumps (value tab-separated lines)."""

from __future__ import annotations

import os
import re
from pathlib import Path


def default_dump_dir() -> Path:
    env = os.environ.get("RAZZLE_ENGINE_DUMP")
    if env:
        return Path(env)
    root = Path(__file__).resolve().parents[2]
    direct = root / "tests" / "fixtures" / "engine_dump"
    if direct.is_dir():
        return direct
    archive = root / "tests" / "fixtures" / "engine_dump.tar.gz"
    if archive.is_file():
        import tarfile

        extract_to = root / "tests" / "fixtures"
        nested = extract_to / "dump" / "s08_Controls.txt"
        flat = extract_to / "engine_dump" / "s08_Controls.txt"
        if not nested.is_file() and not flat.is_file():
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(path=extract_to, filter="data")
        if nested.is_file():
            return extract_to / "dump"
        if flat.is_file():
            return extract_to / "engine_dump"
    legacy = root / "razzle-val" / "dump"
    return legacy


def load_sheet_cells(path: Path) -> dict[str, object]:
    cells: dict[str, object] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("####"):
                break
            if line.startswith("DV "):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3 or not re.match(r"^[A-Z]+\d+$", parts[0]):
                continue
            try:
                value = eval(parts[2])  # noqa: S307 — fixture literals only
            except Exception:
                value = None
            if isinstance(value, str):
                try:
                    value = float(value)
                except ValueError:
                    pass
            cells[parts[0]] = value
    return cells


def load_dump_bundle(dump_dir: Path | None = None) -> dict[str, dict[str, object]]:
    base = dump_dir or default_dump_dir()
    names = {
        "controls": "s08_Controls.txt",
        "team_source": "s18_Team_source.txt",
        "player_source": "s17_Player_source.txt",
        "schedule": "s19_Schedule.txt",
        "gut_calls": "s09_Gut_calls.txt",
        "player_inputs": "s12_Player_inputs.txt",
        "game_engine": "s14_Game_engine.txt",
        "weekly_value": "s13_Weekly_value.txt",
        "screener": "s07_Screener.txt",
        "teams": "s11_Teams.txt",
        "odds_sandbox": "s15_Odds_sandbox.txt",
        "simulation": "s16_Simulation.txt",
    }
    return {key: load_sheet_cells(base / fname) for key, fname in names.items()}
