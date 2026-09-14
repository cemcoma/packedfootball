# Backend (Cloud Run service)

FastAPI service holding everything the client isn't allowed to decide for
itself: match simulation, pack opening, currency balances, leaderboards.
Imports `gameEngine.py`, `packEngine.py` and `game_state.py` from
`packedfootball/` unmodified; `admin_firestore_client.py` plugs into
`GameState` as a service-account-backed client, which bypasses
`firestore.rules` entirely.

Auth is per-request: every endpoint except `/health` and the RevenueCat
webhook takes a Firebase ID token (`verify_id_token`).

## Tests

```sh
pip install -r backend/requirements.txt
pytest                # ~2 min; several cases simulate full 90-minute matches
```

`tests/` covers the match engine: goal frame and posts, restarts, the match
clock, statistics and ratings, the goalkeeper, stamina, height, and
seed reproducibility. `packedfootball/scripts/dump_test_replay.py --seed N
--out /tmp/x.bin` is the end-to-end smoke check (~9s for a full match).

## Running locally

Copy `.env.example` to `.env` (gitignored, and excluded from the Docker
build context by the repo-root `.dockerignore`) and fill in real values:

| Variable | Purpose |
| --- | --- |
| `FIREBASE_PROJECT_ID` | Firestore project. Defaults to `packedfootball` in code. |
| `REVENUECAT_WEBHOOK_SECRET` | Shared secret for `POST /webhooks/revenuecat`. Fails closed if unset. Generate your own (`openssl rand -hex 32`). |

```sh
pip install -r backend/requirements.txt
uvicorn main:app --reload --app-dir backend
```

`main.py` calls `load_dotenv()` at import, which fills `os.environ` from
that file without overriding anything already set.

## Deploying

Two steps. **The deploy step alone does not rebuild** -- it redeploys
whatever `:latest` already points at, so skipping the build ships stale code.

```sh
gcloud builds submit --config cloudbuild.yaml .

gcloud run deploy packedfootball-backend \
  --image gcr.io/<project-id>/packedfootball-backend \
  --region europe-west3 \
  --allow-unauthenticated \
  --max-instances 3 \
  --env-vars-file backend/.env
```

Deploy to the same region as your Firestore database. `gcloud builds
submit .` uploads your working tree, not `HEAD`, so uncommitted changes do
ship.

`--env-vars-file` takes the same dotenv file used locally. It **replaces
the whole env var list on every deploy**, so `backend/.env` must hold every
variable the service needs -- a one-off `--set-env-vars FOO=bar` silently
drops everything not named in that command.

`--allow-unauthenticated` makes the HTTPS endpoint public; per-user auth is
enforced in-app via each request's Firebase ID token, separately from Cloud
Run's IAM invoker check.

Grant the service account Firestore access (once):

```sh
gcloud projects add-iam-policy-binding <project-id> \
  --member="serviceAccount:$(gcloud run services describe packedfootball-backend --region europe-west3 --format='value(spec.template.spec.serviceAccountName)')" \
  --role="roles/datastore.user"
```

On Cloud Run the attached service account supplies Application Default
Credentials automatically -- no key file.

## Endpoints

| Endpoint | What it does |
| --- | --- |
| `GET /health` | Liveness check. |
| `POST /account/bootstrap` | Idempotent. Creates the profile plus an 11-card bronze starter roster on a uid's first ever call; no-op afterwards. |
| `GET /pack/list` | Live pack catalog, filtered by availability. |
| `POST /pack/open` | Charges the pack's currency, rolls cards, writes them. |
| `GET /currency/exchange/list` | Bucks -> credits tiers. |
| `POST /currency/exchange/redeem` | Spends bucks, grants credits. |
| `GET /currency/bucks/list` | Real-money bucks catalog (product ids for RevenueCat). |
| `POST /webhooks/revenuecat` | Grants bucks after a verified purchase. Called by RevenueCat, not the client. |
| `GET /deals/list` | Timed offers, with per-caller availability. |
| `POST /deals/redeem` | Spends a deal's cost currency, grants its rewards. |
| `GET /leaderboard/players` | Ranks `players/{id}` by `goals`/`assists`/`matches_played`. |
| `GET /leaderboard/users` | Ranks `users/{uid}` by `wins`. |
| `POST /match/quick` | Finds an opponent (real account or bot), simulates, rewards, persists. |
| `POST /match/simulate` | Ranked challenge against a named `opponent_uid`. |

Both leaderboard endpoints return `{"stat": ..., "entries": [...]}` already
in rank order; index + 1 is the rank, there's no explicit rank field. They
use a plain `order_by(...).limit(...)`, so no composite index is needed even
on a nested path like `statistics.goals`.

### Matches

Both match endpoints share `_run_match` / `_validate_formation_positions`
and return the same shape (`score`, `replay`, `roster`, ...) for
`mobile/scripts/screens/MatchPlayback.gd` to play back. Both reject a
roster/formation pairing that isn't exact-or-similar-position legal for
every slot, before writing anything.

After simulating, both:

- Persist the **caller's own** players' statistics back to `players/{id}`
  (`_persist_player_stats`). The opponent -- real or bot -- never chose to
  play this match, so their cards and their account-level wins/losses/draws
  stay untouched.
- Snapshot both sides' roster and formation into the `games/{id}` doc
  (`_teams_snapshot`), so a match can be audited later against exactly what
  was played, independent of what those cards look like by then.

Quick Match grants a credit reward scaled by outcome
(`QUICK_MATCH_REWARD_CREDITS = {"win": 100, "draw": 25, "loss": 10}`) and
records wins/losses/draws.

Both responses carry `engine_version`, `replay_format_version` and
`added_time` (clock seconds per half), and both stamp the two versions onto
the `games/{id}` doc alongside the seed -- see Engine versioning below.

### Match statistics and ratings

Cards track `goals`, `assists`, `matches_played`, `shots`,
`shots_on_target`, `passes`, `passes_completed`, `tackles`, `tackles_won`,
`saves`, `clean_sheets`, `goals_conceded`, plus `rating_sum`/`rating_count`
backing `player.average_rating()`.

The engine counts each match separately (`game.match_stats`) and folds the
totals into the cards at full time, so a per-match **rating** can be
computed from what happened in *that* match rather than from career totals.
Rating starts at a 6.0 baseline; keepers are scored on saves, goals conceded
and clean sheets rather than shots and passes.

A shot counts as on target when it actually reaches the frame -- a goal, or
a save -- not from where the shooter aimed. A pass counts as completed when
a teammate brings it under control; a defender who merely deflects it gets
nothing.

**No backward compatibility with pre-statistics cards.** `fields_to_player`
indexes `fields["statistics"]` directly, so a `players/{id}` doc written
before these fields existed raises rather than loading half-populated. Those
cards were deleted rather than migrated. Note `games/{id}.teams` still
embeds whatever `player_to_fields` produced at the time -- it is written but
never read back today, so a future admin panel reading historical snapshots
has to tolerate the older shape itself.

### Match length and stoppage time

`max_steps` is **regulation** length in clock frames (10800 == 90:00), and
added time is played on top of it. The loop advances on `match_clock_frames`
rather than counting iterations, because the halftime pause deliberately
does not advance the clock -- counting iterations is what made every match
end at exactly 88:30.

Added time is computed per half from that half's own stoppages (goals,
throw-ins, corners, goal kicks, woodwork), with seeded jitter, and capped by
`ADDED_TIME_MAX_FRAMES`. A typical match now runs to roughly 92-94 minutes.

### Engine versioning

`gameEngine.ENGINE_VERSION` is stamped onto every `games/{id}` document
along with `replay.FORMAT_VERSION` and the existing `seed`. Seed + engine
version together reproduce a reported match exactly, which is what makes a
bug report or a dispute investigable after the engine has moved on.

It is a **string**, `MAJOR.MINOR.PATCH` (currently `"2.1.0"`) -- bump it
whenever match behaviour changes:

| | means | effect on a stored match |
| --- | --- | --- |
| MAJOR | the sim was reshaped | an old seed replays into a different match; old results aren't comparable |
| MINOR | balance, or a new mechanic | an old seed replays differently, but stats and wire format still mean the same thing |
| PATCH | a fix that doesn't change how a match is meant to play | seeds may still diverge if the bug was in the sim itself |

The full history lives in the comment above the constant in
`packedfootball/gameEngine.py`.

**Pack generation is seed-reproducible across processes.** It briefly wasn't:
`packEngine` rolled attributes by iterating a `set`, and Python randomises
string hashing per process, so the same pack seed produced different cards on
every run. `tests/test_determinism.py` pins this.

### Pack availability

`packs/{id}` carries definitional fields (name, type, description, price,
`price_currency`, cards_per_pack, rates, pos_rates) plus operational fields
that live **only** in Firestore and are never written by a deploy:

- `active` -- must be `true` or the pack is unavailable. **Absent counts as
  false.**
- `max_opens` / `times_opened` -- a hard cap on total opens.
- `expires_at` -- ISO datetime after which it can't be opened.
- `visible` / `available_at` -- opt an unavailable pack into still being
  *shown*, grayed out with a tag, instead of hidden. A display hint only;
  neither auto-flips `active`.

`_pack_unavailable_reason` and `_pack_is_teased` are shared by `/pack/list`
(filters what's shown) and `/pack/open` (rejects a purchase), so the two
can't disagree. An unavailable, un-teased pack is dropped from
`/pack/list` entirely.

### Pack pricing currencies

A pack is bought with **exactly one** currency, never a combination.
`packs/{id}.price_currency` is `"credits"`, `"bucks"` or `"medals"`; absent
means credits, so packs predating the field need no migration.
`PACK_PRICE_CURRENCIES` in `main.py` is the allow-list, and it's exactly the
three balance fields on `users/{uid}` because `/pack/open` indexes the
profile with that name to both check and deduct.

`/pack/open` returns **all three** balances so the client doesn't have to
guess which one moved. Set `price_currency` in `PACK_DATABASE` and
`sync_pack_definitions.py` carries it across.

Nothing grants medals yet (Tournament mode doesn't exist), so a
medals-priced pack is visible but unbuyable.

### Currencies

Three balances on `users/{uid}`: `credits` (soft, earned from matches),
`bucks` (hard, real-money, also spendable on credits), `medals` (tournament
only -- nothing grants these yet). All three are backend-only writes
(`GameState.set_credits`/`set_bucks`/`set_medals`); `firestore.rules` blocks
the client from writing them directly.

`CREDIT_EXCHANGE_RATES` and `BUCKS_IAP_CATALOG` are code constants in
`main.py`, not Firestore-backed -- changing them takes a redeploy, which is
the intent. Exchange redemption writes both new balances in one combined
`update_profile_fields` call, so a crash mid-redeem can't deduct bucks
without the credits landing, and it re-validates the balance server-side
rather than trusting the client's affordability check.

### RevenueCat webhook

[RevenueCat](https://www.revenuecat.com) verifies the purchase with
Apple/Google and calls `POST /webhooks/revenuecat` server-to-server --
the client never forwards a receipt, and the grant lands whether or not the
client is still running.

- Configure the URL in RevenueCat's dashboard as
  `<BACKEND_URL>/webhooks/revenuecat`.
- Set its "Authorization header value" to the same string as
  `REVENUECAT_WEBHOOK_SECRET`. `verify_revenuecat_webhook` compares them in
  constant time and fails closed if the env var is unset.
- RevenueCat's `app_user_id` must be the Firebase uid -- that's how the
  webhook knows which account to credit.
- Only `NON_RENEWING_PURCHASE` (RevenueCat's term for a consumable) is
  handled. Every other event type gets a 200 "ignored" rather than an error,
  because RevenueCat retries non-2xx responses indefinitely.
- `iap_transactions/{event_id}` is the anti-replay guard.

### Deals

`deals/{deal_id}` docs, structurally a cousin of packs: same
`active`/`expires_at`/`visible`/`available_at` convention, checked by
`_deal_unavailable_reason` (async, because the per-account cap needs a real
Firestore read). Rewards are currency-only (`reward_credits`/
`reward_bucks`). Shared by `/deals/list` and `/deals/redeem`, so a deal
you've personally exhausted shows a reason instead of a Buy button while
still being live for everyone else.

Two independent, optional caps:

- `max_redemptions` / `times_redeemed` -- global.
- `max_redemptions_per_account` -- per uid, tracked in a
  `deals/{id}/redemptions/{uid}` subcollection.

A deal can set either, both, or neither.

## Scripts

Standalone admin tools, run locally against production Firestore via
`firebase_admin` + your own Application Default Credentials. Not part of the
deployed image. The `sync_*` scripts support `--dry-run` and are safe to
re-run.

```sh
python3 backend/scripts/<script>.py [--dry-run]
```

| Script | What it does |
| --- | --- |
| `sync_pack_definitions.py` | Pushes `packEngine.PACK_DATABASE`'s definitional fields onto existing `packs/{id}` docs. Never touches operational fields. `--pack-id N` for one pack. Skips ids with no existing doc. |
| `sync_deal_definitions.py` | Same for `packedfootball/deal_database.py`'s `DEAL_DATABASE` -> `deals/{id}`. Unlike the pack version it *creates* missing docs, seeded `active: false`; `--activate-new` seeds them `active: true` instead. Never changes an existing doc's `active`. |
| `sync_player_appearance.py` | Backfills a placeholder `appearance` onto `players/{id}` docs that predate the field. |
| `list_packs.py` | Read-only dump of live `packs/{id}` docs. `--pack-id N` for one. |
| `list_deals.py` | Read-only dump of live `deals/{id}` docs. |
| `list_accounts.py` | Read-only. Lists every `users/{uid}` and whether its roster is Quick-Match complete (`roster_player_ids` length == 11). |

A synced deal left `active: false` won't appear in `GET /deals/list` until
you flip it, in the Firestore console or via `--activate-new` on first sync.

## Firestore rules

`users/{uid}` `update` is an **allow-list**: `display_name`,
`roster_player_ids`, `formation` -- the only three fields the client writes
directly. Everything else on that doc (all three currencies, wins/losses/
draws, anything added later) is deny-by-default. `create` and `delete` are
`false`; the only legitimate creation path is `POST /account/bootstrap` via
the Admin SDK.

`players/{playerId}` denies client `create`/`update`/`delete` outright --
the client only reads its own cards, and every mutation goes through
`GameState._ensure_player_doc` on the Admin SDK. This matters because
`gameEngine.py` trusts stored attributes with no server-side
re-validation.

`inventory/*` is its own explicit `match` (client-writable, for
`Team.gd`'s `save_team()`) rather than a `{subcollection=**}` wildcard, so
any future subcollection starts denied.

`packs`, `deals` and `iap_transactions` have no `match` block at all --
Firestore's default-deny covers them, and only the Admin SDK touches them.

## Waiting on a frontend pass

The engine produces these; nothing displays them yet.

- **Added time** -- `added_time` in both match responses, clock seconds per
  half. Wants a "+3" at the end of each half.
- **Post and crossbar rebounds** -- the ball now bounces off the frame and
  stays live. No replay event is emitted for it (that would mean a new
  `ActionType`, which has to be mirrored into `ReplayReader.gd`), so a
  rebound currently plays back as ordinary ball movement.
- **Match stats and ratings** -- every card carries shots, passes, tackles,
  saves, clean sheets and an average rating. Only goals/assists/matches are
  shown today.
- **Stamina** -- live per-match, 0-100, and it already slows tired players.
  Not surfaced anywhere.
- **Height** -- generated and persisted, nothing reads it yet. It is the
  foundation for headers, free kicks and shots over players.

## Not built yet

Tournament mode: a 1-day, 10-match bracket per entry, 4 skill categories
with promotion by winning, matched against similarly-ranked players rather
than Quick Match's random pool. `mobile/scenes/Tournament.tscn` is a stub
and nothing server-side exists. Medals have nowhere to be earned until it
ships.
