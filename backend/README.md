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
  whether it has a published `lobby/{uid}` entry. That second column is
  vestigial now (see "No more `lobby` in the backend" below) -- kept
  useful as a general "how many accounts, how complete are their rosters"
  check, just no longer describing the actual Quick Match opponent pool
  (which now comes straight from `users/{uid}`, no `lobby` step at all).
  Never writes anything.

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

### No more `lobby` in the backend

Both endpoints used to gate opponent discovery through a `lobby/{uid}`
"opted in to being challenged" doc -- an extra collection that only ever
needed to answer "does this account exist and have a complete roster",
which `users/{uid}` already answers directly. Removed entirely:
`_pick_opponent_profile` now calls `list_collection("users")` (filtering
candidates by `roster_player_ids` length) instead of `list_collection("lobby")`,
and `/match/simulate`'s opponent-exists check reads `users/{opponent_uid}`
instead of `lobby/{opponent_uid}`. Nothing in `backend/main.py` reads or
writes `lobby` anymore.

Deliberately not touched: `GameProfile.gd` still *publishes* to
`lobby/{uid}` after every save (leaderboard-relevant fields only, no
roster -- see `mobile/README.md`), and `packedfootball/game_state.py`'s own
`publish_lobby_entry`/`list_opponents`/`list_leaderboard` (the legacy
pygame client's independent, already-scrapped write/read path) still use
it too. Whether Godot should keep publishing to a collection the backend
no longer reads at all is worth a follow-up call.

Neither match endpoint touches elo at all -- removed from the active
system entirely (no computation, no storage, no field on `GameProfile.gd`
or in what gets published to `lobby/{uid}`). `packedfootball/game_state.py`'s
own elo scaffolding (`DEFAULT_STARTING_ELO`, `GameState.set_elo`, the `elo`
field its `load_or_create_profile`/`publish_lobby_entry`/`list_opponents`/
`list_leaderboard` all carry) is deliberately left alone, for the same
reason as `lobby` itself: `packedfootball/main.py` still depends on it for
its own local elo-based UI, even though it's not part of the active system.

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

## Still to do

- Tighten `firestore.rules` to deny direct client writes to
  `credits`/`roster`/`wins`/`losses`/`draws`/`campaign_level`/`inventory/*`,
  once a client actually calls this backend instead of writing Firestore
  directly.
- Tournament mode (1-day, 10-match bracket, 4 skill categories with
  promotion by winning) -- `mobile/scenes/Tournament.tscn` is an explicit
  stub for now, nothing server-side exists yet.
