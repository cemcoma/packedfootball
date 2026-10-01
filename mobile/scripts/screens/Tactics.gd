extends Control

## Tactics: how the side plays. One section today -- the play style -- in a
## scrolling list of sections, so later settings (captain, set-piece takers,
## crossing) each slot in as another one.
##
## A style is saved the moment it is picked (GameProfile.set_tactic_style),
## the way the kit is: nothing to forget to save on the way out.

const MENU_TILE := preload("res://scenes/components/MenuTile.tscn")

@onready var _style_list: VBoxContainer = %StyleList
@onready var _status_label: Label = %StatusLabel
@onready var _back_button: Button = %BackButton

var _tiles: Dictionary = {}  # style id -> MenuTile
var _saving := false


func _ready() -> void:
	for style in Tactics.STYLE_IDS:
		var tile: MenuTile = MENU_TILE.instantiate()
		tile.title_text = Tactics.display_name(style)
		tile.subtitle_text = Tactics.description(style)
		tile.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		# PASS, or a finger landing on a tile can't drag the list.
		tile.mouse_filter = Control.MOUSE_FILTER_PASS
		tile.pressed.connect(_on_style_pressed.bind(style))
		_style_list.add_child(tile)
		_tiles[style] = tile
	_back_button.pressed.connect(_on_back_pressed)
	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()
	_refresh_selection()


func _apply_theme_colors() -> void:
	MenuTile.style_button(_back_button, ThemeManager.color("surface_border"))


## The picked style is the hero tile; the rest sit back.
func _refresh_selection() -> void:
	var current := GameProfile.tactic_style()
	for style in _tiles:
		var tile: MenuTile = _tiles[style]
		tile.hero = style == current
		tile.accent_key = "heading" if style == current else "accent"
		tile.disabled = _saving


func _on_style_pressed(style: String) -> void:
	if _saving or style == GameProfile.tactic_style():
		return
	_saving = true
	_status_label.text = ""
	_refresh_selection()
	var ok: bool = await GameProfile.set_tactic_style(style)
	_saving = false
	if not ok:
		_status_label.text = tr("Couldn't save your tactics -- check your connection and try again.")
	_refresh_selection()


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/TeamHub.tscn")
