extends MarginContainer

## Keeps the layout clear of a notch or home indicator, on top of the margins
## the scene already asks for.
##
## get_display_safe_area() reports the DISPLAY in physical pixels, while a
## margin is in canvas units -- on a stretched viewport the two differ by the
## stretch factor, and on desktop the display is larger than the window
## entirely. Taking the difference raw produced a negative margin, which makes
## MarginContainer render its child WIDER than the screen.

## The scene's own margins. Safe-area insets are added to these, not
## substituted for them.
const BASE_H := 16
const BASE_V := 12


func _ready() -> void:
	_apply_safe_area()
	get_tree().get_root().size_changed.connect(_apply_safe_area)


func _apply_safe_area() -> void:
	var window_size := DisplayServer.window_get_size()
	var canvas_size := get_viewport_rect().size
	if window_size.x <= 0 or window_size.y <= 0:
		return

	var safe := DisplayServer.get_display_safe_area()
	var left := 0.0
	var top := 0.0
	var right := 0.0
	var bottom := 0.0
	# A safe area bigger than the window is the desktop case: it describes the
	# screen, not us, so there is nothing to inset for.
	if safe.size.x <= window_size.x and safe.size.y <= window_size.y:
		left = maxf(0.0, safe.position.x)
		top = maxf(0.0, safe.position.y)
		right = maxf(0.0, window_size.x - (safe.position.x + safe.size.x))
		bottom = maxf(0.0, window_size.y - (safe.position.y + safe.size.y))

	# Physical pixels -> canvas units.
	var scale_x := canvas_size.x / float(window_size.x)
	var scale_y := canvas_size.y / float(window_size.y)
	add_theme_constant_override("margin_left", BASE_H + int(left * scale_x))
	add_theme_constant_override("margin_right", BASE_H + int(right * scale_x))
	add_theme_constant_override("margin_top", BASE_V + int(top * scale_y))
	add_theme_constant_override("margin_bottom", BASE_V + int(bottom * scale_y))
