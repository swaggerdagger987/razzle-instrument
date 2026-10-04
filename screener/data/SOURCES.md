# Screener sources

NFL season 2025, regular season, QB/RB/WR/TE only. One row per player from https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_2025.csv.gz. Age is years old on 2025-09-01, from birth_date in https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2025.csv joined on gsis_id = player_id.

PPR is computed from counting stats: pass yards × 0.04, pass TD × 4, interception × −2, rush yards × 0.1, rush TD × 6, reception × 1, rec yards × 0.1, rec TD × 6, special-teams TD × 6, two-point conversion × 2, and offensive fumbles lost (sack + rush + receiving) × −2. That matches nflverse `fantasy_points_ppr` on every skill-position row. PPG is PPR divided by games. TD is pass TD + rush TD + rec TD. Pos Rank is within position by PPR and is computed in the page.

College season 2026 (latest files that downloaded with no API key; the season is in progress). Play-derived season stats, FBS skill positions:

- https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_passing/cfb_passing_2026.csv
- https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rushing/cfb_rushing_2026.csv
- https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_receiving/cfb_receiving_2026.csv
- Position and name from https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_rosters/cfb_rosters_2026.csv.gz

GP is the max `games` across those three files. A stat with no source row is left blank. Total yards and total TD sum only the categories that exist. Receiving TD is the `passing_td` column on the receiving file.

Also fetched, then not used as the table: https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_player_box/player_box_2025.csv.gz (one row per player-game, no school, conference, or position).
