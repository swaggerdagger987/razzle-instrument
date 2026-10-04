# Razzle

An instrument for obsessive fantasy players.

Tagline: quantify your gut.

The spec in `spec/` is the source of truth. This shell is the first cut: sign-in, the screener, a player sheet, a saved Sleeper league, and the War Room. Leverage is not the full model yet. Championship odds appear only when they are computed from Sleeper. There are no payments.

## Run

From this folder:

```
python3 app.py
```

Then open http://127.0.0.1:8080

The screener is at http://127.0.0.1:8080/screener/ . It does not need an account.

Register with an email and a password (8 or more characters). Passwords are stored as a salted hash. The session is a cookie. The database is `data/razzle.db`, created on first run, and it is gitignored.

On Home, save a Sleeper username. Leagues are the 2025 NFL season from Sleeper. Pick one. The roster and any record or points on the page come from that league's Sleeper payload. If a championship number cannot be computed from those payloads, the page says odds are not computed yet.

A player sheet (`/player?name=`) reads `screener/data/nfl/2025.json` only. It does not fill in stats that are not in that file.

## War Room

The War Room answers only when `RAZZLE_MODEL_KEY` is set. Until then the page says the key is not set and does not make up a reply.

Optional:

- `RAZZLE_MODEL_URL` — defaults to `https://api.openai.com/v1/chat/completions`
- `RAZZLE_MODEL_NAME` — defaults to `gpt-4o-mini`

The question is sent with team names and roster names that were actually fetched for the saved league.
