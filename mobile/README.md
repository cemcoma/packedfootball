# Packed Football - Mobile (Godot)

Proof-of-concept replay playback. Not the full app yet -- no auth, no menus,
no backend networking. Just: load a locally-dumped match replay, render it,
judge whether the interpolation looks good. See the plan this came from for
the fuller picture.

## Try it

1. Generate (or regenerate) a test replay:
   ```sh
   python3 packedfootball/scripts/dump_test_replay.py
   ```
   Writes to `mobile/test_data/sample_match.bin` by default (`--seed`,
   `--roster-seed`, `--out` all overridable -- see the script's `--help`).
2. Open this `mobile/` folder as a project in Godot 4.3+.
3. Run the project (the main scene is `scenes/Match.tscn`). It loads
   `test_data/sample_match.bin` and plays it back immediately.

## What's here

- `scripts/ReplayReader.gd` -- binary reader for the format
  `packedfootball/replay.py` writes (`ReplayRecorder.encode()`). Keep the two
  in sync if the wire format ever changes.
- `scripts/MatchPlayback.gd` -- loads a replay and renders it every frame:
  Hermite interpolation between the sparse recorded samples using the
  recorded velocity as the tangent (not a naive straight-line lerp, and not
  an estimated Catmull-Rom tangent -- the real velocity is already there),
  the ball glued to whoever's dribbling it rather than interpolated on its
  own, and a brief color flash on events (tackle, shot, goal, etc.).

## Known gap

I couldn't run Godot itself in the environment this was built in (no Godot
CLI available), so the GDScript here is carefully written against the
Godot 4 API from documentation/knowledge but not actually executed. The
Python side (recording, encoding, determinism) has real automated test
coverage; this half needs your eyes in the editor -- if something doesn't
load or a method name is off, that's the most likely place to look first.
