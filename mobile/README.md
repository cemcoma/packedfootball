# Packed Football - Mobile (Godot)

Landscape-first client: real email/anonymous auth, a Menu hub, a real Team
squad-management screen, placeholder Shop/PVP/Profile screens, and a match
replay player. The match replay is still loaded from a local file rather
than fetched from the deployed Cloud Run service -- that's the remaining
piece of backend networking not wired up yet. See the plan this came from
for the fuller picture.

## Try it

1. Generate (or regenerate) a test replay:
   ```sh
   python3 packedfootball/scripts/dump_test_replay.py
   ```
   Writes to `mobile/test_data/sample_match.bin` (+ a `.json` roster sidecar)
   by default (`--seed`, `--roster-seed`, `--out` all overridable -- see the
   script's `--help`).
2. Copy `scripts/config/FirebaseConfig.example.gd` to
   `scripts/config/FirebaseConfig.gd` (gitignored) and fill in your Firebase
   project's real values -- same idea
   as `packedfootball/firebase_config.example.py`.
3. Open this `mobile/` folder as a project in Godot 4.3+.
4. Run the project. It opens on Auth (sign in, register, or continue as
   guest) then the Menu; "Play Match" loads `test_data/sample_match.bin` and
   plays it back once you hit Start; "Team" manages your actual squad
   against your real Firestore data.

## Match screen controls

- **Start Match** -- resets and plays from kickoff.
- **Jump to Halftime** / **Jump to Full Time** -- skip straight to just
  before that point (replaying every earlier event first, so the scoreboard
  is still correct), then let the normal pause/banner trigger naturally.
- **Camera: Zoom / Full Pitch** -- toggles between a ball-following zoomed
  camera and the whole pitch fit to the pitch box, matching
  `gameEngine.py`'s own `render()` camera modes.
- **Speed: 1x/2x/4x** -- cycles playback speed. Scales everything
  time-based uniformly (match clock, halftime pause, event flashes/banners),
  not just the match itself.
- **Back to Menu** -- returns to the hub.

## Team screen

Built from real Control nodes -- `Button`/`Label`/`GridContainer`/
`ScrollContainer` -- rather than hand-drawn/hit-tested, the only scene
besides Auth to make that call (see "Controls vs. hand-drawn" below).
Pick a formation (4-4-2 / 4-3-3 / 3-5-2 / 4-2-3-1 -- ported from
`packedfootball/formations.py`) with a real `ButtonGroup` toggle row, shown
on a true-proportioned pitch (`PitchView.gd`: your own half, goal at the
bottom, same 70x100 shape `MatchPlayback.gd` uses) -- stretched vertically
to fill that whole box rather than sitting in just the bottom half, so x
and y deliberately use different scales (`SCALE_X`/`SCALE_Y`); field
markings share the same stretch so they still line up with the player
slots, which are real, tappable `Button`s tinted by tier. Tap a filled slot
to see their full stats on the right (attributes, goals/assists/matches,
rendered via `PlayerCardView.gd` -- see below) with **Replace** (opens the
bench grid, filtered to that slot's role, scrollable rather than
paginated) and **Clear** buttons; tap an empty slot to jump straight to the
picker. Switching formations carries a player over to a new slot with the
same role automatically (e.g. a CB stays a CB moving 4-4-2 -> 3-5-2);
anyone whose role doesn't exist in the new formation falls back to the
bench. **Save Team** requires every slot filled; until you save, an
"Unsaved changes" banner shows and the Save button itself turns amber --
switching formations or swapping a player never touches Firestore by
itself, only Save does. **Back to Menu discards any unsaved changes**,
reverting the live formation/lineup back to what was last actually saved
(or last loaded, if never saved this session) -- leaving without saving is
a cancel, not a silent keep.

### Controls vs. hand-drawn

Menu/MatchPlayback stayed hand-drawn (`_draw()` + `_unhandled_input()`)
because they're a handful of static buttons -- cheap either way. Team
outgrew that: a formation picker, a scrollable card grid, a stats panel,
several conditional action buttons. Real Control nodes get all of that
mostly for free (layout/anchoring, hover/press feedback, actual scrolling
instead of hand-rolled pagination, no manual `Rect2.has_point()` hit-testing
scattered through input handling) -- see `Team.gd`, `PitchView.gd`, and
`PlayerCardView.gd`. The one thing that stays custom-drawn is the pitch's
grass and line markings (still inside `PitchView.gd`'s own `_draw()`) --
that's inherently a custom visual, not something Controls model well,
same as `MatchPlayback`'s pitch. Shop/PVP/Profile should follow this same
pattern once they're built out, rather than the original hand-drawn stub
style.

Team.tscn is deliberately a thin shell (just the root `Control` with the
script attached) -- the whole node tree is built procedurally in
`Team.gd`'s `_build_ui()` rather than hand-authored in the `.tscn`, since
there's no Godot editor available in the environment this was built in to
place nodes visually; procedural construction is just as "real Controls"
to the engine, and much less error-prone to write blind than a complex
`.tscn` by hand.

### PlayerCardView.gd -- the reusable "card"

A real `.tscn`-authored `Control` (`scenes/components/PlayerCardView.tscn`,
instanced via `PLAYER_CARD_SCENE.instantiate()`) used anywhere a card needs
to be shown -- currently the bench grid and the stats panel's header, later
Shop/PVP too. `set_card(a_player_card)` populates it: a flat background
tinted by `PlayerCard.tier_color()`, overall/position/name/tier labels, and
a `PlayerModelView` child (see below) for the character portrait. When a
real card template/art exists (per-tier background art, a "galaxy" effect
for special/icon tiers), only this one file needs to change -- every
screen that shows a card already goes through it.

**PlayerModelView.gd -- the layered character portrait.** Sits in the
`Model` slot where an empty `Spacer` used to be. Purely `_draw()`-based
(same idiom as `PitchView`'s grass/lines -- a drawn graphic, not something
Control nodes model well), it renders a blocky placeholder character from
5 independent layers: skin tone, hair style (shape) + color (tint), face
(mouth shape), shoe color -- 5 options each, defined in the new
`PlayerAppearance.gd` (`scripts/data/`). That's 5^5 = 3125 distinct looks
from just 25 stored choices, the same "small typed options, extendable"
shape as `PackData.TYPE_COLORS`.

Appearance is real now: `packEngine.PackManager._generate_appearance()`
rolls one per card (pack open, or the bronze starter roster) the same way
it rolls tier/attributes, and it's persisted on `players/{id}` --
`PlayerCard.gd` reads it back like every other field, and
`PlayerModelView.set_card()` prefers it. `PlayerAppearance.mock_from_id()`
(derives all 5 indices deterministically from `player_id` alone, no
storage) is now only a fallback, for a card whose doc predates real
generation and hasn't been backfilled -- see
`backend/scripts/sync_player_appearance.py`'s own docstring (mirrors
`sync_pack_definitions.py`'s shape: `--dry-run`, safely re-runnable, only
touches docs actually missing the field).

**Roster/inventory load once, at login, not on every visit.** All of it --
profile fields, the live formation, the slot assignment, every owned card --
lives in the `GameProfile` autoload as shared global state (the same idea as
`FirebaseAuth.uid`), populated by `GameProfile.load_all()` right after
sign-in succeeds (see `Auth.gd`'s `_go_to_menu()`). Team scene just reads
and mutates that shared state directly instead of holding its own copy or
re-fetching on every visit -- so opening it is instant, and `GameProfile`'s
`is_dirty()` (comparing the live formation/slot_assignment against a
snapshot taken at load time and after every successful save) is what drives
both the unsaved-changes indicator and what `discard_changes()` reverts to.

This talks to Firestore directly with your own signed-in ID token (same
CLIENT-TRUSTED-PHASE model as `packedfootball/firebase_client.py` /
`game_state.py` -- see those files' docstrings), through two new scripts:
`Firestore.gd` (a GDScript port of `firebase_client.py`'s Firestore REST
calls) and `GameProfile.gd` (the roster/inventory/profile cache + save
logic, mirroring `game_state.py`'s `GameState`). It adds one field to the
`users/{uid}` schema, `formation` (a plain string) -- `game_state.py`'s
`load_or_create_profile()` now reads/writes it too, and
`backend/main.py`'s `/match/simulate` passes each side's real formation
into the sim instead of assuming everyone plays 4-4-2 (that was a real bug:
the picker had no effect on actual simulated matches until this).

**Heads-up**: `packedfootball/formations.py`'s `4-2-3-1` still uses
`LCB`/`RCB`/`LDM`/`RDM` role labels while the other three formations were
already simplified to `CB`/`CDM`/`CM` (4-4-2's wide mids are now plain
`CM` too, not `LM`/`RM` -- there's no dedicated wide-midfielder class
distinct from `CM`, so the label was redundant). Cards are only ever
generated with the simplified labels, so this port normalizes `4-2-3-1` to
match -- otherwise its CB/CDM slots could never have an eligible card.
Worth applying the same simplification server-side so client and server
fully agree.

**A brand new account now gets a real starter squad.** `Auth.gd`'s sign-in
flow calls `GameProfile.load_all()`, which now calls the backend's new
`POST /account/bootstrap` first (via the new `Backend.gd` autoload) --
idempotent, so it's a no-op for a returning account, but for a genuinely
new one it generates a full 11-card bronze roster server-side
(`packEngine.py`'s new `generate_starter_roster()`, one card per slot of a
4-4-2) and writes it as that account's profile before the rest of
`load_all()` even reads Firestore. This closes the gap flagged here
before: a brand new Godot-only account used to have no cards and no
roster at all until it also signed into the Python client once.

## Shop screen

Two tabs: **Packs** (real, built now) and **Currency** (microtransactions/
ads -- deliberately a "Coming soon" placeholder; pack mechanics came
first). The pack catalog is fetched fresh from the backend's new
`GET /pack/list` every time the scene loads and again after every
purchase, rather than cached on `GameProfile` like the squad is -- unlike
your own roster, the catalog can change under you at any time (an admin
flips a pack inactive, a limited pack sells out from someone else buying
it), so it's treated as a live storefront, not account data.

Packs have a free-form `type` string (`standard`/`special`/`timed` today,
extendable to more -- nothing branches on a fixed set of them) plus two
independent, optional availability limits that live only on the pack's
Firestore document, never in code: `max_opens` (a hard cap on total opens
-- e.g. a "special" pack selling out after 30) and `expires_at` (an ISO
datetime after which it can't be opened -- e.g. a "timed" pack). Both are
enforced **server-side** in `backend/main.py`'s new `_pack_unavailable_reason()`,
shared by `/pack/list` (to filter what's shown) and `/pack/open` (to
reject a purchase) so the two can't disagree -- verified directly against
8 cases (inactive, under/at/over cap, not-yet/already expired, malformed
date, a pack with neither field at all) before wiring it in. Buying a pack
calls `POST /pack/open`, folds the returned cards straight into
`GameProfile.all_cards` (`add_purchased_cards()`) and updates the credit
balance, then re-fetches the catalog so a now-sold-out pack's card
reflects it immediately.

A pack that's currently unavailable is normally hidden from `/pack/list`
entirely, but an admin can opt one into still being *shown* (grayed tag
instead of a Buy button) via two more Firestore-only fields:
`visible: true` and/or `available_at` (an ISO date alone is enough to
imply it -- e.g. a UCL Promo pack previewed ahead of its real on-sale
date). `backend/main.py`'s `_pack_is_teased()` decides this; `PackData.tag_text()`
picks what the tag says (prefers `available_at`'s date over the raw
`unavailable_reason` when both are present). Neither field auto-flips
`active` once the date passes -- it's a display hint, not a scheduler.

`PackView.gd` / `scenes/components/PackView.tscn` is the pack visual --
"they will have their own image like the cards but for now it can be a
box": a flat rectangle tinted by `PackData.type_color()`, the same
seam `PlayerCardView`/`PackData`'s own doc comments describe for real card
art later. Unlike `PlayerCardView` (tap-anywhere, since picking a card is
low-stakes and reversible), it uses a real labeled **Buy** button --
spending credits deserves a deliberate tap. It also shows the pack's
`description` (flavor text from `packEngine.PACK_DATABASE`) and a small
**i** button in the top-right corner.

### Odds disclosure popup

Tapping a pack's **i** button opens `PackInfoPopup.gd` /
`scenes/components/PackInfoPopup.tscn` -- a single instance embedded
statically in `Shop.tscn` (like `PitchView` is in `Team.tscn`), since only
one can ever be open at a time. It's a `TabContainer` with its tab bar
hidden, paged with custom Prev/Next buttons across 3 pages: description,
card tier odds, then position odds -- the per-tier/per-position
probability disclosure App Store Guideline 3.1.1 and Google Play's loot
box policy both require showing *before* purchase.

The odds come from `PackData.rates` / `.pos_rates` (tier/position ->
0..1 probability), which `/pack/list` now actually returns -- these have
existed in `packEngine.PACK_DATABASE` and been synced to Firestore by
`sync_pack_definitions.py` since packs were first added, but nothing ever
read them back until now. Row order on both odds pages is a fixed
client-side list (`PlayerCard.TIER_COLORS.keys()` for tiers,
`PackInfoPopup.POSITION_CATEGORY_ORDER` for positions), never dictionary
iteration order, since a Firestore/JSON map field's key order isn't
guaranteed to survive the round trip. A tier/position with a 0% rate is
left off the list entirely rather than shown as a 0% row.

**Backend note**: `packEngine.PACK_DATABASE` gained a `type` field on all
4 existing packs (Standard/Jumbo -> `standard`, UCL Promo -> `timed`, Icon
Forward -> `special`), synced by `sync_pack_definitions.py` (now also
syncing `type`, alongside name/price/cards_per_pack/rates/pos_rates).
Neither `max_opens` nor `expires_at` were added to any pack's definition,
by design -- set either directly on a pack's Firestore doc (no redeploy)
whenever you actually want a specific pack to go live with a cap.

## Layout

The pitch (70x100, naturally portrait-shaped) always renders inside a fixed
on-screen box sized to its own aspect ratio (`PITCH_RECT` in
`MatchPlayback.gd`), rather than filling the whole window -- a landscape
phone screen is wide, the pitch is tall, so the extra width next to the
pitch box is where the scoreboard and buttons live (a side panel), instead
of overlaid on top of the pitch the way the pygame reference did (it never
had a side panel to work with, since its window was pitch-only). The
project is configured for landscape orientation with a fixed-aspect stretch
mode, so it won't stretch oddly on a real device's exact resolution.

## What's here

`scripts/` is split into subfolders by role, not left flat, so "where would
the code that does X live" has one obvious answer:

```
scripts/
  screens/     -- one script per navigable scene (1:1 with scenes/*.tscn)
  components/  -- reusable visual building blocks, instanced from screens
  autoload/    -- singletons registered in project.godot's [autoload]
  data/        -- pure data models / format readers -- no I/O, no UI
  config/      -- FirebaseConfig.gd (gitignored) + .example.gd
scenes/
  *.tscn       -- the 7 top-level screens
  components/  -- PlayerCardView.tscn / PlayerModelView.tscn / PitchView.tscn /
				  PackView.tscn / PackInfoPopup.tscn (mirrors scripts/components/)
```

A script's *class_name* (used everywhere scripts reference each other, e.g.
`Formations.get_formation(...)`) resolves globally regardless of which
folder it's in, so moving files around in here never requires touching
those call sites -- only literal path strings (`.tscn` `ext_resource`
lines, `project.godot`'s autoload paths, and the one `preload()` in
`Team.gd`) care where a file actually lives.

### `screens/` -- one script per scene

- `Menu.gd` / `scenes/Menu.tscn` -- navigation hub.
- `Auth.gd` / `scenes/Auth.tscn` -- sign-in/register/guest entry scene (the
  one scene using real Control nodes -- `LineEdit`/`Button` -- instead of
  the hand-drawn style MatchPlayback/Menu use, since native text input is
  exactly what benefits from it).
- `MatchPlayback.gd` / `scenes/Match.tscn` -- loads a replay and renders it
  every frame: Hermite interpolation between the sparse recorded samples
  using the recorded velocity as the tangent (not a naive straight-line
  lerp, and not an estimated Catmull-Rom tangent -- the real velocity is
  already there), the ball glued to whoever's dribbling it rather than
  interpolated on its own, a brief color flash on events (tackle, shot,
  goal, etc.), and the zoom/full camera + speed controls described above.
- `Team.gd` / `scenes/Team.tscn` -- squad management (see above).
- `Profile.gd` / `scenes/Profile.tscn` -- manager profile: rename, squad
  overall/wins/losses/draws, log out. A 1:1 port of
  `packedfootball/main.py`'s `PROFILE` scene -- see its docstring for the
  one deliberate deviation (a real `LineEdit` everywhere instead of
  `main.py`'s browser-vs-desktop branch, since Godot has no pygbag-style
  mobile-text-entry problem to work around).
- `Shop.gd` / `scenes/Shop.tscn` -- pack shop (see above).
- `StubScene.gd` -- shared placeholder script for `scenes/Pvp.tscn` (still
  just sets a `title`), proving scene navigation works before the real
  functionality behind it gets built.

### `components/` -- reusable visuals, not screens themselves

- `PlayerCardView.gd` / `scenes/components/PlayerCardView.tscn` -- the
  reusable card visual (see above).
- `PlayerModelView.gd` / `scenes/components/PlayerModelView.tscn` -- the
  layered placeholder character portrait embedded in `PlayerCardView`
  (see above).
- `PitchView.gd` / `scenes/components/PitchView.tscn` -- the pitch:
  custom-drawn grass/lines + real `Button` slot markers (see above).
- `PackView.gd` / `scenes/components/PackView.tscn` -- the pack "box"
  visual (see above).
- `PackInfoPopup.gd` / `scenes/components/PackInfoPopup.tscn` -- the
  paginated odds-disclosure popup opened from a `PackView`'s **i** button
  (see above).

### `autoload/` -- singletons (registered in `project.godot`)

- `FirebaseAuth.gd` -- GDScript port of `packedfootball/firebase_client.py`'s
  auth flow.
- `Firestore.gd` -- GDScript port of `firebase_client.py`'s Firestore REST
  calls (get/list/set/add/delete document + the field-value wire encoding).
- `Backend.gd` -- calls the Cloud Run backend (`backend/main.py`) with the
  signed-in user's ID token, the same idea as `firebase_client.py`'s
  `call_backend()` split into its own file.
- `GameProfile.gd` -- the live squad model (profile fields, formation, slot
  assignment, every owned card, dirty-checking) on top of `Firestore.gd`,
  mirroring `packedfootball/game_state.py`'s `GameState` plus the caching
  this scene needed on top of it.

### `data/` -- pure data models / format readers

- `Formations.gd` -- the same 4 named formations as
  `packedfootball/formations.py` (see the Team screen section above for the
  one known discrepancy).
- `PlayerCard.gd` -- client-side card data model (fields including the
  real `appearance` dict + `overall()` + `tier_color()`), no gameplay logic
  -- the backend simulates matches, this scene only ever displays/persists
  cards.
- `PlayerAppearance.gd` -- the 5-slot/5-option layered character
  appearance (skin tone, hair style/color, face, shoe color)
  `PlayerModelView` renders, plus the `mock_from_id()` fallback generator
  for a card whose doc predates real generation (see the PlayerCardView
  section above).
- `PackData.gd` -- client-side pack listing data (fields including
  `rates`/`pos_rates` odds + `type_color()`, `is_limited()`/
  `limited_label()`, `tag_text()`), same "display-only" boundary as
  `PlayerCard.gd` -- purchasing is a server-validated backend call, not
  logic that lives here.
- `ReplayReader.gd` -- binary reader for the format `packedfootball/replay.py`
  writes (`ReplayRecorder.encode()`). Keep the two in sync if the wire
  format ever changes.

All buttons across every scene are hand-drawn/hit-tested (`_draw()` +
`_unhandled_input()` with `Rect2.has_point()`) rather than scene-tree
`Button` nodes, kept consistent on purpose everywhere in this project.

## Known gap

I couldn't run Godot itself in the environment this was built in (no Godot
CLI available), so the GDScript here is carefully written against the
Godot 4 API from documentation/knowledge but not actually executed. The
Python side (recording, encoding, determinism) has real automated test
coverage; this half needs your eyes in the editor -- if something doesn't
load, a method name is off, or the button/layout positions need nudging for
your actual screen, that's the most likely place to look first. Team.gd's
Firestore round trip specifically needs a real signed-in account with at
least one card in `roster_player_ids` or `inventory` to show anything (see
the onboarding-gap note above) -- an empty response there isn't necessarily
a bug. The procedurally-built Control tree in `Team.gd`/`PitchView.gd`/
`PlayerCardView.gd` is the newest and least-proven API surface here --
`ButtonGroup`, `GridContainer`/`ScrollContainer` sizing, `StyleBoxFlat`
theme overrides on `Button` states, and the `remove_child()` +
`queue_free()` pairing used everywhere a container gets cleared and
immediately repopulated (necessary because that repopulation can run from
inside one of the very children's own "pressed" signal, e.g. tapping a
bench card or a pitch slot) are all worth a close look first if layout
looks off or a tap doesn't register.
