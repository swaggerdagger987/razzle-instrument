"""Equity-style player tear sheet: build context + render HTML."""

from __future__ import annotations

import math
from typing import Any, Callable

from razzle.player_data import (
    PlayerSheetContext,
    career_for_gsis,
    engine_comps,
    game_log_for_gsis,
    load_engine_details,
    load_player_meta,
    weekly_actuals_chart,
)


def build_nfl_skill_context(
    *,
    gsis: str,
    season: int,
    name: str,
    pos: str,
    team: str,
    season_player: dict | None,
    source: str,
    engine_summary: dict | None,
    sleeper_id: str = "",
    sleeper_rec: dict | None = None,
    league_snapshot: dict | None = None,
    sleeper_index: dict | None = None,
    load_pack: Callable[[int], dict | None],
    catalog_years: set[int],
    week_pack_loader: Callable[[int], dict | None],
) -> PlayerSheetContext:
    meta_all = load_player_meta()
    bio = dict(meta_all.get(gsis) or {})
    if sleeper_rec:
        for key in ("injury_status", "status"):
            if sleeper_rec.get(key):
                bio[key] = sleeper_rec[key]
    detail_all = load_engine_details()
    detail = detail_all.get(gsis)
    summary_index = {}  # filled by caller if needed — use engine_summary parent
    notes = []
    if not engine_summary:
        notes.append("Valuation engine has no row for this player yet. Price and model sections stay blank.")
    if not detail:
        notes.append("Weekly projection detail is not in the engine build for this player.")

    career = career_for_gsis(gsis, catalog_years, load_pack)
    game_log = game_log_for_gsis(gsis, season, week_pack_loader)
    proj_week = 4
    if detail:
        proj_week = detail.get("breakdown", {}).get("week") or proj_week
    weekly_chart = weekly_actuals_chart(game_log, (detail or {}).get("weekly"), proj_week)
    season_chart = [{"year": r["year"], "ppr": r.get("ppr"), "gp": r.get("gp")} for r in career]

    comps = []
    if engine_summary and gsis:
        # summary index must be full — passed via engine_summary as dict with __full__
        full = engine_summary.get("__full_index__") or {}
        comps = engine_comps(gsis, pos, {}, full)

    owners = []
    if league_snapshot and sleeper_id:
        for team_row in league_snapshot.get("teams") or []:
            label = team_row.get("label") or ""
            for key in ("starters", "bench"):
                for entry in team_row.get(key) or []:
                    pid = entry[0] if isinstance(entry, tuple) else None
                    if pid and str(pid) == str(sleeper_id):
                        owners.append(label)
    elif league_snapshot and gsis and sleeper_index:
        for team_row in league_snapshot.get("teams") or []:
            label = team_row.get("label") or ""
            for key in ("starters", "bench"):
                for entry in team_row.get(key) or []:
                    pid = entry[0] if isinstance(entry, tuple) else None
                    if not pid:
                        continue
                    rec = sleeper_index.get(str(pid)) or {}
                    if (rec.get("gsis_id") or "") == gsis:
                        owners.append(label)

    return PlayerSheetContext(
        kind="nfl_skill",
        name=name or (season_player or {}).get("name") or gsis,
        pos=pos or (season_player or {}).get("pos") or "",
        team=team or (season_player or {}).get("team") or bio.get("team") or "",
        gsis_id=gsis,
        sleeper_id=sleeper_id,
        season=season,
        bio=bio,
        engine_summary=engine_summary if engine_summary and "titleOddsPp" in engine_summary else None,
        engine_detail=detail,
        season_stats=season_player,
        career_rows=career,
        game_log=game_log,
        weekly_chart=weekly_chart,
        season_chart=season_chart,
        comps=comps,
        league_owners=owners,
        source_url=source,
        notes=notes,
    )


def _fmt_num(value, digits=1, suffix=""):
    if value is None or value == "":
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{n:.{digits}f}{suffix}"


def _section(title: str, body: str, note: str = "") -> str:
    note_html = f'<p class="sheet-note">{note}</p>' if note else ""
    return f'<section class="sheet-section card"><p class="kicker">{title}</p>{note_html}{body}</section>'


def _svg_weekly_chart(points: list[dict], proj_week: int) -> str:
    if not points:
        return '<p class="sheet-empty">No weekly game log in nflverse for this season yet.</p>'
    width, height = 640, 220
    pad_l, pad_r, pad_t, pad_b = 44, 16, 16, 36
    vals = []
    for p in points:
        if p.get("actual") is not None:
            vals.append(float(p["actual"]))
        if p.get("proj") is not None:
            vals.append(float(p["proj"]))
        if p.get("ceiling") is not None:
            vals.append(float(p["ceiling"]))
        if p.get("floor") is not None:
            vals.append(float(p["floor"]))
    if not vals:
        return '<p class="sheet-empty">Chart needs at least one scored week.</p>'
    y_min = max(0, min(vals) - 2)
    y_max = max(vals) + 2
    if y_max <= y_min:
        y_max = y_min + 10

    def x_pos(i, n):
        inner = width - pad_l - pad_r
        return pad_l + (inner * i / max(1, n - 1))

    def y_pos(v):
        inner = height - pad_t - pad_b
        return pad_t + inner * (1 - (v - y_min) / (y_max - y_min))

    n = len(points)
    band_parts = []
    line_proj = []
    line_act = []
    dots = []
    for i, p in enumerate(points):
        x = x_pos(i, n)
        wk = p["week"]
        if p.get("proj") is not None and p.get("sd") is not None:
            floor = max(0, p["proj"] - p["sd"])
            ceil = p["proj"] + p["sd"]
            y1, y2 = y_pos(ceil), y_pos(floor)
            band_parts.append(
                f'<rect x="{x - 6:.1f}" y="{y2:.1f}" width="12" height="{max(1, y1 - y2):.1f}" '
                f'class="chart-band" opacity="0.35"/>'
            )
        if p.get("proj") is not None:
            line_proj.append(f"{x:.1f},{y_pos(p['proj']):.1f}")
        if p.get("actual") is not None:
            line_act.append(f"{x:.1f},{y_pos(p['actual']):.1f}")
            dots.append(f'<circle cx="{x:.1f}" cy="{y_pos(p["actual"]):.1f}" r="4" class="chart-dot-actual"/>')
    proj_path = f'<polyline points="{" ".join(line_proj)}" class="chart-line-proj" fill="none"/>' if line_proj else ""
    act_path = f'<polyline points="{" ".join(line_act)}" class="chart-line-actual" fill="none"/>' if line_act else ""
    ticks = ""
    for i, p in enumerate(points):
        if i % max(1, n // 8) != 0 and i != n - 1:
            continue
        x = x_pos(i, n)
        ticks += f'<text x="{x:.0f}" y="{height - 8}" text-anchor="middle" class="chart-tick">W{p["week"]}</text>'
    forecast = f'<text x="{pad_l}" y="14" class="chart-annotation">Forecast from W{proj_week} — dashed band = ±1σ</text>'
    return (
        f'<div class="chart-wrap"><svg viewBox="0 0 {width} {height}" class="tear-chart" role="img" '
        f'aria-label="Weekly fantasy points vs engine projection">'
        f"{forecast}{''.join(band_parts)}{proj_path}{act_path}{''.join(dots)}{ticks}"
        f"</svg><p class=\"chart-watermark\">razzle.lol</p></div>"
    )


def _svg_season_chart(rows: list[dict]) -> str:
    pts = [r for r in rows if r.get("ppr") is not None]
    if len(pts) < 2:
        return '<p class="sheet-empty">Need two or more seasons with PPR totals for a trend line.</p>'
    width, height = 640, 160
    pad_l, pad_r, pad_t, pad_b = 44, 16, 20, 32
    years = [r["year"] for r in pts]
    vals = [float(r["ppr"]) for r in pts]
    y_min = max(0, min(vals) * 0.85)
    y_max = max(vals) * 1.05

    def x_pos(i):
        inner = width - pad_l - pad_r
        return pad_l + inner * i / max(1, len(pts) - 1)

    def y_pos(v):
        inner = height - pad_t - pad_b
        return pad_t + inner * (1 - (v - y_min) / (y_max - y_min))

    coords = " ".join(f"{x_pos(i):.1f},{y_pos(v):.1f}" for i, v in enumerate(vals))
    bars = ""
    for i, r in enumerate(pts):
        x = x_pos(i)
        bars += f'<rect x="{x - 10:.0f}" y="{y_pos(r["ppr"]):.0f}" width="20" height="{height - pad_b - y_pos(r["ppr"]):.0f}" class="chart-bar"/>'
        bars += f'<text x="{x:.0f}" y="{height - 10}" text-anchor="middle" class="chart-tick">{r["year"]}</text>'
    return (
        f'<div class="chart-wrap"><svg viewBox="0 0 {width} {height}" class="tear-chart" role="img" '
        f'aria-label="Season PPR totals">'
        f'<polyline points="{coords}" class="chart-line-actual" fill="none"/>'
        f"{bars}</svg><p class=\"chart-watermark\">razzle.lol</p></div>"
    )


def render_tear_sheet(ctx: PlayerSheetContext, escape: Callable[[Any], str], sample_badge_html: str) -> str:
    pos = ctx.pos or "WR"
    pos_cls = escape(pos)
    stripe = f" stripe-{pos.lower()}" if pos in ("QB", "RB", "WR", "TE") else ""
    eng = ctx.engine_summary or {}
    det = ctx.engine_detail or {}
    bd = det.get("breakdown") or {}
    proj_week = bd.get("week") or (det.get("weekly") or [{}])[0].get("week") or 4

    price = eng.get("titleOddsPp")
    price_html = (
        f'<p class="ticker-price">{escape(_fmt_num(price, 1, ""))}<span class="ticker-unit">pp</span></p>'
        f'<p class="ticker-price-label">Title odds vs replacement</p>'
        if price is not None
        else f'<p class="ticker-price missing">—</p><p class="ticker-price-label">No engine price</p>'
    )

    bio_bits = []
    if ctx.bio.get("height"):
        bio_bits.append(str(ctx.bio["height"]))
    if ctx.bio.get("weight"):
        bio_bits.append(f'{ctx.bio["weight"]} lb')
    if ctx.bio.get("college"):
        bio_bits.append(str(ctx.bio["college"]))
    draft_bits = []
    if ctx.bio.get("draftPick"):
        draft_bits.append(f'Pick {ctx.bio["draftPick"]}')
    if ctx.bio.get("draftRound"):
        draft_bits.append(f'Rd {ctx.bio["draftRound"]}')
    if ctx.bio.get("rookieYear"):
        draft_bits.append(f'Class {ctx.bio["rookieYear"]}')
    if ctx.bio.get("yearsExp") is not None:
        draft_bits.append(f'{ctx.bio["yearsExp"]} yr exp')
    age = (ctx.season_stats or {}).get("age")
    if age is not None:
        bio_bits.insert(0, f"Age {age}")

    key_stats = [
        ("Proj W" + str(proj_week), eng.get("proj")),
        ("σ (vol)", eng.get("sd")),
        ("ROS value", eng.get("ros")),
        ("Default Δpp", eng.get("thesisVsDefaultPp")),
    ]

    header = f"""
<header class="ticker-strip card{stripe}">
  <div class="ticker-id">
    <p class="ticker-name">{escape(ctx.name)}</p>
    <p class="ticker-meta">
      <span class="pos {pos_cls}">{pos_cls}</span>
      <span class="ticker-team">{escape(ctx.team or "—")}</span>
    </p>
    <p class="ticker-bio">{escape(" · ".join(bio_bits) or "Bio not in roster file.")}</p>
    <p class="ticker-bio faint">{escape(" · ".join(draft_bits))}</p>
  </div>
  <div class="ticker-quote">
    {price_html}
    <div class="ticker-keys">
      {"".join(
        f'<div class="ticker-key"><span class="label">{escape(label)}</span>'
        f'<span class="value">{escape(_fmt_num(val))}</span></div>'
        for label, val in key_stats
      )}
    </div>
  </div>
</header>
"""

    chart_pts = []
    eng_weekly = {r["week"]: r for r in (det.get("weekly") or [])}
    for row in ctx.weekly_chart:
        wk = row["week"]
        ew = eng_weekly.get(wk) or {}
        chart_pts.append(
            {
                **row,
                "proj": ew.get("mean"),
                "sd": ew.get("sd"),
                "floor": ew.get("floor"),
                "ceiling": ew.get("ceiling"),
            }
        )
    performance = _section(
        "Price & performance",
        _svg_weekly_chart(chart_pts, proj_week)
        + _svg_season_chart(ctx.season_chart),
        "PPR fantasy points (nflverse) vs engine mean; shaded band is ±1σ when a projection exists.",
    )

    val_rows = ""
    if bd:
        val_rows = "<table class='sheet-table'><tbody>"
        for label, key in (
            ("Receiving FP", "recFp"),
            ("Rushing FP", "rushFp"),
            ("Passing FP", "passFp"),
            ("Mean if active", "mean"),
            ("Team expected pts", "teamExpectedPts"),
            ("Yards multiplier", "matchupYardsMult"),
            ("TD multiplier", "matchupTdMult"),
            ("Team dropbacks", "dropbacks"),
            ("Team carries", "carries"),
            ("Team targets", "targets"),
        ):
            val_rows += f"<tr><th>{escape(label)}</th><td class='num'>{escape(_fmt_num(bd.get(key), 2))}</td></tr>"
        val_rows += "</tbody></table>"
        val_rows += (
            "<p class='sheet-note'>Opportunity × shrunk efficiency × PPR weights, with schedule-adjusted "
            "team volume and matchup multipliers. ROS uses playoff-week weights (W15–17 heavier).</p>"
        )
    else:
        val_rows = "<p class='sheet-empty'>No valuation breakdown for this player.</p>"

    valuation = _section(f"Valuation model (W{proj_week})", val_rows)

    pct = det.get("percentiles") or {}
    usage_body = "<table class='sheet-table'><tbody>"
    for label, key, val, pctl_key in (
        ("Target share", "tgtShare", bd.get("tgtShare"), "tgtShare"),
        ("Rush share", "rushShare", bd.get("rushShare"), "rushShare"),
        ("Catch rate", "catchRate", bd.get("catchRate"), None),
        ("Yards per target", "ypt", bd.get("ypt"), None),
        ("Yards per carry", "ypc", bd.get("ypc"), None),
        ("Yards per attempt", "ypa", bd.get("ypa"), None),
    ):
        pctl = pct.get(pctl_key) if pctl_key else None
        pctl_txt = f" <span class='pct-rank'>P{pctl}</span>" if pctl is not None else ""
        usage_body += f"<tr><th>{escape(label)}</th><td class='num'>{escape(_fmt_num(val, 3))}{pctl_txt}</td></tr>"
    usage_body += "</tbody></table>"
    usage_body += "<p class='sheet-note'>Snap and route rates are not in the published nflverse screener build yet.</p>"
    usage = _section("Usage & efficiency", usage_body)

    wk_row = next((r for r in (det.get("weekly") or []) if r.get("week") == proj_week), {})
    risk_body = f"""
<table class="sheet-table"><tbody>
<tr><th>Weekly σ</th><td class="num">{escape(_fmt_num(eng.get("sd")))}</td></tr>
<tr><th>Floor (μ−σ)</th><td class="num">{escape(_fmt_num(wk_row.get("floor")))}</td></tr>
<tr><th>Ceiling (μ+σ)</th><td class="num">{escape(_fmt_num(wk_row.get("ceiling")))}</td></tr>
<tr><th>Availability</th><td class="num">{escape(_fmt_num(det.get("avail"), 2))}</td></tr>
<tr><th>Injury (Sleeper)</th><td>{escape(ctx.bio.get("injury_status") or ctx.bio.get("status") or "—")}</td></tr>
</tbody></table>
"""
    risk = _section("Risk", risk_body, "Injury status only when Sleeper lists it on the player file.")

    sched_rows = ""
    for row in det.get("upcoming") or []:
        sched_rows += (
            f"<tr><td>W{row['week']}</td><td>{escape(row.get('opp') or '')}</td>"
            f"<td class='num'>{escape(_fmt_num(row.get('teamPts'), 1))}</td>"
            f"<td class='num'>{escape(_fmt_num(row.get('yardsMult'), 3))}</td>"
            f"<td class='num'>{escape(_fmt_num(row.get('tdMult'), 3))}</td></tr>"
        )
    schedule = _section(
        "Schedule & matchup",
        (
            "<table class='sheet-table'><thead><tr><th>Wk</th><th>Opp</th><th>Team E[pts]</th>"
            "<th>Yds mult</th><th>TD mult</th></tr></thead><tbody>"
            + (sched_rows or "<tr><td colspan='5'>No remaining schedule in engine.</td></tr>")
            + "</tbody></table>"
        ),
    )

    fin_head = "<table class='sheet-table'><thead><tr><th>Season</th><th>Team</th><th>GP</th><th>PPR</th><th>PPG</th></tr></thead><tbody>"
    fin_rows = ""
    for r in ctx.career_rows:
        fin_rows += (
            f"<tr><td>{r['year']}</td><td>{escape(r.get('team') or '')}</td>"
            f"<td class='num'>{escape(_fmt_num(r.get('gp'), 0))}</td>"
            f"<td class='num'>{escape(_fmt_num(r.get('ppr'), 1))}</td>"
            f"<td class='num'>{escape(_fmt_num(r.get('ppg'), 1))}</td></tr>"
        )
    financials = _section("Career financials (PPR)", fin_head + fin_rows + "</tbody></table>")

    log_head = "<table class='sheet-table compact'><thead><tr><th>Wk</th><th>Opp</th><th>PPR</th><th>TGT</th><th>REC</th><th>RY</th><th>PY</th></tr></thead><tbody>"
    log_rows = ""
    for r in ctx.game_log:
        log_rows += (
            f"<tr><td>{r['week']}</td><td>{escape(r.get('opp') or '')}</td>"
            f"<td class='num'>{escape(_fmt_num(r.get('ppr'), 1))}</td>"
            f"<td class='num'>{escape(_fmt_num(r.get('tgt'), 0))}</td>"
            f"<td class='num'>{escape(_fmt_num(r.get('rec'), 0))}</td>"
            f"<td class='num'>{escape(_fmt_num(r.get('ry'), 0))}</td>"
            f"<td class='num'>{escape(_fmt_num(r.get('py'), 0))}</td></tr>"
        )
    game_log = _section("Game log", log_head + (log_rows or "<tr><td colspan='7'>No weekly rows.</td></tr>") + "</tbody></table>")

    comp_items = ""
    for c in ctx.comps:
        comp_items += (
            f'<li><a href="/player?gsis={escape(c["gsisId"])}&season={ctx.season}">'
            f'{escape(c.get("name") or c["gsisId"])}</a> '
            f'<span class="meta">{escape(_fmt_num(c.get("titleOddsPp"), 1))} pp · ROS {escape(_fmt_num(c.get("ros"), 1))}</span></li>'
        )
    comps = _section("Comps (nearest title-odds pp)", f"<ul class='comp-list'>{comp_items or '<li>No engine peers.</li>'}</ul>")

    league = ""
    if ctx.league_owners:
        league = _section("Your league", "<p>Rostered on: <strong>" + escape(", ".join(ctx.league_owners)) + "</strong></p>")
    elif ctx.kind == "nfl_skill":
        league = _section("Your league", "<p class='sheet-note'>Save a Sleeper league on Home to see roster ownership here.</p>")

    leverage = (
        f'<section class="sheet-section card stripe-muted"><p class="kicker">Desk notes</p>'
        f'<p class="tear-leverage">{escape("Leverage read (sample): rostered in most leagues, but the trade market still sleeps on this usage curve.")} '
        f"{sample_badge_html}</p></section>"
    )

    notes_html = "".join(f"<p class='sheet-note'>{escape(n)}</p>" for n in ctx.notes)
    source = f'<p class="source-line">Source: <a href="{escape(ctx.source_url)}">nflverse regular season</a></p>' if ctx.source_url else ""

    return f"""
<div class="tear-sheet">
{header}
<div class="tear-grid">
  <div class="tear-main">{performance}{financials}{game_log}</div>
  <div class="tear-side">{valuation}{usage}{risk}{schedule}{comps}{league}{leverage}</div>
</div>
{notes_html}
{source}
</div>
"""


def render_college_tear(ctx: PlayerSheetContext, escape: Callable, sample_badge_html: str) -> str:
    rows = ""
    if ctx.season_stats:
        for key, label in (("gp", "GP"), ("ty", "Total yds"), ("td", "TD"), ("py", "Pass"), ("ry", "Rush"), ("rey", "Rec")):
            if ctx.season_stats.get(key) is not None:
                rows += f"<tr><th>{label}</th><td>{escape(ctx.season_stats[key])}</td></tr>"
    body = f"<table class='sheet-table'><tbody>{rows}</tbody></table>" if rows else "<p class='sheet-empty'>No college stat row.</p>"
    return _section(ctx.name, body) + sample_badge_html


def render_sparse_card(title: str, lines: list[str], escape: Callable) -> str:
    return "<section class='card'>" + f"<p class='ticker-name'>{escape(title)}</p>" + "".join(
        f"<p class='sheet-note'>{escape(line)}</p>" for line in lines
    ) + "</section>"
