extends Control

## A small rotating-arc spinner, drawn by hand since Godot has no built-in
## indeterminate spinner Control. Reusable anywhere a "working on it" moment
## needs a visual beyond a plain status label (currently: Play.gd's
## matchmaking popup).

@export var radius: float = 20.0
@export var line_width: float = 4.0
@export var spinner_color: Color = Color(1, 1, 1, 1)
@export var spin_speed: float = 6.0  # radians/second
@export var arc_span: float = TAU * 0.7  # how much of the circle is drawn at once

var _angle: float = 0.0


func _process(delta: float) -> void:
	_angle = fmod(_angle + spin_speed * delta, TAU)
	queue_redraw()


func _draw() -> void:
	var center := size / 2.0
	draw_arc(center, radius, _angle, _angle + arc_span, 32, spinner_color, line_width, true)
