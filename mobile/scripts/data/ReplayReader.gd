class_name ReplayReader
extends RefCounted

## Reads the binary replay format written by packedfootball/replay.py's
## ReplayRecorder.encode() -- see that file's module docstring for the wire
## format spec. Keep the two in sync if the format ever changes.

enum ActionType {
	PASS = 0,
	CLEARANCE = 1,
	CROSS = 2,
	SHOOT = 3,
	TACKLE = 4,
	ANKLEBREAKER = 5,
	RECEIVED_PASS = 6,
	SAVE = 7,
	GOAL = 8,
	KICKOFF = 9,
	THROW_IN = 10,
	CORNER = 11,
	GOAL_KICK = 12,
	HALFTIME = 13,
	FULLTIME = 14,
	HEADER = 15,
	SHOT_OFF_TARGET = 16,
	FOUL = 17,
	FREE_KICK = 18,
	PENALTY = 19,
	SAVE_FAILED = 20,
	FREE_KICK_SHOT = 21,
	THROW_TAKEN = 22,
}

const POSITION_SCALE := 100.0
const MAGIC := "PFRP"
const NUM_PLAYERS := 22

## 45:00 in clock frames, at gameEngine's FRAMES_PER_CLOCK_SECOND = 2.
const REGULATION_HALF_FRAMES := 5400


## The tick the HALFTIME event sits on, or -1.0 if this replay has none.
static func halftime_tick(replay: Dictionary) -> float:
	for event in replay.get("events", []):
		if not (event is Dictionary):
			continue
		if int(event.get("type", -1)) == ActionType.HALFTIME:
			return float(event.get("tick", -1))
	return -1.0


## The clock a viewer should SEE for a raw replay tick.
##
## A replay's tick is one continuous timeline -- it has to be, every sample
## and event is ordered by it -- so the second half carries straight on from
## wherever the first one stopped: 2:12 of stoppage before the break and the
## second half would kick off reading 47:12.
##
## Football restarts the second half at 45:00 however long the first one
## over-ran, so this shifts the shown clock back by exactly that overrun.
## Full time then lands on 90:00 plus only the second half's own stoppage.
## The stored timeline is untouched -- this is display only.
##
## gameEngine.game.display_clock_frames() is the same arithmetic on the
## Python side (it has the halftime frame directly rather than having to
## find the event). Keep the two in step.
static func display_tick(tick: float, halftime: float) -> float:
	if halftime < 0.0 or tick <= halftime:
		return tick
	return tick - (halftime - float(REGULATION_HALF_FRAMES))

# FileAccess's get_8()/get_16() signedness isn't something this project can
# verify without running Godot, so these two helpers make the result correct
# either way: if the value already came back signed (-128..127 / -32768..32767)
# they're a no-op; if it came back unsigned (0..255 / 0..65535) they convert.
static func _to_signed8(value: int) -> int:
	return value - 256 if value >= 128 else value


static func _to_signed16(value: int) -> int:
	return value - 65536 if value >= 32768 else value


## For a replay that arrived over the network (backend/main.py's
## /match/quick or /match/simulate, base64-decoded by the caller) rather
## than a local file. Godot has no "parse a binary format straight out of
## a PackedByteArray" reader with the same get_8()/get_16()/get_32() API
## FileAccess offers, so this writes the bytes to a scratch file in the
## app's own sandboxed user:// directory and reuses load_from_file()
## unchanged -- one extra disk round-trip, negligible for a one-time
## per-match load, and zero risk of a second, subtly-different parser
## drifting from the proven-working one.
static func load_from_bytes(bytes: PackedByteArray) -> Dictionary:
	var tmp_path := "user://_last_match_replay.bin"
	var file := FileAccess.open(tmp_path, FileAccess.WRITE)
	if file == null:
		push_error("Could not create scratch replay file: %s" % FileAccess.get_open_error())
		return {}
	file.store_buffer(bytes)
	file.close()
	return load_from_file(tmp_path)


static func load_from_file(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("Could not open replay file: %s (%s)" % [path, FileAccess.get_open_error()])
		return {}

	var magic := file.get_buffer(4).get_string_from_ascii()
	if magic != MAGIC:
		push_error("Bad replay magic: %s" % magic)
		return {}

	var version := file.get_8()
	var sample_interval_ticks := file.get_16()
	var num_samples := file.get_32()
	var num_events := file.get_32()

	var samples: Array = []
	for i in range(num_samples):
		var tick := file.get_32()
		var players: Array = []
		for p in range(NUM_PLAYERS):
			players.append(
				{
					"x": _to_signed16(file.get_16()) / POSITION_SCALE,
					"y": _to_signed16(file.get_16()) / POSITION_SCALE,
					"vx": _to_signed16(file.get_16()) / POSITION_SCALE,
					"vy": _to_signed16(file.get_16()) / POSITION_SCALE,
				}
			)
		var ball := {
			"x": _to_signed16(file.get_16()) / POSITION_SCALE,
			"y": _to_signed16(file.get_16()) / POSITION_SCALE,
			"vx": _to_signed16(file.get_16()) / POSITION_SCALE,
			"vy": _to_signed16(file.get_16()) / POSITION_SCALE,
			"height": _to_signed16(file.get_16()) / POSITION_SCALE,
		}
		var ball_controller := _to_signed8(file.get_8())
		samples.append({"tick": tick, "players": players, "ball": ball, "ball_controller": ball_controller})

	var events: Array = []
	for i in range(num_events):
		events.append(
			{
				"tick": file.get_32(),
				"type": file.get_8(),
				"player_idx": _to_signed8(file.get_8()),
				"team": _to_signed8(file.get_8()),
			}
		)

	file.close()
	return {
		"version": version,
		"sample_interval_ticks": sample_interval_ticks,
		"samples": samples,
		"events": events,
	}
