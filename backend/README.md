# Backend (Cloud Run service)

FastAPI service holding everything the client isn't allowed to decide for
itself: match simulation, pack opening, currency balances, energy, daily
tournaments, leaderboards, account lifecycle. Imports `gameEngine.py`,
`packEngine.py` and `game_state.py` from `packedfootball/` unmodified;
`admin_firestore_client.py` plugs into `GameState` as a service-account-
backed client, which bypasses `firestore.rules` entirely.

Layout: `main.py` mounts one router per area from `routers/`; the work an
endpoint delegates to lives in `services/` (match simulation, energy,
tournament rules, account rules), where the rule-like parts are pure
functions covered by `tests/`; `config.py` holds every tunable.

Auth is per-request: every endpoint takes a Firebase ID token
(`verify_id_token`) except `/health`, `GET /account/name_available`, the
RevenueCat webhook (shared secret) and `POST /tournament/settle` (its own
shared secret, for Cloud Scheduler).

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
| `TOURNAMENT_ADMIN_SECRET` | Shared secret for `POST /tournament/settle` (Cloud Scheduler). Fails closed if unset. |

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
| `GET /account/name_available` | Unauthenticated. Whether `?display_name=` passes the rules and is free -- the registration form asks before creating the Auth user. Advisory only. |
| `POST /account/display_name` | Renames the manager, uniquely: reserves `display_names/{key}` in the same transaction as the name. 400 with a reason code, 409 when taken. |
| `POST /claim` | One door for every reward that is earned silently and paid on a tap. Body `{"type": ...}` plus what the type needs; today `tournament_full_day` (optional `day_id` + `group_id`, default today's entry). Pays once, returns `rewards` and every `*_remaining` balance. |
| `DELETE /account` | Deletes the account: profile, inventory, every owned card, games it started, its name reservation, its seat in an unsettled tournament group, then the Firebase Auth user (last, so a failed attempt can be retried). Keeps `iap_transactions` and games it only played in as the opponent. Backfill old accounts' name reservations with `scripts/sync_display_names.py`. |
| `GET /pack/list` | Live pack catalog, filtered by availability; puts a pack whose `available_at` has passed on sale as a side effect (see Pack availability). |
| `POST /pack/open` | Charges the pack's currency, rolls cards, writes them. Refuses when the bench can't hold the whole pack (`INVENTORY_CAP`). |
| `POST /player/release`, `/player/release/batch` | Sells cards back for credits by tier family (`RELEASE_CREDITS_BY_TIER`); a starting-XI card is refused. Batch is one transaction, at most `RELEASE_BATCH_MAX`. |
| `POST /player/customize` | Changes appearance slots, `CUSTOMIZE_CREDITS_PER_SLOT` each; indices validated against `APPEARANCE_OPTION_COUNTS`. |
| `GET /currency/exchange/list` | Bucks -> credits tiers. |
| `POST /currency/exchange/redeem` | Spends bucks, grants credits. |
| `GET /currency/bucks/list` | Real-money bucks catalog (product ids for RevenueCat). |
| `POST /webhooks/revenuecat` | Grants bucks after a verified purchase. Called by RevenueCat, not the client. |
| `GET /energy`, `GET /energy/refill/list`, `POST /energy/refill` | The energy bar (regenerates `ENERGY_REGEN_SECONDS` per point up to `ENERGY_MAX`), and buying it back. |
| `POST /ads/reward` | Grants the next step of a rewarded-ad track (`reward` or `energy`), with a daily cap that resets on the tournament day boundary. |
| `GET /deals/list` | Timed offers, with per-caller availability. |
| `POST /deals/redeem` | Spends a deal's cost currency, grants its rewards. |
| `GET /leaderboard/players` | Ranks `players/{id}` by `goals` / `assists` / `avg_rating` / `clean_sheets` / `matches_played`, `LEADERBOARD_PAGE_SIZE` a page (`?page=N`, zero-based), optionally narrowed with `?position=ST` or a family (`attacker`); entries carry their absolute `rank` and the card's `owner_uid`. |
| `GET /leaderboard/users` | Ranks `users/{uid}` by `wins`, same paging; entries carry `wins`/`draws`/`losses` and `is_me`. |
| `GET /manager/{uid}` | Another manager as everyone may see them: name, record, tournament tier, kit, and their XI in formation order. What a leaderboard row opens. 404 for an unknown uid, never creates a profile. |
| `POST /match/quick` | Finds an opponent (real account or bot), spends energy, simulates, rewards, persists. |
| `POST /match/simulate` | Ranked challenge against a named `opponent_uid`. |
| `POST /match/report` | Files a bug report against a match the caller played: `game_id`, a `category` from `MATCH_REPORT_CATEGORIES`, optional text. One `match_reports/{game_id}_{uid}` doc per player per match, carrying the game's seed and engine version; the rosters as played are already on `games/{id}.teams`, so the match can be re-run exactly. Triage with `scripts/list_match_reports.py`. |
| `GET /tournament/today` | Everything the tournament screen needs in one response; settles any overdue day first and carries yesterday's result in `pending_results`. |
| `POST /tournament/join` | Joins today's group in the caller's tier. Refused in the last hour of the day. |
| `POST /tournament/match` | One of the day's `TOURNAMENT_MATCHES_PER_DAY` matches against someone in the same tier's pool (or a tier-appropriate bot). |
| `GET /tournament/results` | A settled day's final table for the caller's group. |
| `POST /tournament/settle` | Scheduler/admin: settles the lookback window, or one `day_id`. |

Both leaderboard endpoints return `{"stat", "page", "page_size",
"has_more", "entries": [...]}` in rank order, one extra row fetched to
answer `has_more`. Unfiltered they use a plain
`order_by(...).offset(...).limit(...)`, which needs no composite index even
on a nested path like `statistics.goals`; the offset costs the skipped rows
as reads, which at ten a page is nothing.

The **position filter** (`where position == / in` plus the order) does
need a composite index per stat. They're declared in the repo-root
`firestore.indexes.json` (`firebase.json` points at it) and ship with
`firebase deploy --only firestore:indexes` -- a stat added to
`PLAYER_LEADERBOARD_STATS` needs an entry there too, or the filtered query
fails with a link to create the missing index.

`avg_rating` is not a counter: `player.py`'s `record_match` writes
`statistics.avg_rating` as a plain field once a card has
`RATED_MATCHES_FOR_AVERAGE` (5) rated matches, because Firestore can't
order on `rating_sum / rating_count`. Cards under the threshold have no
field and are simply absent from that board. `scripts/backfill_avg_rating.py`
fills it in for cards that crossed the line before the field existed.

### Tiers

A card's `tier` is `"<family>"` or `"<family>_<variant>"`: `special_champ`
is a special, a future `diamond_turkish` would be a diamond.
`packEngine.tier_family()` (mirrored by `PlayerCard.tier_family()` on the
client) is the collapse, and everything that treats a tier as a rarity --
release value, card colour, ordering, the pack-odds disclosure -- goes by
the family. The variant only picks the card art and, in `TIER_RANGES`, the
overall range. Adding a variant is a `TIER_RANGES` entry plus a sprite; a
new family also needs rows in `RELEASE_CREDITS_BY_TIER` and the client's
`PlayerCard.TIER_COLORS` / `RELEASE_CREDITS`. Renaming a key means
`scripts/rename_tiers.py` for the cards already out there.

### Daily tournaments

Everyone in a tier is grouped into `tournaments/{day}/groups/{id}` of
`TOURNAMENT_GROUP_CAPACITY` as they join (the tier's *desk* document points
at the group being filled, so a join is a path read, not a query). A day
runs noon-to-noon Istanbul (`TOURNAMENT_DAY_OFFSET_HOURS`), and each player
gets `TOURNAMENT_MATCHES_PER_DAY` matches, each costing one energy.

Settlement is **lazy**: the first request of any kind after a day ends
settles it (`ensure_settled_through`, capped per request so it can't stall
a player's own call), and Cloud Scheduler's `POST /tournament/settle` makes
it punctual. `settle_group` is one idempotent transaction per group: the
`settlement.status` token, the payouts (as `Increment`, never
read-compute-write) and the tier moves land together or not at all.

The rules are pure functions in `services/tournament.py`, tested in
`tests/test_tournament_rules.py`:

- **Full group** -- positional: `TOURNAMENT_PROMOTE_POSITIONS` go up if
  they also reach `TOURNAMENT_PROMOTION_FLOOR` (16), `RELEGATE_POSITIONS` go
  down regardless.
- **Short group** -- thresholds: on or over the floor goes up, under
  `TOURNAMENT_RELEGATION_FLOOR` (8) goes down. Promotion needs at least
  `TOURNAMENT_MIN_GROUP_FOR_PROMOTION` players in the group.
- **Rewards** (`TOURNAMENT_REWARDS`) pay **every position by position**, not
  by whether the player promoted: medals and, on the tier 1 podium, bucks
  at the top, credits down to last place. A player who played nothing is
  paid nothing.
- **Full-day bonus** (`TOURNAMENT_FULL_DAY_REWARD`) for playing every match
  of the day. Earned silently, paid only through `POST /claim`
  (`type: "tournament_full_day"`), once -- `full_day_claimed` on the entry
  and the payout flip in one transaction.

`POST /claim` is the one door for anything earned-then-tapped;
`routers/claims.py`'s `CLAIM_HANDLERS` is where the next claimable type
goes.

### Accounts

Display names are **unique**, case- and spacing-insensitive
(`services/account.py`): `display_names/{key}` reservations are written in
the same transaction as the name, and `firestore.rules` no longer lets the
client write `display_name` directly, so nothing can skip the reservation.
`GET /account/name_available` lets the registration form ask before the
Auth user exists.

`DELETE /account` is what App Store guideline 5.1.1(v) requires. It removes
the profile, inventory pointers, every owned `players/{id}`, games the
account initiated, its name reservation and its seat in any unsettled
group (`member_uids`, entry, matchmaking pool -- so settlement never tries
to pay a deleted account, which would recreate its profile doc), then the
Firebase Auth user **last** so a failed attempt can be retried. It keeps
`iap_transactions` (financial records) and games it only played in as the
opponent.

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

Both responses carry `engine_version`, `replay_format_version`,
`added_time` (clock seconds per half), `player_match_stats` (this match's
per-player numbers, same index order as `roster`) and `kits` (both sides'
shirt strings, `[caller, opponent]`). Both also stamp the two versions onto
the `games/{id}` doc alongside the seed -- see Engine versioning below.

`kits` is passed straight through from each profile's `users/{uid}.kit` and
is never parsed server-side -- the format lives in
`mobile/scripts/data/KitDesign.gd` and is meant to grow without a backend
deploy. A bot opponent has no user document, so its shirt comes from
`BOT_KIT`. The `games/{id}` teams snapshot records each side's kit too, so a
replayed match is drawn in what was actually worn rather than whatever that
manager happens to own today.

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

It is a **string**, `MAJOR.MINOR.PATCH` (currently `"2.2.0"`) -- bump it
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
- `expires_at` -- datetime (or ISO string) after which it can't be opened.
- `available_at` -- a planned on-sale time. Until then the pack is
  *shown* grayed out with an "Available <date>" tag instead of hidden; once
  it passes, the first `/pack/list` or `/pack/open` to see it sets
  `active: true` and **deletes `available_at`** (`_activate_if_due`).
  Deleting is what makes it fire once -- pulling the pack afterwards by
  setting `active: false` sticks, because the date that would re-activate
  it is gone.
- `visible` -- show an unavailable pack grayed out even without a date.

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

Medals come only from tournament placement (`TOURNAMENT_REWARDS`), which is
what makes a medals-priced pack scarce rather than unbuyable.

### Currencies

Three balances on `users/{uid}`: `credits` (soft: matches, placement, the
full-day bonus, ads, releasing cards), `bucks` (hard, real-money, also
spendable on credits; the tier 1 tournament podium is the only in-game
source), `medals` (tournament placement only). All three are backend-only
writes (`GameState.set_credits`/`set_bucks`/`set_medals`, or `Increment`
inside a transaction); `firestore.rules` blocks the client from writing
them directly.

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
| `backfill_avg_rating.py` | Writes `statistics.avg_rating` onto cards with `RATED_MATCHES_FOR_AVERAGE`+ rated matches that predate the field. Re-runnable. |
| `sync_display_names.py` | Backfills `display_names/{key}` reservations for accounts created before names were unique. Oldest account keeps a duplicated name; conflicts are printed, never renamed. |
| `rename_tiers.py` | Rewrites `tier` on `players/{id}` after a `TIER_RANGES` key is renamed (its `RENAMES` map). Run `sync_pack_definitions.py` too, for the pack rates. |
| `list_packs.py` | Read-only dump of live `packs/{id}` docs. `--pack-id N` for one. |
| `list_deals.py` | Read-only dump of live `deals/{id}` docs. |
| `list_match_reports.py` | Read-only. Open bug reports newest first, with seed and engine version; `--dump-dir` writes each report's `games/{id}` doc as JSON. `--all` includes reports whose `status` you've changed by hand. To watch one: paste its game id into Play.tscn's TESTING panel (editor only, "Check a reported match"), which runs `packedfootball/scripts/replay_game.py` -- re-simulates the match on your Mac from the game doc and plays it back, showing the report text and flagging an engine-version mismatch. |
| `list_accounts.py` | Read-only. Lists every `users/{uid}` and whether its roster is Quick-Match complete (`roster_player_ids` length == 11). |
| `settle_tournaments.py` | Settles tournaments by hand when a day is stuck; `--dry-run` to see why it failed (or why it will work). |

A synced deal left `active: false` won't appear in `GET /deals/list` until
you flip it, in the Firestore console or via `--activate-new` on first sync.

## Firestore rules

`users/{uid}` `update` is an **allow-list**: `roster_player_ids`,
`formation`, `kit` -- the only three fields the client writes directly.
`display_name` used to be on it and no longer is: names are unique, and
only `POST /account/display_name` writes the reservation that makes them so. Everything else on that doc (all three currencies, wins/losses/
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
  half. Wants a "+3" at the end of each half; the replay already plays the
  extra minutes, the clock just doesn't say so.
- **Post and crossbar rebounds** -- the ball bounces off the frame and
  stays live. No replay event is emitted for it (that would mean a new
  `ActionType`, which has to be mirrored into `ReplayReader.gd`), so a
  rebound plays back as ordinary ball movement.
- **Stamina** -- live per-match, 0-100, and it already slows tired players.
  Not surfaced anywhere.
- **Height** -- generated and persisted; the client draws taller figures
  from it, but the engine doesn't use it yet. It is the foundation for
  headers, free kicks and shots over players.
