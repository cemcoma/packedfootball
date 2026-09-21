extends Control

## Shirt designer, reached from the Team screen's "Customize Kit" button.
##
## Pick a pattern and two colors (the same color twice is allowed -- that's
## a plain one-color shirt) and Save writes it to users/{uid}.kit as one
## string. See KitDesign.gd for the format and how it stays extendable.
##
## Every button here is built at RUNTIME from KitDesign.PATTERNS and
## KitDesign.AVAILABLE_COLORS rather than authored in CustomizeKit.tscn, so
## adding a pattern or a color is a one-line change in that file and this
## screen picks it up with no scene editing at all.
##
## Edits are local until Save. Leaving without saving simply discards them,
## the same way Team's own Back button discards an unsaved lineup -- there's
## nothing here worth a confirmation dialog.

const SWATCH_SIZE := Vector2(46.0, 46.0)
const SWATCH_CORNER := 6
const SELECTED_BORDER := 3
const UNSELECTED_BORDER := 1

@onready var _title_label: Label = %TitleLabel
@onready var _headings: Array[Label] = [%PatternHeading, %PrimaryHeading, %SecondaryHeading]
@onready var _preview: KitPreview = %KitPreview
@onready var _preview_panel: PanelContainer = %PreviewPanel
@onready var _options_panel: PanelContainer = %OptionsPanel
@onready var _pattern_row: HBoxContainer = %PatternRow
@onready var _primary_grid: GridContainer = %PrimaryGrid
@onready var _secondary_grid: GridContainer = %SecondaryGrid
@onready var _summary_label: Label = %SummaryLabel
@onready var _status_label: Label = %StatusLabel
@onready var _save_button: Button = %SaveButton
@onready var _back_button: Button = %BackButton

# The design being edited -- a copy, so abandoning the screen leaves the
# saved one untouched.
var _design: KitDesign = KitDesign.new()
var _saving: bool = false


func _ready() -> void:
	_design = GameProfile.kit_design()

	_save_button.pressed.connect(_on_save_pressed)
	_back_button.pressed.connect(_on_back_pressed)

	# _refresh (not just _apply_theme_colors) because the swatch borders are
	# painted from the palette too, not only the labels.
	ThemeManager.theme_changed.connect(_refresh)

	_build_pattern_buttons()
	_build_color_grid(_primary_grid, true)
	_build_color_grid(_secondary_grid, false)
	_refresh()


# -- building the pickers -----------------------------------------------------

func _build_pattern_buttons() -> void:
	for pattern in KitDesign.PATTERNS:
		var button := Button.new()
		button.text = KitDesign.PATTERN_NAMES.get(pattern, String(pattern).capitalize())
		button.toggle_mode = true
		button.custom_minimum_size = Vector2(110.0, 40.0)
		button.pressed.connect(_on_pattern_pressed.bind(pattern))
		_pattern_row.add_child(button)


## One tappable swatch per palette entry. A Button rather than a ColorRect
## so it comes with real press/focus behaviour; the color is a StyleBoxFlat
## applied to every state, so it doesn't wash out on hover.
func _build_color_grid(grid: GridContainer, is_primary: bool) -> void:
	for entry in KitDesign.AVAILABLE_COLORS:
		var hex: String = entry["hex"]
		var button := Button.new()
		button.custom_minimum_size = SWATCH_SIZE
		button.tooltip_text = tr(entry["name"])
		button.pressed.connect(_on_color_pressed.bind(hex, is_primary))
		grid.add_child(button)


func _style_swatch(button: Button, hex: String, selected: bool) -> void:
	var style := StyleBoxFlat.new()
	style.anti_aliasing = false
	style.set_corner_radius_all(0)
	style.bg_color = KitDesign.color_from_hex(hex)
	style.set_border_width_all(SELECTED_BORDER if selected else UNSELECTED_BORDER)
	# The selected swatch is marked with the theme's accent, which is legible
	# against every color in the palette in both themes -- a plain white ring
	# disappears on the white swatch, a black one on the black swatch.
	style.border_color = ThemeManager.color("accent") if selected else ThemeManager.color("surface_border")

	for state in ["normal", "hover", "pressed", "focus", "disabled"]:
		button.add_theme_stylebox_override(state, style)


# -- state -> UI --------------------------------------------------------------

func _refresh() -> void:
	_preview.set_design(_design)
	_refresh_pattern_buttons()
	_refresh_color_grid(_primary_grid, _design.primary)
	_refresh_color_grid(_secondary_grid, _design.secondary)
	_summary_label.text = tr("%s  ·  %s and %s") % [
		_design.pattern_name(),
		KitDesign.color_name(_design.primary),
		KitDesign.color_name(_design.secondary),
	]
	_apply_theme_colors()


func _refresh_pattern_buttons() -> void:
	var patterns: Array = KitDesign.PATTERNS
	var children := _pattern_row.get_children()
	for i in range(mini(children.size(), patterns.size())):
		var button: Button = children[i]
		var chosen: bool = patterns[i] == _design.pattern
		button.button_pressed = chosen
		# toggle_mode alone can't show the choice any more: the frame is ours,
		# so the lit state has to be painted here.
		MenuTile.style_button(
			button,
			ThemeManager.color("accent") if chosen else ThemeManager.color("surface_border"),
			chosen,
			Vector2(10, 4)
		)


func _refresh_color_grid(grid: GridContainer, chosen_hex: String) -> void:
	var children := grid.get_children()
	for i in range(mini(children.size(), KitDesign.AVAILABLE_COLORS.size())):
		var hex: String = KitDesign.AVAILABLE_COLORS[i]["hex"]
		_style_swatch(children[i], hex, hex == chosen_hex)


## The labels on this screen sit straight on the screen background with no
## panel behind them, so they need the palette rather than the Theme's Label
## color -- see ThemeManager's note on text_hint.
func _apply_theme_colors() -> void:
	_style_chrome()
	_title_label.add_theme_color_override("font_color", MenuTile.TITLE_COLOR)
	_summary_label.add_theme_color_override("font_color", MenuTile.SUBTITLE_COLOR)
	_status_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	for heading in _headings:
		(heading as Label).add_theme_color_override("font_color", ThemeManager.color("heading"))


## Both columns get the tiles' frame -- the swatch grids used to float on the
## background photo with nothing behind them.
func _style_chrome() -> void:
	var muted := ThemeManager.color("surface_border")
	for panel in [_preview_panel, _options_panel]:
		panel.add_theme_stylebox_override(
			"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, muted, 3, true, Vector2(10, 8))
		)
	MenuTile.style_button(_save_button, ThemeManager.color("accent"))
	MenuTile.style_button(_back_button, muted)


# -- input handlers -----------------------------------------------------------

func _on_pattern_pressed(pattern: String) -> void:
	_design = KitDesign.create(pattern, _design.primary, _design.secondary)
	_set_status("")
	_refresh()


func _on_color_pressed(hex: String, is_primary: bool) -> void:
	if is_primary:
		_design = KitDesign.create(_design.pattern, hex, _design.secondary)
	else:
		_design = KitDesign.create(_design.pattern, _design.primary, hex)
	_set_status("")
	_refresh()


func _on_save_pressed() -> void:
	if _saving:
		return
	_saving = true
	_save_button.disabled = true
	_set_status(tr("Saving..."))

	var ok := await GameProfile.set_kit(_design)

	_saving = false
	_save_button.disabled = false
	_set_status(tr("Kit saved.") if ok else tr("Could not save your kit -- try again."))


func _on_back_pressed() -> void:
	# Straight back to Team. The unsaved lineup (formation/slot_assignment)
	# lives on the GameProfile autoload, not on the Team scene, so a trip
	# through here doesn't lose it.
	get_tree().change_scene_to_file("res://scenes/Team.tscn")


func _set_status(text: String) -> void:
	_status_label.text = text
