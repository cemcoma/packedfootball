# Packed Football -- Mobile (Godot)

Landscape-first Godot 4.7 client. Real email/anonymous auth, a Menu hub,
squad management, Quick Match against a real opponent or a bot, a pack shop
with reveal animation, a currency shop with real-money purchases via
RevenueCat, leaderboards, and dark/light theming.

Fixed 960x540 viewport, landscape orientation, fixed-aspect stretch.

## Setup

1. **Firebase config** -- copy `scripts/config/FirebaseConfig.example.gd` to
   `scripts/config/FirebaseConfig.gd` (gitignored) and fill in your
   project's real values.

2. **RevenueCat config** -- copy `scripts/config/RevenueCatConfig.example.gd`
   to `scripts/config/RevenueCatConfig.gd` (gitignored) and fill in the
   public SDK key.

3. **RevenueCat native binaries** -- download
   [`godotx_revenue_cat.zip`](https://github.com/godot-x/revenuecat/releases/latest)
   and extract its `ios/` and `android/` folders directly into `mobile/`
   (siblings of `addons/`, matching the zip's layout). Both are gitignored
   -- ~1GB unpacked, past GitHub's file limit -- so this is a one-time local
   fetch that `git pull` never gives you.
   `addons/godotx_revenue_cat/` (the GDScript side) **is** committed.

4. **Demo replay** (optional) -- the fallback Match screen plays when Quick
   Match hasn't been used yet:

   ```sh
   python3 packedfootball/scripts/dump_test_replay.py
   ```

   Writes `mobile/test_data/sample_match.bin` plus a `.json` roster sidecar.
   `--seed`, `--roster-seed` and `--out` are all overridable; see `--help`.

5. Open `mobile/` as a project in **Godot 4.7** and run it.

The app opens on Auth (sign in, register, or continue as guest), then Menu.

## Web test build

Driven by the repo-root `Makefile`, using the **Web** preset in
`export_presets.cfg`:

```sh
make web         # export to mobile/build/web/
make serve-web   # export, then serve at http://localhost:8060
make deploy-web  # export, then push to the gh-pages branch
make clean-web
```

A Godot web build can't run from `file://` -- use `make serve-web`, not a
double-click.

Three things about this preset matter, and breaking any of them breaks the
deploy:

- **`thread_support` is off.** Threaded Godot web builds need cross-origin
  isolation (COOP/COEP response headers) for `SharedArrayBuffer`, and GitHub
  Pages can't set headers. Turning it on produces a page that won't boot.
- **`exclude_filter` drops `ios/*` and `android/*`.** Those hold ~1GB of
  RevenueCat native binaries. Without the filter they land in `index.pck`
  (230MB), past GitHub's 100MB per-file limit, and the deploy fails.
- **No real-money purchases.** There's no payment path on web, so
  `CurrencyPanel.gd` hides the Cash tab when `OS.has_feature("web")`.
  Exchange, Deals and Free are backend-driven and work unchanged, as do
  packs, matches, squad and leaderboards.

This is a gameplay test build, not a shipping target.

## Screens

| Scene | Script | What it does |
| --- | --- | --- |
| `Auth.tscn` | `Auth.gd` | Sign in / register / guest. Register also takes a manager name. |
| `Menu.tscn` | `Menu.gd` | Navigation hub plus an account panel (name, squad overall, W/D/L) and currency chips. |
| `Play.tscn` | `Play.gd` | Mode select: Quick Match (real) and Tournament (stub). |
| `Match.tscn` | `MatchPlayback.gd` | Replay playback with a HUD. |
| `MatchResult.tscn` | `MatchResult.gd` | Post-match recap. |
| `Team.tscn` | `Team.gd` | Squad management. |
| `Shop.tscn` | `Shop.gd` | Packs and currency. |
| `PackReveal.tscn` | `PackReveal.gd` | Pack-opening reveal animation. |
| `Leaderboard.tscn` | `Leaderboard.gd` | Users (by wins) and Players (by goals) tabs, each lazy-loaded once and cached. |
| `Settings.tscn` | `Settings.gd` | Rename, color theme, language, log out. |
| `Tournament.tscn` | `StubScene.gd` | Placeholder. |

### Play / Quick Match

Calls `POST /match/quick`, which validates your saved roster, picks an
opponent (a real account with a complete 11-player roster, or a
freshly-rolled bot of random formation and random tier if none is
available), simulates, rewards, and persists -- all before replying. A
`LoadingPopup` covers the whole round trip.

The result reaches the Match screen through the `MatchSession` autoload,
since `change_scene_to_file()` can't carry data. `MatchPlayback.gd` reads it
without clearing it, because `MatchResult.gd` still needs the score and
reward afterwards; whichever of those finishes with it clears it.

With no pending session the Match screen falls back to the bundled demo
replay, so the offline path works with no backend and no account.

### Match screen

`MatchPlayback.gd` lives on `PitchCanvas` (a clipped `Control` child), not
the scene root. The pitch is custom-drawn; everything around it --
scoreboard, timer, pause/camera/speed buttons, pre-match and pause overlays
-- is real Control nodes overlaid as a HUD.

- **Camera** toggles full/zoom. "Full" uses a fixed aspect-correct box
  (`FULL_MODE_BOX_SIZE`, 378x540) so the whole pitch fits; "zoom" fills the
  viewport with a ball-following crop.
- **Speed** cycles 1x -> 2x -> 4x, scaling everything time-based uniformly.
- **Pause** freezes `_process()` entirely and opens a menu with Skip to
  Halftime, Skip to Full Time, and Exit to Main Menu. Skip to Halftime
  disables itself once playback is past halftime -- jumping there would
  rewind the scoreboard, since `_jump_to_event` replays from kickoff to
  reach a correct score.
- **Pre-match** starts fully blacked out behind a Start Match button.
- Playback interpolates between sparse recorded samples with Hermite curves
  using the recorded velocity as the tangent; the ball is glued to whoever
  is dribbling rather than interpolated separately.

Pausing or exiting early can't affect the result -- the simulation already
ran and was persisted server-side before this scene loaded.

Reaching full time in a real match navigates to `MatchResult.tscn`. Exiting
mid-match via pause, or continuing from the result screen, re-fetches the
squad (`GameProfile.load_all()`) behind a `LoadingPopup`, so player stats
updated by the match show up instead of the pre-match cache.

### Team screen

Pick a formation (4-4-2 / 4-3-3 / 3-5-2 / 4-2-3-1, ported from
`packedfootball/formations.py`) with a `ButtonGroup` toggle row, shown on a
true-proportioned pitch. Slots are real tappable `Button`s tinted by tier.

Tap a filled slot for full stats with **Replace** (bench grid, filtered to
that slot's role and similar positions) and **Clear**; tap an empty slot to
go straight to the picker. Switching formations carries a player to a new
slot with the same role (a CB stays a CB moving 4-4-2 -> 3-5-2); anyone
whose role doesn't exist in the new formation falls to the bench.

**Save Team** requires every slot filled and is the only thing that writes
to Firestore -- switching formations or swapping players doesn't. An
"Unsaved changes" banner shows until you save. **Back to Menu discards
unsaved changes**, reverting to the last saved state.

`Team.tscn` is a thin shell; the node tree is built procedurally in
`Team.gd`'s `_build_ui()`.

#### Playing out of position

A bench card can fill a slot whose role isn't its exact position if the two
are similar. `Formations.POSITION_GROUPS` defines this as named groups:
`{CDM, CM}`, `{CM, CAM}`, `{LB, WB, LM, LW}`, `{RB, WB, RM, RW}`,
`{LW, RW, ST}`. Deliberately not transitive (a CDM can play CM, a CM can
play CAM, but a CDM can't play CAM) and not exhaustive (`GK` and `CB` are in
no group, so neither ever substitutes).

The client only *displays* this: the picker widens to include similar-
position cards (tagged, amber position label), the stats panel adds a
warning, and the pitch marker gets an amber border and an "(OOP)" suffix.
The gameplay effect -- a flat 10% cut to every non-tendency attribute --
happens only inside `gameEngine.py`, on a scaled copy built for that one
simulation. The stored card is never touched. `/match/simulate`
independently re-derives and rejects any illegal pairing, since the backend
can't trust that the client went through this picker.

### Shop screen

Two tabs, **Packs** and **Currency**, sharing a `ButtonGroup`. The header
shows all three balances as `CurrencyChip` instances -- an icon plus a
thousand-separated amount, tinted per currency.

Packs are split by **type** via a dropdown (`standard` / `special` /
`timed`). The dropdown is built from the types actually present in what
`/pack/list` returned, never a hardcoded list: `PackData.TYPE_COLORS`' key
order is only a display-order preference, and unrecognized types are
appended rather than dropped, so a new type server-side needs no client
change. The selected type survives a refresh.

The catalog is fetched fresh on every scene load and after every purchase,
not cached on `GameProfile` -- unlike your roster, it can change under you
at any time.

Buying puts up the shared `LoadingPopup` **before** the request, so its
scrim blocks a second Buy tap from firing a second `/pack/open` and charging
twice. Cards then go to the reveal screen.

`PackView` shows the pack's type, name, card count, price (as an icon plus
amount in the pack's own currency) and a tag when teased, plus an **i**
button.

#### Odds disclosure

The **i** button opens `PackInfoPopup` -- one instance embedded statically
in `Shop.tscn`, since only one can be open at a time. A `TabContainer` with
its tab bar hidden, paged with Prev/Next across description, card tier odds,
and position odds. This is the per-tier/per-position disclosure that App
Store Guideline 3.1.1 and Google Play's loot box policy both require showing
before purchase.

Odds come from `PackData.rates` / `.pos_rates`. Row order is a fixed
client-side list, never dictionary iteration order, since a Firestore map
field's key order isn't guaranteed to survive the round trip. A 0% row is
left off entirely.

### Currency tab

`scenes/components/CurrencyPanel.tscn` is instanced into `Shop.tscn` as
`CurrencyTabs`. Four sub-tabs, same `ButtonGroup` + lazy-load-once pattern:

- **Exchange** -- spend bucks for credits at 4 fixed rates from
  `GET /currency/exchange/list`.
- **Cash** -- real-money purchases via RevenueCat (see below).
- **Deals** -- DB-backed timed offers from `GET /deals/list`, with
  availability, expiry and teasing like packs. `DealView` mirrors `PackView`
  but has no odds popup: a deal's reward is fixed and shown on the tile, so
  there's nothing to disclose.
- **Free** -- rewarded ads. **A stub.** The tab and placeholder exist so the
  wiring point is obvious; nothing behind it is real. Doing it properly
  needs an ad SDK, a server-side grant endpoint with its own anti-abuse
  rules, and its own store review.

`CurrencyTileView` is the shared "pay X, get Y" tile for Exchange and Cash
-- both are fixed offers with no availability concept, so it skips
`PackView`'s tag machinery.

`scripts/data/CurrencyDisplay.gd` is the single source for how a currency
looks and reads: labels, icons, colors, and `format_amount()`. **`bucks` is
displayed as "Cash" everywhere** -- the backend field name stays `bucks`.
Change it in one place here, not per-screen.

### In-app purchases via RevenueCat

`IapClient.gd` wraps the plugin's `GodotxRevenueCat` singleton.
`initialize(api_key, uid, debug)` runs once right after sign-in, using the
signed-in Firebase uid as RevenueCat's `app_user_id` -- that's how the
backend webhook knows which account to credit.

`purchase(product_id)` starts a real purchase and emits
`purchase_completed` / `purchase_failed` for UI feedback only. There's no
receipt to forward: RevenueCat verifies with Apple/Google and calls the
backend webhook server-to-server. On success `CurrencyPanel.gd` calls
`GameProfile.load_all()` again after a short delay to pick up the balance
the webhook granted, rather than trusting anything the purchase returned.

`IapClient.is_available()` reports whether that singleton exists in the
current build -- native plugins link at **export** time only, so it's false
in the editor and in macOS builds.

Server side: see [backend/README.md](../backend/README.md)'s RevenueCat
section for the webhook and its shared secret.

### Pack reveal screen

Reached from `Shop.gd` via the `PackSession` autoload. Two states.

**Reveal** -- each card gets a `PlayerCardView`, shown one at a time with a
`Tween` (scale + fade in, hold, fade out), worst tier first
(`PlayerCard.tier_rank()`, rarity first with `overall()` as tiebreak) so the
best card lands last as a hero moment. How much bigger scales with that
card's own tier (`HERO_SCALE_BY_TIER`, 1.25x bronze to 2x icon).

Tapping while a non-hero card shows skips straight to Browse with every card
in its final state -- skip means skip all of it, not advance one card. The
hero card never auto-advances; it awaits an explicit tap.

Skipping fast-forwards the active `Tween` with `custom_step(9999.0)` and
expires the hold's `SceneTreeTimer` via `time_left = 0.0`, rather than
`kill()` -- a killed `Tween` never fires `finished`, which would hang
`await tween.finished` forever.

**Browse** -- every card in a scrollable grid (reparented from the reveal,
or instantiated on the spot for any card an early skip never reached).
Tapping one opens a stats popup.

### Settings

Rename (writes only if the trimmed name is non-empty and actually changed),
**Color Theme** (see Theming), **Language** (see Localization), and Log Out /
Switch Account.

## Localization

Godot's built-in translation system, keyed on the English text:

- **`translations/messages.pot`** is the master list of every UI string.
  **`translations/tr.po`** is Turkish; a new language is a copy of the
  `.pot` with the `msgstr`s filled in, registered under
  `[internationalization]` in `project.godot`, plus one line in
  `LocaleManager.LANGUAGES`.
- **Scene text** (`text`, `placeholder_text`, `tooltip_text` in a `.tscn`)
  translates itself -- Godot looks the string up as a key. **Script text**
  goes through `tr("...")`, or `TranslationServer.translate("...")` inside
  a `static func` (no `self` there). A format string is translated before
  formatting: `tr("Overall %d") % n`. A label pulled from a `const` table
  (`ATTR_ROWS` and friends) is wrapped where it's displayed, not in the
  table -- a `const` can't call `tr()`.
- A key with no entry in the current language shows as written, so a
  missing translation is never a blank label.
- **`LocaleManager`** (autoload) owns the choice: saved in
  `user://settings.cfg`, defaulting to the device language when it's one we
  ship. Switching on the Settings screen reloads that scene, since text a
  script filled with `tr()` was worded in the old language.
- Not translated, by design: anything the **backend** composes -- pack,
  deal and tournament-tier names, HTTP error details.
- The font: `Arial Rounded Bold` lacks `ş ğ İ` (and `₺`), so
  `theme/fonts/AppFont.tres` is a `FontVariation` over it with
  `Nunito-Bold.ttf` (OFL, `Nunito-OFL.txt`) as the fallback for any glyph
  it's missing. Both theme files point at that, not the raw `.ttf`.

## Theming (dark / light)

Colors live in two places, because Godot splits the job:

- **Widget chrome** -- Button/Panel/Label styles and the app font
  (`theme/fonts/AppFont.tres`, see Localization) -- lives in real Theme
  resources: `theme/AppTheme.tres` (dark)
  and `theme/AppThemeLight.tres` (light). `ThemeManager` swaps them wholesale
  on the root Window, restyling every existing Control for free.

  **Keep the two structurally identical.** A key present in only one means a
  widget silently changes in just that mode. The font is exactly that trap:
  a light theme missing `Label/fonts/font` reverts the whole app to Godot's
  default typeface.

- **Everything a Theme can't express** -- per-currency accent colors, the
  surface tints components build `StyleBoxFlat`s from at runtime -- lives in
  `ThemeManager.PALETTES`, read via `ThemeManager.color(key)`.

Components that bake palette colors into a StyleBox (`CurrencyChip`,
`CurrencyTileView`, `DealView`) rebuild on `ThemeManager.theme_changed`.
Anything using only themed Button/Panel styles needs no code.

The mode is chosen in **Settings -> Color Theme** and persists to
`user://settings.cfg`.

The backdrop swaps too: `BackgroundLayer` takes whichever image
`ThemeManager.BACKGROUNDS` names for the current mode
(`general_background_dark` / `general_background_light_medium`). A screen
wanting a fixed backdrop unticks `follow_theme` on its own instance.
**`Match.tscn` is excluded by construction** -- it doesn't instance
`BackgroundLayer` at all, so the swap can't reach it.

## Project layout

```
scripts/
  screens/     -- one script per navigable scene (1:1 with scenes/*.tscn)
  components/  -- reusable visual building blocks, instanced from screens
  autoload/    -- singletons registered in project.godot's [autoload]
  data/        -- pure data models / format readers -- no I/O, no UI
  config/      -- FirebaseConfig.gd + RevenueCatConfig.gd (both gitignored,
				  each with a committed .example.gd)
scenes/
  *.tscn       -- the 11 top-level screens
  components/  -- mirrors scripts/components/
theme/
  AppTheme.tres / AppThemeLight.tres
```

A script's `class_name` resolves globally regardless of folder, so moving
files never requires touching call sites -- only literal path strings
(`.tscn` `ext_resource` lines, `project.godot` autoload paths, and
`preload()` calls) care where a file lives.

### Autoloads

| Autoload | Purpose |
| --- | --- |
| `FirebaseAuth.gd` | Auth flow; holds the signed-in `uid`. |
| `Firestore.gd` | Firestore REST calls (get/list/set/add/delete + field-value wire encoding). |
| `Backend.gd` | Calls the Cloud Run backend with the signed-in ID token. |
| `GameProfile.gd` | The live squad model: profile fields, formation, slot assignment, every owned card, dirty-checking. |
| `MatchSession.gd` | One just-played match's result, `Play.gd` -> `MatchPlayback.gd` -> `MatchResult.gd`. |
| `PackSession.gd` | One just-opened pack's cards, `Shop.gd` -> `PackReveal.gd`. |
| `IapClient.gd` | Wrapper around the RevenueCat plugin singleton. |
| `ThemeManager.gd` | Dark/light mode, palettes, background selection; persists the choice. |
| `LocaleManager.gd` | UI language: applies the locale, persists the choice, defaults to the device language. |

`GameProfile` loads once at sign-in (`Auth.gd`'s `_go_to_menu()`) and is
shared global state for the rest of the session, so opening a screen is
instant. `is_dirty()` compares the live formation and slot assignment
against a snapshot taken at load and after each successful save; that drives
both the unsaved-changes indicator and what `discard_changes()` reverts to.

### Components

| Component | Purpose |
| --- | --- |
| `PlayerCardView` | The reusable card visual. Used by the bench grid, the Team stats header, and the pack reveal. Change card art here once and every screen follows. |
| `PlayerModelView` | Layered placeholder character portrait inside `PlayerCardView`. |
| `PitchView` | The Team screen pitch: drawn grass/lines plus real `Button` slot markers. |
| `PackView` | The pack tile. |
| `PackInfoPopup` | Paginated odds disclosure. |
| `CurrencyPanel` | The Currency tab's four sub-tabs. |
| `CurrencyTileView` | "Pay X, get Y" tile for Exchange and Cash. |
| `DealView` | The Deals tile. |
| `CurrencyChip` | One balance as a tinted pill, for screen headers. |
| `CurrencyAmount` | Icon + number, for inline prices. |
| `LoadingSpinner` | Hand-drawn rotating arc; Godot has no built-in indeterminate spinner. |
| `LoadingPopup` | Shared "working on it" modal: scrim + spinner + `set_status(text)`. |
| `BackgroundLayer` | Theme-following backdrop, instanced first on every screen except Match. |

### Data models

`scripts/data/` is display-only -- no I/O, no gameplay logic. Every model
uses the same defensive `_int`/`_str` field coercion, because
`Dictionary.get(key, default)` only falls back when a key is *absent*: a
present-but-null value still returns null, and assigning null to a typed
`String`/`int` var is a hard runtime error.

- `Formations.gd` -- the 4 formations plus `POSITION_GROUPS` /
  `is_similar_position()`, mirroring `packedfootball/formations.py`.
- `PlayerCard.gd` -- card fields, `overall()`, `tier_color()`,
  `tier_rank()`. `overall()` reproduces `player.py`'s `_calculate_overall`,
  so its `TENDENCY_FIELDS` **and** `PHYSICAL_FIELDS` exclusion lists must
  match the Python ones exactly. `height` is in centimetres; averaging it in
  with 0-100 skills would inflate every card and put this client permanently
  out of step with the server's rating.
- `PlayerAppearance.gd` -- the 5-slot/5-option layered appearance
  `PlayerModelView` renders (5^5 = 3125 looks from 25 stored choices), plus
  `mock_from_id()` as a fallback for cards predating real generation.
- `PackData.gd` -- pack listing data including `rates`/`pos_rates`,
  `price_currency`, `type_color()`, `is_limited()`, `tag_text()`.
- `ExchangeRateData.gd` / `BucksProductData.gd` / `DealData.gd` -- listing
  data for the Currency sub-tabs.
- `CurrencyDisplay.gd` -- labels, icons, colors and formatting for all three
  currencies.
- `ReplayReader.gd` -- binary reader for the format `packedfootball/replay.py`
  writes. **Keep the two in sync if the wire format changes.**
  `load_from_bytes()` is `load_from_file()` fed by a scratch file, for a
  replay that arrived over the network.

## Rendering approach

Every screen is real Control nodes -- layout/anchoring, hover/press
feedback, real scrolling, no manual `Rect2.has_point()` hit-testing.

Two things stay hand-drawn, for different reasons. `Tournament.tscn`
(`StubScene.gd`) simply isn't built yet and should get real Controls when it
is. The pitch itself -- `MatchPlayback.gd`'s `PitchCanvas` and
`PitchView.gd`'s markings -- stays custom-drawn permanently: grass, lines,
and moving players under a panning camera aren't something Controls model
well. Everything *around* the pitch is real Controls.

`PitchCanvas` sets `clip_contents = true`, which clips a Control's own
`_draw()` output as well as its children's -- that's what keeps pitch lines
from spilling past the visible crop in zoom mode, with no per-shape
clipping.

## Known gaps

- No real card-frame art or animation assets. The reveal animates the same
  placeholder visuals used everywhere else.
- No audio anywhere in the project.
- Tournament mode is a stub, so medals have no earning path.
- `packedfootball/formations.py`'s `4-2-3-1` still uses `LCB`/`RCB`/`LDM`/
  `RDM` labels while the other three formations use `CB`/`CDM`/`CM`. The
  client normalizes it, since cards are only generated with the simplified
  labels -- otherwise those slots could never have an eligible card. Worth
  applying the same simplification server-side so both agree.
