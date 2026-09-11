# Packed Football - Mobile (Godot)

Landscape-first client scaffold: a Menu hub, placeholder Shop/Team/PVP/Profile
screens, and a real match replay player. Not the full app yet -- no auth, no
backend networking (the match replay is loaded from a local file, not fetched
from the deployed Cloud Run service). See the plan this came from for the
fuller picture.

## Try it

1. Generate (or regenerate) a test replay:
   ```sh
   python3 packedfootball/scripts/dump_test_replay.py
   ```
   Writes to `mobile/test_data/sample_match.bin` (+ a `.json` roster sidecar)
   by default (`--seed`, `--roster-seed`, `--out` all overridable -- see the
   script's `--help`).
2. Open this `mobile/` folder as a project in Godot 4.3+.
3. Run the project. It opens on the Menu; "Play Match" loads
   `test_data/sample_match.bin` and plays it back once you hit Start.

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
- `scripts/StubScene.gd` -- shared placeholder script for
  `Shop.tscn`/`Team.tscn`/`Pvp.tscn`/`Profile.tscn` (each just sets a
  different `title`), proving scene navigation works before the real
  functionality behind each gets built.

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
your actual screen, that's the most likely place to look first.
