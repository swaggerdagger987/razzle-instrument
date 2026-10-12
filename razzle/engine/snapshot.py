"""Write compact engine outputs for the static app and screener."""

from __future__ import annotations

import json
from pathlib import Path

import math

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
    details = build_player_details(result, bundle)
    (out_dir / "player-details.json").write_text(json.dumps(details, indent=2) + "\n", encoding="utf-8")
    return payload


def build_player_details(result, bundle) -> dict:
    """Per-player weekly projections, valuation breakdown, schedule, usage shares."""
    wk_sel = bundle.config.projection_week
    pos_pop = {pos: {"tgt_share": [], "rush_share": [], "ros": []} for pos in ("QB", "RB", "WR", "TE")}
    for prow in bundle.players:
        pc = result.players[prow.gsis_id]
        pos_pop[prow.pos]["tgt_share"].append(pc.act["tgt"])
        pos_pop[prow.pos]["rush_share"].append(pc.act["rush"])
        pos_pop[prow.pos]["ros"].append(result.screener[prow.gsis_id].ros_thesis)

    sched_by_team: dict[str, list] = {}
    for row in bundle.schedule:
        sched_by_team.setdefault(row.team, []).append(row)

    players_detail = {}
    for prow in bundle.players:
        gsis = prow.gsis_id
        pc = result.players[gsis]
        scr = result.screener[gsis]
        weekly_rows = []
        for week in range(4, 18):
            d = result.weekly[(gsis, week, 1)]
            ge = result.game_engine[(prow.team, week, 1)]
            sig = 0.0 if d.opponent == "BYE" else max(0.0, pc.sd_a + pc.sd_b * d.mean)
            sd_mix = math.sqrt(d.avail * sig**2 + d.avail * (1 - d.avail) * d.mean**2) if d.opponent != "BYE" else 0.0
            weekly_rows.append(
                {
                    "week": week,
                    "mean": round(d.mean, 4),
                    "expected": round(d.expected_pts, 4),
                    "sd": round(sd_mix, 4),
                    "floor": round(max(0.0, d.mean - sd_mix), 4),
                    "ceiling": round(d.mean + sd_mix, 4),
                    "weight": round(d.weight, 4),
                    "opp": d.opponent,
                    "bye": d.opponent == "BYE",
                    "teamPts": round(ge["M"], 4),
                    "yardsMult": round(ge["W"], 4),
                    "tdMult": round(ge["X"], 4),
                    "recFp": round(d.rec_fp, 4),
                    "rushFp": round(d.rush_fp, 4),
                    "passFp": round(d.pass_fp, 4),
                }
            )
        sel = result.weekly[(gsis, wk_sel, 1)]
        sel_ge = result.game_engine[(prow.team, wk_sel, 1)]
        breakdown = {
            "week": wk_sel,
            "recFp": round(sel.rec_fp, 4),
            "rushFp": round(sel.rush_fp, 4),
            "passFp": round(sel.pass_fp, 4),
            "mean": round(sel.mean, 4),
            "teamExpectedPts": round(sel_ge["M"], 4),
            "matchupYardsMult": round(sel_ge["W"], 4),
            "matchupTdMult": round(sel_ge["X"], 4),
            "dropbacks": round(sel_ge["S"], 4),
            "carries": round(sel_ge["T"], 4),
            "targets": round(sel_ge["U"], 4),
            "tgtShare": round(pc.act["tgt"], 4),
            "rushShare": round(pc.act["rush"], 4),
            "catchRate": round(pc.rates["catch"], 4),
            "ypt": round(pc.act["ypt"], 4),
            "ypc": round(pc.act["ypc"], 4),
            "ypa": round(pc.act["ypa"], 4),
            "availability": round(pc.avail, 4),
        }
        upcoming = [r for r in weekly_rows if r["week"] >= wk_sel and not r["bye"]]
        players_detail[gsis] = {
            "weekly": weekly_rows,
            "breakdown": breakdown,
            "upcoming": upcoming,
            "avail": round(pc.avail, 4),
            "percentiles": {
                "tgtShare": _pct(pc.act["tgt"], pos_pop[prow.pos]["tgt_share"]),
                "rushShare": _pct(pc.act["rush"], pos_pop[prow.pos]["rush_share"]),
                "ros": _pct(scr.ros_thesis, pos_pop[prow.pos]["ros"]),
            },
        }
    return {"meta": {"projectionWeek": wk_sel, "season": 2026}, "players": players_detail}


def _pct(value: float, population: list[float]) -> int | None:
    if not population:
        return None
    below = sum(1 for v in population if v < value)
    return int(round(100 * below / len(population)))


def main():
    root = Path(__file__).resolve().parents[2]
    out = root / "screener" / "data" / "engine"
    build_snapshot(out, legacy_case3=False)
    print(f"wrote {out / 'screener.json'}", flush=True)


if __name__ == "__main__":
    main()
