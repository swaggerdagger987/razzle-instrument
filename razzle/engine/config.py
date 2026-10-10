"""Engine knobs: controls, thesis inputs, and documented deviation flags."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TeamSigmaOverride:
    team: str
    offense_z: float | None = None
    defense_z: float | None = None
    pass_lean_z: float | None = None


@dataclass
class PlayerKnobs:
    gsis_id: str
    target_shift_z: float = 0.0
    rush_shift_z: float = 0.0
    rec_eff_z: float = 0.0
    rush_eff_z: float = 0.0
    pass_eff_z: float = 0.0
    availability: float | None = None
    cost_title_pp: float | None = None


@dataclass
class GutCall:
    team: str
    week: int | Literal["All"]
    factor: Literal["Offense", "Defense", "Pass lean"]
    strength_label: str | None = None
    points: float | None = None


@dataclass
class EngineConfig:
    """Runtime configuration.

    ``thesis_active``: when True, basis-1 (your thesis) reads team/player/gut inputs.
    Workbook cases 2–4 map to thesis_active=False. Case 3/4 HOU presets are *not*
    hardcoded; use ``team_overrides`` instead (parity tests set HOU defense z=±2).
    """

    projection_week: int = 4
    semifinal_week: int = 16
    final_week: int = 17
    thesis_active: bool = True
    simulation_draws: int = 10_000
    simulation_seed: int = 20261003
    selected_player_gsis: str | None = None
    team_overrides: list[TeamSigmaOverride] = field(default_factory=list)
    player_knobs: list[PlayerKnobs] = field(default_factory=list)
    gut_calls: list[GutCall] = field(default_factory=list)
    # Deliberate deviation from workbook §9.2: clamp shrunk rates on basis 0 too.
    clamp_default_rates: bool = True
    # When True, ``simulation_draws`` sets trial count (workbook B18 was divisor-only).
    honor_draw_count: bool = True
