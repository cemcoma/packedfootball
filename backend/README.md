# Backend (Cloud Run service)

Authoritative match simulation and pack opening. Reuses `gameEngine.py`,
`packEngine.py`, and `game_state.py` from `packedfootball/` unmodified; see
`admin_firestore_client.py` for how it plugs into `GameState` as a
service-account-backed client instead of the game client's own ID token.

## Deploying

Build via the repo-root `cloudbuild.yaml` (needed because the Dockerfile
lives in `backend/` but the build context has to be the repo root, to `COPY`
both `packedfootball/` and `backend/` -- `gcloud builds submit --tag` alone
can't point at a non-root Dockerfile):

```sh
gcloud builds submit --config cloudbuild.yaml .
```

Deploy it, in the same region as your Firestore database:

```sh
gcloud run deploy packedfootball-backend \
  --image gcr.io/<project-id>/packedfootball-backend \
  --region europe-west3 \
  --allow-unauthenticated \
  --max-instances 3 \
  --set-env-vars FIREBASE_PROJECT_ID=<project-id>
```

`--allow-unauthenticated` makes the HTTPS endpoint public; per-user auth is
still enforced in-app via each request's Firebase ID token
(`verify_id_token` in `main.py`), which is a separate layer from Cloud Run's
own IAM invoker check. `--max-instances` is a cheap guard against a runaway
bill. `FIREBASE_PROJECT_ID` defaults to `"packedfootball"` in code if unset,
but pass it explicitly so this doesn't silently drift if the project is ever
renamed/forked.

Grant the service's account Firestore access (if not already granted):

```sh
gcloud projects add-iam-policy-binding <project-id> \
  --member="serviceAccount:$(gcloud run services describe packedfootball-backend --region europe-west3 --format='value(spec.template.spec.serviceAccountName)')" \
  --role="roles/datastore.user"
```

On Cloud Run, the service's attached service account provides Application
Default Credentials automatically -- no key file needed.

## Scripts

Standalone admin tools, run locally against production Firestore (not part
of the deployed service) via the `firebase_admin` Python SDK + your own
Application Default Credentials -- both support `--dry-run` and are safe to
re-run any time:

- `scripts/sync_pack_definitions.py` -- pushes `packEngine.PACK_DATABASE`'s
  definitional fields (name/type/description/price/cards_per_pack/rates/
  pos_rates) onto existing `packs/{id}` docs, without touching operational
  fields (`active`, `times_opened`, `max_opens`, `expires_at`, `visible`,
  `available_at`) that only ever live in Firestore.
- `scripts/sync_player_appearance.py` -- backfills a placeholder
  `appearance` field onto `players/{id}` docs that predate it (anything
  newly generated already gets one from `PackManager._generate_appearance()`),
  using a fixed per-tier look so at least tiers read as visually distinct
  while testing.
- `scripts/list_accounts.py` -- read-only; lists every `users/{uid}` doc and
  whether its roster is complete enough to be a Quick Match candidate
  (`roster_player_ids` length == 11) -- a general "how many accounts, how
  complete are their rosters" check. Never writes anything.

## Match endpoints

- `POST /match/simulate` -- a deliberate ranked challenge (`opponent_uid`
  required, must be an existing account); updates wins/losses/draws.
- `POST /match/quick` -- Quick Match: no request body, always finds an
  opponent (a random real account with a complete roster, or a
  freshly-rolled bot if none is available/valid -- see
  `_pick_opponent_profile` in `main.py`), grants a credit reward scaled by
  outcome (`QUICK_MATCH_REWARD_CREDITS = {"win": 100, "draw": 25, "loss": 10}`),
  and updates wins/losses/draws. Both endpoints share
  `_run_match`/`_validate_formation_positions` and return the same shape
  (`score`, `replay`, `roster`, ...) for
  `mobile/scripts/screens/MatchPlayback.gd` to play back.

### No more `lobby` anywhere -- backend or Godot

Both endpoints used to gate opponent discovery through a `lobby/{uid}`
"opted in to being challenged" doc -- an extra collection that only ever
needed to answer "does this account exist and have a complete roster",
which `users/{uid}` already answers directly. Removed entirely:
`_pick_opponent_profile` calls `list_collection("users")` (filtering
candidates by `roster_player_ids` length), and `/match/simulate`'s
opponent-exists check reads `users/{opponent_uid}` instead of
`lobby/{opponent_uid}`. Nothing in `backend/main.py` reads or writes
`lobby`.

The original pygame/pygbag client (`packedfootball/main.py` and everything
only it needed -- `auth_scene.py`, `firebase_client.py`,
`firebase_config.example.py`, `native_form.py`) has been removed from the
repo entirely, which also took its `game_state.GameState.publish_lobby_entry`/
`list_opponents`/`list_leaderboard` (the only callers, now gone) and its
`elo` scaffolding (`DEFAULT_STARTING_ELO`, `GameState.set_elo`, the `elo`
field `load_or_create_profile` used to carry) down with it -- both were
kept around this far specifically because that client still depended on
them, and now nothing does. `packedfootball/` is backend-critical code
only now: `gameEngine.py`, `packEngine.py`, `game_state.py`, `formations.py`,
`replay.py`, `player/*`, plus `scripts/dump_test_replay.py` (Godot demo-replay
tooling, not part of the old client) and the `data/` name lists.

`GameProfile.gd` used to also *publish* to `lobby/{uid}` after every save
(leaderboard-relevant fields only, no roster), but that write had no
reader anywhere by that point -- nothing server-side or client-side ever
read `lobby` back, only wrote it -- so it's been deleted too (see
`mobile/README.md`). There is no `lobby` collection or code path left in
this project, client or server; `firestore.rules` no longer grants it any
access either. Leaderboards (sorting the actual player-card blobs, not
user accounts) will be built later by reading `players/{player_id}`
docs directly.

Both endpoints also call `_persist_player_stats` right after
`_run_match()`: each of the CALLER's own players' goals/assists/
matches_played (already correctly tracked *in memory* during simulation by
`player.py`'s `scored()`/`assisted()`/`match_played()`, called from
`gameEngine.py`'s `game`) get re-saved to their own `players/{id}` doc via
`GameState.save_roster()`. This was a real, pre-existing gap --
`/leaderboard/players` already queried `players/{id}.statistics.*`
directly, but nothing had ever written an updated value there, so every
card's stats stayed frozen at whatever they started at.

Both also embed a `"teams"` roster/formation snapshot (`_teams_snapshot`)
into the `games/{id}` doc at match start -- `/match/simulate` already did
this, `/match/quick` now does too, both sharing the same helper. The point
is specifically so a dispute or bug can be checked afterwards against
exactly what was actually played (formation, every player's full card
fields at that moment), independent of whatever either account's
`players/{id}` docs look like by the time anyone looks -- whether from
later, legitimate pack opens or from tampering.

Deliberately caller-only (by design decision, not an oversight): the
opponent -- real or bot -- never chose to play this specific match, so
their own players' stats are left untouched, same as neither endpoint has
ever updated the opponent's own account-level wins/losses/draws.

## Leaderboard endpoints

Both shaped the same way -- a `{stat: field_path}` allow-list dict, a
`stat` query param defaulting to whatever `mobile/scripts/screens/
Leaderboard.gd` actually shows, and `AdminFirestoreClient.query_top(...)`
(a plain Firestore `order_by(...).limit(...)`, no `where` clause, so it
needs no manually-defined composite index even on a dotted nested-field
path like `statistics.goals`) -- adding another rankable stat later to
either one is just another dict entry, not new plumbing:

- `GET /leaderboard/players` -- ranks `players/{id}` docs (`stat` in
  `goals`/`assists`/`matches_played`, defaults to `goals`). Existed
  already; see "Individual player stats" above for why its `statistics.*`
  fields are trustworthy now (they weren't always).
- `GET /leaderboard/users` -- ranks `users/{uid}` docs (`stat` in `wins`
  only, for now). New -- backs the mobile Leaderboard screen's Users tab
  (was the Pvp stub screen; see `mobile/README.md`).

Both just return `{"stat": ..., "entries": [...]}`, entries already in
rank order (index + 1 = rank -- neither response carries an explicit rank
field) -- deliberately minimal, proof-of-concept shaped for early testers
per the mobile client's own docstring; expect more stats and filtering
once there's real usage to design against.

## Still to do

- Tighten `firestore.rules` to deny direct client writes to
  `credits`/`roster`/`wins`/`losses`/`draws`/`campaign_level`/`inventory/*`,
  once a client actually calls this backend instead of writing Firestore
  directly.
- Tournament mode (1-day, 10-match bracket, 4 skill categories with
  promotion by winning) -- `mobile/scenes/Tournament.tscn` is an explicit
  stub for now, nothing server-side exists yet.
