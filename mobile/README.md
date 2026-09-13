# Packed Football - Mobile (Godot)

Landscape-first client: real email/anonymous auth, a Menu hub (with an
account-details panel), a real Team squad-management screen, a real Quick
Match mode (backend-simulated, real opponent or a bot fallback), a
Settings screen (rename works; language/color theme are stubs),
placeholder Shop-currency/Tournament pieces, and a match replay player.
See the plan this came from for the fuller picture.

## Try it

1. Generate (or regenerate) a local demo replay (used as a fallback when
   Play's Quick Match hasn't been used yet -- see "Play / Quick Match"
   below):
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
   guest) then the Menu; "Play" opens the mode-select hub -- Quick Match
   actually simulates a real match against a real/bot opponent backend-side;
   "Team" manages your actual squad against your real Firestore data.

## Menu screen

`AccountPanel` (left side, `Menu.tscn`) shows the signed-in manager's own
account details at a glance -- display name, squad overall, wins/draws/
losses -- populated fresh in `Menu.gd`'s `_ready()` straight off the
already-loaded `GameProfile` cache (no extra Firestore read; squad data is
fetched once at sign-in, see `Auth.gd`'s `_go_to_menu()`). These are the
same fields the old Profile screen used to show as its whole reason to
exist -- that screen is **Settings** now (see below), so this is the only
place they're glanceable without a screen visit. The nav button column
stays independently centered across the full screen (unchanged) rather
than being squeezed into the remaining space next to the panel -- at this
project's fixed 960-wide viewport there's a comfortable gap between them
either way, so a full `HBoxContainer` restructure wasn't needed.

**Settings** (`Settings.tscn`/`.gd`, was "Profile") -- rename (unchanged
behavior: only writes if the trimmed name is non-empty and actually
changed), plus **Language** and **Color Theme** as explicit stubs: disabled
`OptionButton`s with one placeholder entry each ("English" / "Default")
and a "Coming soon." hint underneath, no functionality behind either yet.
Log Out / Switch Account stayed here rather than moving to `AccountPanel`
-- it's an account-management *action*, not a detail to glance at, so it
fits a settings screen better than a HUD panel.

`theme/AppTheme.tres` gained a project-wide default `Panel` style
(`Panel/styles/panel`, same opaque dark/bordered look the "Button theme"
section above already established for buttons) specifically so
`AccountPanel` didn't need its own one-off `StyleBoxFlat` -- and
`Match.tscn`'s `ScoreboardPanel`/`TimerPanel`, which previously each had
their own explicit override with identical values, now just fall through
to this same default instead (a node-level `theme_override_styles/panel`
still wins over the project theme wherever one actually is set, so nothing
depends on this ordering -- it's a de-duplication, not a behavior change).

## Play / Quick Match

Menu's old direct-to-replay "Play Match" button is now "Play", opening
`Play.tscn`: **Quick Match** (real) and **Tournament** (stub -- see below).

Quick Match calls the backend's new `POST /match/quick`, which:
1. Validates your own saved roster/formation the same way `/match/simulate`
   already does (`_validate_formation_positions` -- rejects before writing
   anything if it's not exact-or-similar-position-legal for every slot).
2. Picks a random opponent (`_pick_opponent_profile`): a real signed-up
   account with a complete (11-player) saved roster, queried straight from
   `users/{uid}` and tried in random order, or -- if none exists, or every
   candidate's own data turns out stale -- a freshly-rolled bot instead
   (random formation *and* random tier, bronze through icon, so a bot can
   plausibly be "the best or worst player" too). Quick Match should always
   find *someone* to play.
3. Runs the actual simulation (`_run_match`, shared with `/match/simulate`)
   and returns the score, the base64 replay, and both sides' full roster
   (so `MatchPlayback.gd` can show real names) -- `Play.gd` hands all of it
   to the new `MatchSession` autoload before navigating to `Match.tscn`.
4. Grants a small credit reward, scaled by outcome
   (`QUICK_MATCH_REWARD_CREDITS = {"win": 100, "draw": 25, "loss": 10}`),
   records wins/losses/draws, persists each player's updated
   goals/assists/matches_played back to their own `players/{id}` doc (see
   `_persist_player_stats` below), and snapshots both rosters into the
   `games/{id}` doc (see `_teams_snapshot` below).

**Individual player stats now actually persist after a match -- for the
initiator's own roster only.** `gameEngine.py` was already correctly
tracking each player's goals/assists/matches_played *in memory* during
simulation (`player.py`'s `scored()`/`assisted()`/`match_played()`, called
from `game`'s own goal/full-time handling) -- but nothing ever wrote that
back to Firestore, so `/leaderboard/players` (which already queries
`players/{id}.statistics.*` directly) would only ever have seen the zeros
every card starts at. Both `/match/simulate` and `/match/quick` now call
the new `_persist_player_stats` right after `_run_match()`, which re-saves
the CALLER's roster via `GameState.save_roster()`.

Deliberately caller-only, by design decision: whoever's on the other side
of a match (a real opponent or a bot) never chose to play that specific
game -- having a saved account isn't agreeing to any one match -- so their
own players' stats aren't touched, matching how neither endpoint has ever
updated the opponent's own account-level wins/losses/draws. Also sets up
cleanly for a future where a player's own match count matters for
something like a contract, which should only ever move for whoever
actually chose to play.

Also correct for an out-of-position player specifically: the
scaled-attributes copy `_apply_out_of_position_penalty` builds is a
*shallow* copy, so it shares the exact same `statistics` dict object as
the real, persisted player -- goals/assists scored while playing out of
position still land on the real card, while the temporary scaled
attributes never do (verified directly: mutating the copy's stats updates
the original; the two `.attributes` stay independent).

**Finding a match shows a popup, not just a status label.** `Play.gd`'s
`MatchmakingPopup` (a scrim + a small rotating-arc `LoadingSpinner` --
`scenes/components/LoadingSpinner.tscn`, hand-drawn like everything else
Godot has no built-in Control for -- + a status label) covers the screen
for the whole `/match/quick` round trip. That round trip is genuinely one
request: the backend picks the opponent, simulates the match, and persists
everything before it replies, so there's no real "phase" for the client
to observe -- the "Finding an opponent..." -> "Simulating match..." switch
partway through is a scripted narrative on a timer (`get_tree().create_timer
(0.6)`), not real server progress, purely so the wait reads as "working on
it" rather than a frozen button. A guard flag (`_matchmaking_active`)
stops that timer's callback from touching the status label if the request
already finished (success or failure) before it fires.

**`MatchSession.gd`** (autoload) is how the just-fetched result reaches
`MatchPlayback.gd` -- Godot's `change_scene_to_file()` can't carry data
itself, so this is the same "shared blackboard" idea `GameProfile` already
is for squad state, just for one in-flight match result. `MatchPlayback.gd`
checks `MatchSession.has_pending()` on `_ready()`: true plays that real
match (decoded via `ReplayReader.load_from_bytes()` -- writes the bytes to
a `user://` scratch file and reuses `load_from_file()`'s proven parser
rather than a second, subtly-different in-memory one); false falls back to
the bundled local demo replay exactly as before, so that offline path
(no backend, no signed-in account) still works unchanged.

`MatchPlayback.gd` deliberately does NOT clear `MatchSession` once it's
read it, unlike every other consumed-once autoload field in this project --
`MatchResult.tscn` (see "Match screen" below) still needs `score`/
`credits_earned`/`opponent_display_name`/`opponent_is_bot` off of it after
full time, so clearing happens there instead once it's actually done
reading, or immediately in `MatchPlayback.gd`'s own pause-menu "Exit to
Main Menu" if the player leaves before the match ever gets there.

**`lobby` is gone entirely -- backend and Godot both.** It used to gate
opponent discovery for both match endpoints through a `lobby/{uid}` "opted
in to being challenged" doc -- an extra collection that only ever needed
to answer "does this account exist and have a complete roster", which
`users/{uid}` already answers directly. `_pick_opponent_profile` queries
`list_collection("users")` (filtering by `roster_player_ids` length)
instead, and `/match/simulate`'s opponent-exists check reads
`users/{opponent_uid}` instead of `lobby/{opponent_uid}`. Nothing in
`backend/main.py` reads or writes `lobby`.

`GameProfile.gd` used to also *publish* to `lobby/{uid}` after every
`save_team()` (leaderboard-relevant fields only -- `display_name`/
`overall`/`wins`/`campaign_level`, no roster), but that write had no reader
anywhere at all by that point (the backend never looked at `lobby`, and
Godot never read it either, only wrote it), so it's been deleted too --
`save_team()`/`set_display_name()` no longer touch `lobby` in any way.
Player-blob leaderboards (see `players/{player_id}.statistics` below) will
be built later by reading straight from `users`/`players` docs, not from a
separate snapshot collection -- there is no `lobby` collection anywhere in
this project anymore, client or server.

**Elo is gone from the active system entirely** -- no computation, no
storage, no display, anywhere in `backend/main.py` or `GameProfile.gd`.
`/match/simulate` no longer computes or updates a rating after a match,
and `GameProfile.gd` has no `elo` field at all.

**The original pygame/pygbag client has been removed from the repo
entirely** -- `packedfootball/main.py`, `auth_scene.py`,
`firebase_client.py`, `firebase_config.example.py`, `native_form.py`, and
its `build/` output are all gone. That was the last caller of
`packedfootball/game_state.py`'s own `publish_lobby_entry`/`list_opponents`/
`list_leaderboard` and its elo scaffolding (`DEFAULT_STARTING_ELO`,
`GameState.set_elo`, the `elo` field `load_or_create_profile` used to
carry) -- both had been deliberately left in place through the `lobby` and
elo cleanups above specifically because that client still depended on
them; with it gone, so are they. `packedfootball/` is backend-critical
code only now (see `backend/README.md`).

**`games/{id}` now always carries a roster snapshot.** `/match/simulate`
already embedded a `"teams"` field (both sides' uid/display_name/formation/
full player fields at match time); `/match/quick` now does too, both
sharing the new `_teams_snapshot` helper. The point: a dispute or bug can
be checked afterwards against exactly what was actually played, independent
of whatever either account's `players/{id}` docs look like by the time
anyone looks -- whether from later, legitimate pack opens or suspected
tampering.

**Tournament** (`Tournament.tscn`) is an explicit stub for now -- reuses
`StubScene.gd` (now with a configurable `back_scene`, so its Back button
returns to Play rather than Menu). The eventual design: a 1-day, 10-match
bracket per entry, 4 skill categories (Amateur -> Semi-Pro -> ... ),
promotion by winning, matched against similarly-ranked players rather than
Quick Match's fully-random pool -- not built yet.

**Diagnostics**: `backend/scripts/list_accounts.py` (read-only) lists every
`users/{uid}` doc and whether its roster is complete enough to be a Quick
Match candidate (`roster_player_ids` length == 11) -- a general "how many
accounts, how complete are their rosters" check.

## Match screen

`Match.tscn`'s root is a plain `Control` now, not the whole screen's
script owner -- `MatchPlayback.gd` lives on `PitchCanvas`, a `Control`
child with `clip_contents = true`, centered horizontally by a
`CenterContainer` parent. Everything else -- scoreboard, timer, pause/
camera/speed buttons, the pre-match blackout, the pause overlay -- is real
Control nodes, siblings of `PitchCanvas` under the same root, overlaid on
top of the pitch like a HUD rather than living in a separate side panel
the way the old cramped 350x500-in-a-960 layout did.

**`PitchCanvas`'s size now depends on camera mode**, via
`_update_pitch_canvas_size()` (called on `_ready()` and every camera
toggle): "full" mode keeps the old fixed `FULL_MODE_BOX_SIZE` (378x540,
the pitch's own 70:100 aspect ratio, so the whole pitch fits with zero
letterboxing); "zoom" mode resizes it to `get_viewport_rect().size` --
the whole screen -- since a cropped, ball-following view has no aspect
ratio of its own to preserve, and filling the screen just means more of
that crop is visible at once. `_compute_camera`, the grass fill, and the
banner text all read this box's *live* `size` now rather than a fixed
constant, since it can change out from under them.

Filling the screen in "zoom" mode exposed a real bug in the existing
horizontal camera-follow math, not just a resize: `visible_x_span`
(how much pitch width the view covers) scales with the box's own aspect
ratio, and at full screen width that span (~80 units) exceeds the pitch's
own width (70 units) for the first time -- the old
`clampf(ball_x - span/2, 0, PITCH_WIDTH - span)` collapses to a constant
0 the moment `span > PITCH_WIDTH` (a negative upper clamp bound), which
pins the pitch flush to the screen's *left* edge with all the leftover
width dumped on the right, ignoring the ball entirely, rather than
centering it. `_compute_camera` special-cases `visible_x_span >=
PITCH_WIDTH` now: center on the pitch's own midline instead of clamping,
so the pitch reads as centered (a bit of grass past both touchlines) at
full screen width, while ball-following panning still works exactly as
before whenever the span *does* fit (e.g. "full" mode's narrower box).

**Two bugs this replaced, not just moved:**
- Player index labels and the ball-carrier's name used to scale their font
  size with the camera's current zoom factor (`scale / 5.0`) -- meaning
  switching from "Full Pitch" to "Zoom" mode (which roughly doubles
  `scale`) roughly doubled the text size too. Both now draw at a fixed
  screen-space size regardless of camera mode, the way UI text should.
- Pitch lines (halfway line, penalty boxes, corner arcs, goal netting) had
  no clipping at all -- a line only partly inside the visible crop (mostly
  in "Zoom" mode, which only shows a sub-region of the pitch) still drew
  its *entire* length, spilling out past where the pitch box visually
  ends. `clip_contents = true` on `PitchCanvas` fixes this at the engine
  level for everything drawn there (lines, players, the ball, the goal/
  banner text) -- Godot clips a Control's own `_draw()` output to its rect,
  not just its children's, so this needed no manual per-shape clipping.
  The old per-player "skip if its center point is outside the box" check
  is gone too, superseded by the same real clipping (and looks better: a
  player dot right at the crop edge now shows a partial circle instead of
  vanishing outright).

**Scoreboard** (top-left, `ScoreboardPanel`) is a real opaque `Panel`
(`StyleBoxFlat`, alpha 1 -- same "actually opaque" fix as the button theme
below) showing each team's name with a small color swatch underneath it,
and the score between them. Colors come from `MatchPlayback.gd`'s
`_team_color(team_index)`, which checks `roster["home_color"]`/
`roster["away_color"]` (an `[r, g, b]` array) and falls back to
`DEFAULT_TEAM_COLORS` (blue/red) if absent -- nothing populates that field
yet (today's blue-for-Team-A/red-for-Team-B is always the fallback), but
both the scoreboard swatches and the on-pitch player dots already read
from this one place, so wiring in actual user-chosen shirt colors later is
just populating that field, no rendering changes needed.

**Timer** (top-center, `TimerBar`) is a `CenterContainer` spanning the full
width so its small opaque `TimerPanel` centers regardless of screen width,
rather than being hand-positioned.

**Camera toggle** moved to the bottom-right (was a stacked side-panel
button); **Pause** is new, top-right, with **Speed** (`SpeedButton`,
cycling 1x -> 2x -> 4x -> 1x) right beside it. Speed scales everything
time-based uniformly (`effective_delta = delta * speed_options[speed_index]`
-- match clock, halftime pause, event flashes/banners), not just the match
itself, same as before the redesign.

**Pre-match**: the screen starts fully blacked out (`PreMatchOverlay`, an
opaque `ColorRect` + team names + a **Start Match** button) rather than
showing a static kickoff frame with a small button among several others.
Pressing Start hides it and begins playback exactly as before.

**Pause** (top-right button, toggles): freezes `_process()` entirely
(playback tick, flash timers, banners all hold) and shows a menu with
**Skip to Halftime**, **Skip to Full Time**, and **Exit to Main Menu** --
tapping Pause again (its label flips to "Resume") closes the menu and
un-freezes. Deliberately no scrub-backward control: **Skip to Halftime**
disables itself once playback has already passed halftime, since jumping
there from later in the match would rewind the scoreboard (`_jump_to_event`
replays every event from kickoff up to the target tick to arrive at a
correct score, which is exactly rewinding if the target is in the past).
**Exit to Main Menu** is the only way to leave mid-match now -- there's no
standalone "Back" button during play, on purpose.

Nothing about pausing or exiting early affects the actual result: Quick
Match's entire simulation already ran and was persisted server-side before
`Match.tscn` even loaded (see "Play / Quick Match" above) -- this screen
only ever plays back a replay of an already-decided outcome.

**Full time -> Match Result.** For a real match (not the bundled demo
replay), reaching FULL TIME -- naturally or via **Skip to Full Time** --
waits for the usual "FULL TIME" banner to finish, then navigates to
`MatchResult.tscn`. The demo replay path shows the same banner and simply
stays there (no account, no result to show, `Exit to Main Menu` still
works via pause).

## Match Result screen

`MatchResult.tscn`/`.gd` -- Won/Drew/Lost (colored green/amber/red),
final score, and credits earned, then **Continue** back to Menu. Reads
`MatchSession.score`/`credits_earned`/`opponent_display_name`/
`opponent_is_bot` (still sitting there since `MatchPlayback.gd` didn't
clear it -- see above) and clears it itself once read. Purely a recap
screen -- nothing here writes anything; the win/loss/credits were already
final and persisted by the backend before Quick Match's response ever
reached `Play.gd`.

### Player card stats after a match

**Continue** re-fetches the squad (`await GameProfile.load_all()`) before
navigating to Menu, showing a `LoadingPopup` ("Loading players...") while
it does. Fixes a real desync: `/match/quick` already persists each played
player's updated `goals`/`assists`/`matches_played` server-side (see
`backend/main.py`'s `_persist_player_stats`), but `GameProfile.all_cards`
was only ever populated once, at sign-in (`Auth.gd`'s `_go_to_menu()` ->
`GameProfile.load_all()`) -- nothing had refreshed it since, so `Team`'s
own card views (via `PlayerCardView.gd`) kept showing whatever a player's
stats were *before* the match, until a full app restart happened to
reload everything fresh. The same fix, for the same reason, lives in
`MatchPlayback.gd`'s pause-menu **Exit to Main Menu** too -- Quick Match's
entire simulate-and-persist round trip already finished before playback
ever starts (see "Play / Quick Match" above), so backing out mid-replay
via pause has the exact same stale-cache problem as watching it through to
Continue; skipped entirely for the bundled demo replay (`_is_real_match`
false), since nothing backend-side happened for that path.

`scenes/components/LoadingPopup.tscn` (+ `LoadingPopup.gd`) is a small
extraction from what was `Play.gd`'s own inline `MatchmakingPopup` markup
(scrim + `LoadingSpinner` + a status label) -- now a shared component
(`set_status(text)` + the inherited `visible`) used in all three places a
screen needs to say "working on it": `Play.gd`'s matchmaking, and these
two squad-refresh spots. `Play.gd`'s own staged "Finding an opponent..."
-> "Simulating match..." narrative-over-a-timer logic stayed exactly
where it was (that's specific to how one round trip is narrated, not
something the popup component itself needs to know about) -- only the
markup and the status-label plumbing moved.

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
bench grid, filtered to that slot's role *and any similar position*,
scrollable rather than paginated) and **Clear** buttons; tap an empty slot
to jump straight to the picker. Switching formations carries a player over
to a new slot with the same role automatically (e.g. a CB stays a CB
moving 4-4-2 -> 3-5-2); anyone whose role doesn't exist in the new
formation falls back to the bench. **Save Team** requires every slot
filled; until you save, an "Unsaved changes" banner shows and the Save
button itself turns amber -- switching formations or swapping a player
never touches Firestore by itself, only Save does. **Back to Menu discards
any unsaved changes**, reverting the live formation/lineup back to what
was last actually saved (or last loaded, if never saved this session) --
leaving without saving is a cancel, not a silent keep.

### Playing out of position

A bench card can fill a slot whose role isn't its own exact position if the
two are "similar" -- `Formations.POSITION_GROUPS` (mirrored in
`packedfootball/formations.py`) defines this as named groups rather than a
flat pairwise list: `{CDM, CM}`, `{CM, CAM}`, `{LB, WB, LM, LW}`,
`{RB, WB, RM, RW}`, `{LW, RW, ST}`. Deliberately not transitive across
groups (a CDM can play CM and a CM can play CAM, but a CDM can't play CAM
directly) and not exhaustive (`GK` and `CB` are in no group, so neither
ever substitutes for anything). Anything outside these pairs stays exactly
as filtered-out as it always was.

Godot only ever *shows* this -- the picker widens to include similar-
position cards (tagged, position label tinted amber) alongside exact
matches, the stats panel adds a warning line when the assigned card is out
of position, and the pitch marker itself gets an amber border + "(OOP)"
suffix. The actual gameplay effect -- a flat 10% cut to every non-tendency
attribute (tendencies are behavioral weights, not skill, so scaling them
wouldn't mean "worse") -- only ever applies inside `gameEngine.py`'s
`game.__init__`, as a scaled copy built fresh for that one simulation; the
stored card and everything the Team screen displays are never touched.
`backend/main.py`'s `/match/simulate` independently re-derives and rejects
(before writing anything -- no `games/{id}` doc, no profile write either
way) any roster/formation pairing that isn't an exact-or-similar match for
every slot, since the Team scene's own picker isn't something the backend
can trust a client actually went through.

### Controls vs. hand-drawn

Every real screen is real Control nodes now (`Auth`, `Menu`, `Play`, `Shop`,
`Team`, `Settings`) -- layout/anchoring, hover/press feedback, actual
scrolling instead of hand-rolled pagination, no manual `Rect2.has_point()`
hit-testing scattered through input handling, see `Team.gd`, `PitchView.gd`,
and `PlayerCardView.gd` for the more involved cases. `Menu.gd` was the last
holdout (fixed pixel `Rect2`s hand-tested in `_unhandled_input()`) --
rebuilt the same way as everything else once it stopped being a
proof-that-scene-switching-works throwaway.

Two things stay genuinely hand-drawn, for two different reasons:
`Tournament.tscn` (`StubScene.gd`) is just not built yet -- once it gets
real functionality it should get real Controls at the same time, same as
Shop/Team/Settings/Leaderboard already did (Leaderboard, formerly the Pvp
stub, was the last of those -- see "Leaderboard screen" below). The pitch
itself (`MatchPlayback.gd`'s `PitchCanvas`, and
`PitchView.gd`'s pitch markings) stays custom-drawn permanently -- a
rendered pitch (grass, lines, a moving ball and players under a panning/
zooming camera) is inherently a custom visual, not something Controls
model well. Everything *around* that pitch in `Match.tscn` -- scoreboard,
timer, pause/camera buttons, the pre-match and pause overlays -- is real
Controls, same as everywhere else (see "Match screen" below); the
hand-drawn part is scoped to the pitch rendering specifically, not the
whole screen the way it used to be.

### Background

`scenes/components/BackgroundLayer.tscn` is a single reusable `TextureRect`
(cover-fit via `expand_mode`/`stretch_mode`, `mouse_filter` set to ignore so
it never eats clicks meant for whatever's drawn over it) currently pointed
at one placeholder image (`sprites/backgrounds/title_background.jpg`) for
every screen, instanced as the first child of every real screen's root
(`Auth`, `Menu`, `Play`, `Shop`, `Team`, `Settings`, `Leaderboard`,
`Match`, and the `Tournament` stub) so it paints behind everything else in
that scene. Same image everywhere for now -- swapping in a real per-page
background later is just changing that one instance's `texture` property
in the editor, no script or layout changes needed.

`Match.tscn` gets one too, unlike most of this session's other additions
to this list -- its pitch box no longer fills the whole screen (see
"Layout" below), so the `BackgroundLayer` is genuinely visible in the
empty side margins beside it, not fully hidden behind an opaque pitch
fill the way it would have been under the old edge-to-edge side-panel
layout.

`Tournament.tscn` is the one remaining place `BackgroundLayer` needs
`show_behind_parent = true` set on the instance -- `StubScene.gd`'s root
node draws its own title/back-button directly (`_draw()`), and Godot
paints a node's children after (on top of) the node's own drawing by
default, so without that flag the background would cover the stub's text
instead of sitting behind it.

Team.tscn is deliberately a thin shell (just the root `Control` with the
script attached) -- the whole node tree is built procedurally in
`Team.gd`'s `_build_ui()` rather than hand-authored in the `.tscn`, since
there's no Godot editor available in the environment this was built in to
place nodes visually; procedural construction is just as "real Controls"
to the engine, and much less error-prone to write blind than a complex
`.tscn` by hand.

### Button theme

`theme/AppTheme.tres`, set as the project's default theme
(`project.godot`'s `[gui] theme/custom`), so it applies to every `Button`
everywhere with no per-scene wiring. Explicit opaque `StyleBoxFlat`s for
`normal`/`hover`/`pressed`/`hover_pressed` (Godot's own built-in default
theme doesn't guarantee full alpha across every button state) -- this
barely showed against a plain clear-color background, but became obvious
once the photo `BackgroundLayer` (above) sat behind every button: `hover`/
`pressed` step up to a visibly lighter fill so a press still reads as
tactile feedback rather than just "more opaque." `focus` is outline-only
(`draw_center = false`) so keyboard/controller navigation gets a visible
ring without another filled box competing with `normal`. `disabled` is the
one state that's *supposed* to look washed out, so it's the one still
using a translucent `bg_color` on purpose.

### PlayerCardView.gd -- the reusable "card"

A real `.tscn`-authored `Control` (`scenes/components/PlayerCardView.tscn`,
instanced via `PLAYER_CARD_SCENE.instantiate()`) used anywhere a card needs
to be shown -- `Team.tscn`'s bench grid and stats panel header, and now
`PackReveal.tscn`'s reveal/browse/stats popup too (see "Pack reveal
screen" above). Not `Leaderboard.tscn`'s Players tab, deliberately -- that
one's plain text rows for now (see "Leaderboard screen" below).
`set_card(a_player_card)` populates it: a flat background tinted by
`PlayerCard.tier_color()`, overall/position/name/tier labels, and a
`PlayerModelView` child (see below) for the character portrait. When a
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
balance, then hands the opened cards off to the new **Pack reveal
screen** (see below) instead of staying on `Shop.tscn` -- the catalog
naturally re-fetches next time this scene is (re)entered anyway (`_ready()`
already calls `_load_packs()` every visit), so a now-sold-out pack's card
reflects it by the time you're back here regardless.

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

## Pack reveal screen

`PackReveal.gd`/`scenes/PackReveal.tscn` -- an EA-FC-style reveal for a
just-bought pack, reached from `Shop.gd`'s `_on_buy_pressed` via a new
`PackSession` autoload (mirrors `MatchSession.gd`'s exact contract --
`has_pending()`/a setter/`clear()` -- just simpler: `Shop.gd` already
builds the typed `Array[PlayerCard]` locally for `GameProfile.
add_purchased_cards()`, so this holds that same array directly, no raw-
dict/base64 decoding step the way replay bytes need).

Two states. **Reveal**: each card gets its own `PlayerCardView` instance
(the same reusable component the bench grid and Shop already use --
nothing new needed for the card visual itself), shown one at a time via a
`Tween` (scale + fade in, hold, fade out), worst tier first
(`PlayerCard.tier_rank()`, a new static helper alongside the existing
`tier_color()` -- rarity first, `overall()` as the tiebreak, same as EA FC
hypes a pull) so the best card lands last as a bigger "hero" moment --
how much bigger scales with *that card's own tier*, not a flat multiplier
(`HERO_SCALE_BY_TIER`: 1.25x for a bronze hero up to 2x for icon), plus
`PlayerCardView.set_highlighted()` (an existing hook, previously only used
by `Team.gd`) for a subtle tint. Tapping anywhere while an *earlier*
(non-hero) card is showing skips straight to **Browse** with every card
already in its final resting state -- skip means skip *all* of it, not
advance one card at a time. The hero card itself is different: it never
auto-advances no matter how long you leave it -- `_wait_for_tap()` just
awaits the same tap-anywhere button's own `pressed` signal directly, no
timer at all, forcing an explicit tap before continuing (the hint label
switches from "Tap to skip" to "Tap to continue" at that point). Since
the hero is always the last card either way, "skip the rest" and "tap to
continue past the hero" land on the exact same next state, so this needed
no separate bookkeeping.

This is the first `Tween` usage anywhere in this project (grepped before
starting -- zero prior `Tween`/`AnimationPlayer` usage at all). A killed
`Tween` never fires `finished`, which would hang `await tween.finished`
forever if skip just called `.kill()` -- it instead fast-forwards the
active `Tween` via `custom_step(9999.0)` (a real step, so it still
finishes normally) and force-expires the active hold's `SceneTreeTimer`
via `time_left = 0.0`, so whatever's currently awaited resumes on the very
next frame either way.

An earlier pass added a diamond+ sparkle overlay on `PlayerCardView` and a
firework burst for the special/icon hero moment, both fully hand-drawn
(no texture/particle assets, same reasoning as `PlayerModelView`) -- both
were removed again shortly after (real art/animation for this is coming
later instead), so if you go looking: the tier-based hero *scale* is the
one part of that pass that stayed.

**Browse**: every card (reparented from the reveal, or freshly
instantiated on the spot for any card an early skip never got to --
both cases are handled explicitly, not just the ones that got a turn) in
a scrollable grid, same disposable-child population pattern as Shop's
pack grid and Team's bench grid. Tapping a card reuses `PlayerCardView`'s
existing `pressed` signal (already proven this way in `Team.gd`) to open
a stats popup -- same attribute list as `Team.gd`'s own `ATTR_ROWS`,
looked up by `player_id` from `GameProfile.all_cards` (already merged in
by `add_purchased_cards()` before this screen ever loads), the same
lookup `Team.gd`'s own stats panel already does. Deliberately **not** a
shared refactor of `Team.gd`'s stats panel into a new component -- a
reasonable future cleanup once a third call site wants this, not
something worth touching already-shipped `Team.gd` code for today; the
attribute-row list is duplicated between the two screens on purpose for
the same reason.

**What this doesn't have yet, on purpose**: no real card-frame art or
animation assets exist anywhere in this project -- the reveal animates
the same placeholder visuals (`PlayerCardView`'s tier-colored background,
`PlayerModelView`'s hand-drawn portrait) used everywhere else today, just
in motion. No audio either -- this project has zero sound anywhere, and
none was added here. Both are real future work, not oversights.

## Leaderboard screen

`Leaderboard.gd`/`scenes/Leaderboard.tscn` -- replaces what used to be
`Pvp.tscn` (a `StubScene.gd` placeholder, never anything real). Two tabs,
switched by a `toggle_mode` `Button` pair sharing a `ButtonGroup` (same
mutual-exclusivity idea as `Team.tscn`'s formation row) rather than a
`TabContainer`, matching `Shop.tscn`'s own Packs/Currency tab pattern:

- **Users** -- ranked by wins, `GET /leaderboard/users` (new).
- **Players** -- ranked by goals, `GET /leaderboard/players` (already
  existed -- see `backend/README.md`'s "Leaderboard endpoints").

Each tab lazy-loads once, the first time it's opened, and caches its
result for the rest of the screen's lifetime -- switching back and forth
doesn't refetch. Rows are plain dynamically-created `Label`s (`"1. Alice --
12 wins"`, `"1. Leo Rossi (ST) -- 9 goals"`) built the same
remove-then-`queue_free()`-then-repopulate way `Shop.gd`'s pack grid and
`Team.gd`'s bench grid both already do -- deliberately not `PlayerCardView`
for the Players tab (see "PlayerCardView.gd" above); rank is just
`index + 1`, since neither endpoint's response carries an explicit rank
field.

Explicitly a minimal first pass, not a finished design -- proves the
page/tab/backend-round-trip shape end to end for early testers who want to
see pages exist, same spirit as Shop's own Currency tab. Both backend
endpoints are already shaped to make adding more (a third tab, more stats
per tab, pagination past the top 20) a small, mechanical follow-up rather
than new plumbing, whenever that's actually wanted.

## Layout

The pitch (70x100, naturally portrait-shaped) renders inside a box whose
size depends on camera mode (see "Match screen" above): a fixed
aspect-correct box (`FULL_MODE_BOX_SIZE` in `MatchPlayback.gd`, 378x540)
in "full" mode -- a landscape phone screen is wide, the pitch is tall, so
this leaves real empty margins on both sides (the `BackgroundLayer`
placeholder shows through there -- see "Background" above) -- or the
entire viewport in "zoom" mode, where there's no pitch-shaped aspect ratio
to preserve since the camera only ever shows a ball-following crop anyway.
Scoreboard/timer/pause/camera/speed controls are overlaid on top of the
pitch as a HUD in both modes (see "Match screen" above) rather than living
in a side panel the way this used to work, closer to how the pygame
reference did it (it never had a side panel to work with, since its window
was pitch-only) -- just with real Control nodes instead of everything
hand-drawn. The project is configured for landscape orientation with a
fixed-aspect stretch mode, so it won't stretch oddly on a real device's
exact resolution.

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

- `Menu.gd` / `scenes/Menu.tscn` -- navigation hub + account details panel
  (see "Menu screen" above).
- `Auth.gd` / `scenes/Auth.tscn` -- sign-in/register/guest entry scene, real
  `LineEdit`/`Button` nodes (see "Controls vs. hand-drawn" above) --
  particularly important here since native text input is exactly what
  benefits from it. Two separate panels toggled in place (`SignInPanel`/
  `RegisterPanel`, one `StatusLabel` shared between them): sign-in is just
  email/password; register is a genuinely different form (manager name in
  addition to email/password), since a brand new manager needs a name
  before their squad/leaderboard entry means anything. The chosen name is
  applied via `GameProfile.set_display_name()` *after* `_go_to_menu()`'s
  `GameProfile.load_all()` has run the backend's `/account/bootstrap` --
  writing it any earlier would make bootstrap see an already-existing
  `users/{uid}` doc and skip starter-roster creation entirely (see
  `bootstrap_account`'s own docstring in `backend/main.py`).
- `MatchPlayback.gd` / `scenes/Match.tscn` -- loads a replay and renders it
  every frame: Hermite interpolation between the sparse recorded samples
  using the recorded velocity as the tangent (not a naive straight-line
  lerp, and not an estimated Catmull-Rom tangent -- the real velocity is
  already there), the ball glued to whoever's dribbling it rather than
  interpolated on its own, a brief color flash on events (tackle, shot,
  goal, etc.), and the zoom/full camera toggle. The script lives on
  `PitchCanvas`, a clipped sub-`Control`, not the scene root -- see
  "Match screen" above for the full HUD/pause/pre-match layout.
- `MatchResult.gd` / `scenes/MatchResult.tscn` -- post-match recap (see
  "Match Result screen" above).
- `Team.gd` / `scenes/Team.tscn` -- squad management (see above).
- `Settings.gd` / `scenes/Settings.tscn` (was "Profile") -- rename,
  Language/Color Theme stubs, log out (see "Menu screen" above). Rename
  behavior is a 1:1 port of `packedfootball/main.py`'s `PROFILE` scene --
  see its docstring for the one deliberate deviation (a real `LineEdit`
  everywhere instead of `main.py`'s browser-vs-desktop branch, since Godot
  has no pygbag-style mobile-text-entry problem to work around).
- `Shop.gd` / `scenes/Shop.tscn` -- pack shop (see above).
- `PackReveal.gd` / `scenes/PackReveal.tscn` -- pack-opening reveal
  animation (see "Pack reveal screen" above).
- `Play.gd` / `scenes/Play.tscn` -- match-mode hub: Quick Match (real) and
  Tournament (stub) (see "Play / Quick Match" above).
- `Leaderboard.gd` / `scenes/Leaderboard.tscn` (was "Pvp") -- Users/Players
  tabs (see "Leaderboard screen" above).
- `StubScene.gd` -- shared placeholder script, now only for
  `scenes/Tournament.tscn` (sets a `title` + a `back_scene` to return to),
  proving scene navigation works before the real functionality behind it
  gets built. `scenes/Pvp.tscn` used to be its other user, before becoming
  `Leaderboard.gd`/`scenes/Leaderboard.tscn` (see "Leaderboard screen"
  above).

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
- `LoadingSpinner.gd` / `scenes/components/LoadingSpinner.tscn` -- a small
  rotating-arc spinner, hand-drawn since Godot has no built-in
  indeterminate spinner Control. Used inside `LoadingPopup.tscn` below;
  generic enough on its own to reuse anywhere else a moment needs a spinner
  without the rest of a full modal popup.
- `LoadingPopup.gd` / `scenes/components/LoadingPopup.tscn` -- the shared
  "working on it" modal (scrim + `LoadingSpinner` + a `set_status(text)`
  status label) -- `Play.gd`'s matchmaking popup and the two post-match
  squad-refresh popups (see "Player card stats after a match" above) all
  use this same component now.
- `scenes/components/BackgroundLayer.tscn` -- no script, just a
  pre-configured `TextureRect` (see "Background" above); shared placeholder
  background image, instanced on every real screen.

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
- `MatchSession.gd` -- carries one just-played real match's result
  (replay/roster/score/reward) from `Play.gd` through `MatchPlayback.gd` to
  `MatchResult.gd` (see "Play / Quick Match" above) -- the same
  shared-autoload idea as `GameProfile.gd`, just for a single in-flight
  match instead of the whole squad. Two hops now, not one: `MatchPlayback`
  reads it but doesn't clear it, `MatchResult` does.
- `PackSession.gd` -- same shared-autoload idea, one hop: `Shop.gd` ->
  `PackReveal.gd` (see "Pack reveal screen" above), for one just-opened
  pack's cards.

### `data/` -- pure data models / format readers

- `Formations.gd` -- the same 4 named formations plus `POSITION_GROUPS`/
  `is_similar_position()` as `packedfootball/formations.py` (see the Team
  screen section above for the one known formation discrepancy and the
  "Playing out of position" section for the similarity groups).
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
  format ever changes. `load_from_bytes()` (new) is `load_from_file()` fed
  by a scratch file instead of a bundled one, for a replay that arrived
  over the network (see "Play / Quick Match" above).

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
