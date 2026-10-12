"""Construct engine input tables from workbook dumps or nflverse builds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from razzle.engine.config import EngineConfig, GutCall, PlayerKnobs, TeamSigmaOverride
from razzle.engine.fixtures import load_dump_bundle


POS = ("QB", "RB", "WR", "TE")
STRENGTH_SCALE = {
    "Very bad": -2.0,
    "Bad": -1.0,
    "Slightly worse": -0.5,
    "Neutral": 0.0,
    "Slightly better": 0.5,
    "Good": 1.0,
    "Very good": 2.0,
}


@dataclass
class PlayerRow:
    gsis_id: str
    name: str
    pos: str
    team: str
    games_26: float
    team_tgt_26: float
    team_car_26: float
    team_att_26: float
    tgt: float
    rec: float
    rec_yds: float
    rec_td: float
    car: float
    rush_yds: float
    rush_td: float
    pass_att: float
    pass_yds: float
    pass_td: float
    ints: float
    games_25: float
    team_tgt_25: float
    team_car_25: float
    team_att_25: float
    tgt_25: float
    rec_25: float
    rec_yds_25: float
    rec_td_25: float
    car_25: float
    rush_yds_25: float
    rush_td_25: float
    pass_att_25: float
    pass_yds_25: float
    pass_td_25: float
    ints_25: float
    knobs: PlayerKnobs | None = None


@dataclass
class TeamRow:
    code: str
    games: float
    pf: float
    pa: float
    pass_att: float
    sacks: float
    carries: float
    targets: float
    sos_off_25: float
    sos_def_25: float


@dataclass
class ScheduleRow:
    team: str
    week: int
    opponent: str
    home_sign: float
    game_id: str | None = None


@dataclass
class PositionPriors:
    catch_rate: float
    ypt: float
    ypc: float
    ypa: float
    rec_td_per_tgt: float
    rush_td_per_car: float
    pass_td_per_att: float
    int_per_att: float


@dataclass
class WorkbookBundle:
    controls: dict[str, Any]
    teams: list[TeamRow]
    players: list[PlayerRow]
    schedule: list[ScheduleRow]
    priors: dict[str, PositionPriors]
    gut_calls: list[GutCall]
    config: EngineConfig


def _f(cells: dict[str, Any], ref: str, default: float = 0.0) -> float:
    value = cells.get(ref)
    if value is None or value == "":
        return default
    return float(value)


def controls_from_cells(cells: dict[str, Any]) -> dict[str, Any]:
    """Flatten Controls sheet into a dict used by the pipeline."""
    out: dict[str, Any] = {}
    for ref, value in cells.items():
        out[ref] = value
    # Derived league mean (B32) is recomputed from team source in pipeline.
    return out


def load_workbook_bundle(
    dump_dir=None,
    *,
    case: int | None = None,
    legacy_houston_preset: bool = False,
) -> WorkbookBundle:
    """Load the saved workbook snapshot (406 players, 2026 W4 projection)."""
    dump = load_dump_bundle(dump_dir)
    c = dump["controls"]
    ps = dump["player_source"]
    ts = dump["team_source"]
    sch = dump["schedule"]
    gc = dump["gut_calls"]
    pi = dump["player_inputs"]
    tm = dump["teams"]

    workbook_case = int(c["B6"]) if case is None else case
    thesis_active = workbook_case == 1
    if workbook_case != 1:
        thesis_active = False

    team_overrides: list[TeamSigmaOverride] = []
    if legacy_houston_preset and workbook_case == 3:
        team_overrides.append(TeamSigmaOverride("HOU", defense_z=2.0))
    elif legacy_houston_preset and workbook_case == 4:
        team_overrides.append(TeamSigmaOverride("HOU", defense_z=-1.0))
    elif workbook_case == 1:
        for row in range(7, 39):
            team = ts[f"A{row}"]
            off = tm.get(f"P{row}")
            deff = tm.get(f"Q{row}")
            lean = tm.get(f"R{row}")
            if off not in (None, ""):
                team_overrides.append(TeamSigmaOverride(team, offense_z=float(off)))
            if deff not in (None, ""):
                team_overrides.append(TeamSigmaOverride(team, defense_z=float(deff)))
            if lean not in (None, ""):
                team_overrides.append(TeamSigmaOverride(team, pass_lean_z=float(lean)))

    gut_calls: list[GutCall] = []
    labels = {gc[f"B{r}"]: gc[f"C{r}"] for r in range(11, 18)}
    for row in range(21, 61):
        team = gc.get(f"B{row}")
        if not team:
            continue
        week_raw = gc.get(f"C{row}")
        week: int | str = "All" if week_raw == "All" else int(week_raw)
        factor = gc.get(f"D{row}")
        strength = gc.get(f"E{row}")
        points = gc.get(f"F{row}")
        gut_calls.append(
            GutCall(
                team=str(team),
                week=week,
                factor=str(factor),
                strength_label=str(strength) if strength else None,
                points=float(points) if isinstance(points, (int, float)) else None,
            )
        )

    players: list[PlayerRow] = []
    for row in range(7, 413):
        gsis = str(ps[f"A{row}"])
        knobs = PlayerKnobs(
            gsis_id=gsis,
            target_shift_z=float(pi.get(f"E{row}") or 0),
            rush_shift_z=float(pi.get(f"F{row}") or 0),
            rec_eff_z=float(pi.get(f"G{row}") or 0),
            rush_eff_z=float(pi.get(f"H{row}") or 0),
            pass_eff_z=float(pi.get(f"G{row}") or 0),
            availability=float(pi[f"I{row}"]) if pi.get(f"I{row}") not in (None, "") else None,
            cost_title_pp=float(pi[f"J{row}"]) if pi.get(f"J{row}") not in (None, "") else None,
        )
        players.append(
            PlayerRow(
                gsis_id=gsis,
                name=str(ps[f"B{row}"]),
                pos=str(ps[f"C{row}"]),
                team=str(ps[f"D{row}"]),
                games_26=_f(ps, f"E{row}"),
                team_tgt_26=_f(ps, f"F{row}"),
                team_car_26=_f(ps, f"G{row}"),
                team_att_26=_f(ps, f"H{row}"),
                tgt=_f(ps, f"I{row}"),
                rec=_f(ps, f"J{row}"),
                rec_yds=_f(ps, f"K{row}"),
                rec_td=_f(ps, f"L{row}"),
                car=_f(ps, f"M{row}"),
                rush_yds=_f(ps, f"N{row}"),
                rush_td=_f(ps, f"O{row}"),
                pass_att=_f(ps, f"P{row}"),
                pass_yds=_f(ps, f"Q{row}"),
                pass_td=_f(ps, f"R{row}"),
                ints=_f(ps, f"S{row}"),
                games_25=_f(ps, f"U{row}"),
                team_tgt_25=_f(ps, f"V{row}"),
                team_car_25=_f(ps, f"W{row}"),
                team_att_25=_f(ps, f"X{row}"),
                tgt_25=_f(ps, f"Y{row}"),
                rec_25=_f(ps, f"Z{row}"),
                rec_yds_25=_f(ps, f"AA{row}"),
                rec_td_25=_f(ps, f"AB{row}"),
                car_25=_f(ps, f"AC{row}"),
                rush_yds_25=_f(ps, f"AD{row}"),
                rush_td_25=_f(ps, f"AE{row}"),
                pass_att_25=_f(ps, f"AF{row}"),
                pass_yds_25=_f(ps, f"AG{row}"),
                pass_td_25=_f(ps, f"AH{row}"),
                ints_25=_f(ps, f"AI{row}"),
                knobs=knobs,
            )
        )

    priors: dict[str, PositionPriors] = {}
    for i, pos in enumerate(POS):
        r = 418 + i
        priors[pos] = PositionPriors(
            catch_rate=_f(ps, f"B{r}"),
            ypt=_f(ps, f"C{r}"),
            ypc=_f(ps, f"D{r}"),
            ypa=_f(ps, f"E{r}"),
            rec_td_per_tgt=_f(ps, f"F{r}"),
            rush_td_per_car=_f(ps, f"G{r}"),
            pass_td_per_att=_f(ps, f"H{r}"),
            int_per_att=_f(ps, f"I{r}"),
        )

    teams: list[TeamRow] = []
    for row in range(7, 39):
        teams.append(
            TeamRow(
                code=str(ts[f"A{row}"]),
                games=_f(ts, f"B{row}"),
                pf=_f(ts, f"C{row}"),
                pa=_f(ts, f"D{row}"),
                pass_att=_f(ts, f"E{row}"),
                sacks=_f(ts, f"F{row}"),
                carries=_f(ts, f"G{row}"),
                targets=_f(ts, f"H{row}"),
                sos_off_25=_f(ts, f"I{row}"),
                sos_def_25=_f(ts, f"J{row}"),
            )
        )

    schedule: list[ScheduleRow] = []
    for row in range(7, 455):
        schedule.append(
            ScheduleRow(
                team=str(sch[f"B{row}"]),
                week=int(sch[f"C{row}"]),
                opponent=str(sch[f"D{row}"]),
                home_sign=float(sch[f"E{row}"]),
                game_id=str(sch[f"F{row}"]) if sch.get(f"F{row}") else None,
            )
        )

    selected = None
    for player in players:
        if player.name == c.get("B8"):
            selected = player.gsis_id
            break

    config = EngineConfig(
        projection_week=int(c["B7"]),
        semifinal_week=int(c["B16"]),
        final_week=int(c["B17"]),
        thesis_active=thesis_active,
        simulation_draws=int(c["B18"]),
        simulation_seed=20261003,
        selected_player_gsis=selected,
        team_overrides=team_overrides,
        player_knobs=[p.knobs for p in players if p.knobs],
        gut_calls=gut_calls if thesis_active else [],
        clamp_default_rates=not legacy_houston_preset,
        honor_draw_count=True,
    )
    if legacy_houston_preset:
        config.clamp_default_rates = False

    return WorkbookBundle(
        controls=controls_from_cells(c),
        teams=teams,
        players=players,
        schedule=schedule,
        priors=priors,
        gut_calls=gut_calls,
        config=config,
    )
