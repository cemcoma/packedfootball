class_name LoadingBar
extends Control

const OUTLINE := Color("aec0cc")
const INSIDE := Color("000000")
const FILL_TOP := Color("f56914")
const FILL_BOTTOM := Color("f6c522")

@export_range(0.0, 1.0) var target: float = 0.0
@export var segments: int = 24
@export var border: float = 2.0
@export var gap: float = 2.0
## How fast the fill closes the distance to `target` (per second).
@export var ease_speed: float = 6.0

var _shown: float = 0.0


func _process(delta: float) -> void:
	if is_equal_approx(_shown, target):
		return
	_shown = lerpf(_shown, target, 1.0 - exp(-ease_speed * delta))
	if absf(_shown - target) < 0.002:
		_shown = target
	queue_redraw()


func _draw() -> void:
	var outer := Rect2(Vector2.ZERO, size)
	draw_rect(outer, OUTLINE)
	var inner := outer.grow(-border)
	draw_rect(inner, INSIDE)

	var track := inner.grow(-gap)
	var seg_w := (track.size.x - gap * (segments - 1)) / segments
	var filled := int(round(_shown * segments))
	var half := track.size.y / 2.0
	for i in filled:
		var x := track.position.x + i * (seg_w + gap)
		draw_rect(Rect2(x, track.position.y, seg_w, half), FILL_TOP)
		draw_rect(Rect2(x, track.position.y + half, seg_w, half), FILL_BOTTOM)
