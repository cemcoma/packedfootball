extends Control

## Squad management: pick a formation, tap a pitch slot to view that
## player's stats or (via "Replace") swap them for an eligible bench card,
## and save.
##
## The static structure (formation buttons, panel layout, bench grid,
## stats panel, bottom row) lives in the companion Team.tscn -- open it in
## the editor to rearrange/restyle. This script only connects signals and
## repopulates the genuinely dynamic parts: the bench/picker card grid
## (however many cards are eligible) and the pitch's slot markers (count
## and position depend on the chosen formation) -- neither can be static
## content, regardless of whether this were a .tscn or not. PlayerCardView
## instances are loaded from PlayerCardView.tscn via PLAYER_CARD_SCENE
## rather than PlayerCardView.new(), since that script expects the child
## nodes its .tscn defines (a bare .new() would have none of them).
##
## Data flow unchanged from before: all squad state (formation,
## slot_assignment, all_cards) lives in the GameProfile autoload, fetched
## once at login (see Auth.gd). This scene only owns pure view state: which
## slot is focused, whether we're picking a replacement, and the
## save-status message.

const PLAYER_CARD_SCENE := preload("res://scenes/PlayerCardView.tscn")

const ATTR_ROWS := [
	["Stamina", "stamina"], ["Speed", "speed"], ["Agility", "agility"], ["Passing", "passing"],
	["Ball Ctrl", "ballcontrol"], ["Defending", "defending"], ["Tackling", "tackling"], ["Dribbling", "dribbiling"],
	["Shooting", "shooting"], ["Power", "power"], ["Accuracy", "accuracy"], ["Vision", "vision"],
]

var selected_slot: int = -1  # -1 = nothing focused
var picker_mode: bool = false  # only meaningful when selected_slot != -1
var status_text: String = ""

var _formation_buttons: Dictionary = {}  # name -> Button

@onready var _formation_button_442: Button = %FormationButton442
@onready var _formation_button_433: Button = %FormationButton433
@onready var _formation_button_352: Button = %FormationButton352
@onready var _formation_button_4231: Button = %FormationButton4231

@onready var _pitch_view: PitchView = %Pitch
@onready var _panel_header: Label = %PanelHeader
@onready var _bench_scroll: ScrollContainer = %BenchScroll
@onready var _bench_grid: GridContainer = %BenchGrid
@onready var _cancel_button: Button = %CancelButton
@onready var _stats_panel: VBoxContainer = %StatsPanel
@onready var _stats_card_view: PlayerCardView = %StatsCard
@onready var _stats_attr_grid: GridContainer = %StatsAttrGrid
@onready var _stats_extra_label: Label = %StatsExtraLabel
@onready var _replace_button: Button = %ReplaceButton
@onready var _clear_button: Button = %ClearButton
@onready var _close_button: Button = %CloseButton
@onready var _status_label: Label = %StatusLabel
@onready var _save_button: Button = %SaveButton
@onready var _back_button: Button = %BackButton


func _ready() -> void:
	_formation_buttons = {
		"4-4-2": _formation_button_442,
		"4-3-3": _formation_button_433,
		"3-5-2": _formation_button_352,
		"4-2-3-1": _formation_button_4231,
	}
	for formation_name in _formation_buttons.keys():
		var button: Button = _formation_buttons[formation_name]
		button.pressed.connect(_on_formation_button_pressed.bind(formation_name))

	_pitch_view.slot_pressed.connect(_on_slot_tapped)
	_cancel_button.pressed.connect(_on_cancel_picker_pressed)
	_replace_button.pressed.connect(_on_replace_pressed)
	_clear_button.pressed.connect(_on_clear_pressed)
	_close_button.pressed.connect(_on_close_stats_pressed)
	_save_button.pressed.connect(_on_save_pressed)
	_back_button.pressed.connect(_on_back_pressed)

	_refresh_all()


# -- state -> UI --------------------------------------------------------------


func _refresh_all() -> void:
	_refresh_formation_buttons()
	_refresh_pitch()
	_refresh_right_panel()
	_refresh_bottom()


func _refresh_formation_buttons() -> void:
	for formation_name in _formation_buttons.keys():
		var button: Button = _formation_buttons[formation_name]
		button.button_pressed = (formation_name == GameProfile.formation)


func _refresh_pitch() -> void:
	var slots := Formations.get_formation(GameProfile.formation)
	_pitch_view.set_formation(slots, GameProfile.slot_assignment, GameProfile.all_cards, selected_slot)


func _refresh_right_panel() -> void:
	var showing_stats: bool = selected_slot != -1 and not picker_mode
	var showing_picker: bool = selected_slot != -1 and picker_mode

	_stats_panel.visible = showing_stats
	_bench_scroll.visible = not showing_stats
	_cancel_button.visible = showing_picker

	if showing_stats:
		_panel_header.text = "Player"
		_populate_stats_panel()
	elif showing_picker:
		var slots := Formations.get_formation(GameProfile.formation)
		var role: String = slots[selected_slot]["role"]
		_panel_header.text = "Pick a %s:" % role
		_populate_bench_grid(_eligible_bench_ids(role))
	else:
		_panel_header.text = "Bench (tap a slot to assign)"
		_populate_bench_grid(_sorted_bench_ids(GameProfile.bench_ids()))


func _sorted_bench_ids(ids: Array) -> Array:
	var sorted_ids: Array = ids.duplicate()
	sorted_ids.sort_custom(func(a, b): return GameProfile.all_cards[a].overall() > GameProfile.all_cards[b].overall())
	return sorted_ids


func _eligible_bench_ids(role: String) -> Array:
	var matching: Array = []
	for player_id in GameProfile.bench_ids():
		var card: PlayerCard = GameProfile.all_cards[player_id]
		if card.position == role:
			matching.append(player_id)
	return _sorted_bench_ids(matching)


func _populate_bench_grid(ids: Array) -> void:
	# This can run from inside a card view's own "pressed" signal (tapping a
	# bench card -> _on_card_view_pressed -> _refresh_all() -> here), so the
	# old views can't be torn down with plain free() -- that's only safe once
	# their own signal has finished dispatching. remove_child() detaches them
	# immediately (so a same-frame add_child() below never sees a stale
	# leftover child), then queue_free() defers the actual deallocation.
	for child in _bench_grid.get_children():
		_bench_grid.remove_child(child)
		child.queue_free()

	if ids.is_empty():
		var empty_label := Label.new()
		empty_label.text = "No eligible players." if (selected_slot != -1 and picker_mode) else "No bench players."
		_bench_grid.add_child(empty_label)
		return

	for player_id in ids:
		var card: PlayerCard = GameProfile.all_cards[player_id]
		var view: PlayerCardView = PLAYER_CARD_SCENE.instantiate()
		_bench_grid.add_child(view)
		view.set_card(card)
		view.pressed.connect(_on_card_view_pressed.bind(player_id))


func _populate_stats_panel() -> void:
	var player_id: String = GameProfile.slot_assignment[selected_slot]
	var card: PlayerCard = GameProfile.all_cards[player_id]
	_stats_card_view.set_card(card)

	for child in _stats_attr_grid.get_children():
		_stats_attr_grid.remove_child(child)
		child.queue_free()
	for row in ATTR_ROWS:
		var label_name: String = row[0]
		var key: String = row[1]
		var value: int = card.attributes.get(key, 0)
		var name_label := Label.new()
		name_label.text = label_name
		_stats_attr_grid.add_child(name_label)
		var value_label := Label.new()
		value_label.text = str(value)
		_stats_attr_grid.add_child(value_label)

	var goals: int = card.statistics.get("goals", 0)
	var assists: int = card.statistics.get("assists", 0)
	var matches: int = card.statistics.get("matches_played", 0)
	_stats_extra_label.text = "Goals: %d   Assists: %d   Matches: %d\n%s  -  %s" % [
		goals, assists, matches, card.country, card.hometown
	]


func _refresh_bottom() -> void:
	var dirty: bool = GameProfile.is_dirty()
	var message := status_text
	if (status_text == "" or status_text == "Saved!") and dirty:
		message = "Unsaved changes"
	_status_label.text = message
	_status_label.add_theme_color_override("font_color", Color(1.0, 0.7, 0.3) if dirty else Color(0.6, 1.0, 0.6))
	_save_button.text = "Save Team*" if dirty else "Save Team"


# -- input handlers -----------------------------------------------------------


func _on_formation_button_pressed(formation_name: String) -> void:
	if formation_name == GameProfile.formation:
		_refresh_formation_buttons()  # keep the active one looking pressed
		return
	GameProfile.switch_formation(formation_name)
	selected_slot = -1
	picker_mode = false
	status_text = ""
	_refresh_all()


func _on_slot_tapped(i: int) -> void:
	if selected_slot == i:
		selected_slot = -1
		picker_mode = false
	else:
		selected_slot = i
		# Nothing to show stats for on an empty slot -- go straight to picking.
		picker_mode = (GameProfile.slot_assignment[i] == "")
	_refresh_all()


func _on_replace_pressed() -> void:
	picker_mode = true
	_refresh_all()


func _on_clear_pressed() -> void:
	GameProfile.slot_assignment[selected_slot] = ""
	selected_slot = -1
	picker_mode = false
	_refresh_all()


func _on_cancel_picker_pressed() -> void:
	# If the slot being replaced already had a player, fall back to viewing
	# their stats instead of fully deselecting.
	if selected_slot != -1 and GameProfile.slot_assignment[selected_slot] != "":
		picker_mode = false
	else:
		selected_slot = -1
		picker_mode = false
	_refresh_all()


func _on_close_stats_pressed() -> void:
	selected_slot = -1
	picker_mode = false
	_refresh_all()


func _on_card_view_pressed(player_id: String) -> void:
	if selected_slot == -1 or not picker_mode:
		return  # browsing only -- tapping does nothing
	var slots := Formations.get_formation(GameProfile.formation)
	var role: String = slots[selected_slot]["role"]
	var card: PlayerCard = GameProfile.all_cards[player_id]
	if card.position != role:
		return  # shouldn't happen (list is already role-filtered), but stay safe
	GameProfile.slot_assignment[selected_slot] = player_id
	selected_slot = -1
	picker_mode = false
	_refresh_all()


func _on_save_pressed() -> void:
	for player_id in GameProfile.slot_assignment:
		if player_id == "":
			status_text = "Fill every slot before saving."
			_refresh_bottom()
			return

	status_text = "Saving..."
	_refresh_bottom()

	var ok: bool = await GameProfile.save_team()
	status_text = "Saved!" if ok else "Save failed -- try again."
	_refresh_all()


func _on_back_pressed() -> void:
	if GameProfile.is_dirty():
		GameProfile.discard_changes()
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")
