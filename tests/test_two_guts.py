"""Acceptance: opposite team σ theses move sandbox title odds."""

import unittest

from razzle.engine.config import EngineConfig, TeamSigmaOverride
from razzle.engine.core import run_engine
from razzle.engine.workbook import load_workbook_bundle


class TwoGutsTest(unittest.TestCase):
    def test_bengals_offense_sigma_moves_odds(self):
        bundle = load_workbook_bundle(legacy_houston_preset=False)
        burrow = next(p.gsis_id for p in bundle.players if p.name == "Joe Burrow")

        def run_with(off_z: float):
            cfg = EngineConfig(
                projection_week=bundle.config.projection_week,
                semifinal_week=bundle.config.semifinal_week,
                final_week=bundle.config.final_week,
                thesis_active=True,
                simulation_draws=2000,
                simulation_seed=20261003,
                selected_player_gsis=burrow,
                player_knobs=bundle.config.player_knobs,
                clamp_default_rates=True,
                team_overrides=[TeamSigmaOverride("CIN", offense_z=off_z)],
            )
            return run_engine(bundle, cfg)

        low = run_with(-1.0)
        high = run_with(2.0)
        odds_low = low.screener[burrow].analytic_title_odds
        odds_high = high.screener[burrow].analytic_title_odds
        self.assertNotAlmostEqual(odds_low, odds_high, places=4)
        self.assertGreater(odds_high, odds_low)


if __name__ == "__main__":
    unittest.main()
