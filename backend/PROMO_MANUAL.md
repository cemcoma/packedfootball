# Promo manual: new card types and pack art without an app update

New card types (like `special_toty`) and new pack art can go live without an
App Store update or a backend deploy. The images live in Firebase Storage. The
app downloads each one once, keeps it on the phone, and never downloads it again.

- **Part 1** is a one-time setup for going to prod.
- **Part 2** is what you do for every promo.
- **Parts 3–5** cover changes, mistakes to avoid, and fixes.

---

## Part 1: Going to prod (once, in this order)

> **Two hard rules**
> 1. **Never create a pack that sells a new card type until the new backend is deployed.**
>    The old backend gives an unknown tier 40–50 stats, and nothing warns you.
> 2. **Players on an app version from before this feature see promo cards with no background,**
>    and promo packs with the standard pack art. There is no forced update, so
>    wait until most players have updated before your first remote promo.

1. **Deploy the backend**, as in [README → Deploying](README.md#deploying).
   This is safe before the app update, because old app versions ignore the new `art` field.
2. **Enable Firebase Storage**: Firebase Console → Build → Storage → Get started.
   - **Location:** `us-central1` if it's offered, because downloads are free up to 100 GB a month. Otherwise choose Europe; it costs ~$0.12/GB, a few dollars a month at most.
   - **Bucket name:** write down the one shown at the top of the Files tab (`gs://…`). If it isn't
     `packedfootball.firebasestorage.app`, change `ART_BUCKET` in [config.py](config.py).
     Only the upload script reads it, so this needs no backend redeploy.
3. **Deploy the Storage rules** from the repo root:
   ```sh
   firebase deploy --only storage
   ```
   Without this, every download fails (403) and players only ever see the base-rarity art.
4. **Web test build only:** let the browser download from the bucket.
   ```sh
   gcloud storage buckets update gs://<bucket> --cors-file=storage-cors.json
   ```
5. **Set up the script on your Mac.**
   ```sh
   pip install -r backend/requirements.txt      # Pillow + firebase-admin
   gcloud auth application-default login        # only if the script complains about credentials
   ```
6. **Smoke test.** This is safe to delete afterwards.
   ```sh
   python3 backend/scripts/upload_art.py pack SmokeTest mobile/sprites/packs/standard/StandardGold.png
   ```
   Open the `url:` it prints in a browser; you should see the pack image.
   - A permission error means step 3 wasn't done.
   - "bucket does not exist" means step 2 wasn't done, or `ART_BUCKET` is wrong.

   Afterwards, delete the `pack_art/SmokeTest` doc in the Firestore console. You can also delete its file in Storage → `pack_art/`.
7. **Ship the app update.** It contains `RemoteArt.gd`. This is the last update a promo ever needs.

---

## Part 2: Running a promo

The example below is a "Team of the Year" promo: card type `special_toty`, pack `promo_toty`.

### Step 1: Prepare the art

| What | Format | Shape |
| --- | --- | --- |
| Card background | PNG | **440×600**, or any size with that ratio, e.g. 880×1200 |
| Pack art | PNG | **600×800**, or any size with that ratio |

The script refuses a wrong ratio. 16-bit PNGs are fine, because it converts everything.
Use the existing files in `mobile/sprites/player_cards/` and `mobile/sprites/packs/` as a guide for how the art should look.

### Step 2: Choose the card type name

The name is `<rarity>_<name>`, in lowercase letters and digits. For example: `special_toty`, `gold_rttk`, `diamond_turkish`.

- **The rarity** must be one of `bronze silver gold platinum diamond special icon`. It decides:
  - the card colour
  - its group in the odds popup
  - its release value
  - how strong the walkout is
  - which art shows while the promo art downloads
- **The name part** is shown in capitals on the card: `special_toty` shows as "Special TOTY".
- **Choose carefully.** Every card stores this name forever, so it can't be renamed later.

A brand-new rarity (a new colour, for example) is not possible this way; that still needs an app update.

### Step 3: Upload the card type

Run a dry run first, and save a preview so you can check the quality:
```sh
python3 backend/scripts/upload_art.py card special_toty toty.png --range 87 90 --dry-run --preview toty_check.webp
```
Open `toty_check.webp` in Preview or a browser.
- **If it looks blurry or blocky,** add `--quality 95` or `--lossless`.
- **If it looks right,** run the same command without `--dry-run` and `--preview`.

Options:
- `--range 87 90` sets the overall range of cards from this type. Compare with the existing tiers in
  `TIER_RANGES` in [game_config.py](../packedfootball/game_config.py).
- `--text-color "#ffffff"` is only for art so light or dark that the default text is hard to read.

### Step 4: Upload the pack art

```sh
python3 backend/scripts/upload_art.py pack TOTYPack toty_pack.png
```
The sprite_key (`TOTYPack`) may use letters, digits, `_` and `-`.
Don't reuse an existing key (`StandardGold`, `CONFPack`, …) unless you want to replace that pack's art everywhere.

### Step 5: Create the pack in the Firestore console

**Don't add the pack to `pack_database.py`.** The pack tests only know the bundled tiers, so they will fail.

Create it by hand instead:
1. Open Firestore → `packs` → **Add document**.
2. Set the Document ID to the pack's slug, e.g. `promo_toty`.
3. Add these fields:

| Field | Type | Example |
| --- | --- | --- |
| `name` | string | Team of the Year Pack |
| `type` | string | `timed` (the shop section) |
| `description` | string | 3 cards with a chance at a TOTY special! |
| `order` | number | 70 |
| `price` | number | 4000 |
| `price_currency` | string | `credits`, `bucks` or `medals` |
| `cards_per_pack` | number | 3 |
| `rates` | map | `silver` 0.5, `gold` 0.45, `platinum` 0.05 |
| `slot_rates` | map *(optional)* | `"0"` → map: `platinum` 0.9, `diamond` 0.05, `special_toty` 0.05 |
| `guarantees` | array *(optional)* | one map: `tier` = `special_toty`, `count` = 1 |
| `pos_rates` | map | `goalkeeper` 0.1, `defender` 0.3, `midfielder` 0.3, `attacker` 0.3 |
| `sprite_key` | string | `TOTYPack` |
| `active` | boolean | **false** |
| `available_at` | timestamp | the launch time |
| `expires_at` | timestamp *(optional)* | the end time |
| `max_opens` | number *(optional)* | a cap on total opens across all players |

Rules for these fields:
- **Every rates map must add up to 1.0**: `rates`, and each slot inside `slot_rates`.
- **Use `active: false` plus `available_at`.** The pack then shows in the shop greyed out as
  "Available <date>" and goes on sale by itself at that time.
  **Never set `active: true` with a future `available_at`,** because it would sell immediately.
- **While the pack is greyed out, phones are already downloading its pack and card art,**
  so launch day is instant.
- **From now on, `seed_packs.py` lists this pack as unknown to the catalog.** That's expected.

### Step 6: Check it in the app

- **Shop:** the greyed-out pack shows your pack art. The first time, the standard art may appear for a moment before it swaps.
- **The pack's (i) button:** shows the odds, with the promo tier grouped under its rarity.
- **Launch day:** open one yourself first.

---

## Part 3: Changing things later

| You want to… | Do this |
| --- | --- |
| Fix or replace a card's art | Re-run the same `card` command with the new PNG. Range and text colour are kept if you leave them out. Phones download the new image once. |
| Change a card type's range | Re-run it with a new `--range`. Only cards opened afterwards use it; cards players already own keep their stats. |
| Remove a text colour | Re-run it with `--no-text-color`. |
| Replace a pack's art | Re-run the `pack` command with the new PNG. |
| End a promo | Set the pack's `active` to false, or give it an `expires_at`. **Keep the card type.** |
| Re-skin a bundled tier (e.g. Christmas gold) | `upload_art.py card gold xmas_gold.png`, with no `--range`; the normal range stays. To undo it, delete the `card_types/gold` doc. That's safe **only** for bundled tiers. |

Changes reach players within **5 minutes**, because the backend caches the list. If a pack is opened that sells a card type the backend doesn't know yet, it checks again straight away.

---

## Part 4: Never do this

- **Never delete a `card_types` doc for a new type (like `special_toty`) once a pack has sold it.**
  Those cards fall back to plain rarity art, and any pack still selling the type stops opening.
- **Never replace an image by hand in the Storage console.** The app checks every file against
  the hash stored in Firestore, so a hand-swapped file is rejected and players keep the old art.
  Always use the script.
- **Don't delete old files from Storage.** They are tiny, and a phone may still be finishing a download of one.
- **Don't create the pack before uploading its card type.** The pack refuses to open (players see
  "Could not open … try again"). Upload first, then create the pack.

---

## Part 5: Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Players get "Could not open … try again" on the promo pack; Cloud Run shows a 500 on `/pack/open` | The card type was never uploaded, the tier is misspelled in the pack's rates, or the family or range is bad. Check that `card_types/<tier>` exists. Cloud Run logs print `card_types/<tier>: unknown family …` or `bad range …`. |
| A card keeps showing the plain rarity art | The download is failing. Open the doc's `url` in a browser. A 403 means the Storage rules weren't deployed (Part 1, step 3); a 404 means the file is missing, so re-run the script. Phones try again after a minute or on the next shop visit. |
| A new upload doesn't appear | It can take up to 5 minutes (backend cache). Reopen the shop after that. |
| The web build shows no promo art | CORS was never set (Part 1, step 4). |
| The script says `DefaultCredentialsError` | Run `gcloud auth application-default login`. |
| The script says the bucket doesn't exist | Storage isn't enabled, or `ART_BUCKET` is wrong (Part 1, step 2). |
| The script says "needs the 440:600 aspect ratio" | Crop or resize the image to the right ratio (see Step 1). |
| Some players see blank promo cards | They're on an app version from before this feature and need to update. |

---

## How it works (short)

- **Firestore**
  - `card_types/{tier}`: `family, range, url, sha256, bytes, text_color?`
  - `pack_art/{sprite_key}`: `url, sha256, bytes`
- **Storage:** `card_art/<tier>.<hash>.webp` and `pack_art/<key>.<hash>.webp`.
  A new image always gets a new file name, so nothing is ever overwritten.
- **Backend** ([services/remote_art.py](services/remote_art.py))
  - re-reads both collections every 5 minutes
  - adds the new ranges to pack opening
  - sends the list as `art` in `/account/bootstrap` and `/pack/list`
- **App** ([RemoteArt.gd](../mobile/scripts/autoload/RemoteArt.gd))
  - saves the list
  - downloads missing images, two at a time
  - checks each file's hash and keeps it in `user://remote_art/`
  - never downloads the bundled art
- **Cost:** each phone downloads each image once. An image is about 10–60 KB after WebP conversion, so it's close to free.
- **Script:** [scripts/upload_art.py](scripts/upload_art.py). It converts to WebP, uploads, and writes the Firestore doc.
  Run `--help` to see every option.
