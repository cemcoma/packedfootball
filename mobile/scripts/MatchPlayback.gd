extends Node2D

## Proof-of-concept replay playback: loads a locally-dumped match replay
## (see packedfootball/scripts/dump_test_replay.py) and renders it with
## Hermite interpolation between the sparse recorded samples, using the
## recorded velocity as the tangent at each end -- this is what keeps
## movement looking like momentum rather than a dot sliding between two
## points. The ball is parented (visually) to whoever's dribbling it rather
## than interpolated independently, using the recorded ball_controller.
##
## Not wired to the backend yet -- this scaffold is deliberately isolated so
## the interpolation/rendering can be judged on its own before the rest of
## the app (auth, menus, networking) exists.

const PITCH_WIDTH := 70.0
const PITCH_HEIGHT := 100.0
const PIXELS_PER_UNIT := 8.0
const TICKS_PER_SECOND := 60.0
const REPLAY_PATH := "res://test_data/sample_match.bin"
const ROSTER_PATH := "res://test_data/sample_match.json"

var replay: Dictionary = {}
var roster: Dictionary = {}
var playback_tick: float = 0.0
var next_event_index: int = 0
var player_flash_timers: Array = []
var ball_flash_timer: float = 0.0
var home_score: int = 0
var away_score: int = 0
var goal_popup_text: String = ""
var goal_popup_timer: float = 0.0


func _ready() -> void:
	replay = ReplayReader.load_from_file(REPLAY_PATH)
	if replay.is_empty():
		push_error("No replay loaded -- run packedfootball/scripts/dump_test_replay.py first.")
		return
	roster = _load_roster(ROSTER_PATH)
	player_flash_timers.resize(ReplayReader.NUM_PLAYERS)
	player_flash_timers.fill(0.0)
	set_process(true)


func _load_roster(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_warning("No roster metadata at %s -- names/team labels will be blank." % path)
		return {}
	var parsed = JSON.parse_string(file.get_as_text())
	file.close()
	return parsed if parsed is Dictionary else {}


func _player_name(idx: int) -> String:
	var players: Array = roster.get("players", [])
	if idx < 0 or idx >= players.size():
		return ""
	return players[idx].get("lname", "")


func _process(delta: float) -> void:
	if replay.is_empty():
		return

	var samples: Array = replay["samples"]
	if samples.is_empty():
		return

	playback_tick += delta * TICKS_PER_SECOND
	var last_tick: float = samples[-1]["tick"]
	if playback_tick > last_tick:
		playback_tick = last_tick  # hold on the final frame rather than loop/crash

	_process_events(playback_tick)

	for i in range(player_flash_timers.size()):
		player_flash_timers[i] = maxf(0.0, player_flash_timers[i] - delta)
	ball_flash_timer = maxf(0.0, ball_flash_timer - delta)
	goal_popup_timer = maxf(0.0, goal_popup_timer - delta)

	queue_redraw()


func _process_events(current_tick: float) -> void:
	var events: Array = replay["events"]
	while next_event_index < events.size() and events[next_event_index]["tick"] <= current_tick:
		var event: Dictionary = events[next_event_index]
		var idx: int = event["player_idx"]
		if idx >= 0 and idx < ReplayReader.NUM_PLAYERS:
			player_flash_timers[idx] = 0.3
		if event["type"] == ReplayReader.ActionType.GOAL:
			ball_flash_timer = 1.0
			var team: int = event["team"]
			if team == 0:
				home_score += 1
			else:
				away_score += 1
			var scorer := _player_name(idx)
			goal_popup_text = "GOAL: %s" % scorer if scorer != "" else "GOAL"
			goal_popup_timer = 3.0
		next_event_index += 1


func _find_bracket(samples: Array, tick: float) -> Array:
	if tick <= samples[0]["tick"]:
		return [samples[0], samples[0]]
	for i in range(samples.size() - 1):
		if samples[i]["tick"] <= tick and tick <= samples[i + 1]["tick"]:
			return [samples[i], samples[i + 1]]
	return [samples[-1], samples[-1]]


# Cubic Hermite interpolation using the *recorded* velocity as the tangent at
# each end (not an estimated Catmull-Rom tangent -- we actually have the real
# velocity, so use it). p0/p1 in pitch units, v0/v1 in units/second, dt in
# seconds (the time between the two samples), s in [0, 1] (position within
# that interval).
static func _hermite(p0: Vector2, v0: Vector2, p1: Vector2, v1: Vector2, dt: float, s: float) -> Vector2:
	var s2 := s * s
	var s3 := s2 * s
	var h00 := 2.0 * s3 - 3.0 * s2 + 1.0
	var h10 := s3 - 2.0 * s2 + s
	var h01 := -2.0 * s3 + 3.0 * s2
	var h11 := s3 - s2
	return h00 * p0 + h10 * dt * v0 + h01 * p1 + h11 * dt * v1


func _interpolated_state() -> Dictionary:
	var samples: Array = replay["samples"]
	var bracket := _find_bracket(samples, playback_tick)
	var s0: Dictionary = bracket[0]
	var s1: Dictionary = bracket[1]

	var interval_ticks: float = s1["tick"] - s0["tick"]
	var dt := interval_ticks / TICKS_PER_SECOND
	var s := 0.0
	if interval_ticks > 0.0:
		s = clampf((playback_tick - s0["tick"]) / interval_ticks, 0.0, 1.0)

	var players: Array = []
	for i in range(ReplayReader.NUM_PLAYERS):
		var p0: Dictionary = s0["players"][i]
		var p1: Dictionary = s1["players"][i]
		players.append(
			_hermite(
				Vector2(p0["x"], p0["y"]),
				Vector2(p0["vx"], p0["vy"]),
				Vector2(p1["x"], p1["y"]),
				Vector2(p1["vx"], p1["vy"]),
				dt,
				s
			)
		)

	var ball_pos: Vector2
	var controller: int = s0["ball_controller"] if s < 0.5 else s1["ball_controller"]
	if controller != -1:
		# Glue the ball to the dribbler instead of interpolating it
		# independently -- otherwise it visibly drifts away from whoever
		# actually has it.
		ball_pos = players[controller]
	else:
		var b0: Dictionary = s0["ball"]
		var b1: Dictionary = s1["ball"]
		ball_pos = _hermite(
			Vector2(b0["x"], b0["y"]), Vector2(b0["vx"], b0["vy"]), Vector2(b1["x"], b1["y"]), Vector2(b1["vx"], b1["vy"]), dt, s
		)

	return {"players": players, "ball": ball_pos, "ball_controller": controller}


func _to_screen(pitch_pos: Vector2) -> Vector2:
	return pitch_pos * PIXELS_PER_UNIT


func _draw() -> void:
	if replay.is_empty():
		return

	var font: Font = ThemeDB.fallback_font
	var font_size: int = ThemeDB.fallback_font_size

	draw_rect(Rect2(0, 0, PITCH_WIDTH * PIXELS_PER_UNIT, PITCH_HEIGHT * PIXELS_PER_UNIT), Color(0.09, 0.47, 0.22))

	var state := _interpolated_state()
	var players: Array = state["players"]
	var controller: int = state["ball_controller"]

	for i in range(ReplayReader.NUM_PLAYERS):
		var pos: Vector2 = _to_screen(players[i])
		var color := Color(0.2, 0.5, 1.0) if i < 11 else Color(1.0, 0.35, 0.35)
		if player_flash_timers[i] > 0.0:
			color = Color(1.0, 1.0, 0.2)
		if i == controller:
			draw_circle(pos, PIXELS_PER_UNIT * 1.2, Color(1.0, 1.0, 1.0), false, 2.0)
		draw_circle(pos, PIXELS_PER_UNIT * 0.9, color)
		draw_string(
			font, pos + Vector2(-6, 5), str(i), HORIZONTAL_ALIGNMENT_CENTER, 12, int(font_size * 0.7), Color.BLACK
		)

	if controller != -1:
		var carrier_pos: Vector2 = _to_screen(players[controller])
		var name: String = _player_name(controller)
		if name != "":
			draw_string(
				font,
				carrier_pos + Vector2(-40, -PIXELS_PER_UNIT * 1.8),
				name,
				HORIZONTAL_ALIGNMENT_CENTER,
				80,
				font_size,
				Color.WHITE
			)

	var ball_pos: Vector2 = _to_screen(state["ball"])
	var ball_color := Color(1.0, 0.85, 0.2) if ball_flash_timer > 0.0 else Color(1.0, 1.0, 1.0)
	draw_circle(ball_pos, PIXELS_PER_UNIT * 0.4, ball_color)

	_draw_scoreboard(font, font_size)
	_draw_goal_popup(font, font_size)


func _draw_scoreboard(font: Font, font_size: int) -> void:
	var home_name: String = roster.get("home_name", "Home")
	var away_name: String = roster.get("away_name", "Away")

	draw_rect(Rect2(10, 10, 220, 60), Color(0, 0, 0, 0.6))
	draw_string(
		font,
		Vector2(20, 35),
		"%s %d - %d %s" % [home_name, home_score, away_score, away_name],
		HORIZONTAL_ALIGNMENT_LEFT,
		200,
		font_size,
		Color.WHITE
	)

	var clock_total_seconds := int(playback_tick / 2.0)  # matches gameEngine.py's render() clock convention
	var minutes := clock_total_seconds / 60
	var seconds := clock_total_seconds % 60
	draw_string(
		font,
		Vector2(20, 58),
		"%02d:%02d" % [minutes, seconds],
		HORIZONTAL_ALIGNMENT_LEFT,
		200,
		int(font_size * 0.8),
		Color(0.85, 0.85, 0.85)
	)


func _draw_goal_popup(font: Font, font_size: int) -> void:
	if goal_popup_timer <= 0.0:
		return
	var alpha: float = clampf(goal_popup_timer / 3.0, 0.0, 1.0)
	var viewport_width: float = get_viewport_rect().size.x
	draw_string(
		font,
		Vector2(viewport_width / 2.0 - 150, 150),
		goal_popup_text,
		HORIZONTAL_ALIGNMENT_CENTER,
		300,
		int(font_size * 2.0),
		Color(1.0, 1.0, 1.0, alpha)
	)
