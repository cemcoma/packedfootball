extends Control

## Match replay playback: loads a locally-dumped match replay (see
## packedfootball/scripts/dump_test_replay.py) and renders it with Hermite
## interpolation between the sparse recorded samples, using the recorded
## velocity as the tangent at each end -- this is what keeps movement
## looking like momentum rather than a dot sliding between two points. The
## ball is parented (visually) to whoever's dribbling it rather than
## interpolated independently, using the recorded ball_controller.
##
## This script lives on Match.tscn's "PitchCanvas" node specifically (a
## Control with clip_contents = true), not the scene root -- everything it
## draws is in PitchCanvas's own LOCAL coordinates (relative to its live
## `size`, not a screen-absolute rect -- see _update_pitch_canvas_size(),
## since that size now changes with camera_mode), and clip_contents is what
## keeps a pitch line (or a player, or the ball) that's only partly inside
## the visible crop from spilling its full extent out over the rest of the
## screen -- Godot clips a Control's own _draw() output (not just its
## children) to its rect, so this is real engine-level clipping rather
## than the old per-shape manual "skip if the center point is outside the
## box" check, which only ever worked for player dots and never touched
## the pitch lines at all (that was the actual bug report: a partly-visible
## halfway line used to draw in full instead of just the visible sliver).
##
## The rest of the screen (scoreboard, timer, pause/camera buttons, the
## pre-match blackout and pause overlay) are real Control nodes, siblings
## of PitchCanvas under Match.tscn's root -- reached below via the usual
## %-prefixed unique-name lookups despite this script living on a non-root
## node (unique names are scoped to the whole edited scene, not to the
## caller's own subtree).
##
## Not wired to the backend for the bundled demo replay path -- that
## scaffold is deliberately isolated so the interpolation/rendering can be
## judged on its own with no account/network needed. A real match (Quick
## Match today) arrives via the MatchSession autoload instead; see _ready().

const PITCH_WIDTH := 70.0
const PITCH_HEIGHT := 100.0
const TICKS_PER_SECOND := 60.0
const REPLAY_PATH := "res://test_data/sample_match.bin"
const ROSTER_PATH := "res://test_data/sample_match.json"

# PitchCanvas's own size in "full" camera mode: full viewport height, width
# kept at the pitch's own 70:100 aspect ratio so the whole pitch fits with
# zero letterboxing. In "zoom" mode this script instead resizes the node to
# the full viewport (see _update_pitch_canvas_size()) -- zoom already only
# ever shows a cropped sub-region of the pitch, so there's no aspect ratio
# to preserve, and filling the screen means more of the pitch is visible at
# once instead of being boxed into the same narrower column "full" mode
# needs. Position is handled by Match.tscn's layout (a CenterContainer
# centers this horizontally -- a no-op when the size is already the full
# viewport width), not by this script -- everything drawn below is in
# LOCAL coordinates (relative to this box's own top-left, read live off
# `size` rather than a fixed constant, since that size now changes with
# camera_mode), not the screen's.
const FULL_MODE_BOX_SIZE := Vector2(378.0, 540.0)
const PLAYER_RADIUS_UNITS := 1.3
const BALL_RADIUS_UNITS := 0.55

# Shirt colors for home/Team A and away/Team B when the roster carries no
# kit -- the bundled demo replay, or a response from a backend that predates
# kits. A real match sends both managers' kits (see _resolve_team_colors).
const DEFAULT_TEAM_COLORS := [Color(0.2, 0.5, 1.0), Color(1.0, 0.35, 0.35)]

# How different two shirts have to be before the away side is made to
# change. Straight RGB distance, which is crude but right for the job: these
# are 3-pixel dots, and the only question that matters is "can you tell the
# two teams apart at a glance".
const TEAM_COLOR_MIN_DISTANCE := 0.42
# Tried in order when the away kit clashes, first one far enough from the
# home shirt wins: their own second color, then the built-in away red, then
# near-white and near-black (between them nothing can clash with both).
const CHANGE_KIT_FALLBACKS := [Color(0.95, 0.95, 0.96), Color(0.12, 0.12, 0.14)]

# Every action in the replay stream used to flash the same yellow, so the
# pitch told you SOMETHING happened but never what. These are the same
# events, colored by what they actually are -- see _action_color(), which is
# the single place the mapping lives.
#
# Chosen to read against the pitch green (0.09, 0.47, 0.22) and against both
# shirt colors, and grouped so related events share a family: the ball
# leaving a foot is warm (pass/cross/clearance), a duel is hot
# (tackle/anklebreaker), goalkeeping is cold, and a restart is neutral.
const ACTION_COLOR_GOAL := Color(1.0, 0.85, 0.15)          # gold
const ACTION_COLOR_SHOOT := Color(1.0, 0.45, 0.1)          # orange
const ACTION_COLOR_SAVE := Color(0.25, 0.85, 1.0)          # cyan
const ACTION_COLOR_TACKLE := Color(1.0, 0.25, 0.25)        # red
const ACTION_COLOR_ANKLEBREAKER := Color(0.85, 0.35, 1.0)  # violet
const ACTION_COLOR_PASS := Color(1.0, 1.0, 1.0)            # white
const ACTION_COLOR_RECEIVED := Color(0.6, 1.0, 0.75)       # mint
const ACTION_COLOR_CROSS := Color(0.55, 0.75, 1.0)         # pale blue
const ACTION_COLOR_CLEARANCE := Color(0.95, 0.75, 0.45)    # sand
const ACTION_COLOR_RESTART := Color(0.85, 0.9, 0.95)       # pale grey
# Anything the enum grows that nobody has assigned a color to yet: the
# original flash, so a new event type still shows rather than going invisible.
const ACTION_COLOR_DEFAULT := Color(1.0, 1.0, 0.2)

# Size of one color chip in the pause screen's key (see _build_legend).
const LEGEND_SWATCH_SIZE := Vector2(14.0, 14.0)

var replay: Dictionary = {}
var roster: Dictionary = {}
var playback_tick: float = 0.0
var next_event_index: int = 0
var player_flash_timers: Array = []
# Parallel to player_flash_timers: what color that player's current flash is,
# i.e. which action they just performed. Kept as a second array rather than
# recomputed at draw time because by then the event is long past.
var player_flash_colors: Array = []
var ball_flash_timer: float = 0.0
var ball_flash_color: Color = ACTION_COLOR_GOAL
var home_score: int = 0
var away_score: int = 0
var banner_text: String = ""
var banner_timer: float = 0.0
var banner_color: Color = Color.WHITE
var halftime_pause_remaining: float = 0.0
const HALFTIME_PAUSE_SECONDS := 3.0  # matches gameEngine.py's halftime_pause_timer=180 ticks @ 60/sec

var has_started: bool = false
var is_paused: bool = false

# Set once at load (see _ready()) by scanning for the replay's HALFTIME
# event -- lets the pause menu disable "Skip to Halftime" once playback is
# already past it, since jumping "back" to halftime from later in the match
# would otherwise rewind the score (see _jump_to_event's own docstring).
# -1.0 means "no halftime event in this replay" (shouldn't happen for a
# real 2-half match, but guards the lookup regardless).
var _halftime_tick: float = -1.0

# True once FULL TIME has been processed for a real match -- _process()
# waits for the FULLTIME banner to finish its run before actually leaving,
# so skip-to-full-time (from the pause menu) and a natural full-time both
# end the same way instead of one feeling abrupt.
var _pending_result_transition: bool = false

# [home, away], worked out once at load from both managers' kits -- see
# _resolve_team_colors() for the clash rule.
var _team_colors: Array = DEFAULT_TEAM_COLORS.duplicate()

var camera_mode: String = "zoom"  # "zoom" | "full" -- matches gameEngine.py's render()

var speed_options := [1.0, 2.0, 4.0]
var speed_index: int = 0

# Only meaningful when this playback came from a real MatchSession (Quick
# Match today) rather than the bundled local demo replay -- captured in
# _ready() before this scene either clears MatchSession (on an early exit)
# or hands off to MatchResult.tscn (which reads MatchSession itself, and
# clears it once it has).
var _is_real_match: bool = false

@onready var _home_name_label: Label = %HomeNameLabel
@onready var _away_name_label: Label = %AwayNameLabel
@onready var _score_label: Label = %ScoreLabel
@onready var _home_color_swatch: ColorRect = %HomeColorSwatch
@onready var _away_color_swatch: ColorRect = %AwayColorSwatch
@onready var _timer_label: Label = %TimerLabel

@onready var _pause_button: Button = %PauseButton
@onready var _camera_toggle_button: Button = %CameraToggleButton
@onready var _speed_button: Button = %SpeedButton

@onready var _pre_match_overlay: Control = %PreMatchOverlay
@onready var _pre_match_teams_label: Label = %PreMatchTeamsLabel
@onready var _start_button: Button = %StartButton

@onready var _pause_overlay: Control = %PauseOverlay
@onready var _legend_grid: GridContainer = %LegendGrid
@onready var _skip_halftime_button: Button = %SkipHalftimeButton
@onready var _skip_fulltime_button: Button = %SkipFulltimeButton
@onready var _exit_button: Button = %ExitButton

@onready var _loading_popup: Control = %LoadingPopup


func _ready() -> void:
	# A real match just played via Play.gd's Quick Match (or, later, a
	# ranked challenge) takes priority over the bundled local demo replay --
	# see MatchSession.gd's own docstring for why this exists at all. Either
	# way this scene is entered directly (no MatchSession data pending),
	# it falls back to the same local file this always loaded, so the
	# offline demo path keeps working with no backend/account needed.
	#
	# MatchSession is deliberately NOT cleared here -- if this turns out to
	# be a real match, MatchResult.tscn reads score/credits_earned/opponent
	# info straight off of it after FULL TIME, and clears it itself once
	# it has (see class docstring above). An early exit via the pause
	# menu's "Exit to Main Menu" clears it directly (see _on_exit_pressed).
	if MatchSession.has_pending():
		replay = MatchSession.replay()
		roster = MatchSession.roster()
		_is_real_match = true
	else:
		replay = ReplayReader.load_from_file(REPLAY_PATH)
		roster = _load_roster(ROSTER_PATH)

	if replay.is_empty():
		push_error("No replay loaded -- run packedfootball/scripts/dump_test_replay.py first.")
		return

	player_flash_timers.resize(ReplayReader.NUM_PLAYERS)
	player_flash_timers.fill(0.0)
	player_flash_colors.resize(ReplayReader.NUM_PLAYERS)
	player_flash_colors.fill(ACTION_COLOR_DEFAULT)

	_halftime_tick = ReplayReader.halftime_tick(replay)

	_resolve_team_colors()  # before _setup_scoreboard -- it paints the swatches
	_setup_scoreboard()
	_build_legend()
	_pre_match_teams_label.text = "%s vs %s" % [roster.get("home_name", "Home"), roster.get("away_name", "Away")]
	_update_camera_button_label()
	_update_speed_button_label()
	_update_pitch_canvas_size()

	_start_button.pressed.connect(_on_start_match_pressed)
	_pause_button.pressed.connect(_on_pause_pressed)
	_camera_toggle_button.pressed.connect(_on_camera_toggle_pressed)
	_speed_button.pressed.connect(_on_speed_pressed)
	_skip_halftime_button.pressed.connect(_on_skip_halftime_pressed)
	_skip_fulltime_button.pressed.connect(_on_skip_fulltime_pressed)
	_exit_button.pressed.connect(_on_exit_pressed)

	set_process(true)
	queue_redraw()  # draw the static kickoff frame (hidden behind the pre-match blackout for now)


func _setup_scoreboard() -> void:
	_home_name_label.text = roster.get("home_name", "Home")
	_away_name_label.text = roster.get("away_name", "Away")
	_home_color_swatch.color = _team_color(0)
	_away_color_swatch.color = _team_color(1)
	_update_score_label()

func _legend_entries() -> Array:
	return [
		[ReplayReader.ActionType.GOAL, "Goal"],
		[ReplayReader.ActionType.SHOOT, "Shot"],
		[ReplayReader.ActionType.SAVE, "Save"],
		[ReplayReader.ActionType.TACKLE, "Tackle"],
		[ReplayReader.ActionType.ANKLEBREAKER, "Skill move"],
		[ReplayReader.ActionType.PASS, "Pass"],
		[ReplayReader.ActionType.RECEIVED_PASS, "Received"],
		[ReplayReader.ActionType.CROSS, "Cross"],
		[ReplayReader.ActionType.CLEARANCE, "Clearance"],
		[ReplayReader.ActionType.THROW_IN, "Restart"],
	]

func _build_legend() -> void:
	for child in _legend_grid.get_children():
		_legend_grid.remove_child(child)
		child.queue_free()

	for entry in _legend_entries():
		var swatch := ColorRect.new()
		swatch.color = _action_color(entry[0])
		swatch.custom_minimum_size = LEGEND_SWATCH_SIZE
		swatch.size_flags_vertical = Control.SIZE_SHRINK_CENTER
		_legend_grid.add_child(swatch)

		var label := Label.new()
		label.text = entry[1]
		label.add_theme_font_size_override("font_size", 12)
		# The pause scrim is black in BOTH themes, so this is explicitly
		# white rather than left to the Theme's Label color, which goes
		# near-black in light mode and would vanish here.
		label.add_theme_color_override("font_color", Color.WHITE)
		_legend_grid.add_child(label)


## Works out what each side wears, once, at load. Called before anything
## draws; _team_color() just reads the answer.
##
## The pitch dots are small circles, so only ONE color per side survives to
## the screen -- the kit's primary. Pattern and secondary still matter
## (they're what the Customize Kit preview and, later, anything bigger than
## a dot will show), they just can't be rendered at this size.
##
## Hence the clash rule. Two managers who both picked royal blue would
## otherwise be indistinguishable for 90 minutes, and real football solves
## exactly this with a change kit: the AWAY side is the one that changes,
## the home side always wears what it picked.
## TODO: Have the teams actually wear the kit
func _resolve_team_colors() -> void:
	var home_kit := KitDesign.parse(roster.get("home_kit", ""))
	var away_kit := KitDesign.parse(roster.get("away_kit", ""))

	var home: Color = home_kit.primary_color() if roster.has("home_kit") else DEFAULT_TEAM_COLORS[0]
	var away: Color = away_kit.primary_color() if roster.has("away_kit") else DEFAULT_TEAM_COLORS[1]

	if _too_similar(home, away):
		var candidates := [away_kit.secondary_color(), DEFAULT_TEAM_COLORS[1]]
		candidates.append_array(CHANGE_KIT_FALLBACKS)
		for candidate in candidates:
			if not _too_similar(home, candidate):
				away = candidate
				break

	_team_colors = [home, away]


func _too_similar(a: Color, b: Color) -> bool:
	return Vector3(a.r - b.r, a.g - b.g, a.b - b.b).length() < TEAM_COLOR_MIN_DISTANCE


func _team_color(team_index: int) -> Color:
	return _team_colors[team_index]


func _update_score_label() -> void:
	_score_label.text = "%d - %d" % [home_score, away_score]


func _update_timer_label() -> void:
	# display_tick, not the raw playback tick: the second half restarts at
	# 45:00 rather than carrying on from wherever the first half's stoppage
	# left off. Same convention as gameEngine.py's render().
	var shown := ReplayReader.display_tick(playback_tick, _halftime_tick)
	var clock_total_seconds := int(shown / 2.0)
	_timer_label.text = "%02d:%02d" % [clock_total_seconds / 60, clock_total_seconds % 60]


func _update_camera_button_label() -> void:
	_camera_toggle_button.text = "Camera: Zoom" if camera_mode == "zoom" else "Camera: Full Pitch"


# "Zoom" already only shows a cropped sub-region of the pitch (see
# _compute_camera), so there's no fixed aspect ratio to preserve the way
# "full" mode needs -- filling the whole viewport just means more of that
# crop is visible at once. custom_minimum_size is enough to drive this:
# PitchCanvas's only parent (PitchCenterContainer) sizes it to exactly its
# minimum and centers it, which is a no-op once that minimum is already the
# full viewport width.
func _update_pitch_canvas_size() -> void:
	custom_minimum_size = get_viewport_rect().size if camera_mode == "zoom" else FULL_MODE_BOX_SIZE


func _update_speed_button_label() -> void:
	_speed_button.text = "Speed: %dx" % int(speed_options[speed_index])


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


func _reset_state() -> void:
	next_event_index = 0
	home_score = 0
	away_score = 0
	banner_text = ""
	banner_timer = 0.0
	banner_color = Color.WHITE
	halftime_pause_remaining = 0.0
	ball_flash_timer = 0.0
	ball_flash_color = ACTION_COLOR_GOAL
	_pending_result_transition = false
	for i in range(player_flash_timers.size()):
		player_flash_timers[i] = 0.0
		player_flash_colors[i] = ACTION_COLOR_DEFAULT
	_update_score_label()


func _on_start_match_pressed() -> void:
	_pre_match_overlay.visible = false
	_reset_state()
	playback_tick = 0.0
	has_started = true


func _on_pause_pressed() -> void:
	is_paused = not is_paused
	_pause_overlay.visible = is_paused
	_pause_button.text = "Resume" if is_paused else "Pause"
	if is_paused:
		# "No going back": once playback has moved past halftime, jumping to
		# it again would rewind the score -- see _jump_to_event's docstring.
		_skip_halftime_button.disabled = _halftime_tick < 0.0 or playback_tick >= _halftime_tick


func _close_pause_overlay() -> void:
	is_paused = false
	_pause_overlay.visible = false
	_pause_button.text = "Pause"


func _on_skip_halftime_pressed() -> void:
	_jump_to_event(ReplayReader.ActionType.HALFTIME)
	_close_pause_overlay()


func _on_skip_fulltime_pressed() -> void:
	_jump_to_event(ReplayReader.ActionType.FULLTIME)
	_close_pause_overlay()


## Re-fetches the squad from Firestore before heading back to Menu, same as
## MatchResult.gd's own _on_continue_pressed() and for the same reason:
## /match/quick already persisted this match's goals/assists/matches_played
## server-side, but GameProfile.all_cards was only ever populated once at
## sign-in, so it stays stale until something re-runs load_all(). Skipped
## entirely for the bundled demo replay (_is_real_match false) -- nothing
## backend-side happened for that path, so there's nothing new to fetch.
func _on_exit_pressed() -> void:
	if _is_real_match:
		_exit_button.disabled = true
		_loading_popup.set_status("Loading players...")
		_loading_popup.visible = true
		await GameProfile.load_all()
	MatchSession.clear()
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")


func _on_camera_toggle_pressed() -> void:
	camera_mode = "full" if camera_mode == "zoom" else "zoom"
	_update_camera_button_label()
	_update_pitch_canvas_size()


func _on_speed_pressed() -> void:
	speed_index = (speed_index + 1) % speed_options.size()
	_update_speed_button_label()


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

	if not has_started or is_paused:
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

	if _pending_result_transition and banner_timer <= 0.0:
		_pending_result_transition = false
		get_tree().change_scene_to_file("res://scenes/MatchResult.tscn")
		return

	_update_timer_label()
	queue_redraw()

func _action_color(event_type: int) -> Color:
	match event_type:
		ReplayReader.ActionType.GOAL:
			return ACTION_COLOR_GOAL
		ReplayReader.ActionType.SHOOT:
			return ACTION_COLOR_SHOOT
		ReplayReader.ActionType.SAVE:
			return ACTION_COLOR_SAVE
		ReplayReader.ActionType.TACKLE:
			return ACTION_COLOR_TACKLE
		ReplayReader.ActionType.ANKLEBREAKER:
			return ACTION_COLOR_ANKLEBREAKER
		ReplayReader.ActionType.PASS:
			return ACTION_COLOR_PASS
		ReplayReader.ActionType.RECEIVED_PASS:
			return ACTION_COLOR_RECEIVED
		ReplayReader.ActionType.CROSS:
			return ACTION_COLOR_CROSS
		ReplayReader.ActionType.CLEARANCE:
			return ACTION_COLOR_CLEARANCE
		ReplayReader.ActionType.KICKOFF, ReplayReader.ActionType.THROW_IN, ReplayReader.ActionType.CORNER, ReplayReader.ActionType.GOAL_KICK:
			return ACTION_COLOR_RESTART
	return ACTION_COLOR_DEFAULT


func _process_events(current_tick: float) -> void:
	var events: Array = replay["events"]
	while next_event_index < events.size() and events[next_event_index]["tick"] <= current_tick:
		var event: Dictionary = events[next_event_index]
		var idx: int = event["player_idx"]
		var event_type: int = event["type"]

		if idx >= 0 and idx < ReplayReader.NUM_PLAYERS:
			player_flash_timers[idx] = 0.3
			player_flash_colors[idx] = _action_color(event_type)

		if event_type == ReplayReader.ActionType.SHOOT or event_type == ReplayReader.ActionType.SAVE:
			ball_flash_timer = 0.4
			ball_flash_color = _action_color(event_type)

		if event_type == ReplayReader.ActionType.GOAL:
			ball_flash_timer = 1.0
			ball_flash_color = ACTION_COLOR_GOAL
			var team: int = event["team"]
			if team == 0:
				home_score += 1
			else:
				away_score += 1
			_update_score_label()
			var scorer := _player_name(idx)
			banner_text = "GOAL: %s" % scorer if scorer != "" else "GOAL"
			banner_timer = 3.0
			banner_color = ACTION_COLOR_GOAL
		elif event_type == ReplayReader.ActionType.HALFTIME:
			banner_text = "HALF TIME"
			banner_timer = HALFTIME_PAUSE_SECONDS
			banner_color = Color.WHITE
			halftime_pause_remaining = HALFTIME_PAUSE_SECONDS
		elif event_type == ReplayReader.ActionType.FULLTIME:
			banner_text = "FULL TIME"
			banner_timer = 4.0
			banner_color = Color.WHITE
			if _is_real_match:
				_pending_result_transition = true

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
# this box (here, with zero letterboxing -- FULL_MODE_BOX_SIZE's 378x540
# already matches the pitch's own 70x100 aspect ratio); "zoom" follows the
# ball with a fixed *vertical* (goal-to-goal) span so up/down-field context
# stays consistent, letting the horizontal (sideline) span be whatever that
# implies for this box's current aspect ratio.
#
# Since "zoom" mode fills the full (landscape) viewport width -- see
# _update_pitch_canvas_size -- that implied horizontal span (~80 units) is
# now routinely *wider* than the pitch itself (70 units), which the normal
# ball-following clamp below was never built for: clamping a span wider
# than its own bounds to `[0, bounds - span]` (a negative upper bound)
# collapses to a single fixed value of 0 regardless of the ball's actual
# position, pinning the pitch flush to the screen's left edge with all the
# leftover width bunched on the right instead of following the ball or
# even just sitting centered. Handled as its own case: when the span is
# too wide to pan at all, center it on the pitch's own midline instead
# (the pitch reads as centered with a bit of grass showing past both
# touchlines, rather than lopsided) -- panning still works normally the
# moment the span is narrow enough to fit (e.g. back in "full" mode's
# narrower box, or if this box's aspect ratio ever changes).
func _compute_camera(ball_pos: Vector2) -> Dictionary:
	var w := size.x
	var h := size.y

	if camera_mode == "full":
		var scale := minf(w / PITCH_WIDTH, h / PITCH_HEIGHT)
		var offset_x := (w - PITCH_WIDTH * scale) / 2.0
		var offset_y := (h - PITCH_HEIGHT * scale) / 2.0
		return {"scale": scale, "cam_x": -offset_x / scale, "cam_y": -offset_y / scale}

	var visible_y_span := 45.0
	var visible_x_span := visible_y_span * (w / h)
	var scale := h / visible_y_span

	var cam_x: float
	if visible_x_span >= PITCH_WIDTH:
		cam_x = (PITCH_WIDTH - visible_x_span) / 2.0
	else:
		cam_x = clampf(ball_pos.x - visible_x_span / 2.0, 0.0, PITCH_WIDTH - visible_x_span)
	var cam_y := clampf(ball_pos.y - visible_y_span / 2.0, 0.0, maxf(0.0, PITCH_HEIGHT - visible_y_span))
	return {"scale": scale, "cam_x": cam_x, "cam_y": cam_y}


# Local to PitchCanvas -- (0, 0) is this box's own top-left, not the
# screen's. clip_contents on the node this script lives on (see class
# docstring) is what keeps anything landing outside this box's current
# `size` from actually showing.
func _pitch_to_screen(p: Vector2, cam: Dictionary) -> Vector2:
	# cam's values come back typed as Variant (Dictionary access), which
	# GDScript's `:=` type inference can't always resolve through an
	# operator like `*` -- pulling them into explicitly-typed locals first
	# sidesteps that everywhere below, rather than fighting it call by call.
	var scale: float = cam.scale
	var cam_x: float = cam.cam_x
	var cam_y: float = cam.cam_y
	return Vector2((p.x - cam_x) * scale, (p.y - cam_y) * scale)


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
	var point_count := 16  # Higher count makes the curve smoother
	draw_arc(base, arc_radius, start_angle, end_angle, point_count, Color.WHITE, 2.0, true)


# Everything drawn on PitchCanvas is raw CanvasItem calls, not themed Control
# nodes -- AppTheme.tres's project-wide Label shadow (see mobile/README.md's
# "Naked text" section) has no effect here at all, so text drawn directly
# over the pitch (which is a busy, moving, colored scene, unlike a flat
# panel background) needs its own manual shadow: the same string drawn
# twice, once offset in dark and mostly-transparent, once for real on top.
# Shadow alpha rides on the real text's own alpha so a fading banner's
# shadow fades with it instead of leaving a lingering dark smudge behind.
func _draw_string_with_shadow(
	font: Font, pos: Vector2, text: String, alignment: int, width: float, font_size: int, color: Color
) -> void:
	var shadow_color := Color(0.0, 0.0, 0.0, color.a * 0.8)
	draw_string(font, pos + Vector2(2, 2), text, alignment, width, font_size, shadow_color)
	draw_string(font, pos, text, alignment, width, font_size, color)


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

	# Grass fill: clip_contents (set on this node in Match.tscn) guarantees
	# nothing drawn below ever shows outside this box's current `size`
	# (378x540 in "full" mode, the whole viewport in "zoom" -- see
	# _update_pitch_canvas_size), so a flat full-box fill is correct in both
	# modes with no extra math.
	draw_rect(Rect2(Vector2.ZERO, size), Color(0.09, 0.47, 0.22))

	_draw_pitch_lines(cam)
	_draw_goal(cam, 0.0, -1.0)
	_draw_goal(cam, PITCH_HEIGHT, 1.0)
	_draw_corner_quarter(cam, Vector2(0, 0), 0.0, PI / 2.0)
	_draw_corner_quarter(cam, Vector2(PITCH_WIDTH, 0), PI / 2.0, PI)
	_draw_corner_quarter(cam, Vector2(PITCH_WIDTH, PITCH_HEIGHT), PI, 3.0 * PI / 2.0)
	_draw_corner_quarter(cam, Vector2(0, PITCH_HEIGHT), -PI / 2.0, 0.0)

	for i in range(ReplayReader.NUM_PLAYERS):
		var pos: Vector2 = _pitch_to_screen(players[i], cam)
		var color := _team_color(0) if i < 11 else _team_color(1)
		if player_flash_timers[i] > 0.0:
			color = player_flash_colors[i]
		if i == controller:
			draw_circle(pos, PLAYER_RADIUS_UNITS * 1.35 * scale, Color(1.0, 1.0, 1.0), false, 2.0)
		draw_circle(pos, PLAYER_RADIUS_UNITS * scale, color)
		draw_string(
			font,
			pos + Vector2(-6, 5),
			str(i),
			HORIZONTAL_ALIGNMENT_CENTER,
			24,
			maxi(8, int(font_size * 0.6)),
			Color.BLACK
		)

	if controller != -1:
		var carrier_pos: Vector2 = _pitch_to_screen(players[controller], cam)
		var name: String = _player_name(controller)
		if name != "":
			_draw_string_with_shadow(
				font,
				carrier_pos + Vector2(-40, -PLAYER_RADIUS_UNITS * scale - 10),
				name,
				HORIZONTAL_ALIGNMENT_CENTER,
				80,
				font_size,
				Color.WHITE
			)

	var ball_pos: Vector2 = _pitch_to_screen(state["ball"], cam)
	var ball_color := ball_flash_color if ball_flash_timer > 0.0 else Color(1.0, 1.0, 1.0)
	draw_circle(ball_pos, BALL_RADIUS_UNITS * scale, ball_color)

	_draw_banner(font, font_size)


func _draw_banner(font: Font, font_size: int) -> void:
	if banner_timer <= 0.0:
		return
	# Fades out over its last second, however long the banner's total duration was.
	var alpha: float = clampf(banner_timer, 0.0, 1.0)
	var color := banner_color
	color.a = alpha
	_draw_string_with_shadow(
		font,
		Vector2(size.x / 2.0 - 150, size.y / 2.0),
		banner_text,
		HORIZONTAL_ALIGNMENT_CENTER,
		300,
		int(font_size * 1.6),
		color
	)
