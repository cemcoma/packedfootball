extends Node

## The one place colors live, so a dark/light swap is a single call rather
## than hunting hardcoded Color(...) literals through every scene.
##
## Two halves, because Godot splits the job:
##   - Widget chrome (Button/Panel/Label styles) lives in a real Theme
##     resource, swapped wholesale on the root Window -- that's what
##     restyles every existing Control for free, no per-node work.
##   - Everything a Theme can't express -- per-currency accent colors, the
##     tile surface tints components build StyleBoxFlats from at runtime --
##     lives in PALETTES here and is read through color().
##
## Components that draw with palette colors should rebuild themselves on the
## theme_changed signal; ones that only use themed Button/Panel styles need
## to do nothing at all.

signal theme_changed

const DARK_THEME := "res://theme/AppTheme.tres"
const LIGHT_THEME := "res://theme/AppThemeLight.tres"

const SETTINGS_PATH := "user://settings.cfg"

const PALETTES := {
	"dark": {
		"credits": Color(0.95, 0.75, 0.25),
		"bucks": Color(0.35, 0.8, 0.55),
		"medals": Color(0.65, 0.7, 0.95),
		"surface": Color(0.13, 0.13, 0.16),
		"surface_border": Color(0.45, 0.45, 0.5),
		"text_muted": Color(0.7, 0.7, 0.75),
		"accent": Color(1.0, 0.85, 0.35),
	},
	"light": {
		# Deeper, more saturated than their dark counterparts on purpose --
		# the pale gold/green that reads well on near-black is nearly
		# invisible on near-white.
		"credits": Color(0.72, 0.52, 0.08),
		"bucks": Color(0.13, 0.55, 0.33),
		"medals": Color(0.32, 0.38, 0.72),
		"surface": Color(0.97, 0.97, 0.98),
		"surface_border": Color(0.6, 0.6, 0.66),
		"text_muted": Color(0.35, 0.35, 0.42),
		"accent": Color(0.85, 0.6, 0.05),
	},
}

const FALLBACK_COLOR := Color(0.7, 0.7, 0.75)

## Shared screen background per mode (see BackgroundLayer.gd). Match.tscn
## deliberately doesn't use BackgroundLayer at all -- it draws its own pitch
## -- so it's unaffected by a theme swap either way.
const BACKGROUNDS := {
	"dark": "res://sprites/backgrounds/general_background_dark.jpg",
	"light": "res://sprites/backgrounds/general_background_light_medium.jpg",
}

var mode: String = "dark"


func _ready() -> void:
	_load_saved_mode()
	_apply_theme_resource()


## Any palette color for the CURRENT mode -- currency keys ("credits"/
## "bucks"/"medals") and surface keys ("surface"/"surface_border"/
## "text_muted"/"accent") both come through here.
func color(key: String) -> Color:
	return PALETTES.get(mode, PALETTES["dark"]).get(key, FALLBACK_COLOR)


func is_light() -> bool:
	return mode == "light"


## The current mode's screen background, or null if that file isn't there --
## callers keep whatever texture they already had rather than blanking out.
func background_texture() -> Texture2D:
	var path: String = BACKGROUNDS.get(mode, "")
	if path == "" or not ResourceLoader.exists(path):
		return null
	return load(path) as Texture2D


func set_mode(new_mode: String) -> void:
	if not PALETTES.has(new_mode) or new_mode == mode:
		return
	mode = new_mode
	_apply_theme_resource()
	_save_mode()
	theme_changed.emit()


## Swapping the root Window's theme is what makes every already-built
## Control pick up the new Button/Panel/Label styles without being
## rebuilt -- theme lookups walk up the tree, so the root is the one place
## an override reaches everything.
func _apply_theme_resource() -> void:
	var path := LIGHT_THEME if mode == "light" else DARK_THEME
	if not ResourceLoader.exists(path):
		return  # light theme not authored yet -- keep whatever's already applied
	var theme := load(path) as Theme
	if theme != null:
		get_tree().root.theme = theme


func _save_mode() -> void:
	var config := ConfigFile.new()
	config.load(SETTINGS_PATH)  # keep any other settings already in the file
	config.set_value("display", "theme_mode", mode)
	config.save(SETTINGS_PATH)


func _load_saved_mode() -> void:
	var config := ConfigFile.new()
	if config.load(SETTINGS_PATH) != OK:
		return
	var saved = config.get_value("display", "theme_mode", "dark")
	if saved is String and PALETTES.has(saved):
		mode = saved
