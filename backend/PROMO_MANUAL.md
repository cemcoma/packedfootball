# Promo manual

All card and pack art comes from the Firebase Storage bucket. Changing it needs no app
update and no deploy. The sprites bundled in the app are only a fallback.

> **Wait for the iOS update before selling a new card type.** Until the iOS update with
> remote art is out and most players have it, a **new** card type shows with no background
> on old iOS versions.

On a new machine, run this once: `pip install -r backend/requirements.txt` and `gcloud auth application-default login`.

## Run a promo

1. **Art:** PNG. Card art is **440×600**, pack art is **600×800**. Any size with the same ratio also works.
2. **Card type name:** `<rarity>_<name>`, lowercase, e.g. `special_toty`.
   - The rarity must be one of `bronze silver gold platinum diamond special icon`. It sets the colour, the release value and the walkout.
   - It shows on the card as "Special TOTY".
   - **It can't be renamed later.**
3. **Upload the card type.** Check the preview image first, then run the command again without `--dry-run`:
   ```sh
   python3 backend/scripts/upload_art.py card special_toty toty.png --range 87 90 --dry-run --preview check.webp
   ```
   - `--range` is the overall range; compare `TIER_RANGES` in `packedfootball/game_config.py`.
   - Optional: `--text-color "#ffffff"` if the text is hard to read on the art.
   - Optional: `--quality 95` or `--lossless` if the preview looks blocky.
4. **Upload the pack art:**
   ```sh
   python3 backend/scripts/upload_art.py pack TOTYPack toty_pack.png
   ```
5. **Create the pack:** Firestore console → `packs` → Add document. The document ID is the slug, e.g. `promo_toty`.
   Don't put it in `pack_database.py`; its tests reject new card types.

   | Field | Type | Example |
   | --- | --- | --- |
   | `name` | string | Team of the Year Pack |
   | `type` | string | `timed` |
   | `description` | string | 3 cards with a chance at a TOTY special! |
   | `order` | number | 70 |
   | `price` | number | 4000 |
   | `price_currency` | string | `credits` / `bucks` / `medals` |
   | `cards_per_pack` | number | 3 |
   | `rates` | map | `silver` 0.5, `gold` 0.45, `platinum` 0.05 |
   | `slot_rates` | map, optional | `"0"` → map: `platinum` 0.9, `diamond` 0.05, `special_toty` 0.05 |
   | `guarantees` | array, optional | map: `tier` = `special_toty`, `count` = 1 |
   | `pos_rates` | map | `goalkeeper` 0.1, `defender` 0.3, `midfielder` 0.3, `attacker` 0.3 |
   | `sprite_key` | string | `TOTYPack` |
   | `active` | boolean | **false** |
   | `available_at` | timestamp | launch time |
   | `expires_at` | timestamp, optional | end time |
   | `max_opens` | number, optional | cap on total opens |

   - Each rates map must add up to 1.0.
   - With `active: false` and `available_at`, the pack shows greyed out and goes on sale by itself at that time.
   - **Never set `active: true` with a future `available_at`.** The pack sells immediately.
6. **Check it:** the shop shows the new pack art. On launch day, open one yourself first.

## Change things

| To… | Do |
| --- | --- |
| Replace card or pack art (any tier, including bronze–icon) | Re-run the same command with the new PNG. |
| Change a card type's range | Re-run it with a new `--range`. Only newly opened cards get it. |
| Remove a text colour | Re-run it with `--no-text-color`. |
| End a promo | Set the pack's `active` to false, or set `expires_at`. |
| Add a new PNG to the app | Upload it too. |

Changes reach players within 5 minutes.

## Never

- Delete a `card_types` or `pack_art` doc.
- Replace an image by hand in the Storage console. Always use the script.
- Delete files from Storage.
- Create a pack before uploading its card type.

## If something's wrong

| Problem | Fix |
| --- | --- |
| The pack won't open ("Could not open… try again") | The card type is missing or misspelled in the pack's rates. Check `card_types/<tier>`. |
| A card or pack shows old or bundled art | Open the doc's `url` in a browser. If it's a 404, re-run the script. |
| A new upload doesn't show | Wait 5 minutes, then reopen the shop. |
| `DefaultCredentialsError` | Run `gcloud auth application-default login`. |
| "needs the 440:600 aspect ratio" | Crop or resize the image to that ratio. |
