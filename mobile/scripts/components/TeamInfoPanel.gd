class_name TeamInfoPanel
extends PanelContainer

## One side at a glance: name and kit swatch, record, formation, tactic and
## overall, in the tiles' frame. PreMatch shows two of them with VS between,
## ManagerView shows one. Callers add their own lines with add_row() and their
## own buttons to `extra`.

## Inner padding of the frame; ManagerView's narrow column wants less.
@export var pad := Vector2(18, 14)

@onready var extra: VBoxContainer = $Box/Extra
@onready var _name_label: Label = $Box/NameKitContainer/NameLabel
@onready var _kit_swatch: KitSwatch = $Box/NameKitContainer/KitSwatch
@onready var _info_box: VBoxContainer = $Box/InfoBox


func _ready() -> void:
	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()


## `record` {} (a bot) reads 0-0-0; `overall` 0 reads "--".
func set_team(team_name: String, kit: String, record: Dictionary, formation: String, tactic_style: String, overall: int) -> void:
	_name_label.text = team_name
	_kit_swatch.set_design(KitDesign.parse(kit))
	_value("RecordRow").text = tr("%d W  %d D  %d L") % [
		int(record.get("wins", 0)), int(record.get("draws", 0)), int(record.get("losses", 0))
	]
	_value("FormationRow").text = formation
	_value("TacticRow").text = Tactics.display_name(tactic_style)
	_value("OverallRow").text = str(overall) if overall > 0 else "--"


## One more caption/value line under the standard ones; returns the value label.
func add_row(caption: String, value: String) -> Label:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 20)
	var caption_label := Label.new()
	caption_label.name = "Caption"
	caption_label.text = caption
	caption_label.add_theme_font_size_override("font_size", 14)
	row.add_child(caption_label)
	var value_label := Label.new()
	value_label.name = "Value"
	value_label.text = value
	value_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	value_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	value_label.add_theme_font_size_override("font_size", 16)
	row.add_child(value_label)
	_info_box.add_child(row)
	_apply_theme_colors()
	return value_label


func _value(row: String) -> Label:
	return _info_box.get_node(row + "/Value")


## Dark in both themes (MenuTile.BASE_FILL), so the text keeps the tiles' fixed
## colours; only the frame follows the palette.
func _apply_theme_colors() -> void:
	add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, ThemeManager.color("surface_border"), 3, true, pad)
	)
	_name_label.add_theme_color_override("font_color", MenuTile.TITLE_COLOR)
	for row in _info_box.get_children():
		var caption := row.get_node_or_null("Caption") as Label
		if caption:
			caption.add_theme_color_override("font_color", MenuTile.SUBTITLE_COLOR)
		row.get_node("Value").add_theme_color_override("font_color", MenuTile.TITLE_COLOR)
