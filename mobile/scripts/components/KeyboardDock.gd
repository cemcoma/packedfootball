class_name KeyboardDock
extends Node

## Slides `slide` up so the form being typed into sits at the top of the
## screen, clear of the on-screen keyboard. Docking follows whether a field is
## being edited, not the keyboard's reported height: that height drops to 0 and
## changes size as focus moves between fields.

## Where the focused field's panel docks, measured from the top of the screen.
const DOCK_TOP := 12.0
## Gap kept between the focused field and the keyboard.
const CLEARANCE := 16.0
const SLIDE_SEC := 0.18
## Grace before undocking, so a focus hand-off never reads as "done typing".
const UNDOCK_DELAY := 0.15

## Moved by position.y, so its parent must not be a container.
@export var slide: Control
## Faded out while docked.
@export var fade: Array[Control] = []

var _rest_y := 0.0
var _shift := 0.0
var _docked := false
var _idle := 0.0
var _pointer_down := false
var _tween: Tween


static func attach(to: Control, faded: Array[Control] = []) -> KeyboardDock:
	var dock := KeyboardDock.new()
	dock.slide = to
	dock.fade = faded
	to.add_child(dock)
	return dock


func _ready() -> void:
	_rest_y = slide.position.y
	slide.gui_input.connect(_on_slide_input)


func _input(event: InputEvent) -> void:
	if event is InputEventScreenTouch or event is InputEventMouseButton:
		_pointer_down = event.pressed


func _process(delta: float) -> void:
	var field := _edited_field()
	if field == null:
		_idle += delta
		# Never undock under a held finger: the button it's on would slide away.
		if _docked and _idle >= UNDOCK_DELAY and not _pointer_down:
			_docked = false
			_move_to(0.0)
		return
	_idle = 0.0
	var docking := not _docked
	var wanted := _shift
	if docking:
		_docked = true
		wanted = _dock_shift(field)
	# Only ever grows while docked, so keyboard-height flicker can't move the form.
	wanted = maxf(wanted, _keyboard_shift(field))
	if docking or not is_equal_approx(wanted, _shift):
		_move_to(wanted)


func _edited_field() -> LineEdit:
	if not DisplayServer.has_feature(DisplayServer.FEATURE_VIRTUAL_KEYBOARD):
		return null
	var focused := get_viewport().gui_get_focus_owner()
	if focused is LineEdit and focused.is_editing() and slide.is_ancestor_of(focused):
		return focused
	return null


## How far up the field's panel has to move to sit DOCK_TOP from the top.
func _dock_shift(field: LineEdit) -> float:
	var anchor: Control = field
	var node := field.get_parent()
	while node != slide and node != null:
		if node is PanelContainer:
			anchor = node
			break
		node = node.get_parent()
	return maxf(0.0, _unshifted(anchor.get_global_rect().position.y) - DOCK_TOP)


## Extra shift needed when a tall keyboard would still cover the docked field.
func _keyboard_shift(field: LineEdit) -> float:
	var keyboard_px := DisplayServer.virtual_keyboard_get_height()
	if keyboard_px <= 0:
		return 0.0
	# Keyboard height is in window pixels; the canvas is stretched.
	var canvas_height := get_viewport().get_visible_rect().size.y
	var keyboard := keyboard_px * canvas_height / maxf(float(DisplayServer.window_get_size().y), 1.0)
	var field_bottom := _unshifted(field.get_global_rect().end.y)
	return field_bottom + CLEARANCE - (canvas_height - keyboard)


## A y position as it would be with the slide at rest (mid-tween included).
func _unshifted(y: float) -> float:
	return y + (_rest_y - slide.position.y)


func _move_to(shift: float) -> void:
	_shift = shift
	if _tween:
		_tween.kill()
	_tween = create_tween().set_parallel().set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	_tween.tween_property(slide, "position:y", _rest_y - shift, SLIDE_SEC)
	for node in fade:
		_tween.tween_property(node, "modulate:a", 0.0 if _docked else 1.0, SLIDE_SEC)


## A tap on empty space closes the keyboard.
func _on_slide_input(event: InputEvent) -> void:
	var pressed: bool = (
		(event is InputEventScreenTouch or event is InputEventMouseButton) and event.pressed
	)
	var focused := get_viewport().gui_get_focus_owner()
	if pressed and focused is LineEdit and slide.is_ancestor_of(focused):
		get_viewport().gui_release_focus()
