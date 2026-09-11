extends Node2D

## Match replay playback: loads a locally-dumped match replay (see
## packedfootball/scripts/dump_test_replay.py) and renders it with Hermite
## interpolation between the sparse recorded samples, using the recorded
## velocity as the tangent at each end -- this is what keeps movement
## looking like momentum rather than a dot sliding between two points. The
## ball is parented (visually) to whoever's dribbling it rather than
## interpolated independently, using the recorded ball_controller.
##
## Layout is landscape-first: the pitch (70x100, naturally portrait-shaped)
## renders inside a fixed on-screen box sized to its own aspect ratio, and
## everything else -- scoreboard, playback controls -- lives in the side
## panel that a wide/landscape screen leaves free next to it, rather than
## overlaid on top of the pitch the way the pygame reference did (which
## never had a side panel to work with, since its window was pitch-only).
##
## Not wired to the backend yet -- this scaffold is deliberately isolated so
## the interpolation/rendering can be judged on its own before the rest of
## the app (auth, menus, networking) exists.

const PITCH_WIDTH := 70.0
const PITCH_HEIGHT := 100.0
const TICKS_PER_SECOND := 60.0
const REPLAY_PATH := "res://test_data/sample_match.bin"
const ROSTER_PATH := "res://test_data/sample_match.json"

# On-screen box the pitch always renders within, regardless of camera mode --
# 5px per pitch unit in both axes (350x500), so "full pitch" mode fits it
# with zero letterboxing since the ratio already matches the pitch's own.
var PITCH_RECT := Rect2(20, 20, 350, 500)
const PLAYER_RADIUS_UNITS := 1.3
const BALL_RADIUS_UNITS := 0.55

var replay: Dictionary = {}
var roster: Dictionary = {}
var playback_tick: float = 0.0
var next_event_index: int = 0
var player_flash_timers: Array = []
var ball_flash_timer: float = 0.0
var home_score: int = 0
var away_score: int = 0
var banner_text: String = ""
var banner_timer: float = 0.0
var halftime_pause_remaining: float = 0.0
const HALFTIME_PAUSE_SECONDS := 3.0  # matches gameEngine.py's halftime_pause_timer=180 ticks @ 60/sec

var has_started: bool = false

var camera_mode: String = "zoom"  # "zoom" | "full" -- matches gameEngine.py's render()

var speed_options := [1.0, 2.0, 4.0]
var speed_index: int = 0

# Side-panel playback control buttons, drawn/hit-tested by hand (see _draw()
# and _unhandled_input()) rather than scene-tree Button nodes.
var start_button_rect := Rect2(400, 20, 220, 40)
var halftime_button_rect := Rect2(400, 70, 220, 40)
var fulltime_button_rect := Rect2(400, 120, 220, 40)
var camera_button_rect := Rect2(400, 170, 220, 40)
var speed_button_rect := Rect2(400, 220, 220, 40)
var back_button_rect := Rect2(400, 270, 220, 40)


func _ready() -> void:
	replay = ReplayReader.load_from_file(REPLAY_PATH)
	if replay.is_empty():
		push_error("No replay loaded -- run packedfootball/scripts/dump_test_replay.py first.")
		return
	roster = _load_roster(ROSTER_PATH)
	player_flash_timers.resize(ReplayReader.NUM_PLAYERS)
	player_flash_timers.fill(0.0)
	set_process(true)
	queue_redraw()  # draw the static kickoff frame + buttons before Start is pressed


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


func _unhandled_input(event: InputEvent) -> void:
	if not (event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT):
		return
	var pos: Vector2 = make_input_local(event).position
	if start_button_rect.has_point(pos):
		_on_start_match_pressed()
	elif halftime_button_rect.has_point(pos):
		_jump_to_event(ReplayReader.ActionType.HALFTIME)
	elif fulltime_button_rect.has_point(pos):
		_jump_to_event(ReplayReader.ActionType.FULLTIME)
	elif camera_button_rect.has_point(pos):
		camera_mode = "full" if camera_mode == "zoom" else "zoom"
	elif speed_button_rect.has_point(pos):
		speed_index = (speed_index + 1) % speed_options.size()
	elif back_button_rect.has_point(pos):
		get_tree().change_scene_to_file("res://scenes/Menu.tscn")


func _reset_state() -> void:
	next_event_index = 0
	home_score = 0
	away_score = 0
	banner_text = ""
	banner_timer = 0.0
	halftime_pause_remaining = 0.0
	ball_flash_timer = 0.0
	for i in range(player_flash_timers.size()):
		player_flash_timers[i] = 0.0


func _on_start_match_pressed() -> void:
	_reset_state()
	playback_tick = 0.0
	has_started = true


func _jump_to_event(action_type: int) -> void:
	var events: Array = replay["events"]
	for event in events:
		if event["type"] == action_type:
			_reset_state()
			# Stop one tick short of the target and let the normal per-frame
			# event processing cross it next -- reuses the exact same
			# pause/banner logic a real playthrough would trigger, instead
			# of duplicating it here. _process_events catches up every
			# earlier event first (so goals scored before this point are
			# still correctly tallied into the scoreboard).
			playback_tick = maxf(0.0, event["tick"] - 1.0)
			_process_events(playback_tick)
			has_started = true
			return


func _process(delta: float) -> void:
	if replay.is_empty():
		return

	var samples: Array = replay["samples"]
	if samples.is_empty():
		return

	if not has_started:
		queue_redraw()
		return

	# Speed affects everything time-based uniformly -- the match itself,
	# the halftime pause, and the flash/banner cosmetics -- so a sped-up
	# playthrough feels consistently faster rather than having some things
	# (like a 3-second banner) feel disproportionately long at 4x.
	var effective_delta: float = delta * speed_options[speed_index]

	if halftime_pause_remaining > 0.0:
		halftime_pause_remaining = maxf(0.0, halftime_pause_remaining - effective_delta)
		banner_timer = maxf(0.0, banner_timer - effective_delta)
		queue_redraw()
		return  # action is genuinely paused -- playback_tick does not advance

	playback_tick += effective_delta * TICKS_PER_SECOND
	var last_tick: float = samples[-1]["tick"]
	if playback_tick > last_tick:
		playback_tick = last_tick  # hold on the final frame rather than loop/crash

	_process_events(playback_tick)

	for i in range(player_flash_timers.size()):
		player_flash_timers[i] = maxf(0.0, player_flash_timers[i] - effective_delta)
	ball_flash_timer = maxf(0.0, ball_flash_timer - effective_delta)
	banner_timer = maxf(0.0, banner_timer - effective_delta)

	queue_redraw()


func _process_events(current_tick: float) -> void:
	var events: Array = replay["events"]
	while next_event_index < events.size() and events[next_event_index]["tick"] <= current_tick:
		var event: Dictionary = events[next_event_index]
		var idx: int = event["player_idx"]
		var event_type: int = event["type"]

		if idx >= 0 and idx < ReplayReader.NUM_PLAYERS:
			player_flash_timers[idx] = 0.3

		if event_type == ReplayReader.ActionType.GOAL:
			ball_flash_timer = 1.0
			var team: int = event["team"]
			if team == 0:
				home_score += 1
			else:
				away_score += 1
			var scorer := _player_name(idx)
			banner_text = "GOAL: %s" % scorer if scorer != "" else "GOAL"
			banner_timer = 3.0
		elif event_type == ReplayReader.ActionType.HALFTIME:
			banner_text = "HALF TIME"
			banner_timer = HALFTIME_PAUSE_SECONDS
			halftime_pause_remaining = HALFTIME_PAUSE_SECONDS
		elif event_type == ReplayReader.ActionType.FULLTIME:
			banner_text = "FULL TIME"
			banner_timer = 4.0

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


# Ported from gameEngine.py's render(): "full" fits the whole pitch into
# PITCH_RECT (here, with zero letterboxing -- the rect's 350x500 already
# matches the pitch's own 70x100 aspect ratio); "zoom" follows the ball with
# a fixed *vertical* (goal-to-goal) span so up/down-field context stays
# consistent, letting the horizontal (sideline) span be whatever that
# implies for PITCH_RECT's aspect ratio, clamped to the pitch bounds.
func _compute_camera(ball_pos: Vector2) -> Dictionary:
	var w := PITCH_RECT.size.x
	var h := PITCH_RECT.size.y

	if camera_mode == "full":
		var scale := minf(w / PITCH_WIDTH, h / PITCH_HEIGHT)
		var offset_x := (w - PITCH_WIDTH * scale) / 2.0
		var offset_y := (h - PITCH_HEIGHT * scale) / 2.0
		return {"scale": scale, "cam_x": -offset_x / scale, "cam_y": -offset_y / scale}

	var visible_y_span := 45.0
	var visible_x_span := visible_y_span * (w / h)
	var scale := h / visible_y_span
	var cam_x := clampf(ball_pos.x - visible_x_span / 2.0, 0.0, maxf(0.0, PITCH_WIDTH - visible_x_span))
	var cam_y := clampf(ball_pos.y - visible_y_span / 2.0, 0.0, maxf(0.0, PITCH_HEIGHT - visible_y_span))
	return {"scale": scale, "cam_x": cam_x, "cam_y": cam_y}


func _pitch_to_screen(p: Vector2, cam: Dictionary) -> Vector2:
	# cam's values come back typed as Variant (Dictionary access), which
	# GDScript's `:=` type inference can't always resolve through an
	# operator like `*` -- pulling them into explicitly-typed locals first
	# sidesteps that everywhere below, rather than fighting it call by call.
	var scale: float = cam.scale
	var cam_x: float = cam.cam_x
	var cam_y: float = cam.cam_y
	return PITCH_RECT.position + Vector2((p.x - cam_x) * scale, (p.y - cam_y) * scale)


# Outline of a pitch-space rect (px, py, pw, ph), matching gameEngine.py's
# render()'s draw_pitch_rect helper -- same dimensions, ported 1:1 (outer
# boundary, halfway line, center circle, both penalty/six-yard boxes).
func _draw_pitch_rect_outline(cam: Dictionary, px: float, py: float, pw: float, ph: float, color: Color, width: float) -> void:
	var scale: float = cam.scale
	var top_left := _pitch_to_screen(Vector2(px, py), cam)
	var size: Vector2 = Vector2(pw, ph) * scale
	draw_rect(Rect2(top_left, size), color, false, width)


func _draw_pitch_lines(cam: Dictionary) -> void:
	var scale: float = cam.scale
	var line_color := Color(1.0, 1.0, 1.0, 0.9)
	var line_width := 1.5

	_draw_pitch_rect_outline(cam, 0.0, 0.0, PITCH_WIDTH, PITCH_HEIGHT, line_color, line_width)

	draw_line(
		_pitch_to_screen(Vector2(0.0, PITCH_HEIGHT / 2.0), cam),
		_pitch_to_screen(Vector2(PITCH_WIDTH, PITCH_HEIGHT / 2.0), cam),
		line_color,
		line_width
	)

	var center := _pitch_to_screen(Vector2(PITCH_WIDTH / 2.0, PITCH_HEIGHT / 2.0), cam)
	draw_arc(center, 9.15 * scale, 0.0, TAU, 48, line_color, line_width)
	draw_circle(center, 2.0, line_color)

	# Penalty boxes + six-yard boxes, top and bottom -- same dimensions as
	# gameEngine.py's render().
	_draw_pitch_rect_outline(cam, 14.0, 0.0, 42.0, 18.0, line_color, line_width)
	_draw_pitch_rect_outline(cam, 26.0, 0.0, 18.0, 5.5, line_color, line_width)
	_draw_pitch_rect_outline(cam, 14.0, 82.0, 42.0, 18.0, line_color, line_width)
	_draw_pitch_rect_outline(cam, 26.0, 94.5, 18.0, 5.5, line_color, line_width)


# Goal frame + netting. goal_y is 0 (top) or PITCH_HEIGHT (bottom); depth_dir
# is which way the goal extends beyond the pitch boundary (-1 for the top
# goal, +1 for the bottom one). GOAL_WIDTH/depth match gameEngine.py's own
# goal-mouth dimensions (GOAL_WIDTH=7.5, centered on x=35).
func _draw_goal(cam: Dictionary, goal_y: float, depth_dir: float) -> void:
	var half_width := 3.75
	var depth := 2.0
	var left_x := 35.0 - half_width
	var right_x := 35.0 + half_width
	var back_y := goal_y + depth_dir * depth

	var top_left := _pitch_to_screen(Vector2(left_x, goal_y), cam)
	var top_right := _pitch_to_screen(Vector2(right_x, goal_y), cam)
	var back_left := _pitch_to_screen(Vector2(left_x, back_y), cam)
	var back_right := _pitch_to_screen(Vector2(right_x, back_y), cam)

	# Netting: a light crosshatch inside the goal's footprint.
	var net_color := Color(1.0, 1.0, 1.0, 0.35)
	var net_divisions := 5
	for i in range(net_divisions + 1):
		var t := float(i) / net_divisions
		draw_line(top_left.lerp(top_right, t), back_left.lerp(back_right, t), net_color, 1.0)
		draw_line(top_left.lerp(back_left, t), top_right.lerp(back_right, t), net_color, 1.0)

	# Posts + back of the net.
	var post_color := Color.WHITE
	draw_line(top_left, back_left, post_color, 3.0)
	draw_line(top_right, back_right, post_color, 3.0)
	draw_line(back_left, back_right, post_color, 3.0)
	draw_line(top_left, top_right, post_color, 4.0)


func _draw_corner_quarter(cam: Dictionary, corner: Vector2, start_angle: float, end_angle: float) -> void:
	var scale: float = cam.scale
	var base := _pitch_to_screen(corner, cam)

	var arc_radius := 2.0 * scale 
	var point_count := 16 # Higher count makes the curve smoother
	draw_arc(base, arc_radius, start_angle, end_angle, point_count, Color.WHITE, 2.0, true)




func _draw() -> void:
	if replay.is_empty():
		return

	var font: Font = ThemeDB.fallback_font
	var font_size: int = ThemeDB.fallback_font_size

	var state := _interpolated_state()
	var players: Array = state["players"]
	var controller: int = state["ball_controller"]
	var cam := _compute_camera(state["ball"])
	var scale: float = cam.scale

	# Background: in "full" mode this fits exactly (PITCH_RECT already
	# matches the pitch's aspect ratio); in "zoom" mode the camera only ever
	# shows a sub-region that's entirely inside the pitch, so the whole box
	# is grass either way. Intersected with PITCH_RECT as a hard safety
	# bound regardless of mode.
	var bg_rect: Rect2 = Rect2(_pitch_to_screen(Vector2.ZERO, cam), Vector2(PITCH_WIDTH, PITCH_HEIGHT) * scale)
	draw_rect(PITCH_RECT.intersection(bg_rect), Color(0.09, 0.47, 0.22))

	_draw_pitch_lines(cam)
	_draw_goal(cam, 0.0, -1.0)
	_draw_goal(cam, PITCH_HEIGHT, 1.0)
	_draw_corner_quarter(cam, Vector2(0, 0), 0.0, PI / 2.0)
	_draw_corner_quarter(cam, Vector2(PITCH_WIDTH, 0), PI / 2.0, PI)
	_draw_corner_quarter(cam, Vector2(PITCH_WIDTH, PITCH_HEIGHT), PI, 3.0 * PI / 2.0)
	_draw_corner_quarter(cam, Vector2(0, PITCH_HEIGHT), -PI / 2.0, 0.0)

	# Godot's built-in clipping needs a dedicated Control node, which this
	# single-script hand-drawn setup doesn't have -- so anything that would
	# land outside PITCH_RECT (always true for some players in "zoom" mode,
	# since most of the pitch is off the visible window) is simply skipped
	# rather than drawn into the side panel.
	for i in range(ReplayReader.NUM_PLAYERS):
		var pos: Vector2 = _pitch_to_screen(players[i], cam)
		if not PITCH_RECT.has_point(pos):
			continue
		var color := Color(0.2, 0.5, 1.0) if i < 11 else Color(1.0, 0.35, 0.35)
		if player_flash_timers[i] > 0.0:
			color = Color(1.0, 1.0, 0.2)
		if i == controller:
			draw_circle(pos, PLAYER_RADIUS_UNITS * 1.35 * scale, Color(1.0, 1.0, 1.0), false, 2.0)
		draw_circle(pos, PLAYER_RADIUS_UNITS * scale, color)
		draw_string(
			font,
			pos + Vector2(-6, 5),
			str(i),
			HORIZONTAL_ALIGNMENT_CENTER,
			24,
			maxi(8, int(font_size * 0.6 * (scale / 5.0))),
			Color.BLACK
		)

	if controller != -1:
		var carrier_pos: Vector2 = _pitch_to_screen(players[controller], cam)
		if PITCH_RECT.has_point(carrier_pos):
			var name: String = _player_name(controller)
			if name != "":
				draw_string(
					font,
					carrier_pos + Vector2(-40, -PLAYER_RADIUS_UNITS * scale - 10),
					name,
					HORIZONTAL_ALIGNMENT_CENTER,
					80,
					maxi(8, int(font_size * (scale / 5.0))),
					Color.WHITE
				)

	var ball_pos: Vector2 = _pitch_to_screen(state["ball"], cam)
	if PITCH_RECT.has_point(ball_pos):
		var ball_color := Color(1.0, 0.85, 0.2) if ball_flash_timer > 0.0 else Color(1.0, 1.0, 1.0)
		draw_circle(ball_pos, BALL_RADIUS_UNITS * scale, ball_color)

	_draw_scoreboard(font, font_size)
	_draw_banner(font, font_size)
	_draw_buttons(font, font_size)


func _draw_button(rect: Rect2, label: String, font: Font, font_size: int) -> void:
	draw_rect(rect, Color(0.15, 0.15, 0.18, 0.9))
	draw_rect(rect, Color(0.8, 0.8, 0.8), false, 2.0)
	draw_string(
		font, rect.position + Vector2(14, rect.size.y * 0.65), label, HORIZONTAL_ALIGNMENT_LEFT, rect.size.x - 20, font_size, Color.WHITE
	)


func _draw_buttons(font: Font, font_size: int) -> void:
	_draw_button(start_button_rect, "Start Match", font, font_size)
	_draw_button(halftime_button_rect, "Jump to Halftime", font, font_size)
	_draw_button(fulltime_button_rect, "Jump to Full Time", font, font_size)
	var camera_label := "Camera: Zoom" if camera_mode == "zoom" else "Camera: Full Pitch"
	_draw_button(camera_button_rect, camera_label, font, font_size)
	_draw_button(speed_button_rect, "Speed: %dx" % int(speed_options[speed_index]), font, font_size)
	_draw_button(back_button_rect, "Back to Menu", font, font_size)


func _draw_scoreboard(font: Font, font_size: int) -> void:
	var home_name: String = roster.get("home_name", "Home")
	var away_name: String = roster.get("away_name", "Away")
	var rect := Rect2(400, 320, 220, 70)

	draw_rect(rect, Color(0, 0, 0, 0.6))
	draw_string(
		font,
		rect.position + Vector2(10, 25),
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
		rect.position + Vector2(10, 50),
		"%02d:%02d" % [minutes, seconds],
		HORIZONTAL_ALIGNMENT_LEFT,
		200,
		int(font_size * 0.8),
		Color(0.85, 0.85, 0.85)
	)


func _draw_banner(font: Font, font_size: int) -> void:
	if banner_timer <= 0.0:
		return
	# Fades out over its last second, however long the banner's total duration was.
	var alpha: float = clampf(banner_timer, 0.0, 1.0)
	draw_string(
		font,
		PITCH_RECT.position + Vector2(PITCH_RECT.size.x / 2.0 - 150, PITCH_RECT.size.y / 2.0),
		banner_text,
		HORIZONTAL_ALIGNMENT_CENTER,
		300,
		int(font_size * 1.6),
		Color(1.0, 1.0, 1.0, alpha)
	)
