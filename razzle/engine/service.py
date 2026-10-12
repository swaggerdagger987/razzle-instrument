"""Cached workbook bundle + user thesis overlays for the HTTP app."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from razzle.engine.config import EngineConfig, GutCall, TeamSigmaOverride
from razzle.engine.core import EngineResult, run_engine
from razzle.engine.workbook import WorkbookBundle, load_workbook_bundle

_LOCK = threading.Lock()
_BUNDLE: WorkbookBundle | None = None
_SNAPSHOT: dict | None = None


def get_workbook_bundle() -> WorkbookBundle:
    global _BUNDLE
    with _LOCK:
        if _BUNDLE is None:
            bundle = load_workbook_bundle(legacy_houston_preset=False)
            bundle.config.clamp_default_rates = True
            bundle.config.thesis_active = True
            _BUNDLE = bundle
        return _BUNDLE


def load_static_snapshot(root: Path) -> dict | None:
    global _SNAPSHOT
    path = root / "screener" / "data" / "engine" / "screener.json"
    if not path.is_file():
        return None
    with _LOCK:
        if _SNAPSHOT is None:
            _SNAPSHOT = json.loads(path.read_text(encoding="utf-8"))
        return _SNAPSHOT


def config_from_form(form: dict) -> EngineConfig:
    bundle = get_workbook_bundle()
    config = EngineConfig(
        projection_week=bundle.config.projection_week,
        semifinal_week=bundle.config.semifinal_week,
        final_week=bundle.config.final_week,
        thesis_active=True,
        simulation_draws=int(form.get("draws") or bundle.config.simulation_draws),
        simulation_seed=bundle.config.simulation_seed,
        selected_player_gsis=bundle.config.selected_player_gsis,
        player_knobs=bundle.config.player_knobs,
        clamp_default_rates=True,
        honor_draw_count=True,
        team_overrides=[],
        gut_calls=[],
    )
    team = (form.get("team") or "").strip().upper()
    if team:
        def f(key):
            raw = (form.get(key) or "").strip()
            if not raw:
                return None
            return float(raw)

        config.team_overrides.append(
            TeamSigmaOverride(
                team,
                offense_z=f("off_z"),
                defense_z=f("def_z"),
                pass_lean_z=f("pass_z"),
            )
        )
    gut_team = (form.get("gut_team") or "").strip().upper()
    gut_week = (form.get("gut_week") or "").strip()
    gut_factor = (form.get("gut_factor") or "").strip()
    gut_strength = (form.get("gut_strength") or "").strip()
    if gut_team and gut_factor:
        week: int | str = "All" if gut_week == "All" or not gut_week else int(gut_week)
        config.gut_calls.append(
            GutCall(
                team=gut_team,
                week=week,
                factor=gut_factor,
                strength_label=gut_strength or "Neutral",
            )
        )
    sel = (form.get("player_gsis") or "").strip()
    if sel:
        config.selected_player_gsis = sel
    return config


def run_with_config(config: EngineConfig) -> EngineResult:
    bundle = get_workbook_bundle()
    return run_engine(bundle, config)


def engine_player_row(result: EngineResult, gsis: str) -> dict | None:
    if gsis not in result.screener:
        return None
    scr = result.screener[gsis]
    player = result.players[gsis]
    wk = result.config.projection_week
    w = result.weekly[(gsis, wk, 1)]
    return {
        "proj": scr.thesis_pts,
        "projDefault": scr.default_pts,
        "sd": scr.thesis_sd,
        "ros": scr.ros_thesis,
        "rosDefault": scr.ros_default,
        "titleOddsPp": scr.title_odds_pp,
        "titleOddsPpDefault": scr.default_title_odds_pp,
        "weeklyMean": w.mean,
        "weeklyOpp": w.opponent,
        "name": player.name,
        "pos": player.pos,
        "team": player.team,
    }
