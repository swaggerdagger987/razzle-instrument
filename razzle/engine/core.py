"""Valuation pipeline: teams → players → game engine → weekly value → screener → odds."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import stdev
from typing import Any

from razzle.engine.config import EngineConfig, GutCall, TeamSigmaOverride
from razzle.engine.workbook import (
    POS,
    PlayerRow,
    PositionPriors,
    ScheduleRow,
    STRENGTH_SCALE,
    TeamRow,
    WorkbookBundle,
)


def phi(z: float) -> float:
    return 0.5 * math.erfc(-z / math.sqrt(2))


@dataclass
class PlayerComputed:
    gsis_id: str
    name: str
    pos: str
    team: str
    base: dict[str, float]
    act: dict[str, float]
    rates: dict[str, float]
    avail: float
    cost_pp: float | None
    sd_a: float
    sd_b: float
    repl_sd: float


@dataclass
class WeeklyRow:
    rec_fp: float
    rush_fp: float
    pass_fp: float
    mean: float
    avail: float
    replacement: float
    weight: float
    weighted_par: float
    expected_pts: float
    opponent: str


@dataclass
class ScreenerRow:
    default_pts: float
    thesis_pts: float
    thesis_sd: float
    ros_default: float
    ros_thesis: float
    title_odds_pp: float
    default_title_odds_pp: float
    thesis_vs_default_pp: float
    playoff_slot_semi_mean: float
    playoff_slot_semi_sd: float
    playoff_slot_final_mean: float
    playoff_slot_final_sd: float
    analytic_title_odds: float
    analytic_title_odds_repl: float
    analytic_title_odds_default: float


@dataclass
class SimulationResult:
    draws: int
    thesis_wins: int
    default_wins: int
    repl_wins: int
    title_shares: dict[str, int]
    paired_se_pp: float
    contribution_pp: float


@dataclass
class EngineResult:
    config: EngineConfig
    players: dict[str, PlayerComputed]
    screener: dict[str, ScreenerRow]
    weekly: dict[tuple[str, int, int], WeeklyRow]
    game_engine: dict[tuple[str, int, int], dict[str, float]]
    simulation: SimulationResult | None
    selected_gsis: str | None


def _ctl(controls: dict[str, Any], col: str, pos: str) -> float:
    posrow = {p: 25 + i for i, p in enumerate(POS)}
    return float(controls[f"{col}{posrow[pos]}"])


def _gut_sigma(gut: GutCall, controls: dict[str, Any]) -> float:
    if gut.points is not None and gut.factor != "Pass lean":
        denom = float(controls["B35"]) if gut.factor == "Defense" else float(controls["B34"])
        return gut.points / denom
    if gut.strength_label and gut.strength_label in STRENGTH_SCALE:
        return STRENGTH_SCALE[gut.strength_label]
    return 0.0


def _team_override_map(overrides: list[TeamSigmaOverride]) -> dict[str, TeamSigmaOverride]:
    merged: dict[str, TeamSigmaOverride] = {}
    for item in overrides:
        prev = merged.get(item.team)
        if prev is None:
            merged[item.team] = TeamSigmaOverride(item.team, item.offense_z, item.defense_z, item.pass_lean_z)
        else:
            merged[item.team] = TeamSigmaOverride(
                item.team,
                item.offense_z if item.offense_z is not None else prev.offense_z,
                item.defense_z if item.defense_z is not None else prev.defense_z,
                item.pass_lean_z if item.pass_lean_z is not None else prev.pass_lean_z,
            )
    return merged


def _gut_sums(gut_calls: list[GutCall], controls: dict[str, Any]) -> dict[tuple[str, int | str, str], float]:
    out: dict[tuple[str, int | str, str], float] = {}
    for call in gut_calls:
        sigma = _gut_sigma(call, controls)
        key = (call.team, call.week, call.factor)
        out[key] = out.get(key, 0.0) + sigma
    return out


def _sum_gut(
    gut_index: dict[tuple[str, int | str, str], float],
    team: str,
    week: int,
    factor: str,
) -> float:
    total = gut_index.get((team, week, factor), 0.0)
    total += gut_index.get((team, "All", factor), 0.0)
    return total


def _build_teams(
    bundle: WorkbookBundle,
    config: EngineConfig,
    controls: dict[str, Any],
) -> dict[str, dict[str, float]]:
    teams = {row.code: row for row in bundle.teams}
    mu = sum(row.pf for row in bundle.teams) / sum(row.games for row in bundle.teams)
    lg_db = (
        sum(row.pass_att + row.sacks for row in bundle.teams) / sum(row.games for row in bundle.teams)
    )
    lg_car = sum(row.carries for row in bundle.teams) / sum(row.games for row in bundle.teams)
    lg_pr = lg_db / (lg_db + lg_car)
    overrides = _team_override_map(config.team_overrides)
    out: dict[str, dict[str, float]] = {}
    for row in bundle.teams:
        t = row.code
        g = row.games
        pf, pa = row.pf / g, row.pa / g
        margin = pf - pa
        db = (row.pass_att + row.sacks) / g
        car = row.carries / g
        tgt_db = row.targets / (row.pass_att + row.sacks) if (row.pass_att + row.sacks) else 0.0
        k = float(controls["B51"])
        ndb = (g * (db + float(controls["B49"]) * margin) + k * lg_db) / (g + k)
        ncar = (g * (car + float(controls["B50"]) * margin) + k * lg_car) / (g + k)
        npr = ndb / (ndb + ncar) if (ndb + ncar) else 0.0
        d_off = float(controls["B58"]) + float(controls["B59"]) * row.sos_off_25 + float(controls["B60"]) * (pf - mu)
        d_def = float(controls["B61"]) + float(controls["B62"]) * row.sos_def_25 + float(controls["B63"]) * (pa - mu)
        z_off = d_off / float(controls["B34"])
        z_def = -d_def / float(controls["B35"])
        z_pass = (npr - lg_pr) / float(controls["B36"])
        ov = overrides.get(t)
        if ov:
            a_off = ov.offense_z if ov.offense_z is not None else z_off
            a_def = ov.defense_z if ov.defense_z is not None else z_def
            a_pass = ov.pass_lean_z if ov.pass_lean_z is not None else z_pass
        else:
            a_off, a_def, a_pass = z_off, z_def, z_pass
        out[t] = {
            "mu": mu,
            "pf": pf,
            "pa": pa,
            "margin": margin,
            "tgt_db": tgt_db,
            "d_off": d_off,
            "d_def": d_def,
            "z_off": z_off,
            "z_def": z_def,
            "z_pass": z_pass,
            "a_off": a_off * float(controls["B34"]),
            "a_def": -a_def * float(controls["B35"]),
            "npr": npr,
            "apr": max(0.0, min(1.0, lg_pr + a_pass * float(controls["B36"]))),
            "ndb": ndb,
            "ncar": ncar,
            "lg_pr": lg_pr,
        }
    return out


def _player_inputs(
    bundle: WorkbookBundle,
    config: EngineConfig,
    controls: dict[str, Any],
) -> dict[str, PlayerComputed]:
    pri = bundle.priors
    knob_by_id = {k.gsis_id: k for k in config.player_knobs}
    out: dict[str, PlayerComputed] = {}
    for row in bundle.players:
        pr = pri[row.pos]
        k_role = float(controls["B57"])
        e = row.games_26
        l_ = 0.0 if row.team_tgt_26 == 0 else row.tgt / row.team_tgt_26
        m_ = l_ if row.tgt_25 == 0 else row.tgt_25 / row.team_tgt_25
        n_ = (l_ * e + m_ * k_role) / (e + k_role) if (e + k_role) else 0.0
        o_ = 0.0 if row.team_car_26 == 0 else row.car / row.team_car_26
        p_ = o_ if row.car_25 == 0 else row.car_25 / row.team_car_25
        q_ = (o_ * e + p_ * k_role) / (e + k_role) if (e + k_role) else 0.0
        r_qb = 0.0 if (row.pos != "QB" or row.team_att_26 == 0) else row.pass_att / row.team_att_26
        s_ = (row.rec + float(controls["B52"]) * (row.rec_25 / row.tgt_25 if row.tgt_25 > 0 else pr.catch_rate)) / (
            row.tgt + float(controls["B52"])
        )
        t_ = (row.rec_yds + float(controls["B52"]) * (row.rec_yds_25 / row.tgt_25 if row.tgt_25 > 0 else pr.ypt)) / (
            row.tgt + float(controls["B52"])
        )
        u_ = (row.rush_yds + float(controls["B53"]) * (row.rush_yds_25 / row.car_25 if row.car_25 > 0 else pr.ypc)) / (
            row.car + float(controls["B53"])
        )
        v_ = (row.pass_yds + float(controls["B55"]) * (row.pass_yds_25 / row.pass_att_25 if row.pass_att_25 > 0 else pr.ypa)) / (
            row.pass_att + float(controls["B55"])
        )
        w_ = (row.rec_td + float(controls["B54"]) * pr.rec_td_per_tgt) / (row.tgt + float(controls["B54"]))
        x_ = (
            pr.rush_td_per_car
            if row.pos == "QB"
            else (row.rush_td + float(controls["B54"]) * pr.rush_td_per_car) / (row.car + float(controls["B54"]))
        )
        y_ = (row.pass_td + float(controls["B56"]) * pr.pass_td_per_att) / (row.pass_att + float(controls["B56"]))
        z_ = (row.ints + float(controls["B56"]) * pr.int_per_att) / (row.pass_att + float(controls["B56"]))
        knobs = knob_by_id.get(row.gsis_id) or row.knobs
        on = config.thesis_active
        aa = max(0.0, min(1.0, n_ + (knobs.target_shift_z * _ctl(controls, "I", row.pos) if on else 0.0)))
        ab = max(0.0, min(1.0, q_ + (knobs.rush_shift_z * _ctl(controls, "J", row.pos) if on else 0.0)))
        ac = max(0.0, t_ + (knobs.rec_eff_z * _ctl(controls, "K", row.pos) if on else 0.0))
        ad = max(0.0, u_ + (knobs.rush_eff_z * _ctl(controls, "L", row.pos) if on else 0.0))
        ae = max(0.0, v_ + (knobs.pass_eff_z * _ctl(controls, "M", row.pos) if on else 0.0))
        if on and knobs.availability is not None:
            avail = knobs.availability
        elif on:
            avail = 1.0
        else:
            avail = 1.0
        base = {"tgt": n_, "rush": q_, "ypt": t_, "ypc": u_, "ypa": v_}
        act = {"tgt": aa, "rush": ab, "ypt": ac, "ypc": ad, "ypa": ae}
        if config.clamp_default_rates:
            base = {
                "tgt": max(0.0, min(1.0, base["tgt"])),
                "rush": max(0.0, min(1.0, base["rush"])),
                "ypt": max(0.0, base["ypt"]),
                "ypc": max(0.0, base["ypc"]),
                "ypa": max(0.0, base["ypa"]),
            }
        out[row.gsis_id] = PlayerComputed(
            gsis_id=row.gsis_id,
            name=row.name,
            pos=row.pos,
            team=row.team,
            base=base,
            act=act,
            rates={"catch": s_, "ypt": t_, "ypc": u_, "ypa": v_, "rec_td": w_, "rush_td": x_, "pass_td": y_, "int": z_, "qb_share": r_qb},
            avail=avail,
            cost_pp=knobs.cost_title_pp,
            sd_a=_ctl(controls, "N", row.pos),
            sd_b=_ctl(controls, "O", row.pos),
            repl_sd=_ctl(controls, "P", row.pos),
        )
    return out


def _game_engine(
    bundle: WorkbookBundle,
    config: EngineConfig,
    controls: dict[str, Any],
    teams: dict[str, dict[str, float]],
    gut_index: dict[tuple[str, int | str, str], float],
) -> dict[tuple[str, int, int], dict[str, float]]:
    mu = next(iter(teams.values()))["mu"]
    ge: dict[tuple[str, int, int], dict[str, float]] = {}
    for basis in (0, 1):
        for sched in bundle.schedule:
            t, w, opp, hs = sched.team, sched.week, sched.opponent, sched.home_sign
            bye = opp == "BYE"
            o = t if bye else opp
            live = basis == 1 and config.thesis_active
            gut_off = _sum_gut(gut_index, t, w, "Offense") if live else 0.0
            gut_def = _sum_gut(gut_index, t, w, "Defense") if live else 0.0
            gut_off_o = _sum_gut(gut_index, o, w, "Offense") if live and not bye else 0.0
            gut_def_o = _sum_gut(gut_index, o, w, "Defense") if live and not bye else 0.0
            gut_pass = _sum_gut(gut_index, t, w, "Pass lean") if live else 0.0
            tt, ot = teams[t], teams[o]
            i_val = tt["d_off"] if basis == 0 else tt["a_off"] + gut_off * float(controls["B34"])
            j_val = tt["d_def"] if basis == 0 else tt["a_def"] - gut_def * float(controls["B35"])
            k_val = ot["d_off"] if basis == 0 else ot["a_off"] + gut_off_o * float(controls["B34"])
            l_val = ot["d_def"] if basis == 0 else ot["a_def"] - gut_def_o * float(controls["B35"])
            m_pts = 0.0 if bye else max(0.0, mu + i_val + l_val + hs * float(controls["B33"]) + float(controls["B43"]) * (tt["d_def"] - j_val))
            n_pts = 0.0 if bye else max(0.0, mu + k_val + j_val - hs * float(controls["B33"]) + float(controls["B43"]) * (ot["d_def"] - l_val))
            margin = m_pts - n_pts
            total = m_pts + n_pts
            q_extra = float(controls["B41"]) * l_val + float(controls["B42"]) * (i_val - tt["d_off"])
            pass_xfer = 0.0
            if basis == 1:
                pr_t = max(0.0, min(1.0, tt["apr"] + gut_pass * float(controls["B36"])))
                pass_xfer = (pr_t - tt["npr"]) * (tt["ndb"] + tt["ncar"])
            dropbacks = 0.0 if bye else max(
                0.0,
                tt["ndb"]
                + float(controls["B37"]) * margin
                + float(controls["B39"]) * (total - 2 * mu)
                + tt["npr"] * q_extra
                + pass_xfer,
            )
            carries = 0.0 if bye else max(
                0.0,
                tt["ncar"]
                + float(controls["B38"]) * margin
                + float(controls["B40"]) * (total - 2 * mu)
                + (1 - tt["npr"]) * q_extra
                - pass_xfer,
            )
            targets = dropbacks * tt["tgt_db"]
            matchup = (i_val - tt["d_off"]) + l_val + float(controls["B43"]) * (tt["d_def"] - j_val)
            yards_mult = max(0.0, 1 + float(controls["B44"]) * matchup / float(controls["B46"]))
            td_mult = 0.0 if bye else m_pts / (mu + tt["d_off"]) if (mu + tt["d_off"]) else 0.0
            ge[(t, w, basis)] = {
                "M": m_pts,
                "N": n_pts,
                "S": dropbacks,
                "T": carries,
                "U": targets,
                "V": matchup,
                "W": yards_mult,
                "X": td_mult,
                "opp": opp,
            }
    return ge


def _weekly_value(
    players: dict[str, PlayerComputed],
    ge: dict[tuple[str, int, int], dict[str, float]],
    controls: dict[str, Any],
) -> dict[tuple[str, int, int], WeeklyRow]:
    repl_col = {"QB": "J", "RB": "K", "WR": "L", "TE": "M"}
    out: dict[tuple[str, int, int], WeeklyRow] = {}
    for pid, player in players.items():
        for basis in (0, 1):
            rates = player.act if basis == 1 else player.base
            for week in range(4, 18):
                gkey = (player.team, week, basis)
                ge_row = ge[gkey]
                opp = ge_row["opp"]
                i_fp = ge_row["U"] * rates["tgt"] * (
                    player.rates["catch"] * float(controls["B20"])
                    + rates["ypt"] * ge_row["W"] * float(controls["B21"])
                    + min(1.0, player.rates["rec_td"] * ge_row["X"]) * float(controls["B24"])
                )
                j_fp = ge_row["T"] * rates["rush"] * (
                    rates["ypc"] * max(0.0, 1 + float(controls["B45"]) * ge_row["V"] / float(controls["B47"])) * float(controls["B22"])
                    + min(1.0, player.rates["rush_td"] * ge_row["X"]) * float(controls["B25"])
                )
                k_fp = (
                    ge_row["S"]
                    * float(controls["B48"])
                    * player.rates["qb_share"]
                    * (
                        rates["ypa"] * ge_row["W"] * float(controls["B23"])
                        + min(1.0, player.rates["pass_td"] * ge_row["X"]) * float(controls["B26"])
                        + player.rates["int"] * float(controls["B27"])
                    )
                )
                mean = i_fp + j_fp + k_fp
                if opp == "BYE":
                    avail = 0.0
                elif basis == 0:
                    avail = 1.0
                else:
                    avail = player.avail
                replacement = float(controls[f"{repl_col[player.pos]}{week + 3}"])
                weight = float(controls[f"I{week + 3}"])
                out[(pid, week, basis)] = WeeklyRow(
                    rec_fp=i_fp,
                    rush_fp=j_fp,
                    pass_fp=k_fp,
                    mean=mean,
                    avail=avail,
                    replacement=replacement,
                    weight=weight,
                    weighted_par=weight * avail * max(0.0, mean - replacement),
                    expected_pts=avail * mean,
                    opponent=opp,
                )
    return out


def _sd_if_active(player: PlayerComputed, mean: float, opponent: str) -> float:
    if opponent == "BYE":
        return 0.0
    return max(0.0, player.sd_a + player.sd_b * mean)


def _playoff_slot(player: PlayerComputed, weekly: WeeklyRow) -> tuple[float, float]:
    rsd = player.repl_sd
    repl = weekly.replacement
    a = weekly.avail
    mean = weekly.mean
    slot_mean = repl + a * max(0.0, mean - repl)
    if mean <= repl:
        slot_sd = rsd
    else:
        sig = _sd_if_active(player, mean, weekly.opponent)
        slot_sd = math.sqrt(a * sig**2 + (1 - a) * rsd**2 + a * (1 - a) * (mean - repl) ** 2)
    return slot_mean, slot_sd


def _title_odds(
    controls: dict[str, Any],
    semi_mean: float,
    semi_sd: float,
    final_mean: float,
    final_sd: float,
) -> float:
    i37, j37, k37, l37 = float(controls["I37"]), float(controls["J37"]), float(controls["K37"]), float(controls["L37"])
    opp = {
        "A": (float(controls["I38"]), float(controls["J38"]), float(controls["K38"]), float(controls["L38"])),
        "B": (float(controls["I39"]), float(controls["J39"]), float(controls["K39"]), float(controls["L39"])),
        "C": (float(controls["I40"]), float(controls["J40"]), float(controls["K40"]), float(controls["L40"])),
    }
    p_bc = phi((opp["B"][0] - opp["C"][0]) / math.sqrt(opp["B"][1] ** 2 + opp["C"][1] ** 2))
    p_semi = phi(((i37 + semi_mean) - opp["A"][0]) / math.sqrt(j37**2 + semi_sd**2 + opp["A"][1] ** 2))
    p_vb = phi(((k37 + final_mean) - opp["B"][2]) / math.sqrt(l37**2 + final_sd**2 + opp["B"][3] ** 2))
    p_vc = phi(((k37 + final_mean) - opp["C"][2]) / math.sqrt(l37**2 + final_sd**2 + opp["C"][3] ** 2))
    return p_semi * (p_bc * p_vb + (1 - p_bc) * p_vc)


def _screener(
    players: dict[str, PlayerComputed],
    weekly: dict[tuple[str, int, int], WeeklyRow],
    controls: dict[str, Any],
    config: EngineConfig,
) -> dict[str, ScreenerRow]:
    wk = config.projection_week
    semi, fin = config.semifinal_week, config.final_week
    out: dict[str, ScreenerRow] = {}
    for pid, player in players.items():
        d0 = weekly[(pid, wk, 0)]
        d1 = weekly[(pid, wk, 1)]
        sd1 = math.sqrt(d1.avail * _sd_if_active(player, d1.mean, d1.opponent) ** 2 + d1.avail * (1 - d1.avail) * d1.mean**2)
        ros0 = sum(weekly[(pid, w, 0)].weighted_par for w in range(4, 18))
        ros1 = sum(weekly[(pid, w, 1)].weighted_par for w in range(4, 18))
        ys, zs = _playoff_slot(player, weekly[(pid, semi, 1)])
        yf, zf = _playoff_slot(player, weekly[(pid, fin, 1)])
        bs, bzs = _playoff_slot(player, weekly[(pid, semi, 0)])
        bf, bzf = _playoff_slot(player, weekly[(pid, fin, 0)])
        rsd = player.repl_sd
        ai = _title_odds(controls, ys, zs, yf, zf)
        am = _title_odds(
            controls,
            weekly[(pid, semi, 1)].replacement,
            rsd,
            weekly[(pid, fin, 1)].replacement,
            rsd,
        )
        au = _title_odds(controls, bs, bzs, bf, bzf)
        out[pid] = ScreenerRow(
            default_pts=d0.expected_pts,
            thesis_pts=d1.expected_pts,
            thesis_sd=sd1,
            ros_default=ros0,
            ros_thesis=ros1,
            title_odds_pp=100 * (ai - am),
            default_title_odds_pp=100 * (au - am),
            thesis_vs_default_pp=100 * (ai - am) - 100 * (au - am),
            playoff_slot_semi_mean=ys,
            playoff_slot_semi_sd=zs,
            playoff_slot_final_mean=yf,
            playoff_slot_final_sd=zf,
            analytic_title_odds=ai,
            analytic_title_odds_repl=am,
            analytic_title_odds_default=au,
        )
    return out


def _draws(n: int, seed: int) -> list[list[float]]:
    x = seed & 0xffffffff
    def u() -> float:
        nonlocal x
        x ^= (x << 13) & 0xffffffff
        x ^= x >> 17
        x ^= (x << 5) & 0xffffffff
        return (x + 0.5) / 2**32

    out: list[list[float]] = []
    for _ in range(n):
        row: list[float] = []
        for _ in range(8):
            u1, u2 = u(), u()
            row.append(math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2))
        out.append(row)
    return out


def run_engine(bundle: WorkbookBundle, config: EngineConfig | None = None) -> EngineResult:
    config = config or bundle.config
    controls = bundle.controls
    teams = _build_teams(bundle, config, controls)
    gut_index = _gut_sums(config.gut_calls if config.thesis_active else [], controls)
    players = _player_inputs(bundle, config, controls)
    ge = _game_engine(bundle, config, controls, teams, gut_index)
    weekly = _weekly_value(players, ge, controls)
    screener = _screener(players, weekly, controls, config)
    selected = config.selected_player_gsis
    simulation = None
    if selected and selected in screener:
        scr = screener[selected]
        player = players[selected]
        # default playoff slots for simulation base 2
        semi_def = weekly[(selected, config.semifinal_week, 0)]
        fin_def = weekly[(selected, config.final_week, 0)]
        ys_d, zs_d = _playoff_slot(player, semi_def)
        yf_d, zf_d = _playoff_slot(player, fin_def)
        # Patch screener default slots into simulate by temporary attrs — use dedicated tuple
        n = config.simulation_draws if config.honor_draw_count else int(controls["B18"])
        simulation = _simulate_bracket(
            controls,
            thesis=(scr.playoff_slot_semi_mean, scr.playoff_slot_semi_sd, scr.playoff_slot_final_mean, scr.playoff_slot_final_sd),
            default=(ys_d, zs_d, yf_d, zf_d),
            replacement=(
                weekly[(selected, config.semifinal_week, 1)].replacement,
                player.repl_sd,
                weekly[(selected, config.final_week, 1)].replacement,
                player.repl_sd,
            ),
            n=n,
            seed=config.simulation_seed,
        )
    return EngineResult(
        config=config,
        players=players,
        screener=screener,
        weekly=weekly,
        game_engine=ge,
        simulation=simulation,
        selected_gsis=selected,
    )


def _simulate_bracket(
    controls: dict[str, Any],
    *,
    thesis: tuple[float, float, float, float],
    default: tuple[float, float, float, float],
    replacement: tuple[float, float, float, float],
    n: int,
    seed: int,
) -> SimulationResult:
    z = _draws(n, seed)
    i37, j37, k37, l37 = float(controls["I37"]), float(controls["J37"]), float(controls["K37"]), float(controls["L37"])
    opp = {
        "A": (float(controls["I38"]), float(controls["J38"]), float(controls["K38"]), float(controls["L38"])),
        "B": (float(controls["I39"]), float(controls["J39"]), float(controls["K39"]), float(controls["L39"])),
        "C": (float(controls["I40"]), float(controls["J40"]), float(controls["K40"]), float(controls["L40"])),
    }
    bases = [
        (i37 + thesis[0], math.sqrt(j37**2 + thesis[1] ** 2), k37 + thesis[2], math.sqrt(l37**2 + thesis[3] ** 2)),
        (i37 + default[0], math.sqrt(j37**2 + default[1] ** 2), k37 + default[2], math.sqrt(l37**2 + default[3] ** 2)),
        (i37 + replacement[0], math.sqrt(j37**2 + replacement[1] ** 2), k37 + replacement[2], math.sqrt(l37**2 + replacement[3] ** 2)),
    ]
    wins = [[0] * 5 for _ in bases]
    paired: list[float] = []
    for row in z:
        bc = 3 if opp["B"][0] + opp["B"][1] * row[2] >= opp["C"][0] + opp["C"][1] * row[3] else 4
        bcs = opp["B"][2] + opp["B"][3] * row[6] if bc == 3 else opp["C"][2] + opp["C"][3] * row[7]
        res = []
        for sm, ssd, fm, fsd in bases:
            if sm + ssd * row[0] >= opp["A"][0] + opp["A"][1] * row[1]:
                wnr = 1 if fm + fsd * row[4] >= bcs else bc
            else:
                wnr = 2 if opp["A"][2] + opp["A"][3] * row[5] >= bcs else bc
            res.append(wnr)
        for i, wnr in enumerate(res):
            wins[i][wnr] += 1
        paired.append((res[0] == 1) - (res[2] == 1))
    shares = {"you": wins[0][1], "A": wins[0][2], "B": wins[0][3], "C": wins[0][4]}
    contrib = 100 * (wins[0][1] / n - wins[2][1] / n)
    pse = 100 * stdev(paired) / math.sqrt(n) if len(paired) > 1 else 0.0
    return SimulationResult(
        draws=n,
        thesis_wins=wins[0][1],
        default_wins=wins[1][1],
        repl_wins=wins[2][1],
        title_shares=shares,
        paired_se_pp=pse,
        contribution_pp=contrib,
    )
