extends TextureRect

## The shared screen background, now theme-aware: it takes whichever image
## ThemeManager's current mode points at and re-takes it whenever the mode
## changes, so every screen's backdrop follows a dark/light swap without
## each scene having to know anything about it.
##
## Screens that want a FIXED backdrop regardless of mode (a branded title
## screen, say) untick follow_theme in the inspector and keep whatever
## texture the scene sets -- that's the one escape hatch, and it's per
## instance, so it doesn't affect anything else.
##
## Match.tscn doesn't instance this component at all (it draws its own
## pitch), so the match screen is untouched by any of this by construction.

@export var follow_theme: bool = true


func _ready() -> void:
	if not follow_theme:
		return
	ThemeManager.theme_changed.connect(_apply_theme_background)
	_apply_theme_background()


func _apply_theme_background() -> void:
	var background := ThemeManager.background_texture()
	if background != null:
		texture = background
