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
2. Copy `scripts/FirebaseConfig.example.gd` to `scripts/FirebaseConfig.gd`
   (gitignored) and fill in your Firebase project's real values -- same idea
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

A `Control` subclass instanced with `PlayerCardView.new()` (no companion
`.tscn`) anywhere a card needs to be shown -- currently the bench grid and
the stats panel's header, later Shop/PVP too. `set_card(a_player_card)`
populates it; today that's just a flat background tinted by
`PlayerCard.tier_color()` plus overall/position/name/tier labels. When a
real card template/art exists (per-tier background art, a "galaxy" effect
for special/icon tiers), only this one file needs to change -- every
screen that shows a card already goes through it.

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
logic, mirroring `game_state.py`'s `GameState`). It adds one new field to
the `users/{uid}` schema, `formation` (a plain string), which the Python
side doesn't read or write yet -- worth wiring into whatever builds a
match's `teamA`/`teamB` when you update the backend.

**Heads-up**: `packedfootball/formations.py`'s `4-2-3-1` still uses
`LCB`/`RCB`/`LDM`/`RDM` role labels while the other three formations were
already simplified to `CB`/`CDM`. Cards are only ever generated with the
simplified labels, so this port normalizes `4-2-3-1` to match them --
otherwise its CB/CDM slots could never have an eligible card. Worth
applying the same simplification server-side so client and server agree.

**Also**: a brand new account created straight through this Godot client's
Auth scene has no starting roster or cards at all yet -- `main.py`'s
`load_or_create_profile()` (which seeds a default squad on first login)
is Python-only and isn't called from here. Team scene will just show an
empty pitch and bench until either that seeding gets ported, a backend
"create profile" endpoint exists, or the same account has signed in through
the Python client at least once.

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

- `scripts/ReplayReader.gd` -- binary reader for the format
  `packedfootball/replay.py` writes (`ReplayRecorder.encode()`). Keep the two
  in sync if the wire format ever changes.
- `scripts/MatchPlayback.gd` -- loads a replay and renders it every frame:
  Hermite interpolation between the sparse recorded samples using the
  recorded velocity as the tangent (not a naive straight-line lerp, and not
  an estimated Catmull-Rom tangent -- the real velocity is already there),
  the ball glued to whoever's dribbling it rather than interpolated on its
  own, a brief color flash on events (tackle, shot, goal, etc.), and the
  zoom/full camera + speed controls described above.
- `scripts/Menu.gd` / `scenes/Menu.tscn` -- navigation hub.
- `scripts/Auth.gd` / `scenes/Auth.tscn` -- sign-in/register/guest entry
  scene (the one scene using real Control nodes -- `LineEdit`/`Button` --
  instead of the hand-drawn style everywhere else, since native text input
  is exactly what benefits from it).
- `scripts/FirebaseAuth.gd` -- autoload; GDScript port of
  `packedfootball/firebase_client.py`'s auth flow.
- `scripts/Firestore.gd` -- autoload; GDScript port of
  `firebase_client.py`'s Firestore REST calls (get/list/set/add/delete
  document + the field-value wire encoding).
- `scripts/GameProfile.gd` -- autoload; the live squad model (profile
  fields, formation, slot assignment, every owned card, dirty-checking) on
  top of `Firestore.gd`, mirroring `packedfootball/game_state.py`'s
  `GameState` plus the caching this scene needed on top of it.
- `scripts/Formations.gd` -- the same 4 named formations as
  `packedfootball/formations.py` (see the Team screen section above for the
  one known discrepancy).
- `scripts/PlayerCard.gd` -- client-side card data model (fields +
  `overall()` + `tier_color()`), no gameplay logic -- the backend simulates
  matches, this scene only ever displays/persists cards.
- `scripts/PlayerCardView.gd` -- the reusable card visual (see above).
- `scripts/PitchView.gd` -- the pitch: custom-drawn grass/lines +
  real `Button` slot markers (see above).
- `scripts/Team.gd` / `scenes/Team.tscn` -- squad management (see above).
- `scripts/StubScene.gd` -- shared placeholder script for
  `Shop.tscn`/`Pvp.tscn`/`Profile.tscn` (each just sets a different
  `title`), proving scene navigation works before the real functionality
  behind each gets built.

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
