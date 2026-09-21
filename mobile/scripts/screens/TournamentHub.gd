extends Control

## Tournament hub: pick a format. Daily is real; the rest are declared but
## disabled, so the shape of what's coming is visible without pretending it
## exists.


const MENU_TILE_SCENE := preload("res://scenes/components/MenuTile.tscn")

## Formats that don't exist yet. Shown greyed out with a reason, because a
## silent absence reads as a missing feature and a disabled tile with a
## label reads as a roadmap.
const COMING_SOON := [
	{"name": "Weekly League", "hint": "Seven days, bigger groups, bigger prizes."},
	{"name": "Monthly Cup", "hint": "A knockout bracket across the whole month."},
	{"name": "Seasonal", "hint": "Long-form competition with its own ranking."},
]

@onready var _daily_button: MenuTile = %DailyTile
@onready var _coming_soon_box: VBoxContainer = %ComingSoonBox
@onready var _back_button: Button = %BackButton


func _ready() -> void:
	_daily_button.pressed.connect(_on_daily_pressed)
	_back_button.pressed.connect(_on_back_pressed)

	_build_coming_soon()

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()


## The tiles restyle themselves; Back is a plain Button sitting beside them
## and would otherwise stay flat.
func _apply_theme_colors() -> void:
	MenuTile.style_button(_back_button, ThemeManager.color("surface_border"))


## The unbuilt formats are disabled tiles rather than disabled buttons with
## loose hints -- same roadmap, but the reason now sits on the tile instead of
## floating on the background photo.
func _build_coming_soon() -> void:
	for entry in COMING_SOON:
		var tile: MenuTile = MENU_TILE_SCENE.instantiate()
		_coming_soon_box.add_child(tile)
		tile.title_text = entry["name"]
		tile.subtitle_text = tr("Coming soon. %s") % tr(entry["hint"])
		tile.accent_key = "surface_border"
		tile.set_tile_disabled(true)


func _on_daily_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/DailyTournament.tscn")


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Play.tscn")
