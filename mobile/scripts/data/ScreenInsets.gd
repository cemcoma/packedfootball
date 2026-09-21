class_name ScreenInsets
extends RefCounted

## The safe area as margins in CANVAS UNITS. Static only, no state -- same
## shape as CurrencyDisplay.gd and TimeFormat.gd.
##
## get_display_safe_area() reports the DISPLAY in physical pixels, while a
## margin is in canvas units -- on a stretched viewport the two differ by the
## stretch factor, and on desktop the display is larger than the window
## entirely. Taking the difference raw produced a negative margin, which makes
## a MarginContainer render its child WIDER than the screen.
##
## Lives here rather than on SafeMargin so the currency HUD can place itself
## against the same numbers without the two depending on each other.

const ZERO := {"left": 0.0, "top": 0.0, "right": 0.0, "bottom": 0.0}


static func of(viewport: Viewport) -> Dictionary:
	if viewport == null:
		return ZERO.duplicate()
	return compute(
		DisplayServer.get_display_safe_area(),
		DisplayServer.window_get_size(),
		viewport.get_visible_rect().size
	)


## The arithmetic on its own, taking the three numbers rather than reading
## them, so it can be checked against a real device's values without one --
## this only ever runs for real on a notched phone.
static func compute(safe: Rect2i, window_size: Vector2i, canvas_size: Vector2) -> Dictionary:
	if window_size.x <= 0 or window_size.y <= 0:
		return ZERO.duplicate()
	# A safe area bigger than the window is the desktop case: it describes the
	# screen, not us, so there is nothing to inset for.
	if safe.size.x > window_size.x or safe.size.y > window_size.y:
		return ZERO.duplicate()

	var scale_x := canvas_size.x / float(window_size.x)
	var scale_y := canvas_size.y / float(window_size.y)
	return {
		"left": maxf(0.0, safe.position.x) * scale_x,
		"top": maxf(0.0, safe.position.y) * scale_y,
		"right": maxf(0.0, window_size.x - (safe.position.x + safe.size.x)) * scale_x,
		"bottom": maxf(0.0, window_size.y - (safe.position.y + safe.size.y)) * scale_y,
	}
