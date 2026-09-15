# Packed Football

A PvP football manager game built around opening packs: open packs to get
stronger players, build a squad, play matches. Special players are awarded
around real footballing events (UCL, World Cup).

Work in progress.

| Area | Progress |
| --- | --- |
| Immersive gameplay (agents deciding in real time, tendencies, hidden stats) | 90% |
| Pack mechanics | 90% |
| Social mechanics | 5% |
| PvP | 95% |

## Repo layout

- **`mobile/`** -- the Godot 4.7 client (landscape, iOS-first).
  See [mobile/README.md](mobile/README.md).
- **`backend/`** -- FastAPI service on Cloud Run: authoritative match
  simulation, pack opening, currency, leaderboards.
  See [backend/README.md](backend/README.md).
- **`packedfootball/`** -- shared game logic the backend imports:
  `gameEngine.py`, `packEngine.py`, `game_state.py`, `formations.py`,
  `replay.py`, `deal_database.py`, plus `player/` and the `data/` name lists.
- **`firestore.rules`** -- Firestore security rules.
- **`cloudbuild.yaml`** -- container build for the backend (context is the
  repo root, so it can copy both `backend/` and `packedfootball/`).

## Running it

Backend: see [backend/README.md](backend/README.md).
Client: see [mobile/README.md](mobile/README.md).

Deploy rules with:

```sh
firebase deploy --only firestore:rules
```

## Web test build

The `Makefile` exports the Godot client to the web and publishes it to
GitHub Pages. **Testing only** -- real-money purchases are absent on web
(the Shop's Cash tab hides itself there), everything else works normally.

```sh
make web         # export to mobile/build/web/
make serve-web   # export, then serve at http://localhost:8060
make deploy-web  # export, then push to the gh-pages branch
make clean-web   # remove mobile/build/
```

Needs the Godot editor binary and web export templates. Override the
binary path with `make web GODOT=/path/to/Godot.app/Contents/MacOS/Godot`.
