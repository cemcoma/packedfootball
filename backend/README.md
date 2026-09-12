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

## Still to do

- Tighten `firestore.rules` to deny direct client writes to
  `credits`/`roster`/`elo`/`wins`/`losses`/`draws`/`campaign_level`/`inventory/*`,
  once a client actually calls this backend instead of writing Firestore
  directly.
