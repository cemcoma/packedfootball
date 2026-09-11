extends Node2D

## Main navigation hub. Proves scene switching works end to end; each button
## opens either the real match playback scaffold or a placeholder stub scene
## until the real functionality behind it gets built.

var buttons := [
	{"label": "Play Match", "scene": "res://scenes/Match.tscn", "rect": Rect2(540, 150, 220, 50)},
	{"label": "Shop", "scene": "res://scenes/Shop.tscn", "rect": Rect2(540, 220, 220, 50)},
	{"label": "Team", "scene": "res://scenes/Team.tscn", "rect": Rect2(540, 290, 220, 50)},
	{"label": "PVP", "scene": "res://scenes/Pvp.tscn", "rect": Rect2(540, 360, 220, 50)},
	{"label": "Profile", "scene": "res://scenes/Profile.tscn", "rect": Rect2(540, 430, 220, 50)},
]


func _ready() -> void:
	queue_redraw()


func _unhandled_input(event: InputEvent) -> void:
	if not (event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT):
		return
	var pos: Vector2 = make_input_local(event).position
	for b in buttons:
		var rect: Rect2 = b["rect"]
		if rect.has_point(pos):
			get_tree().change_scene_to_file(b["scene"])
			return


func _draw() -> void:
	var font: Font = ThemeDB.fallback_font
	var font_size: int = ThemeDB.fallback_font_size

	draw_string(font, Vector2(540, 100), "Packed Football", HORIZONTAL_ALIGNMENT_LEFT, 500, int(font_size * 2.5), Color.WHITE)

	for b in buttons:
		var rect: Rect2 = b["rect"]
		draw_rect(rect, Color(0.15, 0.15, 0.18, 0.9))
		draw_rect(rect, Color(0.8, 0.8, 0.8), false, 2.0)
		draw_string(
			font, rect.position + Vector2(14, rect.size.y * 0.65), b["label"], HORIZONTAL_ALIGNMENT_LEFT, rect.size.x - 20, font_size, Color.WHITE
		)
