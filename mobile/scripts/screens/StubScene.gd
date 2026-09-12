extends Node2D

## Placeholder scene proving scene navigation works before the real
## functionality (PVP matchmaking) gets built. Only Pvp.tscn uses this now
## -- Shop.tscn got its own real script once pack mechanics landed.

@export var title: String = "Stub"

var back_button_rect := Rect2(20, 20, 200, 40)


func _ready() -> void:
	queue_redraw()


func _unhandled_input(event: InputEvent) -> void:
	if not (event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT):
		return
	var pos: Vector2 = make_input_local(event).position
	if back_button_rect.has_point(pos):
		get_tree().change_scene_to_file("res://scenes/Menu.tscn")


func _draw() -> void:
	var font: Font = ThemeDB.fallback_font
	var font_size: int = ThemeDB.fallback_font_size

	draw_rect(back_button_rect, Color(0.15, 0.15, 0.18, 0.9))
	draw_rect(back_button_rect, Color(0.8, 0.8, 0.8), false, 2.0)
	draw_string(
		font,
		back_button_rect.position + Vector2(14, back_button_rect.size.y * 0.65),
		"Back to Menu",
		HORIZONTAL_ALIGNMENT_LEFT,
		back_button_rect.size.x - 20,
		font_size,
		Color.WHITE
	)

	draw_string(font, Vector2(20, 150), title, HORIZONTAL_ALIGNMENT_LEFT, 600, int(font_size * 2.5), Color.WHITE)
	draw_string(font, Vector2(20, 190), "Coming soon.", HORIZONTAL_ALIGNMENT_LEFT, 600, font_size, Color(0.7, 0.7, 0.7))
