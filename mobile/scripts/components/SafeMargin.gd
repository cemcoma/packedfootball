extends MarginContainer

## Keeps the layout clear of a notch, a home indicator and the currency HUD,
## on top of the margins the scene already asks for. ScreenInsets.gd does the
## physical-pixel to canvas-unit conversion; this only adds it on.

## The scene's own margins. Safe-area insets are added to these, not
## substituted for them.
const BASE_H := 16
const BASE_V := 12


func _ready() -> void:
	_apply_safe_area()
	get_tree().get_root().size_changed.connect(_apply_safe_area)
	# The strip comes and goes with the screen, and so must the space for it.
	CurrencyHud.reserve_changed.connect(_apply_safe_area)


func _apply_safe_area() -> void:
	var inset := ScreenInsets.of(get_viewport())
	add_theme_constant_override("margin_left", BASE_H + int(inset["left"]))
	add_theme_constant_override("margin_right", BASE_H + int(inset["right"]))
	add_theme_constant_override("margin_bottom", BASE_V + int(inset["bottom"]))
	add_theme_constant_override(
		"margin_top", BASE_V + int(inset["top"]) + CurrencyHud.reserved_height()
	)
