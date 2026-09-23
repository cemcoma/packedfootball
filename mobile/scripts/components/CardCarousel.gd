class_name CardCarousel
extends Control

## A horizontal strip of cards that keeps one of them centred: the middle
## card is full size and lit, its neighbours shrink and dim away to either
## side, and a drag, a flick or a tap brings another one in.
##
## The drag is read here rather than by a ScrollContainer because a card
## swallows the press a drag starts with -- its tap button, the containers
## under it and its model view all take one. A card handed over is made
## deaf instead, and a press that never travels comes back as `card_tapped`.

## The centred card, emitted live while a drag is still moving.
signal focus_changed(index: int)
## A press that ended without becoming a drag, on the card under it.
signal card_tapped(index: int)

## The gap between two cards at their resting size. The centred one is
## bigger than that, so it overlaps its neighbours' edges -- which is why
## it is also the one raised to the front.
const SEPARATION := 10.0
const FOCUS_SCALE := 1.4
const SIDE_SCALE := 0.9
const SIDE_ALPHA := 0.55

## How far a press may wander before it counts as a drag and not a tap.
const TAP_SLOP := 10.0
## Release speed (px/sec) past which the strip carries on to the next card
## instead of settling on whichever one is nearest.
const FLICK_SPEED := 320.0
const SNAP_SECONDS := 0.22

var _views: Array = []
## Distance between two card centres -- a resting card plus the gap.
var _spacing: float = 0.0
## How far the strip is scrolled, in px: i * _spacing centres card i.
var _offset: float = 0.0
var _index: int = 0
var _snap_tween: Tween = null

var _pressing: bool = false
var _dragging: bool = false
var _press_x: float = 0.0
var _press_offset: float = 0.0
var _velocity: float = 0.0


func _ready() -> void:
	clip_contents = true
	resized.connect(_layout)


# -- contents ------------------------------------------------------------------

## Appends a card to the right-hand end of the strip. The card is taken
## over whole: it stops taking input and it is sized and placed from here.
func add_view(view: PlayerCardView) -> void:
	add_child(view)
	_go_deaf(view)
	view.size = view.get_combined_minimum_size()
	view.pivot_offset = view.size * 0.5
	view.scale = Vector2.ONE
	view.rotation = 0.0
	view.modulate = Color.WHITE
	_views.append(view)
	_spacing = view.size.x * SIDE_SCALE + SEPARATION
	_layout()
	_raise_centred()


## Takes a card out of the strip without freeing it -- the caller owns it.
## The focus lands on whatever card fills the gap.
func remove_view(view: PlayerCardView) -> void:
	var i: int = _views.find(view)
	if i < 0:
		return
	_views.remove_at(i)
	remove_child(view)
	_index = clampi(_index, 0, maxi(_views.size() - 1, 0))
	_set_offset(_index * _spacing)
	focus_changed.emit(focus_index())


## Everything under a card has to let the press through, or the drag it
## starts never reaches the strip -- the tap button, the containers and the
## model view all take one by default.
static func _go_deaf(node: Node) -> void:
	var control := node as Control
	if control != null:
		control.mouse_filter = Control.MOUSE_FILTER_IGNORE
	for child in node.get_children():
		_go_deaf(child)


func view_count() -> int:
	return _views.size()


## -1 when the strip is empty.
func focus_index() -> int:
	return _index if not _views.is_empty() else -1


func snap_to(index: int, animate: bool = true) -> void:
	if _views.is_empty():
		return
	var target: float = clampi(index, 0, _views.size() - 1) * _spacing
	_kill_snap()
	if not animate:
		_set_offset(target)
		return
	_snap_tween = create_tween().set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	_snap_tween.tween_method(_set_offset, _offset, target, SNAP_SECONDS)


# -- layout --------------------------------------------------------------------

func _set_offset(value: float) -> void:
	_offset = clampf(value, 0.0, maxf(0.0, (_views.size() - 1) * _spacing))
	_layout()
	var centred: int = clampi(int(round(_offset / _spacing)), 0, maxi(_views.size() - 1, 0))
	if centred != _index:
		_index = centred
		_raise_centred()
		focus_changed.emit(_index)


## Cards are placed by hand rather than by a container: scale here is a
## visual fade towards the edges, so it must not push the neighbours around.
func _layout() -> void:
	if _views.is_empty() or _spacing <= 0.0:
		return
	var middle: float = size.x * 0.5
	for i in _views.size():
		var view: Control = _views[i]
		var from_middle: float = i * _spacing - _offset
		var nearness: float = clampf(1.0 - absf(from_middle) / _spacing, 0.0, 1.0)
		view.scale = Vector2.ONE * lerpf(SIDE_SCALE, FOCUS_SCALE, nearness)
		view.modulate.a = lerpf(SIDE_ALPHA, 1.0, nearness)
		view.position = Vector2(
			middle + from_middle - view.size.x * 0.5, (size.y - view.size.y) * 0.5
		)


## Draw order, not z_index: a z_index here would lift the card over the
## whole screen, the sell overlay included.
func _raise_centred() -> void:
	if _index >= 0 and _index < _views.size():
		move_child(_views[_index], get_child_count() - 1)


# -- input ---------------------------------------------------------------------

func _gui_input(event: InputEvent) -> void:
	if _views.is_empty():
		return

	# Both halves of every pointer event arrive here: the project emulates
	# touch from the mouse, so a click is a button event AND a touch. The
	# press is tracked as an absolute offset, so handling it twice is a
	# no-op rather than double movement.
	var touch := event as InputEventScreenTouch
	var button := event as InputEventMouseButton
	if touch != null or (button != null and button.button_index == MOUSE_BUTTON_LEFT):
		var pressed: bool = touch.pressed if touch != null else button.pressed
		var at: Vector2 = touch.position if touch != null else button.position
		if pressed:
			_begin_press(at)
		else:
			_end_press(at)
		accept_event()
		return

	var drag := event as InputEventScreenDrag
	var motion := event as InputEventMouseMotion
	if _pressing and (drag != null or motion != null):
		var at: Vector2 = drag.position if drag != null else motion.position
		var velocity: Vector2 = drag.velocity if drag != null else motion.velocity
		_continue_press(at, velocity.x)
		accept_event()
		return

	# The wheel is only there so the strip is usable on a desktop build.
	if button != null and button.pressed:
		if button.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			snap_to(_index + 1)
			accept_event()
		elif button.button_index == MOUSE_BUTTON_WHEEL_UP:
			snap_to(_index - 1)
			accept_event()


func _begin_press(at: Vector2) -> void:
	_kill_snap()
	_pressing = true
	_dragging = false
	_press_x = at.x
	_press_offset = _offset
	_velocity = 0.0


func _continue_press(at: Vector2, velocity_x: float) -> void:
	var travelled: float = at.x - _press_x
	if not _dragging and absf(travelled) > TAP_SLOP:
		_dragging = true
	if _dragging:
		_velocity = velocity_x
		_set_offset(_press_offset - travelled)


func _end_press(at: Vector2) -> void:
	if not _pressing:
		return
	_pressing = false
	if not _dragging:
		var hit: int = _index_at(at)
		if hit >= 0:
			card_tapped.emit(hit)
		return
	_dragging = false
	snap_to(_settle_index())


## Where a released drag comes to rest: the nearest card, or the next one
## along if it was let go fast enough to count as a flick.
func _settle_index() -> int:
	var raw: float = _offset / _spacing
	var landing: float = round(raw)
	if _velocity < -FLICK_SPEED:
		landing = ceil(raw)
	elif _velocity > FLICK_SPEED:
		landing = floor(raw)
	return clampi(int(landing), 0, _views.size() - 1)


## The card a point lands on, or -1 for the gaps between them. The centred
## card is tried first, since it is the one drawn over the overlap.
func _index_at(at: Vector2) -> int:
	if _covers(_index, at):
		return _index
	var i: int = int(round((at.x - size.x * 0.5 + _offset) / _spacing))
	return i if _covers(i, at) else -1


func _covers(index: int, at: Vector2) -> bool:
	if index < 0 or index >= _views.size():
		return false
	var view: Control = _views[index]
	var scaled: Vector2 = view.size * view.scale
	var middle: Vector2 = view.position + view.size * 0.5
	return Rect2(middle - scaled * 0.5, scaled).has_point(at)


func _kill_snap() -> void:
	if _snap_tween != null:
		_snap_tween.kill()
		_snap_tween = null
