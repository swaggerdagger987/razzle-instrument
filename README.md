# Razzle

An instrument for obsessive fantasy players.

Tagline: quantify your gut.

The spec in `spec/` is the source of truth. This shell includes the valuation engine (workbook v0 math), screener engine columns, player-sheet projections, and a four-team championship-odds sandbox on Home with σ knobs. Sleeper league payloads still power standings and the thin championship-share read. Leverage copy on the player sheet remains sample text. There are no payments.

### Valuation engine

- Code: `razzle/engine/` — see `razzle/engine/DEVIATIONS.md` for intentional workbook fixes.
- Parity tests: `python3 -m unittest discover -s tests -v` (fixtures in `tests/fixtures/engine_dump.tar.gz`).
- Optional rebuild: `python3 -m razzle.engine.snapshot` → `screener/data/engine/*.json`.

## Run

From this folder:

```
python3 app.py
```

Then open http://127.0.0.1:8080

The screener is at http://127.0.0.1:8080/screener/ . It does not need an account.

Player tear sheets use committed `screener/data/engine/screener.json`, `player-details.json`, and `screener/data/nfl/player-meta.json`. After `git pull`, restart `python3 app.py` only — no build step. If engine JSON is missing, startup rebuilds it automatically (~10s).

Register with an email and a password (8 or more characters). Passwords are stored as a salted hash. The session is a cookie. The database is `data/razzle.db`, created on first run, and it is gitignored.

On Home, the hero number is sandbox title odds from the engine (not league Monte Carlo yet). Use the formula builder to nudge team σ and gut calls. Save a Sleeper username for standings and roster context.

Player sheets join nflverse screener stats with engine projections when a row exists in `screener/data/engine/screener.json`.

## War Room

The War Room answers only when `RAZZLE_MODEL_KEY` is set. Until then the page says the key is not set and does not make up a reply.

Optional:

- `RAZZLE_MODEL_URL` — defaults to `https://api.openai.com/v1/chat/completions`
- `RAZZLE_MODEL_NAME` — defaults to `gpt-4o-mini`

The question is sent with team names and roster names that were actually fetched for the saved league.
