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


const PITCH_WIDTH := 70.0
const PITCH_HEIGHT := 100.0
const TICKS_PER_SECOND := 60.0
const REPLAY_PATH := "res://test_data/sample_match.bin"
const ROSTER_PATH := "res://test_data/sample_match.json"
const OPPONENT_SQUAD_SCENE := "res://scenes/OpponentSquad.tscn"


const FULL_MODE_BOX_SIZE := Vector2(378.0, 540.0)
const BALL_RADIUS_UNITS := 0.55


const BALL_HEIGHT_LIFT := 0.55
const BALL_HEIGHT_GROW := 0.06
const BALL_GROUND_EPSILON := 0.05   # below this, don't bother with a shadow
const BALL_SHADOW_ALPHA := 0.35
const BALL_SHADOW_MIN_SCALE := 0.45 # how far the shadow tightens when high
const BALL_SHADOW_FADE_UNITS := 6.0 # height at which it's fully faded/tight

# How tall a drawn player is, in pitch units. NOT the simulation's physical
# radius (gameEngine's possession_radius works against 1.3) -- a figure
# stands on its position instead of being centred on it, so it can be this
# much taller than its footprint without the sim changing. ~48px at the
# zoom camera below.
const FIGURE_HEIGHT_UNITS := 3.2
const FIGURE_FULL_DETAIL_PX := 26.0
const FACING_MIN_SPEED := 0.6
const RUN_CYCLE_SPEED := 0.09
const ZOOM_VISIBLE_Y_SPAN := 36.0
# How far past each goal line the camera may show. Has to cover the goal
# itself (2 units deep, drawn at y -2..0 and 100..102) plus a figure's worth
# of overhang, since a keeper on their line is drawn FIGURE_HEIGHT_UNITS
# upward from it.
const CAMERA_MARGIN_UNITS := 4.5

# A goal STOPS the replay -- playback_tick does not advance -- for this many
# REAL seconds, so there is time to actually watch the celebration. The
# engine's own goal pause (gameEngine._award_goal sets goal_pause_timer =
# 90) is only 1.5s of playback and the clock keeps running through it, which
# is far too short to read as anything. PlayerFigure's, because the
# celebration timelines are written to fit it.
const GOAL_CELEBRATION_SECONDS := PlayerFigure.CELEBRATE_DURATION
# Once the replay resumes, the scoring side keeps its arms up for the rest
# of the engine's own dead-ball window rather than snapping straight back to
# running -- otherwise there's a stretch of players milling about around a
# ball sitting in the net before the kickoff reset.
const GOAL_CELEBRATION_FRAMES := 90.0
# How fast the scorer runs off during their celebration, pitch units per
# real second -- about a real sprint (a player covers ~9 units/s in the
# engine). The recipe says how long they run for; this says how far that
# gets them.
const CELEBRATION_RUN_SPEED := 7.0
# How far back toward halfway the run-off angles, per unit of sideways --
# the scorer heads for the corner flag, not straight into the touchline.
const CELEBRATION_RUN_BACK := 0.6
# Teammates' arm waves are offset by this many seconds each so ten figures
# don't wave in lockstep.
const CELEBRATION_TEAMMATE_STAGGER := 0.13

# Home / away shirts when the roster carries no kit (demo replay, or a
# backend older than kits).
const DEFAULT_TEAM_COLORS := [Color(0.2, 0.5, 1.0), Color(1.0, 0.35, 0.35)]

# How different two shirts must be before the away side changes kit.
const TEAM_COLOR_MIN_DISTANCE := 0.42
# Last resorts when even the away kit's second colour clashes: between
# near-white and near-black, nothing can clash with both.
const CHANGE_KIT_FALLBACKS := [Color(0.95, 0.95, 0.96), Color(0.12, 0.12, 0.14)]

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

const ACTION_COLOR_DEFAULT := Color(1.0, 1.0, 0.2)

# Size of one color chip in the pause screen's key (see _build_legend).
const LEGEND_SWATCH_SIZE := Vector2(14.0, 14.0)

var replay: Dictionary = {}
var roster: Dictionary = {}
var playback_tick: float = 0.0
var next_event_index: int = 0
var player_flash_timers: Array = []
var player_flash_colors: Array = []
var player_facings: Array = []
var player_poses: Array = []
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
var _halftime_tick: float = -1.0
var _pending_result_transition: bool = false


var _team_kits: Array = []
var _team_colors: Array = DEFAULT_TEAM_COLORS.duplicate()

# Goal celebration, entirely a playback concern -- the engine doesn't stop
# the players, it only stops the BALL (tick() early-returns during the goal
# pause while step() keeps running), so left alone they just carry on
# milling about while the net bulges. These pin the scoring side where they
# stood when the goal went in, arms up, until the pause is over.
var _celebration_until_tick: float = -1.0
var _celebration_team: int = -1
var _celebration_positions: Array = []
# Who scored (roster index, -1 if the event didn't say) and which way they
# run off: only they do their own celebration and move; the rest of the
# side does PlayerAppearance.TEAMMATE_CELEBRATION where they stand.
var _celebration_scorer: int = -1
var _celebration_direction: Vector2 = Vector2.ZERO
var _celebration_facing: int = PlayerFigure.FACING_S
# The scorer's PlayerFigure.celebration_state for this frame, computed
# once in _draw_players before the draw loop needs its stage.
var _celebration_stage: String = PlayerFigure.STAGE_POSE
# Real seconds left on the hold, and the clock that drives the arm wave
# while everything else is frozen.
var goal_pause_remaining: float = 0.0
var _celebration_phase: float = 0.0

var camera_mode: String = "zoom"  # "zoom" | "full" -- matches gameEngine.py's render()

var speed_options := [1.0, 2.0, 4.0]
var speed_index: int = 0


var _is_real_match: bool = false #for local testing demo replays

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
@onready var _view_opponent_button: Button = %ViewOpponentButton
@onready var _start_button: Button = %StartButton

@onready var _pause_overlay: Control = %PauseOverlay
@onready var _legend_grid: GridContainer = %LegendGrid
@onready var _skip_halftime_button: Button = %SkipHalftimeButton
@onready var _skip_fulltime_button: Button = %SkipFulltimeButton
@onready var _exit_button: Button = %ExitButton

@onready var _loading_popup: Control = %LoadingPopup


func _ready() -> void:

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
	player_facings.resize(ReplayReader.NUM_PLAYERS)
	player_poses.resize(ReplayReader.NUM_PLAYERS)
	# Each side starts facing the goal it's attacking: team A up the pitch
	# (screen north), team B down it.
	for i in range(ReplayReader.NUM_PLAYERS):
		player_facings[i] = PlayerFigure.FACING_S if i < 11 else PlayerFigure.FACING_N
		player_poses[i] = ""

	_halftime_tick = ReplayReader.halftime_tick(replay)

	_resolve_team_colors()  # before _setup_scoreboard -- it paints the swatches
	_setup_scoreboard()
	_build_legend()
	_pre_match_teams_label.text = tr("%s vs %s") % [roster.get("home_name", tr("Home")), roster.get("away_name", tr("Away"))]
	# Only a real match has a roster worth opening -- the bundled demo's
	# sidecar carries names only (see _attributes_for), so there'd be
	# nothing to show but a grid of blanks.
	_view_opponent_button.visible = _is_real_match
	_update_camera_button_label()
	_update_speed_button_label()
	_update_pitch_canvas_size()

	_view_opponent_button.pressed.connect(_on_view_opponent_pressed)
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
	_home_name_label.text = roster.get("home_name", tr("Home"))
	_away_name_label.text = roster.get("away_name", tr("Away"))
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
		# Context disambiguates "Save" (the keeper's) from the Save button.
		label.text = tr(entry[1], "match_legend")
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

	# No kit at all (bundled demo replay, or a backend older than kits):
	# dress both sides in the built-in colours rather than leaving them
	# both in KitDesign's default royal blue.
	if not roster.has("home_kit"):
		home_kit = _kit_from_color(DEFAULT_TEAM_COLORS[0])
	if not roster.has("away_kit"):
		away_kit = _kit_from_color(DEFAULT_TEAM_COLORS[1])

	if _too_similar(home_kit.primary_color(), away_kit.primary_color()):
		# Change kit, in the order a club would: their own second colour
		# first, then a neutral that cannot clash with anything.
		var candidates := [away_kit.secondary_color(), DEFAULT_TEAM_COLORS[1]]
		candidates.append_array(CHANGE_KIT_FALLBACKS)
		for candidate in candidates:
			if not _too_similar(home_kit.primary_color(), candidate):
				# Keep their pattern and second colour, swap the primary --
				# a change kit is the same shirt in different colours.
				away_kit = KitDesign.create(
					away_kit.pattern, candidate.to_html(false), away_kit.secondary
				)
				break

	_team_kits = [home_kit, away_kit]
	_team_colors = [home_kit.primary_color(), away_kit.primary_color()]


## A plain one-colour kit, for the paths that have a Color but no kit string.
func _kit_from_color(color: Color) -> KitDesign:
	return KitDesign.create(KitDesign.PATTERN_SOLID, color.to_html(false), Color.WHITE.to_html(false))


func _too_similar(a: Color, b: Color) -> bool:
	return Vector3(a.r - b.r, a.g - b.g, a.b - b.b).length() < TEAM_COLOR_MIN_DISTANCE


func _team_color(team_index: int) -> Color:
	return _team_colors[team_index]


func _update_score_label() -> void:
	_score_label.text = "%d - %d" % [home_score, away_score]


func _update_timer_label() -> void:# display_tick, not the raw playback tick:
	var shown := ReplayReader.display_tick(playback_tick, _halftime_tick)
	var clock_total_seconds := int(shown / 2.0)
	_timer_label.text = "%02d:%02d" % [clock_total_seconds / 60, clock_total_seconds % 60]


func _update_camera_button_label() -> void:
	_camera_toggle_button.text = tr("Camera: Zoom") if camera_mode == "zoom" else tr("Camera: Full Pitch")

func _update_pitch_canvas_size() -> void:
	custom_minimum_size = get_viewport_rect().size if camera_mode == "zoom" else FULL_MODE_BOX_SIZE


func _update_speed_button_label() -> void:
	_speed_button.text = tr("Speed: %dx") % int(speed_options[speed_index])


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
	_celebration_until_tick = -1.0
	_celebration_team = -1
	_celebration_positions = []
	_celebration_scorer = -1
	goal_pause_remaining = 0.0
	_celebration_phase = 0.0
	for i in range(player_flash_timers.size()):
		player_flash_timers[i] = 0.0
		player_flash_colors[i] = ACTION_COLOR_DEFAULT
		player_poses[i] = ""
	_update_score_label()


## A look at the other side before kicking off. A plain scene change, not
## an overlay: MatchSession keeps the match, so coming back re-runs
## _ready() from the same data and lands on this same popup, with nothing
## having started in between. Not offered once the match is under way.
func _on_view_opponent_pressed() -> void:
	get_tree().change_scene_to_file(OPPONENT_SQUAD_SCENE)


func _on_start_match_pressed() -> void:
	_pre_match_overlay.visible = false
	_reset_state()
	playback_tick = 0.0
	has_started = true


func _on_pause_pressed() -> void:
	is_paused = not is_paused
	_pause_overlay.visible = is_paused
	_pause_button.text = tr("Resume") if is_paused else tr("Pause")
	if is_paused:
		# "No going back": once playback has moved past halftime, jumping to
		# it again would rewind the score -- see _jump_to_event's docstring.
		_skip_halftime_button.disabled = _halftime_tick < 0.0 or playback_tick >= _halftime_tick


func _close_pause_overlay() -> void:
	is_paused = false
	_pause_overlay.visible = false
	_pause_button.text = tr("Pause")


func _on_skip_halftime_pressed() -> void:
	_jump_to_event(ReplayReader.ActionType.HALFTIME)
	_close_pause_overlay()


func _on_skip_fulltime_pressed() -> void:
	_jump_to_event(ReplayReader.ActionType.FULLTIME)
	_close_pause_overlay()

func _on_exit_pressed() -> void:
	if _is_real_match and not MatchSession.is_local:
		_exit_button.disabled = true
		_loading_popup.set_status(tr("Loading players..."))
		_loading_popup.visible = true
		await GameProfile.load_all()
	# Before clear(), which resets it -- see MatchSession.return_scene.
	var destination := MatchSession.return_scene
	MatchSession.clear()
	get_tree().change_scene_to_file(destination)


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
			# That catch-up replays every earlier GOAL, and each one arms a
			# 5-second hold -- which would otherwise leave the screen frozen
			# on a celebration for a goal scored twenty minutes ago the
			# instant you skip to halftime. The scoreboard tally it produced
			# is what we wanted; the pause is not.
			goal_pause_remaining = 0.0
			_celebration_team = -1
			_celebration_positions = []
			_celebration_scorer = -1
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

	# A goal holds the picture the same way halftime does, and for the same
	# reason: something happened worth looking at. Counted in REAL seconds
	# (plain `delta`, not effective_delta) so the celebration is the length
	# it says it is whatever playback speed you're watching at -- unlike the
	# halftime pause, which scales. _celebration_phase is what keeps the
	# arms waving while the match clock is standing still.
	if goal_pause_remaining > 0.0:
		goal_pause_remaining = maxf(0.0, goal_pause_remaining - delta)
		_celebration_phase += delta
		banner_timer = maxf(0.0, banner_timer - delta)
		queue_redraw()
		return

	# The tail of the celebration (the engine's own dead-ball frames after
	# the hold) keeps animating rather than freezing mid-wave.
	if _celebrating():
		_celebration_phase += delta

	playback_tick += effective_delta * TICKS_PER_SECOND
	var last_tick: float = samples[-1]["tick"]
	if playback_tick > last_tick:
		playback_tick = last_tick  # hold on the final frame rather than loop/crash

	_process_events(playback_tick)

	for i in range(player_flash_timers.size()):
		player_flash_timers[i] = maxf(0.0, player_flash_timers[i] - effective_delta)
		if player_flash_timers[i] <= 0.0:
			player_poses[i] = ""  # back to run/idle, chosen by speed at draw time
	ball_flash_timer = maxf(0.0, ball_flash_timer - effective_delta)
	banner_timer = maxf(0.0, banner_timer - effective_delta)

	if _pending_result_transition and banner_timer <= 0.0:
		_pending_result_transition = false
		get_tree().change_scene_to_file("res://scenes/MatchResult.tscn")
		return

	_update_timer_label()
	queue_redraw()

## Which body pose an action reads as. Several actions share one -- a pass, a
## shot and a clearance are all "boot the ball" as far as a 48px figure is
## concerned; the colour flash is what tells them apart.
func _action_pose(event_type: int) -> String:
	match event_type:
		ReplayReader.ActionType.SHOOT, ReplayReader.ActionType.PASS, \
		ReplayReader.ActionType.CROSS, ReplayReader.ActionType.CLEARANCE, \
		ReplayReader.ActionType.GOAL, ReplayReader.ActionType.KICKOFF, \
		ReplayReader.ActionType.THROW_IN, ReplayReader.ActionType.CORNER, \
		ReplayReader.ActionType.GOAL_KICK:
			return PlayerFigure.POSE_KICK
		ReplayReader.ActionType.TACKLE, ReplayReader.ActionType.ANKLEBREAKER:
			return PlayerFigure.POSE_LUNGE
		ReplayReader.ActionType.SAVE:
			return PlayerFigure.POSE_REACH
	return ""


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
			# Same timer drives the pose, so a shot both flashes orange AND
			# reads as a kick for those 0.3s -- no replay format change
			# needed, the event stream already says who did what.
			player_poses[idx] = _action_pose(event_type)

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
			_celebration_team = team
			_celebration_scorer = idx if idx >= 0 and idx < ReplayReader.NUM_PLAYERS else -1
			_celebration_until_tick = float(event["tick"]) + GOAL_CELEBRATION_FRAMES
			goal_pause_remaining = GOAL_CELEBRATION_SECONDS
			_celebration_phase = 0.0
			# Cleared, not filled: _draw_players latches the positions on the
			# first frame it actually draws the celebration, which is the
			# only place the interpolated state exists.
			_celebration_positions = []
			var scorer := _player_name(idx)
			banner_text = "GOAL: %s" % scorer if scorer != "" else "GOAL"
			# Matched to the hold, so the scorer's name is on screen for the
			# whole celebration instead of fading two seconds before it ends.
			banner_timer = GOAL_CELEBRATION_SECONDS
			banner_color = ACTION_COLOR_GOAL
		elif event_type == ReplayReader.ActionType.HALFTIME:
			banner_text = tr("HALF TIME")
			banner_timer = HALFTIME_PAUSE_SECONDS
			banner_color = Color.WHITE
			halftime_pause_remaining = HALFTIME_PAUSE_SECONDS
		elif event_type == ReplayReader.ActionType.FULLTIME:
			banner_text = tr("FULL TIME")
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
	# Velocities come back too: they're what decides which of the 8 ways a
	# figure faces, and whether it's running or standing. Straight lerp
	# rather than Hermite -- there's no recorded acceleration to use as a
	# tangent, and a facing only needs the direction to be about right.
	var velocities: Array = []
	for i in range(ReplayReader.NUM_PLAYERS):
		var p0: Dictionary = s0["players"][i]
		var p1: Dictionary = s1["players"][i]
		var v0 := Vector2(p0["vx"], p0["vy"])
		var v1 := Vector2(p1["vx"], p1["vy"])
		players.append(
			_hermite(Vector2(p0["x"], p0["y"]), v0, Vector2(p1["x"], p1["y"]), v1, dt, s)
		)
		velocities.append(v0.lerp(v1, s))

	var ball_pos: Vector2
	# Recorded all along (replay.py writes ball[4], ReplayReader decodes it)
	# and simply never drawn until now. Straight lerp, not Hermite: the
	# format stores no vertical velocity to use as a tangent.
	var ball_height := 0.0
	var controller: int = s0["ball_controller"] if s < 0.5 else s1["ball_controller"]
	if controller != -1:
		# Glue the ball to the dribbler instead of interpolating it
		# independently -- otherwise it visibly drifts away from whoever
		# actually has it. A ball at someone's feet is on the ground.
		ball_pos = players[controller]
	else:
		var b0: Dictionary = s0["ball"]
		var b1: Dictionary = s1["ball"]
		ball_pos = _hermite(
			Vector2(b0["x"], b0["y"]), Vector2(b0["vx"], b0["vy"]), Vector2(b1["x"], b1["y"]), Vector2(b1["vx"], b1["vy"]), dt, s
		)
		ball_height = lerpf(float(b0["height"]), float(b1["height"]), s)

	return {
		"players": players,
		"velocities": velocities,
		"ball": ball_pos,
		"ball_height": maxf(0.0, ball_height),
		"ball_controller": controller,
	}


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
		# Fit the pitch PLUS the margin behind each goal line, so both goals
		# and both keepers are in frame rather than cropped off at y=0/100.
		var full_height := PITCH_HEIGHT + CAMERA_MARGIN_UNITS * 2.0
		var scale := minf(w / PITCH_WIDTH, h / full_height)
		var offset_x := (w - PITCH_WIDTH * scale) / 2.0
		var offset_y := (h - full_height * scale) / 2.0
		return {"scale": scale, "cam_x": -offset_x / scale, "cam_y": -offset_y / scale - CAMERA_MARGIN_UNITS}

	# Tightened from 45 when players became figures rather than dots: at 45
	# a character is 38px and the customization nobody can see isn't worth
	# selling. 36 puts it at ~48px while still showing most of the pitch's
	# width and about a third of its length.
	var visible_y_span := ZOOM_VISIBLE_Y_SPAN
	var visible_x_span := visible_y_span * (w / h)
	var scale := h / visible_y_span

	var cam_x: float
	if visible_x_span >= PITCH_WIDTH:
		cam_x = (PITCH_WIDTH - visible_x_span) / 2.0
	else:
		cam_x = clampf(ball_pos.x - visible_x_span / 2.0, 0.0, PITCH_WIDTH - visible_x_span)
	# The vertical clamp used to stop dead on the goal lines, which meant the
	# top of the screen WAS y=0: a keeper standing on their line had their
	# whole figure drawn above it and off-screen, and the goal (which lives
	# at y -2..0) was never visible at all. Letting the camera run
	# CAMERA_MARGIN_UNITS past each end is what puts the keeper, the goal and
	# a ball in the net on screen.
	var cam_y := clampf(
		ball_pos.y - visible_y_span / 2.0,
		-CAMERA_MARGIN_UNITS,
		maxf(-CAMERA_MARGIN_UNITS, PITCH_HEIGHT + CAMERA_MARGIN_UNITS - visible_y_span)
	)
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

	# Dark backing inside the goal mouth. Without it the goal is a white
	# wireframe on green and a white ball sitting in the net disappears into
	# the crosshatch -- this is what makes a goal read as a goal.
	draw_colored_polygon(
		PackedVector2Array([top_left, top_right, back_right, back_left]),
		Color(0.05, 0.16, 0.10, 0.55)
	)

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

	_draw_players(state, cam, font)

	if controller != -1:
		var carrier_pos: Vector2 = _pitch_to_screen(players[controller], cam)
		var name: String = _player_name(controller)
		if name != "":
			_draw_string_with_shadow(
				font,
				carrier_pos + Vector2(-40, -FIGURE_HEIGHT_UNITS * scale - 12),
				name,
				HORIZONTAL_ALIGNMENT_CENTER,
				80,
				font_size,
				Color.WHITE
			)

	_draw_ball(state, cam)

	_draw_banner(font, font_size)


## The ball, lifted off the turf by its recorded height.
##
##   - the ball is drawn ABOVE its pitch position (foreshortened, or a long
##     clearance would sail off the top of the screen)
##   - its SHADOW stays behind on the ground, at the real position, so the
##     gap between the two is the height
##   - it grows slightly, as something nearer the camera would

func _draw_ball(state: Dictionary, cam: Dictionary) -> void:
	var scale: float = cam.scale
	var ground: Vector2 = _pitch_to_screen(state["ball"], cam)
	var height: float = state.get("ball_height", 0.0)

	var radius := BALL_RADIUS_UNITS * scale
	var color := ball_flash_color if ball_flash_timer > 0.0 else Color(1.0, 1.0, 1.0)

	if height <= BALL_GROUND_EPSILON:
		draw_circle(ground, radius, color)
		return

	# Shadow first: it tightens and fades as the ball climbs, which is the
	# cue that says "high" rather than "slightly off the ground".
	var fade := clampf(height / BALL_SHADOW_FADE_UNITS, 0.0, 1.0)
	draw_circle(
		ground,
		radius * lerpf(1.0, BALL_SHADOW_MIN_SCALE, fade),
		Color(0.0, 0.0, 0.0, lerpf(BALL_SHADOW_ALPHA, BALL_SHADOW_ALPHA * 0.35, fade))
	)

	var lifted := ground - Vector2(0.0, height * scale * BALL_HEIGHT_LIFT)
	draw_circle(lifted, radius * (1.0 + height * BALL_HEIGHT_GROW), color)


## All 22 figures, back to front.
##
## Sorted by screen y before drawing: figures are much taller than the discs
## they replaced, so without this a player standing further up the pitch is
## drawn on top of one in front of them and the depth reads inside out.
## Painter's algorithm -- feet lowest on screen last.
func _draw_players(state: Dictionary, cam: Dictionary, font: Font) -> void:
	var players: Array = state["players"]
	var velocities: Array = state["velocities"]
	var controller: int = state["ball_controller"]
	var scale: float = cam.scale

	var celebrating := _celebrating()
	if celebrating:
		# Latch where the scoring side stood when the ball went in, on the
		# first frame of the celebration, and hold them there. The recorded
		# positions keep drifting (the engine never stops step()), and a
		# celebration that wanders is not a celebration.
		if _celebration_positions.is_empty():
			_celebration_positions = players.duplicate()
			_celebration_direction = _celebration_run_direction()
			_celebration_facing = PlayerFigure.facing_from_direction(_celebration_direction)
		players = _celebration_positions
		# ...except the scorer, who runs off along their celebration's
		# timeline: toward the nearest corner, as far as its stages carry
		# them, then stops there. Copied so the latch itself stays put.
		if _celebration_scorer >= 0:
			players = players.duplicate()
			var recipe := PlayerAppearance.celebration(
				int(_appearance_for(_celebration_scorer).get("celebration", 0))
			)
			var timeline: Dictionary = PlayerFigure.celebration_state(recipe, _celebration_phase)
			_celebration_stage = timeline.stage
			var travel: float = timeline.travel
			var run_off: Vector2 = _celebration_direction * travel * CELEBRATION_RUN_SPEED
			var start: Vector2 = _celebration_positions[_celebration_scorer]
			players[_celebration_scorer] = Vector2(
				clampf(start.x + run_off.x, 1.0, PITCH_WIDTH - 1.0),
				clampf(start.y + run_off.y, 1.0, PITCH_HEIGHT - 1.0)
			)

	var order: Array = []
	for i in range(ReplayReader.NUM_PLAYERS):
		order.append(i)
	order.sort_custom(func(a, b): return players[a].y < players[b].y)

	var height_px: float = FIGURE_HEIGHT_UNITS * scale
	var detail: int = PlayerFigure.DETAIL_FULL if height_px >= FIGURE_FULL_DETAIL_PX else PlayerFigure.DETAIL_LOW

	for i in order:
		var feet: Vector2 = _pitch_to_screen(players[i], cam)
		var team: int = 0 if i < 11 else 1
		var velocity: Vector2 = velocities[i]

		player_facings[i] = PlayerFigure.facing_from_velocity(
			velocity, int(player_facings[i]), FACING_MIN_SPEED
		)

		var pose: String = player_poses[i]
		var appearance: Dictionary = _appearance_for(i)
		# Offset per player so 22 figures don't run in lockstep.
		var phase: float = playback_tick * RUN_CYCLE_SPEED + float(i)
		if celebrating:
			# Scorers celebrate; the side that conceded just stands there,
			# which is its own kind of correct. Only the scorer does THEIR
			# celebration -- everyone else on the side gets the plain
			# arms-up, so nobody knee-slides in their own half.
			pose = PlayerFigure.POSE_CELEBRATE if team == _celebration_team else PlayerFigure.POSE_IDLE
			if i == _celebration_scorer:
				# The match clock is stopped dead during the hold, so the
				# celebration runs on its own real-time clock -- and for
				# the scorer that clock IS the timeline, so no offset. They
				# face the way they're running while they run, then turn
				# to the camera for the pose itself: a shush with the back
				# of the head to you is nothing.
				phase = _celebration_phase
				var running := _celebration_stage in [PlayerFigure.STAGE_RUN, PlayerFigure.STAGE_JUMP]
				player_facings[i] = _celebration_facing if running else PlayerFigure.FACING_S
			else:
				phase = _celebration_phase + float(i) * CELEBRATION_TEAMMATE_STAGGER
				if team == _celebration_team:
					appearance = appearance.duplicate()
					appearance["celebration"] = PlayerAppearance.TEAMMATE_CELEBRATION
		elif pose == "":
			pose = PlayerFigure.POSE_RUN if velocity.length() > FACING_MIN_SPEED else PlayerFigure.POSE_IDLE

		var flash := Color(0, 0, 0, 0)
		if player_flash_timers[i] > 0.0:
			flash = player_flash_colors[i]
		elif i == controller:
			# The carrier gets a ring on the ground instead of a flash, so
			# you can always see who has the ball.
			flash = Color(1.0, 1.0, 1.0, 0.85)

		PlayerFigure.draw_into(
			self,
			feet,
			height_px,
			appearance,
			_team_kits[team] if _team_kits.size() == 2 else null,
			int(player_facings[i]),
			pose,
			detail,
			phase,
			i % 11 + 1,  # squad number: no real one exists in the data model
			flash,
			font,
			# Index 0 / 11 are the keepers by formation contract -- the same
			# assumption gameEngine._award_goal makes when it charges a goal
			# to the conceding keeper.
			i == 0 or i == 11,
			# Taller/wider from this card's own height and power, so 22
			# figures aren't 22 identical blocks.
			PlayerFigure.build_from(_attributes_for(i))
		)


## Which way the scorer runs off: to the nearer touchline, angled back
## toward endline -- the corner flag, roughly, from anywhere in the box.
## Pitch units, so +y is the home side's attacking direction.
func _celebration_run_direction() -> Vector2:
	if _celebration_scorer < 0:
		return Vector2.ZERO
	var start: Vector2 = _celebration_positions[_celebration_scorer]
	var sideways := 1.0 if start.x >= PITCH_WIDTH / 2.0 else -1.0
	var back := 1.0 if _celebration_team == 0 else -1.0
	return Vector2(sideways, back * CELEBRATION_RUN_BACK).normalized()


## True while a goal is still being celebrated. Two windows back to back:
## the real-time hold where the replay is stopped dead, and then the rest of
## the engine's own dead-ball frames once it resumes -- so the arms stay up
## until the kickoff reset instead of dropping the moment play restarts.
##
## The second half is keyed off playback_tick rather than a countdown so it
## survives seeking: jump backwards past a goal and it is simply not active.
func _celebrating() -> bool:
	if _celebration_team < 0:
		return false
	return goal_pause_remaining > 0.0 or playback_tick < _celebration_until_tick


## This card's attributes, which is where the figure's build comes from
## (height in cm, power). Empty for the bundled demo replay's roster sidecar,
## which carries names only -- PlayerFigure turns that into an average build.
func _attributes_for(index: int) -> Dictionary:
	var attributes = _roster_entry(index).get("attributes")
	return attributes if attributes is Dictionary else {}


## This player's 5 appearance slots. Empty for the demo replay's sidecar,
## which PlayerFigure handles by falling back to its default colours.
func _appearance_for(index: int) -> Dictionary:
	var appearance = _roster_entry(index).get("appearance")
	return appearance if appearance is Dictionary else {}


## One player's whole roster record (the shape backend/main.py's
## player_to_fields writes), or {} if this match didn't ship one.
func _roster_entry(index: int) -> Dictionary:
	var players: Array = roster.get("players", [])
	if index < 0 or index >= players.size():
		return {}
	var entry = players[index]
	return entry if entry is Dictionary else {}


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
