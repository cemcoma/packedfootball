class_name PitchView
extends Control

## Draws the pitch (grass + line markings, still custom _draw() -- that
## part is inherently a custom visual, not something Control nodes model
## well) and overlays one real, tappable Button per formation slot,
## replacing hand-tested Rect2/circle hit-testing with genuine Button
## press/hover feedback. Formation coordinates come from Formations.gd
## (pitch-space units); this class only handles the pitch-space ->
## local-pixel mapping and the visual/interactive side.
##
## The companion PitchView.tscn just sets this script + a minimum size --
## there's no other static content to author there, since every slot marker's
## count and position depends on the currently-chosen formation and has to be
## built at runtime regardless of whether this were a .tscn or not.
##
## Everything is mapped from the node's CURRENT size, not a fixed box: the
## pitch used to draw at a hardcoded 280x400 whatever it was given, so a
## layout that handed it less silently clipped the goal line off the bottom.

signal slot_pressed(index: int)

const PITCH_WIDTH := 70.0
const HALF_HEIGHT := 50.0  # only y in [0, 50] (the player's own half) ever has slots
const MARKER_SIZE := Vector2(48.0, 48.0)

## Below this the pitch has no useful area to map into -- skip the pass
## rather than divide by it.
const MIN_DRAW := 8.0

var _slot_buttons: Array = []

# The last formation handed to set_formation, replayed whenever the node is
# resized -- marker positions are pixels, so they don't survive a resize.
var _slots: Array = []
var _slot_assignment: Array = []
var _all_cards: Dictionary = {}
var _selected_index: int = -1


func _ready() -> void:
	resized.connect(_rebuild)


## Pitch units -> pixels, against whatever size the layout has given us. The y
## axis is deliberately stretched more than x: only the player's own half is
## drawn, and it fills the taller box end to end.
func _scale() -> Vector2:
	return Vector2(size.x / PITCH_WIDTH, size.y / HALF_HEIGHT)


func _pitch_to_local(p: Vector2) -> Vector2:
	var s := _scale()
	return Vector2(p.x * s.x, size.y - p.y * s.y)


## Rebuilds the 11 slot markers for the given formation. `slots` is
## Formations.get_formation(name)'s return (Array of {"pos", "role"});
## `slot_assignment` is GameProfile.slot_assignment (player_ids, "" where
## empty); `all_cards` is GameProfile.all_cards; `selected_index` highlights
## that slot's marker (-1 for none).
func set_formation(slots: Array, slot_assignment: Array, all_cards: Dictionary, selected_index: int) -> void:
	_slots = slots
	_slot_assignment = slot_assignment
	_all_cards = all_cards
	_selected_index = selected_index
	_rebuild()


func _rebuild() -> void:
	if size.x < MIN_DRAW or size.y < MIN_DRAW:
		return
	# This routinely runs from inside a slot button's own "pressed" signal
	# (tapping a slot -> _on_slot_button_pressed -> slot_pressed.emit() ->
	# Team.gd's handler -> back here), so the old buttons can't be torn down
	# with plain free() -- only queue_free() is safe while their own signal
	# is still dispatching. remove_child() first detaches them immediately,
	# so nothing stale lingers as a child before the new buttons are added.
	for button in _slot_buttons:
		remove_child(button)
		button.queue_free()
	_slot_buttons.clear()

	for i in range(_slots.size()):
		var slot_pos: Vector2 = _slots[i]["pos"]
		var role: String = _slots[i]["role"]
		var player_id: String = _slot_assignment[i]

		var bg_color := Color(0.4, 0.4, 0.4, 0.6)
		var label_text := role
		# Not is_similar_position() -- an assigned card whose position isn't
		# the slot's role is out of position regardless of *why* that's
		# allowed; Formations.gd's compatibility table only ever gates
		# whether an assignment is allowed in the first place (see Team.gd),
		# not whether to show this warning.
		var out_of_position := false
		if player_id != "":
			var card: PlayerCard = _all_cards[player_id]
			bg_color = PlayerCard.tier_color(card.tier)
			out_of_position = card.position != role
			label_text = "%s\n%s" % [role, card.display_name()]

		var button := Button.new()
		button.custom_minimum_size = MARKER_SIZE
		button.size = MARKER_SIZE
		var center := _pitch_to_local(slot_pos)
		button.position = center - MARKER_SIZE / 2.0
		button.text = label_text
		button.clip_text = true
		button.add_theme_font_size_override("font_size", 11)

		var style := StyleBoxFlat.new()
		style.bg_color = bg_color
		style.set_corner_radius_all(int(MARKER_SIZE.x / 2.0))
		if i == _selected_index:
			style.set_border_width_all(3)
			style.border_color = Color(1.0, 0.9, 0.2)
		elif out_of_position:
			style.set_border_width_all(1)
			style.border_color = Color(1.0, 0.7, 0.3)  # same amber as Team.gd's "unsaved changes"
		button.add_theme_stylebox_override("normal", style)
		button.add_theme_stylebox_override("hover", style)
		button.add_theme_stylebox_override("pressed", style)
		button.add_theme_stylebox_override("focus", style)

		button.pressed.connect(_on_slot_button_pressed.bind(i))

		add_child(button)
		_slot_buttons.append(button)

	queue_redraw()


func _on_slot_button_pressed(index: int) -> void:
	slot_pressed.emit(index)


func _draw() -> void:
	var line_color := Color(1.0, 1.0, 1.0, 0.9)
	var line_width := 1.5
	var s := _scale()
	var rect := Rect2(Vector2.ZERO, size)

	draw_rect(rect, Color(0.09, 0.47, 0.22))
	# The same hard dark edge the panels wear, so the pitch reads as one of them.
	draw_rect(Rect2(Vector2(1.5, 1.5), size - Vector2(3.0, 3.0)), MenuTile.BASE_FILL, false, 3.0)
	draw_rect(rect, line_color, false, line_width)

	# The halfway line (pitch y=HALF_HEIGHT) lands exactly on this box's own
	# top edge -- already drawn by the outline above -- since the whole
	# half-pitch is stretched to fill the box end to end. Only the center
	# circle's near half still needs drawing, dipping down from that edge.
	var center_spot := _pitch_to_local(Vector2(PITCH_WIDTH / 2.0, HALF_HEIGHT))
	var arc_radius := 9.15 * (s.x + s.y) / 2.0  # a circle can't follow two different axis scales at once
	draw_arc(center_spot, arc_radius, 0.0, PI, 32, line_color, line_width)

	var penalty_top_left := _pitch_to_local(Vector2(14.0, 18.0))
	var penalty_size := Vector2(42.0 * s.x, 18.0 * s.y)
	draw_rect(Rect2(penalty_top_left, penalty_size), line_color, false, line_width)
	var six_yard_top_left := _pitch_to_local(Vector2(26.0, 5.5))
	var six_yard_size := Vector2(18.0 * s.x, 5.5 * s.y)
	draw_rect(Rect2(six_yard_top_left, six_yard_size), line_color, false, line_width)

	var goal_left := _pitch_to_local(Vector2(31.25, 0.0))
	var goal_right := _pitch_to_local(Vector2(38.75, 0.0))
	draw_line(goal_left, goal_right, Color.WHITE, 4.0)
