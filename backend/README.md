# Backend (Cloud Run service)

Authoritative match simulation and pack opening. Reuses `gameEngine.py`,
`packEngine.py`, and `game_state.py` from `packedfootball/` unmodified; see
`admin_firestore_client.py` for how it plugs into `GameState` as a
service-account-backed client instead of the game client's own ID token.

## Local development

Copy `.env.example` to `.env` (gitignored, and excluded from the Docker
build context via the repo-root `.dockerignore` -- never baked into the
deployed image either way) and fill in real values, then run:

```sh
pip install -r backend/requirements.txt
uvicorn main:app --reload --app-dir backend
```

`main.py` calls `load_dotenv()` right at the top, which fills in
`os.environ` from that file -- but never overrides a variable that's
already set (`python-dotenv`'s own default), so this changes nothing about
the deployed service below, which gets its real values via
`--set-env-vars`/`--set-secrets` and has no `.env` file in the image at
all. `.env` is purely a local shortcut so `uvicorn` works without
exporting a dozen variables by hand first -- as more secrets show up
(RevenueCat today, others later), add them to both `.env.example`
(placeholder) and the real deploy command below (real value), same as
`REVENUECAT_WEBHOOK_SECRET` did.

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
  --env-vars-file backend/.env
```

`--env-vars-file` reads the exact same `backend/.env` used for local development above (`gcloud` accepts plain dotenv-format files directly, not just YAML) -- one file, kept up to date, used both places, rather than retyping values into a `--set-env-vars` list by hand.

**Replaces the whole env var list on every use** -- `gcloud` removes every existing environment variable on the service before applying the file's, so `backend/.env` needs to hold *every* variable the service actually needs, not just the one you're currently changing. Point every future deploy/update at the same file for exactly this reason: a one-off `--set-env-vars SOME_VAR=value` on an update call would silently wipe out any other var not named in that command (this already happened once here with `FIREBASE_PROJECT_ID` -- harmless only because its code-level default already matches the real project id).

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
- `scripts/sync_deal_definitions.py` -- the Deals-tab counterpart to
  `sync_pack_definitions.py`, pushing `packedfootball/deal_database.py`'s
  `DEAL_DATABASE` (name/description/cost_currency/cost_amount/
  reward_credits/reward_bucks) onto `deals/{deal_id}` docs, same
  operational-fields-stay-in-Firestore-only rule. Unlike the pack version,
  a deal id with no existing doc gets one *created* (seeded `active: false`
  by default -- pass `--activate-new` to seed it `active: true` instead;
  either way this never touches an *existing* doc's `active` value) rather
  than skipped -- there's no separate one-time `seed_deals.py`. A synced
  deal that stays `active: false` won't appear in `GET /deals/list` at all
  (same as an inactive pack) until you flip it, in the Firestore console or
  via `--activate-new` on its first sync.
- `scripts/list_deals.py` -- read-only counterpart to `list_packs.py`, for
  inspecting live `deals/{id}` docs.
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

## Pack pricing currencies

A pack is bought with **exactly one** currency, never a combination --
that's what keeps this a single Firestore field rather than a cost map.
`packs/{id}.price_currency` is `"credits"`, `"bucks"` or `"medals"`, and an
absent value means credits, so every pack that predates the field keeps
working with **no migration**. `PACK_PRICE_CURRENCIES` in `main.py` is the
allow-list, and it's deliberately exactly the three balance fields on
`users/{uid}`, since `/pack/open` both checks and deducts by indexing the
profile with that name.

`/pack/open` validates the currency (500 for a misconfigured pack), checks
that specific balance (402 `"Not enough medals"`), deducts from it via
`update_profile_fields`, and returns **all three** balances so the client
doesn't have to guess which one moved. Add `price_currency` to a pack in
`PACK_DATABASE` and `sync_pack_definitions.py` carries it across; omit it
for ordinary credit-priced packs.

**Nothing grants medals yet** -- Tournament mode is still a stub -- so a
medals-priced pack is visible but unbuyable by everyone until that ships.
The existing teased-pack fields (`visible`/`available_at`) are the natural
way to show one as coming soon in the meantime.

## Currency endpoints

Three currencies live on `users/{uid}`: `credits` (existing, soft), `bucks`
(new -- hard, real-money purchased, also spendable on credits), `medals`
(new -- schema only for now; nothing grants these yet, the same state
`campaign_level` used to be in before it was deleted as dead code -- zero
callers anywhere, confirmed by a repo-wide grep, and not part of the next
iteration of the game). All three are backend-only writes
(`GameState.set_credits`/`set_bucks`/`set_medals`), same as credits already
was -- see `firestore.rules`.

- `GET /currency/exchange/list` / `POST /currency/exchange/redeem` -- the
  Credits Exchange tab. Fixed, code-defined rates (`CREDIT_EXCHANGE_RATES`
  in `main.py`), not Firestore-backed like packs/deals, since these aren't
  meant to be admin-editable without a redeploy. Spends bucks, grants
  credits, one combined `update_profile_fields` write so a crash mid-redeem
  can't leave bucks deducted with the credits reward never landing, and
  re-validates the bucks balance server-side (never trusts the client's own
  affordability check, same principle `/pack/open` already follows for
  credits).
- `GET /currency/bucks/list` -- the Bucks tab's real-money catalog.
  `BUCKS_IAP_CATALOG` maps a product id to a bucks amount; the client passes
  that product id to RevenueCat's SDK to start a real purchase (see
  `mobile/scripts/autoload/IapClient.gd`).
- `POST /webhooks/revenuecat` -- grants bucks for a real-money purchase.
  **Not the client calling this** -- [RevenueCat](https://www.revenuecat.com)
  verifies the purchase with Apple/Google itself and calls this directly,
  server-to-server, independent of whether the client that made the
  purchase is even still running by the time it lands. Gated by
  `verify_revenuecat_webhook` (a `Depends`, same shape as `verify_id_token`
  elsewhere in this file): RevenueCat signs webhook requests with whatever
  literal string is configured as the "Authorization header value" in
  their dashboard, checked here against the `REVENUECAT_WEBHOOK_SECRET` env
  var via a constant-time comparison, failing closed if that env var isn't
  set at all. Only handles the `NON_RENEWING_PURCHASE` event type (that's
  RevenueCat's term for a consumable/one-time purchase -- exactly what a
  bucks top-up is, not a subscription); any other event type gets a 200
  "ignored" response rather than an error, since RevenueCat retries non-2xx
  responses indefinitely and an event type this endpoint will never handle
  should never end up in an infinite retry loop. `iap_transactions/{event_id}`
  is the anti-replay guard -- same mechanism a previous, now-removed
  direct-Apple-verification design already used, just keyed by RevenueCat's
  own event id instead of a raw platform transaction id.

  Webhook URL to configure in RevenueCat's dashboard:
  `<BACKEND_URL>/webhooks/revenuecat`. Needs `REVENUECAT_WEBHOOK_SECRET` set
  as a Cloud Run env var/secret, matching whatever string is entered as the
  Authorization header value on RevenueCat's side -- an arbitrary shared
  secret you choose, not something RevenueCat generates for you.

- `GET /deals/list` / `POST /deals/redeem` -- the Deals tab, DB-based timed
  offers, direct structural cousin of packs: `deals/{deal_id}` Firestore
  docs with the same `active`/`expires_at`/`visible`/`available_at`
  operational-fields convention (see `_deal_unavailable_reason`, an async
  version of `_pack_unavailable_reason` -- async because the new
  `max_redemptions_per_account` cap needs a real Firestore read that packs'
  global-only `max_redemptions` cap never needed). Both caps are optional
  and independent -- a deal can set a global cap, a per-account cap, both,
  or neither. Rewards are currency-only for now (`reward_credits`/
  `reward_bucks`) -- no free packs/cards yet, an easy later extension. See
  the Scripts section above for `deal_database.py` + its sync/list scripts.

## Still to do

- ~~Tighten `firestore.rules`~~ -- done. `users/{uid}`'s `update` rule is
  now an allow-list (`display_name`/`roster_player_ids`/`formation` only,
  the exact 3 fields the client ever writes there directly -- confirmed by
  grepping every `Firestore.set_document`/`add_document`/`delete_document`
  call site in `mobile/scripts/`), so `credits`/`bucks`/`medals`/`wins`/
  `losses`/`draws` are all backend-only now, and any future sensitive field
  added to this doc is deny-by-default automatically rather than needing
  its own rule update. `players/{playerId}` similarly denies client
  `create`/`update`/`delete` outright -- the client only ever reads its own
  cards directly, every mutation already went through
  `GameState._ensure_player_doc` via the Admin SDK, so this was pure
  unused-but-exploitable surface (a modified client could previously
  rewrite its own card's tier/attributes to anything).
- Tournament mode (1-day, 10-match bracket, 4 skill categories with
  promotion by winning) -- `mobile/scenes/Tournament.tscn` is an explicit
  stub for now, nothing server-side exists yet. Medals (see Currency
  endpoints above) have nowhere to be earned until this exists.
