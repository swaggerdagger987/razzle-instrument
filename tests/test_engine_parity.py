"""Parity against workbook streamed dumps (see ENGINE_SPEC deviations)."""

from __future__ import annotations

import math
import unittest

from razzle.engine.core import run_engine
from razzle.engine.fixtures import default_dump_dir, load_dump_bundle
from razzle.engine.workbook import load_workbook_bundle


class EngineParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dump = load_dump_bundle()
        if not (default_dump_dir() / "s08_Controls.txt").is_file():
            raise unittest.SkipTest("engine dump fixtures not extracted")

    def test_legacy_workbook_exact(self):
        """Full workbook parity (case 3, HOU preset, unclamped basis-0 rates)."""
        bundle = load_workbook_bundle(legacy_houston_preset=True)
        result = run_engine(bundle)
        wv_x = self.dump["weekly_value"]
        ge_x = self.dump["game_engine"]
        sc_x = self.dump["screener"]
        players = bundle.players
        gp = []
        for idx, prow in enumerate(players):
            for basis in (0, 1):
                for week in range(4, 18):
                    r = 7 + idx * 28 + basis * 14 + (week - 4)
                    d = result.weekly[(prow.gsis_id, week, basis)]
                    for col, attr in (
                        ("I", "rec_fp"),
                        ("J", "rush_fp"),
                        ("K", "pass_fp"),
                        ("L", "mean"),
                        ("M", "avail"),
                        ("N", "replacement"),
                        ("O", "weight"),
                        ("P", "weighted_par"),
                        ("Q", "expected_pts"),
                    ):
                        gp.append((getattr(d, attr), wv_x[f"{col}{r}"]))
        mx = max(abs(a - b) for a, b in gp)
        self.assertLess(mx, 1e-9, f"weekly value max diff {mx}")

        sp = []
        for idx, prow in enumerate(players):
            r = 7 + idx
            row = result.screener[prow.gsis_id]
            for col, attr in (
                ("E", "default_pts"),
                ("F", "thesis_pts"),
                ("H", "thesis_sd"),
                ("I", "ros_default"),
                ("J", "ros_thesis"),
                ("L", "title_odds_pp"),
                ("M", "default_title_odds_pp"),
                ("Y", "playoff_slot_semi_mean"),
                ("Z", "playoff_slot_semi_sd"),
                ("AA", "playoff_slot_final_mean"),
                ("AB", "playoff_slot_final_sd"),
                ("AI", "analytic_title_odds"),
                ("AM", "analytic_title_odds_repl"),
                ("AU", "analytic_title_odds_default"),
            ):
                sp.append((getattr(row, attr), sc_x[f"{col}{r}"]))
        mx = max(abs(a - b) for a, b in sp)
        self.assertLess(mx, 1e-8, f"screener max diff {mx}")

        sim = result.simulation
        self.assertIsNotNone(sim)
        os_x = self.dump["odds_sandbox"]
        self.assertEqual(sim.thesis_wins, int(os_x["G11"] * bundle.config.simulation_draws))
        self.assertEqual(sim.default_wins, int(os_x["G12"] * bundle.config.simulation_draws))
        self.assertEqual(sim.repl_wins, int(os_x["G13"] * bundle.config.simulation_draws))
        self.assertEqual(sim.title_shares["you"], 2672)
        self.assertEqual(sim.title_shares["A"], 2312)
        self.assertEqual(sim.title_shares["B"], 3002)
        self.assertEqual(sim.title_shares["C"], 2014)

    def test_default_rate_floor_fix(self):
        """With clamped basis-0 rates, thesis-default weekly delta is 0 without user knobs."""
        bundle = load_workbook_bundle(legacy_houston_preset=False)
        bundle.config.team_overrides = []
        bundle.config.thesis_active = False
        bundle.config.clamp_default_rates = True
        result = run_engine(bundle)
        # Players named in ENGINE_SPEC §9.2
        names = {"Drew Lock", "Cooper Rush", "Nick Mullens", "Travis Homer"}
        for prow in bundle.players:
            if prow.name not in names:
                continue
            for week in range(4, 18):
                d0 = result.weekly[(prow.gsis_id, week, 0)]
                d1 = result.weekly[(prow.gsis_id, week, 1)]
                if d0.opponent == "BYE":
                    continue
                self.assertAlmostEqual(d0.mean, d1.mean, places=9, msg=f"{prow.name} w{week}")

    def test_draw_count_honored(self):
        bundle = load_workbook_bundle(legacy_houston_preset=True)
        bundle.config.simulation_draws = 500
        result = run_engine(bundle)
        self.assertEqual(result.simulation.draws, 500)
        self.assertEqual(sum(result.simulation.title_shares.values()), 500)


if __name__ == "__main__":
    unittest.main()
