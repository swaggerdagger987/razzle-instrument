# Screener sources

NFL regular season, QB/RB/WR/TE only, one row per player per season. Seasons 2015 through the latest year that downloaded. Each season file is `screener/data/nfl/YEAR.json`, built from:

- 2015: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_2015.csv.gz (556 players)
- 2016: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_2016.csv.gz (557 players)
- 2017: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_2017.csv.gz (553 players)
- 2018: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_2018.csv.gz (577 players)
- 2019: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_2019.csv.gz (572 players)
- 2020: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_2020.csv.gz (602 players)
- 2021: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_2021.csv.gz (633 players)
- 2022: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_2022.csv.gz (608 players)
- 2023: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_2023.csv.gz (577 players)
- 2024: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_2024.csv.gz (589 players)
- 2025: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_2025.csv.gz (610 players)
- 2026: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_2026.csv.gz (454 players)

Age is years old on September 1 of that season, from `birth_date` in the roster file joined on `gsis_id` = `player_id`. A player with no birth date has no age.

- 2015 roster: https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2015.csv
- 2016 roster: https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2016.csv
- 2017 roster: https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2017.csv
- 2018 roster: https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2018.csv
- 2019 roster: https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2019.csv
- 2020 roster: https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2020.csv
- 2021 roster: https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2021.csv
- 2022 roster: https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2022.csv
- 2023 roster: https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2023.csv
- 2024 roster: https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2024.csv
- 2025 roster: https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2025.csv
- 2026 roster: https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2026.csv

PPR is computed from counting stats: pass yards × 0.04, pass TD × 4, interception × −2, rush yards × 0.1, rush TD × 6, reception × 1, rec yards × 0.1, rec TD × 6, special-teams TD × 6, two-point conversion × 2, and offensive fumbles lost (sack + rush + receiving) × −2. A blank component counts as 0 only inside that formula. That matches nflverse `fantasy_points_ppr` on every skill-position row, season and week. PPG is PPR divided by games, and only when the file has a games value. TD is pass TD + rush TD + rec TD. Pos Rank is within position by PPR and is computed in the page.

Weekly view uses the same positions and the same formula, one row per player per week, regular season only (`season_type` = REG). A week with more than one row for a player is summed. The week file has no `games` column, so GP and PPG are left blank in a week view. Files:

- 2015: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2015.csv.gz — weeks present: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17. Disabled (inside 1 through the last present week, but with no skill-position rows): none.
- 2016: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2016.csv.gz — weeks present: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17. Disabled (inside 1 through the last present week, but with no skill-position rows): none.
- 2017: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2017.csv.gz — weeks present: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17. Disabled (inside 1 through the last present week, but with no skill-position rows): none.
- 2018: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2018.csv.gz — weeks present: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17. Disabled (inside 1 through the last present week, but with no skill-position rows): none.
- 2019: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2019.csv.gz — weeks present: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17. Disabled (inside 1 through the last present week, but with no skill-position rows): none.
- 2020: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2020.csv.gz — weeks present: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17. Disabled (inside 1 through the last present week, but with no skill-position rows): none.
- 2021: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2021.csv.gz — weeks present: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18. Disabled (inside 1 through the last present week, but with no skill-position rows): none.
- 2022: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2022.csv.gz — weeks present: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18. Disabled (inside 1 through the last present week, but with no skill-position rows): none.
- 2023: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2023.csv.gz — weeks present: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18. Disabled (inside 1 through the last present week, but with no skill-position rows): none.
- 2024: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2024.csv.gz — weeks present: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18. Disabled (inside 1 through the last present week, but with no skill-position rows): none.
- 2025: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2025.csv.gz — weeks present: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18. Disabled (inside 1 through the last present week, but with no skill-position rows): none.
- 2026: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2026.csv.gz — weeks present: 1, 2, 3, 4. Disabled (inside 1 through the last present week, but with no skill-position rows): none.

The week control lists every week from 1 through the last week that has rows. A missing week in that span is disabled. Weeks that the file does not contain past that span are not shown. No week numbers were invented.

College seasons downloaded with no API key: 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026. Play-derived season stats, skill positions. One file per season at `screener/data/college/YEAR.json`.

- 2015 passing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_2015.csv
- 2015 rushing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_2015.csv
- 2015 receiving: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_2015.csv
- 2015 roster: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_2015.csv.gz — 2300 players
- 2016 passing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_2016.csv
- 2016 rushing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_2016.csv
- 2016 receiving: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_2016.csv
- 2016 roster: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_2016.csv.gz — 2281 players
- 2017 passing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_2017.csv
- 2017 rushing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_2017.csv
- 2017 receiving: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_2017.csv
- 2017 roster: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_2017.csv.gz — 2375 players
- 2018 passing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_2018.csv
- 2018 rushing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_2018.csv
- 2018 receiving: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_2018.csv
- 2018 roster: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_2018.csv.gz — 2473 players
- 2019 passing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_2019.csv
- 2019 rushing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_2019.csv
- 2019 receiving: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_2019.csv
- 2019 roster: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_2019.csv.gz — 2502 players
- 2020 passing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_2020.csv
- 2020 rushing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_2020.csv
- 2020 receiving: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_2020.csv
- 2020 roster: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_2020.csv.gz — 2277 players
- 2021 passing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_2021.csv
- 2021 rushing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_2021.csv
- 2021 receiving: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_2021.csv
- 2021 roster: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_2021.csv.gz — 2523 players
- 2022 passing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_2022.csv
- 2022 rushing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_2022.csv
- 2022 receiving: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_2022.csv
- 2022 roster: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_2022.csv.gz — 2554 players
- 2023 passing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_2023.csv
- 2023 rushing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_2023.csv
- 2023 receiving: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_2023.csv
- 2023 roster: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_2023.csv.gz — 2583 players
- 2024 passing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_2024.csv
- 2024 rushing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_2024.csv
- 2024 receiving: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_2024.csv
- 2024 roster: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_2024.csv.gz — 2583 players
- 2025 passing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_2025.csv
- 2025 rushing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_2025.csv
- 2025 receiving: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_2025.csv
- 2025 roster: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_2025.csv.gz — 2745 players
- 2026 passing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_2026.csv
- 2026 rushing: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_2026.csv
- 2026 receiving: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_2026.csv
- 2026 roster: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_2026.csv.gz — 2196 players

GP is the max `games` across the passing, rushing, and receiving files. A stat with no source row is left blank. Total yards and total TD sum only the categories that exist. Receiving TD is the `passing_td` column on the receiving file. Roster position wins when it is QB, RB, WR, or TE. A roster position of blank or `-` falls back to the stat file `position_group`. College files are season totals, not weeks, so the page has no college week control.

Also fetched in an earlier pass, then not used as the table: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_player_box/player_box_2025.csv.gz (one row per player-game, no school, conference, or position).
