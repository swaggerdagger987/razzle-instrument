"""Write compact engine outputs for the static app and screener."""

from __future__ import annotations

import json
from pathlib import Path

from razzle.engine.core import run_engine
from razzle.engine.workbook import load_workbook_bundle


def build_snapshot(out_dir: Path, *, legacy_case3: bool = True) -> dict:
    bundle = load_workbook_bundle(legacy_houston_preset=legacy_case3)
    if not legacy_case3:
        from razzle.engine.config import TeamSigmaOverride

        bundle.config.team_overrides = [TeamSigmaOverride("HOU", defense_z=2.0)]
        bundle.config.thesis_active = True
        bundle.config.clamp_default_rates = True
    result = run_engine(bundle)
    wk = bundle.config.projection_week
    players_out = {}
    for prow in bundle.players:
        scr = result.screener[prow.gsis_id]
        players_out[prow.gsis_id] = {
            "gsisId": prow.gsis_id,
            "name": prow.name,
            "pos": prow.pos,
            "team": prow.team,
            "proj": round(scr.thesis_pts, 4),
            "projDefault": round(scr.default_pts, 4),
            "sd": round(scr.thesis_sd, 4),
            "ros": round(scr.ros_thesis, 4),
            "rosDefault": round(scr.ros_default, 4),
            "titleOddsPp": round(scr.title_odds_pp, 4),
            "titleOddsPpDefault": round(scr.default_title_odds_pp, 4),
            "thesisVsDefaultPp": round(scr.thesis_vs_default_pp, 4),
        }
    selected = bundle.config.selected_player_gsis
    sim = result.simulation
    meta = {
        "projectionWeek": wk,
        "season": 2026,
        "scoring": "ppr",
        "playerCount": len(players_out),
        "selectedPlayerGsis": selected,
        "deviations": [
            "Basis-0 rates are clamped like thesis (fixes negative YPC edge cases).",
            "Cases 3/4 HOU presets removed; use team σ overrides instead.",
            "Simulation draw count controls trial N (workbook B18 was divisor-only).",
            "Pipeline keyed by gsis/team id, not sheet row order.",
        ],
    }
    odds = {
        "bracket": "four_team_sandbox",
        "analyticTitleOdds": round(result.screener[selected].analytic_title_odds, 6) if selected else None,
        "simulatedTitleOdds": round(sim.thesis_wins / sim.draws, 6) if sim else None,
        "contributionPp": round(sim.contribution_pp, 4) if sim else None,
        "pairedSePp": round(sim.paired_se_pp, 6) if sim else None,
        "titleShares": sim.title_shares if sim else {},
        "draws": sim.draws if sim else 0,
        "note": "Four-team fixed bracket (not league Sleeper odds). Full-league Monte Carlo plugs in later.",
    }
    payload = {"meta": meta, "players": players_out, "odds": odds}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "screener.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main():
    root = Path(__file__).resolve().parents[2]
    out = root / "screener" / "data" / "engine"
    build_snapshot(out, legacy_case3=False)
    print(f"wrote {out / 'screener.json'}", flush=True)


if __name__ == "__main__":
    main()
