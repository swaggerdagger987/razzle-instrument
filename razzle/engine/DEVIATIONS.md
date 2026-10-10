# Workbook parity vs production engine

The engine reproduces `Razzle_Player_Valuation.xlsx` math. These intentional fixes change numbers outside parity mode:

| Deviation | Workbook behavior | Production behavior | Effect |
|---|---|---|---|
| Basis-0 rate floor | Unclamped shrunk YPC/YPT on default basis | Same `max(0,…)` / `min(1,…)` as thesis basis | ~52 player-week rows (e.g. Drew Lock, Cooper Rush, Nick Mullens, Travis Homer) no longer show spurious thesis≠default deltas with no user input |
| Case 3/4 HOU preset | Hardcoded `HOU` defense σ in Teams!T | User `team_overrides` only (two-guts test sets CIN/Bengals σ in the form) | Same math when overrides match; no hidden team string in code |
| Simulation draw count | `Controls!B18` divides fixed 10k rows | `simulation_draws` sets actual trial count | Odds scale correctly when draws ≠ 10000 |
| Row topology | Sheet row offsets | Keys: `gsis_id`, `(team, week, basis)` | Re-sorting players does not change results |

Parity tests: `python3 -m unittest tests.test_engine_parity` (legacy workbook mode must match dumps to ~1e-9).
