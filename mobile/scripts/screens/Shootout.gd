extends Control

## The daily shootout, a kick at a time, on the match's own pitch.
##
## The ground, the goal and the pitch-space -> pixel camera are PitchDraw's,
## the same ones MatchPlayback uses, so a penalty here is drawn on the pitch a
## match is played on rather than a second one that drifts from it. The
## figures are PlayerFigure's, in both sides' real kits.
##
## THE GEOMETRY IS THE ENGINE'S. Every number below is read off
## packedfootball/minigames/minigamesEngine.py's _animate_kick, so where the
## drawn ball ends up is where the engine says it ended up: a save dies in
## FRONT of the line, a goal ends BEHIND it, a miss reaches the line outside
## the frame. If those ever disagree, the picture is lying about the result.
##
## Every outcome is already decided before a frame is drawn -- the backend
## resolves the penalty and answers with the corner and the dive, and this
## only plays that back. No ReplayReader: a match ships a whole replay file,
## one penalty is three numbers.

# -- the engine's geometry (minigamesEngine.py) --------------------------------
const PITCH_WIDTH := 70.0
const PITCH_HEIGHT := 100.0
const GOAL_WIDTH := 7.5
const PENALTY_SPOT_DISTANCE := 11.0
## The end team A attacks in a match, so the player shoots the way they always
## shoot. Everything below is a distance measured toward it.
const SHOOTOUT_GOAL_Y := PITCH_HEIGHT
const ATTACK_DIR := 1.0
const SPOT_Y := SHOOTOUT_GOAL_Y - ATTACK_DIR * PENALTY_SPOT_DISTANCE
const KEEPER_REACH := 6.2
const KEEPER_DIVE_FRACTION := 0.7
const SAVE_STOP_DEPTH := 0.3
const GOAL_STOP_DEPTH := 1.2
const PENALTY_SHOT_SPEED := 26.0
## How far behind the ball the taker stands. Deliberately further back than
## the engine's 1.5: a figure is drawn FIGURE_HEIGHT_UNITS tall from its feet,
## so at 1.5 his head covers the ball and the spot kick has no visible ball
## sitting on the spot. A drawing distance, not a simulation one.
const TAKER_STANDOFF := 3.0
## The share of the flight the keeper takes to commit. He holds that side
## afterwards -- no drifting back onto a ball he is already beaten by.
const DIVE_COMMIT_FRACTION := 0.6

# -- the view ------------------------------------------------------------------
## How much pitch to show down the screen, and where the top edge sits.
##
## Drawn the same way up as a match: the shootout is at the y = PITCH_HEIGHT
## goal, so that goal is at the BOTTOM and the taker runs onto it from above,
## exactly as team A attacks in a replay. Turning the pitch around to put the
## goal on top would look tidier and be a different end than the one being
## played.
## The goal sits about two thirds down, which leaves the bottom third for the
## prompt and the aim panel without drawing them over the net.
const FRAME_Y_SPAN := 28
const FRAME_TOP_Y := SHOOTOUT_GOAL_Y - 25

const FIGURE_HEIGHT_UNITS := 1.9
const BALL_RADIUS_UNITS := 0.3

## After the kick. A goal gets the taker's own celebration -- the one he does
## in a match, held as long as a match holds it. A miss gets a beat with his
## hands on his head, then a slow walk back toward halfway.
const CELEBRATION_SECONDS := PlayerFigure.CELEBRATE_DURATION
const CELEBRATION_RUN_SPEED := 7.0     # MatchPlayback's
const CELEBRATION_RUN_BACK := 0.6      # MatchPlayback's: angled toward the corner flag
## The match's run-off would carry him out of this much tighter frame, so the
## whole run is scaled to end this many units from where he struck it.
const CELEBRATION_MAX_RUN := 8.0
const DEJECTED_SECONDS := 0.5
const WALK_OFF_SECONDS := 1.5
const WALK_OFF_SPEED := 2.0            # units/s -- a match run is 7
## Leg swing, radians per second: the run-up's stride, and a walk's.
const RUN_CYCLE := PlayerFigure.CELEBRATE_RUN_CYCLE
const WALK_CYCLE := 7.0

## The run-up: he walks back, then comes at it. The ball does not move until
## his boot arrives, so the strike reads as the cause of the flight.
const RUNUP_SECONDS := 0.55
## How close his planted foot gets to the ball. Short of it, or the figure
## covers the thing he is about to kick.
const RUNUP_FINISH_UNITS := 1.1

## Five marks a side, oldest dropped once sudden death runs past them -- the
## board shows the last five kicks, not the first five.
const MARK_SLOTS := 5
const MARK_SCORED := "O"
const MARK_MISSED := "X"
const MARK_EMPTY := "."

## The board sizes itself to its names, so a long one would push it off the
## screen. Each name is trimmed to this share of the width instead -- trimmed
## rather than clipped, because a clipped Label reports no width at all, which
## is what used to squeeze both names down to a single letter.
const NAME_WIDTH_SHARE := 0.29

const KEEPER_COLOR_FALLBACK := Color(0.95, 0.75, 0.25)

## The pre-match picker. Kicks past minigamesEngine.REGULATION_KICKS are
## sudden death, which is why the order list marks where it starts: the back
## half of the order still gets used.
const REGULATION_KICKS := 5
const TAKER_ROW_HEIGHT := 40

@onready var _pitch: Control = %PitchCanvas
@onready var _scoreboard: PanelContainer = %ScoreboardPanel
@onready var _home_name_label: Label = %HomeNameLabel
@onready var _away_name_label: Label = %AwayNameLabel
@onready var _home_swatch: KitSwatch = %HomeSwatch
@onready var _away_swatch: KitSwatch = %AwaySwatch
@onready var _score_label: Label = %ScoreLabel
@onready var _home_marks: HBoxContainer = %HomeMarks
@onready var _away_marks: HBoxContainer = %AwayMarks
@onready var _turn_label: Label = %TurnLabel
@onready var _aim_panel: PanelContainer = %AimPanel
@onready var _aim_title: Label = %AimTitle
@onready var _left_button: Button = %LeftButton
@onready var _middle_button: Button = %MiddleButton
@onready var _right_button: Button = %RightButton
## The end popup and the ad button under it, shown and hidden together.
@onready var _result_stack: VBoxContainer = %ResultStack
@onready var _result_panel: PanelContainer = %ResultPanel
@onready var _result_label: Label = %ResultLabel
@onready var _reward_label: Label = %RewardLabel
@onready var _retry_button: Button = %RetryButton
@onready var _continue_button: Button = %ContinueButton
@onready var _status_label: Label = %StatusLabel
@onready var _takers_panel: PanelContainer = %TakersPanel
@onready var _takers_title: Label = %TakersTitle
@onready var _takers_hint: Label = %TakersHint
@onready var _order_title: Label = %OrderTitle
@onready var _order_pen_title: Label = %OrderPenTitle
@onready var _order_list: VBoxContainer = %OrderList
@onready var _squad_title: Label = %SquadTitle
@onready var _squad_pen_title: Label = %SquadPenTitle
@onready var _squad_list: VBoxContainer = %SquadList
@onready var _takers_status: Label = %TakersStatus
@onready var _takers_back_button: Button = %TakersBackButton
@onready var _auto_select_button: Button = %AutoSelectButton
@onready var _send_button: Button = %SendButton

## A kick plays as run-up then flight. `_runup` and `_anim` are each 0..1 over
## their own phase; both at 1 with no kick means "ball on the spot, waiting".
var _runup: float = 1.0
var _anim: float = 1.0
var _flight_seconds: float = 0.4
## Seconds since the ball stopped; below 0 until it has.
var _after: float = -1.0
var _kick: Dictionary = {}
var _kits: Array = []
var _names: Array = []
var _busy: bool = false

## The picker's squad, as GET /shootout/daily/takers sent it: idx -> player,
## the best-first order Auto-select fills with, and the order picked so far.
var _squad: Dictionary = {}
var _suggested: Array = []
var _picked: Array = []


func _ready() -> void:
	_left_button.pressed.connect(_on_side_pressed.bind(-1))
	_middle_button.pressed.connect(_on_side_pressed.bind(0))
	_right_button.pressed.connect(_on_side_pressed.bind(1))
	_continue_button.pressed.connect(_on_continue_pressed)
	_retry_button.pressed.connect(_on_retry_pressed)
	_takers_back_button.pressed.connect(_on_takers_back_pressed)
	_auto_select_button.pressed.connect(_on_auto_select_pressed)
	_send_button.pressed.connect(_on_send_pressed)

	_pitch.draw.connect(_draw_pitch)
	_pitch.resized.connect(_pitch.queue_redraw)
	AdManager.ad_reward_completed.connect(_on_ad_completed)

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()

	# Your own name needs no session, so the board carries it through the wait
	# for one rather than showing the scene's placeholder.
	_fit_name(_home_name_label, GameProfile.display_name_or_you())
	# A shootout already under way has its order locked in; a new one starts
	# with the player picking it.
	if ShootoutSession.resume:
		_start()
	else:
		_open_picker()


func _apply_theme_colors() -> void:
	var accent := ThemeManager.color("accent")
	for button in [_left_button, _middle_button, _right_button]:
		MenuTile.style_button(button, accent)
	MenuTile.style_button(_retry_button, ThemeManager.color("bucks"))
	MenuTile.style_button(_continue_button, ThemeManager.color("surface_border"))
	for panel in [_aim_panel, _result_panel]:
		panel.add_theme_stylebox_override(
			"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, accent, 2, true)
		)
	# The scoreboard wears the match's own frame, so a shootout reads as the
	# same game rather than a different screen. It sits in the top-left corner
	# and is sized by its contents -- the scene pins it to 1x1 and Godot grows
	# it to its minimum -- so both names fit whole.
	_scoreboard.add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, ThemeManager.color("surface_border"), 3, true, Vector2(0, 0))
	)
	for label in [_home_name_label, _away_name_label, _score_label]:
		label.add_theme_color_override("font_color", MenuTile.TITLE_COLOR)
	# The two below sit straight on the grass, so they carry their own contrast
	# rather than relying on a panel behind them.
	_aim_title.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	_status_label.add_theme_color_override("font_color", ThemeManager.color("warning"))

	# The picker covers the whole screen: a solid fill, not pixel_frame's
	# near-opaque one, which let the pitch and the aim panel ghost through.
	var backdrop := StyleBoxFlat.new()
	backdrop.bg_color = MenuTile.BASE_FILL
	_takers_panel.add_theme_stylebox_override("panel", backdrop)
	MenuTile.style_button(_takers_back_button, ThemeManager.color("surface_border"))
	MenuTile.style_button(_auto_select_button, accent)
	MenuTile.style_button(_send_button, ThemeManager.color("positive"), true)
	_takers_title.add_theme_color_override("font_color", MenuTile.TITLE_COLOR)
	for label in [_takers_hint, _order_title, _order_pen_title, _squad_title, _squad_pen_title, _takers_status]:
		label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	if _takers_panel.visible and not _squad.is_empty():
		_rebuild_picker()
	_pitch.queue_redraw()


func _process(delta: float) -> void:
	if _runup < 1.0:
		_runup = min(1.0, _runup + delta / RUNUP_SECONDS)
		_pitch.queue_redraw()
		return
	if _anim < 1.0:
		_anim = min(1.0, _anim + delta / _flight_seconds)
		if _anim >= 1.0 and not _kick.is_empty():
			_after = 0.0
		_pitch.queue_redraw()
		return
	if _after >= 0.0 and _after < _aftermath_seconds():
		_after = min(_aftermath_seconds(), _after + delta)
		_pitch.queue_redraw()


# -- the kick order ------------------------------------------------------------
#
# Before a new shootout the player orders their XI: tap a player on the right
# to put him next in the order on the left, tap a pick to take him back out.
# Send stays off until all eleven are placed; Auto-select fills whatever is
# left, best penalty taker first, without moving the picks already made.


func _open_picker() -> void:
	_takers_panel.visible = true
	_set_busy(true)
	# A retry reopens on the order just played, so it can go again as it is.
	_picked = ShootoutSession.takers.duplicate()
	if _squad.is_empty():
		_auto_select_button.disabled = true
		_send_button.disabled = true
		_takers_status.text = tr("Loading your squad...")
		if not _load_squad(await ShootoutSession.load_squad()):
			_takers_status.text = tr("Couldn't load your squad -- go back and try again.")
			return
	_picked = _picked.filter(func(idx) -> bool: return _squad.has(idx))
	_rebuild_picker()


## False when the response holds no squad to pick from.
func _load_squad(data: Dictionary) -> bool:
	var players = data.get("players", [])
	if not (players is Array) or players.is_empty():
		return false
	for entry in players:
		if entry is Dictionary:
			_squad[int(entry.get("idx", -1))] = entry
	var suggested = data.get("suggested", [])
	for idx in (suggested if suggested is Array else []):
		if _squad.has(int(idx)):
			_suggested.append(int(idx))
	# The engine's order is the backend's to send; an older one that did not
	# still leaves Auto-select something to fill with.
	for idx in _squad:
		if not _suggested.has(idx):
			_suggested.append(idx)
	return true


func _rebuild_picker() -> void:
	for list in [_order_list, _squad_list]:
		for child in list.get_children():
			list.remove_child(child)
			child.queue_free()

	# Every slot, filled or not, so the size of the job is visible up front.
	for slot in range(_squad.size()):
		if slot == REGULATION_KICKS:
			_order_list.add_child(_sudden_death_divider())
		var number := str(slot + 1)
		if slot < _picked.size():
			var idx: int = _picked[slot]
			_order_list.add_child(_taker_row(number, _squad[idx], _on_pick_pressed.bind(idx)))
		else:
			_order_list.add_child(_taker_row(number, {}, Callable()))

	# Whoever is still to place, best first -- the order Auto-select uses.
	for idx in _suggested:
		if not _picked.has(idx):
			_squad_list.add_child(_taker_row("", _squad[idx], _on_squad_pressed.bind(idx)))

	var complete := _picked.size() == _squad.size()
	_send_button.disabled = not complete
	_auto_select_button.disabled = complete
	_takers_status.text = (
		tr("All set -- send your order to start.") if complete
		else tr("%d of %d picked. Tap Auto-select to fill the rest, then Send.") % [
			_picked.size(), _squad.size()
		]
	)


## One row: the slot number (order list only), position, name and penalty
## score. An empty `player` is an open slot -- drawn, but not pressable.
func _taker_row(number: String, player: Dictionary, on_press: Callable) -> Button:
	var filled := not player.is_empty()
	var button := Button.new()
	# PASS, not a Button's default STOP, so a drag that starts on a row still
	# scrolls the list instead of being swallowed.
	button.mouse_filter = Control.MOUSE_FILTER_PASS
	button.custom_minimum_size = Vector2(0, TAKER_ROW_HEIGHT)
	button.disabled = not filled
	MenuTile.style_button(
		button,
		ThemeManager.color("accent") if filled else ThemeManager.color("surface_border"),
		false,
		Vector2(8, 4)
	)
	if filled:
		button.pressed.connect(on_press)

	var row := HBoxContainer.new()
	row.mouse_filter = Control.MOUSE_FILTER_IGNORE
	row.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	row.offset_left = 10
	row.offset_right = -10
	row.add_theme_constant_override("separation", 6)
	button.add_child(row)

	if number != "":
		row.add_child(_row_label(number, 22, ThemeManager.color("text_muted")))
	if not filled:
		var open_slot := _row_label("--", 0, ThemeManager.color("text_muted"))
		open_slot.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(open_slot)
		return button

	row.add_child(_row_label(str(player.get("position", "")), 28, ThemeManager.color("text_hint")))
	# Clipped on purpose here: the row is a fixed share of the screen, and a
	# long surname should shorten rather than push the score off the end.
	var name_label := _row_label(str(player.get("name", "")), 0, MenuTile.TITLE_COLOR)
	name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	name_label.clip_text = true
	name_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	row.add_child(name_label)
	var score := _row_label(str(int(player.get("score", 0))), 26, ThemeManager.color("positive"))
	score.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	row.add_child(score)
	return button


func _row_label(text: String, width: float, color: Color) -> Label:
	var label := Label.new()
	label.text = text
	label.custom_minimum_size = Vector2(width, 0)
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.add_theme_font_size_override("font_size", 13)
	label.add_theme_color_override("font_color", color)
	return label


func _sudden_death_divider() -> Label:
	var label := Label.new()
	label.text = tr("Sudden death")
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.add_theme_font_size_override("font_size", 11)
	label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	return label


# The rebuilds are deferred: they free the very row whose `pressed` is still
# being emitted, and a Button taken out of the tree mid-signal logs errors.
func _on_squad_pressed(idx: int) -> void:
	if _picked.has(idx) or _picked.size() >= _squad.size():
		return
	_picked.append(idx)
	_rebuild_picker.call_deferred()


func _on_pick_pressed(idx: int) -> void:
	_picked.erase(idx)
	_rebuild_picker.call_deferred()


## Fills every open slot, best penalty taker first. Picks already made stay
## exactly where the player put them.
func _on_auto_select_pressed() -> void:
	for idx in _suggested:
		if not _picked.has(idx):
			_picked.append(idx)
	_rebuild_picker()


func _on_send_pressed() -> void:
	if _squad.is_empty() or _picked.size() != _squad.size():
		return
	ShootoutSession.takers = _picked.duplicate()
	_takers_panel.visible = false
	_start()


func _on_takers_back_pressed() -> void:
	var destination := ShootoutSession.return_scene
	ShootoutSession.clear()
	get_tree().change_scene_to_file(destination)


# -- the session ---------------------------------------------------------------


func _start() -> void:
	_set_busy(true)
	var error: String = await ShootoutSession.start()
	if error != "":
		_status_label.text = error
		_show_result_panel(true)
		return
	_status_label.text = ""
	var kits = ShootoutSession.state.get("kits", [])
	_kits = kits if kits is Array else []
	_build_scoreboard()
	_refresh()


func _on_side_pressed(side: int) -> void:
	if _busy or ShootoutSession.is_finished():
		return
	_set_busy(true)
	var error: String = await ShootoutSession.kick(side)
	if error != "":
		_status_label.text = error
		_set_busy(false)
		return

	_kick = ShootoutSession.last_kick
	_runup = 0.0
	_anim = 0.0
	_after = -1.0
	_flight_seconds = _flight_time()
	_pitch.queue_redraw()
	
	await get_tree().create_timer(RUNUP_SECONDS + _flight_seconds).timeout
	_update_score()
	await get_tree().create_timer(_aftermath_seconds()).timeout
	_refresh()


func _aftermath_seconds() -> float:
	if _kick.get("scored", false):
		return CELEBRATION_SECONDS
	return DEJECTED_SECONDS + WALK_OFF_SECONDS


## The flight lasts as long as the distance takes at the speed the engine
## strikes it, so a ball blazed wide takes longer than one rolled in.
func _flight_time() -> float:
	var spot := Vector2(PITCH_WIDTH / 2.0, SPOT_Y)
	return max(0.25, spot.distance_to(_ball_stop()) / PENALTY_SHOT_SPEED)


func _refresh() -> void:
	_update_score()
	if ShootoutSession.is_finished():
		_show_result_panel()
		return

	# The scene resets between kicks, as the engine's _place_scene does: keeper
	# back on his line, ball back on the spot. Without this he stays lying
	# where he dived at the last one.
	_kick = {}
	_runup = 1.0
	_anim = 1.0
	_after = -1.0
	_pitch.queue_redraw()

	_set_busy(false)
	var mine := ShootoutSession.my_turn()
	# The banner can fall back to the other side's name; the label over the
	# figure never does -- it names the player or nobody.
	var taker: String = _upcoming_name()
	if taker == "":
		taker = _side_name(1, tr("They"))

	# Whose kick it is, said three times in three places, because getting this
	# wrong means the player aims when they meant to dive. The banner colour
	# carries it even before the words are read.
	_turn_label.text = tr("YOU SHOOT") if mine else tr("%s SHOOTS") % taker.to_upper()
	_turn_label.add_theme_color_override(
		"font_color", ThemeManager.color("positive" if mine else "warning")
	)
	_aim_title.text = tr("YOUR AIM") if mine else tr("YOUR DIVE")


## Names, kits and the running total. Built once a session exists, since the
## bot's name and both kits arrive with it.
func _build_scoreboard() -> void:
	var state := ShootoutSession.state
	var names = state.get("names", [])
	_names = names if names is Array else []
	_fit_name(_home_name_label, _side_name(0, GameProfile.display_name_or_you()))
	_fit_name(_away_name_label, _side_name(1, str(state.get("bot_name", ""))))
	_home_swatch.set_design(_kit_for(0))
	_away_swatch.set_design(_kit_for(1))
	for row in [_home_marks, _away_marks]:
		for child in row.get_children():
			child.queue_free()
	_update_score()


## A name, trimmed to what its half of the board can hold. Measured in pixels
## rather than characters because sixteen W's are twice the width of sixteen
## i's, and the panel is as wide as whatever it is handed.
func _fit_name(label: Label, value: String) -> void:
	var budget := get_viewport_rect().size.x * NAME_WIDTH_SHARE
	var font := label.get_theme_font("font")
	var font_size := label.get_theme_font_size("font_size")
	var text := value
	while (
		text.length() > 1
		and font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x > budget
	):
		text = text.left(text.length() - 2) + "."
	label.text = text


func _side_name(team: int, fallback: String) -> String:
	if _names.size() == 2 and _names[team] is String and _names[team] != "":
		return _names[team]
	return fallback


func _update_score() -> void:
	var score := ShootoutSession.score()
	_score_label.text = "%d - %d" % [int(score[0]), int(score[1])]
	_rebuild_marks(_home_marks, 0)
	_rebuild_marks(_away_marks, 1)


## One mark per kick: O for scored, X for missed, a dim dot for a kick not yet
## taken. Only MARK_SLOTS fit, so past five the oldest scroll off -- in sudden
## death the board shows the last five rounds rather than the first five.
func _rebuild_marks(row: HBoxContainer, team: int) -> void:
	var taken: Array = []
	for kick in ShootoutSession.kicks():
		if int(kick.get("team", 0)) == team:
			taken.append(bool(kick.get("scored", false)))
	var shown: Array = taken.slice(max(0, taken.size() - MARK_SLOTS))

	# Reuse the labels rather than rebuilding the row every kick: a queue_free
	# is deferred, so rebuilding leaves the old ones on screen for a frame.
	while row.get_child_count() < MARK_SLOTS:
		var label := Label.new()
		label.add_theme_font_size_override("font_size", 16)
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		label.custom_minimum_size = Vector2(16, 0)
		row.add_child(label)

	for slot in range(MARK_SLOTS):
		var label: Label = row.get_child(slot)
		if slot < shown.size():
			label.text = MARK_SCORED if shown[slot] else MARK_MISSED
			label.add_theme_color_override(
				"font_color",
				ThemeManager.color("positive") if shown[slot] else ThemeManager.color("warning")
			)
		else:
			label.text = MARK_EMPTY
			label.add_theme_color_override("font_color", ThemeManager.color("text_muted"))


## Whoever is about to kick, named, or "" when the backend did not say --
## before the first kick there is no history to read it from.
func _upcoming_name() -> String:
	return str(ShootoutSession.upcoming().get("taker_name", ""))


## The taker's look, for his own celebration. From the kick once it is taken,
## from `upcoming` before; {} is PlayerFigure's documented default.
func _taker_appearance() -> Dictionary:
	var source := _kick if not _kick.is_empty() else ShootoutSession.upcoming()
	var look = source.get("taker_appearance", {})
	return look if look is Dictionary else {}


func _kick_verdict(kick: Dictionary) -> String:
	if kick.is_empty():
		return ""
	var mine := int(kick.get("team", 0)) == 0
	if kick.get("scored", false):
		return tr("Scored!") if mine else tr("They scored.")
	if kick.get("saved", false):
		return tr("Saved!") if not mine else tr("Keeper got it.")
	return tr("Wide!") if mine else tr("They missed.")


# -- the end screen ------------------------------------------------------------


func _show_result_panel(finished_early: bool = false) -> void:
	_set_busy(true)
	_aim_panel.visible = false
	_result_stack.visible = true

	if finished_early:
		_result_label.text = tr("Not today")
		_reward_label.text = ""
		_retry_button.visible = false
		return

	var state := ShootoutSession.state
	var won := ShootoutSession.won()
	_result_label.text = tr("You won!") if won else tr("You lost")
	_result_label.add_theme_color_override(
		"font_color", ThemeManager.color("positive" if won else "warning")
	)
	_reward_label.text = _rewards_line(state)

	# Under the popup, on every platform -- the shop's ad buttons show
	# everywhere too, and off iOS AdManager walks the flow through to
	# "pending". Whether an ad would buy anything is the server's call: not
	# after a win, and not once today's retry ad is spent.
	_retry_button.visible = not won and bool(state.get("retry_available", not won))


func _rewards_line(state: Dictionary) -> String:
	var rewards = state.get("rewards", {})
	var parts: Array[String] = []
	if rewards is Dictionary:
		for currency in rewards:
			var amount := int(rewards[currency])
			if amount > 0:
				parts.append("+%s %s" % [
					CurrencyDisplay.format_amount(amount),
					CurrencyDisplay.lowercase_label_for(currency),
				])
	var line := " ".join(parts) if not parts.is_empty() else tr("No reward this time.")
	if state.get("prestiged", false):
		line += "\n" + tr("Cycle complete -- prestige %d!") % int(state.get("prestige", 1))
	return line


func _on_retry_pressed() -> void:
	_retry_button.disabled = true
	_status_label.text = ""
	if not AdManager.show_ad_for_track(ShootoutSession.RETRY_TRACK):
		_status_label.text = tr("Ad not ready -- try again in a moment.")
		_retry_button.disabled = false


## AdManager's signal is global, so the track has to be checked -- the shop's
## currency panel listens to the same one.
func _on_ad_completed(track: String, status: String) -> void:
	if track != ShootoutSession.RETRY_TRACK:
		return
	match status:
		"granted":
			_status_label.text = ""
			_reset_for_retry()
		"pending":
			_status_label.text = tr("Reward is on its way -- it lands within a minute.")
			_retry_button.disabled = false
		_:
			_status_label.text = tr("Ad was closed early or failed to verify.")
			_retry_button.disabled = false


func _reset_for_retry() -> void:
	_result_stack.visible = false
	_retry_button.disabled = false
	_aim_panel.visible = true
	_kick = {}
	_runup = 1.0
	_anim = 1.0
	_after = -1.0
	_pitch.queue_redraw()
	# A retry is a new shootout, so it gets the picker too -- pre-filled with
	# the order just played.
	_open_picker()


## No reload: the final kick's balances are already in GameProfile (see
## ShootoutSession._apply_rewards), and a shootout touches nothing else.
func _on_continue_pressed() -> void:
	var destination := ShootoutSession.return_scene
	ShootoutSession.clear()
	get_tree().change_scene_to_file(destination)


func _set_busy(value: bool) -> void:
	_busy = value
	for button in [_left_button, _middle_button, _right_button]:
		button.disabled = value


# -- the picture ---------------------------------------------------------------


func _draw_pitch() -> void:
	var box := _pitch.size
	if box.x <= 0.0 or box.y <= 0.0:
		return
	var cam := PitchDraw.camera_for_span(box, PITCH_WIDTH / 2.0, FRAME_Y_SPAN, FRAME_TOP_Y)
	PitchDraw.draw_pitch(_pitch, cam, box)

	var scale: float = cam.scale
	var height_px: float = FIGURE_HEIGHT_UNITS * scale
	var font: Font = ThemeDB.fallback_font

	# The penalty spot: a painted mark, drawn the size the centre spot is. Any
	# bigger and it reads as a second ball sitting behind the one in flight.
	var spot := Vector2(PITCH_WIDTH / 2.0, SPOT_Y)
	_pitch.draw_circle(PitchDraw.to_screen(spot, cam), 2.0, PitchDraw.LINE_COLOR)

	# Back to front: the taker stands further UP the screen than the keeper, so
	# he is drawn first and the keeper over him -- the same depth order the
	# match sorts its 22 figures into.
	var taker_pos := _taker_pos()
	_draw_figure(
		taker_pos, cam, height_px, _taking_team(), false, _taker_pose(), font,
		_taker_appearance(), _taker_facing(), _taker_phase()
	)
	_draw_taker_name(taker_pos, cam, height_px, font)

	var keeper_pos := Vector2(_keeper_x(), SHOOTOUT_GOAL_Y)
	_draw_figure(
		keeper_pos, cam, height_px, _defending_team(), true, _keeper_pose(), font,
		{}, PlayerFigure.FACING_N, 0.0
	)

	_draw_ball(cam)


## The taker faces the viewer (he shoots toward +y, down the screen) and the
## keeper looks back up the pitch at him. Only the taker's look is sent;
## the keeper draws from {}, PlayerFigure's documented default.
func _draw_figure(
	pitch_pos: Vector2, cam: Dictionary, height_px: float, team: int,
	is_keeper: bool, pose: String, font: Font,
	appearance: Dictionary, facing: int, phase: float
) -> void:
	PlayerFigure.draw_into(
		_pitch,
		PitchDraw.to_screen(pitch_pos, cam),
		height_px,
		appearance,
		_keeper_kit_for(team) if is_keeper else _kit_for(team),
		facing,
		pose,
		PlayerFigure.DETAIL_FULL if height_px >= 26.0 else PlayerFigure.DETAIL_LOW,
		phase,
		0,
		Color(0, 0, 0, 0),
		font,
		is_keeper
	)


## Both shirts as the backend sent them, caller first. A missing kit falls
## back to a plain colour rather than no figure at all.
func _kit_for(team: int) -> KitDesign:
	if _kits.size() == 2 and _kits[team] is String and _kits[team] != "":
		return KitDesign.parse(_kits[team])
	var fallback := ThemeManager.color("accent") if team == 0 else KEEPER_COLOR_FALLBACK
	return KitDesign.create(KitDesign.PATTERN_SOLID, fallback.to_html(false), Color.WHITE.to_html(false))


## The keeper's own shirt, changed if it would blend into the taker's.
func _keeper_kit_for(team: int) -> KitDesign:
	return _kit_for(team).keeper().avoiding([_kit_for(1 - team).primary_color()])


## Which side is taking this kick, and which is keeping. Before the first
## kick the session says whose turn it is; during one, the kick itself does.
func _taking_team() -> int:
	if not _kick.is_empty():
		return int(_kick.get("team", 0))
	return 0 if ShootoutSession.my_turn() else 1


func _defending_team() -> int:
	return 1 - _taking_team()


## Where the taker is this frame: standing off before the whistle, running in
## over the run-up, planted beside the ball once he has struck it -- then off
## on his celebration, or walking back toward halfway.
func _taker_pos() -> Vector2:
	var standing := Vector2(PITCH_WIDTH / 2.0, SPOT_Y - ATTACK_DIR * TAKER_STANDOFF)
	if _kick.is_empty():
		return standing
	var planted := Vector2(PITCH_WIDTH / 2.0, SPOT_Y - ATTACK_DIR * RUNUP_FINISH_UNITS)
	if _after < 0.0:
		return standing.lerp(planted, _ease_out(_runup))
	if _kick.get("scored", false):
		return planted + _celebration_direction() * _celebration_run()
	var walked := maxf(0.0, _after - DEJECTED_SECONDS) * WALK_OFF_SPEED
	return planted - Vector2(0.0, ATTACK_DIR * walked)


## How far the celebration has carried him: the match's timeline at the
## match's speed, scaled down only if it would leave the frame.
func _celebration_run() -> float:
	var recipe := _celebration_recipe()
	var full: float = PlayerFigure.celebration_state(recipe, CELEBRATION_SECONDS).travel
	var now: float = PlayerFigure.celebration_state(recipe, _after).travel
	if full <= 0.0:
		return 0.0
	return now * CELEBRATION_RUN_SPEED * minf(1.0, CELEBRATION_MAX_RUN / (full * CELEBRATION_RUN_SPEED))


## Toward the corner flag on the side he put it, as a match scorer heads for
## the nearer one.
func _celebration_direction() -> Vector2:
	var side := -1.0 if int(_kick.get("aim", 0)) < 0 else 1.0
	return Vector2(side, ATTACK_DIR * CELEBRATION_RUN_BACK).normalized()


func _celebration_recipe() -> Dictionary:
	return PlayerAppearance.celebration(int(_taker_appearance().get("celebration", 0)))


## Eases in so the last stride is the slow one, which is where the strike
## lands -- a linear run-up arrives at full pelt and stops dead.
func _ease_out(t: float) -> float:
	var x: float = clampf(t, 0.0, 1.0)
	return 1.0 - (1.0 - x) * (1.0 - x)


func _taker_pose() -> String:
	if _kick.is_empty():
		return PlayerFigure.POSE_IDLE
	if _runup < 1.0:
		return PlayerFigure.POSE_RUN
	if _after < 0.0:
		# Struck the moment the flight starts, then stood watching it.
		return PlayerFigure.POSE_KICK if _anim < 0.35 else PlayerFigure.POSE_IDLE
	if _kick.get("scored", false):
		return PlayerFigure.POSE_CELEBRATE
	return PlayerFigure.POSE_DEJECTED if _after < DEJECTED_SECONDS else PlayerFigure.POSE_RUN


## POSE_RUN's leg cycle, or for a celebration the seconds since the goal --
## the clock PlayerFigure runs a celebration timeline on.
func _taker_phase() -> float:
	if _kick.is_empty():
		return 0.0
	if _runup < 1.0:
		return _runup * RUNUP_SECONDS * RUN_CYCLE
	if _after < 0.0:
		return 0.0
	if _kick.get("scored", false):
		return _after
	return maxf(0.0, _after - DEJECTED_SECONDS) * WALK_CYCLE


## Toward the viewer, except while running off: along the celebration's run,
## as a match scorer does, or away up the pitch on the walk back.
func _taker_facing() -> int:
	if _after < 0.0 or _kick.is_empty():
		return PlayerFigure.FACING_S
	if _kick.get("scored", false):
		var stage: String = PlayerFigure.celebration_state(_celebration_recipe(), _after).stage
		if stage in [PlayerFigure.STAGE_RUN, PlayerFigure.STAGE_JUMP]:
			return PlayerFigure.facing_from_direction(_celebration_direction())
		return PlayerFigure.FACING_S
	return PlayerFigure.FACING_S if _after < DEJECTED_SECONDS else PlayerFigure.FACING_N


## The taker's name over his head, the way the match labels whoever has the
## ball. Drawn with its own shadow: the pitch underneath is busy and moving,
## and AppTheme's Label shadow does not reach raw canvas drawing.
func _draw_taker_name(pitch_pos: Vector2, cam: Dictionary, height_px: float, font: Font) -> void:
	var taker: String = (
		str(_kick.get("taker_name", "")) if not _kick.is_empty() else _upcoming_name()
	)
	if taker == "":
		return
	var at := PitchDraw.to_screen(pitch_pos, cam) + Vector2(-60.0, -height_px - 8.0)
	_pitch.draw_string(
		font, at + Vector2(2, 2), taker, HORIZONTAL_ALIGNMENT_CENTER, 120, 13,
		Color(0, 0, 0, 0.8)
	)
	_pitch.draw_string(font, at, taker, HORIZONTAL_ALIGNMENT_CENTER, 120, 13, Color.WHITE)


func _keeper_pose() -> String:
	if _kick.is_empty() or _runup < 1.0 or _anim <= 0.0:
		return PlayerFigure.POSE_IDLE
	# A dive to a corner is a lunge; a keeper staying central just reaches.
	return PlayerFigure.POSE_IDLE if int(_kick.get("dive", 0)) == 0 else PlayerFigure.POSE_LUNGE


## Where the keeper ends up: the corner he picked, KEEPER_REACH * the dive
## fraction from the middle -- the engine's own reach, so the same dive
## carries the same distance here as it does in a match.
func _keeper_x() -> float:
	if _runup < 1.0:
		return PITCH_WIDTH / 2.0     # he holds his line until it is struck
	var committed: float = min(1.0, _anim / DIVE_COMMIT_FRACTION)
	return lerpf(PITCH_WIDTH / 2.0, _dive_x(), committed)


## Where the resolved kick put the ball. Mirrors minigamesEngine._animate_kick
## exactly: inside the frame on target, outside the near post when not, and
## dead at the keeper on a save.
func _ball_stop() -> Vector2:
	if _kick.is_empty():
		return Vector2(PITCH_WIDTH / 2.0, SPOT_Y)

	var aim := float(int(_kick.get("aim", 0)))
	var on_target: bool = _kick.get("on_target", true)
	var scored: bool = _kick.get("scored", false)
	var saved: bool = _kick.get("saved", false)

	var target_x := PITCH_WIDTH / 2.0 + aim * (GOAL_WIDTH / 2.0 - 0.6)
	if not on_target:
		target_x += (GOAL_WIDTH * 0.8) * (1.0 if aim >= 0.0 else -1.0)

	if saved:
		# It dies at the keeper, SHORT of the line -- it never crosses.
		return Vector2(_dive_x(), SHOOTOUT_GOAL_Y - ATTACK_DIR * SAVE_STOP_DEPTH)
	if scored:
		return Vector2(target_x, SHOOTOUT_GOAL_Y + ATTACK_DIR * GOAL_STOP_DEPTH)
	return Vector2(target_x, SHOOTOUT_GOAL_Y)


## Where the keeper's dive lands him, full stretch.
func _dive_x() -> float:
	var dive := float(int(_kick.get("dive", 0))) if not _kick.is_empty() else 0.0
	return PITCH_WIDTH / 2.0 + dive * KEEPER_REACH * KEEPER_DIVE_FRACTION


func _draw_ball(cam: Dictionary) -> void:
	var scale: float = cam.scale
	var spot := Vector2(PITCH_WIDTH / 2.0, SPOT_Y)
	# Still on the spot until the run-up finishes: a ball that leaves before
	# the boot arrives reads as nobody having kicked it.
	var ball := spot if _runup < 1.0 else spot.lerp(_ball_stop(), _anim)
	var centre := PitchDraw.to_screen(ball, cam)
	var radius: float = maxf(3.0, BALL_RADIUS_UNITS * scale)
	# Outlined, like the match ball -- white on white netting vanishes.
	_pitch.draw_circle(centre, radius, Color.BLACK)
	_pitch.draw_circle(centre, radius * 0.8, Color.WHITE)
