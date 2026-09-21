class_name MenuTile
extends Button

## A navigation tile: icon, title, one line of subtitle, in a hard-edged
## pixel-art frame. Replaces the flat theme Button on the menus, where five
## identical rectangles gave the most important action the same weight as the
## least.
##
## Extends Button rather than wrapping one, so `pressed`, focus and `disabled`
## all keep working exactly as the screens already expect. The contents are
## ordinary children anchored over it; _ready() makes every one of them
## mouse-transparent so the click still lands on the button itself.
##
## Pixel-art rules, both here and in any tile art added later: StyleBoxFlat
## with anti_aliasing off and zero corner radius (a rounded, smoothed edge is
## the one thing that reads as "not pixel art"), and NEAREST filtering on the
## icon so a 16px sprite scales up in hard squares rather than a blur.

const CORNER_RADIUS := 0
const BORDER_NORMAL := 3
const BORDER_HERO := 4
const SHADOW_OFFSET := 4

## How far the fill is pulled toward the accent. The border carries the
## colour; the fill only hints at it, or the label stops being readable.
const FILL_MIX := 0.18
const FILL_MIX_HERO := 0.28

## Near-opaque: at 0.9 the background photo bleeds through and washes the
## fill out, which is what made the first pass look pale.
const FILL_ALPHA := 0.96

## Dark in BOTH themes, like every other panel in this project: the light
## theme is a bright photo behind dark translucent panels, and
## ThemeManager.color("surface") is near-white there -- building the fill
## from it turned the tiles pale and swallowed the labels.
const BASE_FILL := Color(0.07, 0.08, 0.10)

## The labels stay white in both themes -- the tile is always a dark frame,
## the way the light theme's panels already are.
const TITLE_COLOR := Color(1.0, 1.0, 1.0)
const SUBTITLE_COLOR := Color(0.78, 0.80, 0.84)

@export var title_text: String = "":
	set(value):
		title_text = value
		_refresh()

@export_multiline var subtitle_text: String = "":
	set(value):
		subtitle_text = value
		_refresh()

## A res:// path. A file that isn't there yet degrades to no icon rather than
## an error, so art can land one sprite at a time -- the same contract
## CurrencyDisplay.icon_for() already uses.
@export var icon_path: String = "":
	set(value):
		icon_path = value
		_refresh()

## A ThemeManager palette key, so tiles follow a dark/light swap.
@export var accent_key: String = "accent":
	set(value):
		accent_key = value
		_restyle()

@export var hero: bool = false:
	set(value):
		hero = value
		_refresh()
		_restyle()

## Overrides the hero/normal height. 0 keeps the default -- a hub with only
## two destinations wants taller tiles than a five-item menu.
@export var min_height: int = 0:
	set(value):
		min_height = value
		_refresh()

var _subtitle_color: Color = SUBTITLE_COLOR

@onready var _icon: TextureRect = %TileIcon
@onready var _title_label: Label = %TileTitle
@onready var _subtitle_label: Label = %TileSubtitle


func _ready() -> void:
	if _title_label == null:
		# The script alone is not a tile: the icon and labels live in
		# MenuTile.tscn. Attaching just the script leaves every _refresh and
		# _restyle below to bail out, and the button renders blank and
		# unstyled -- which is exactly how it shipped on TeamHub's Back.
		push_warning("MenuTile on '%s' has no tile children -- instance MenuTile.tscn, don't attach the script to a bare Button." % name)
		return
	# The label and icon sit ON the button, so they must not eat its input.
	_make_children_transparent(self)
	ThemeManager.theme_changed.connect(_restyle)
	_refresh()
	_restyle()


func _make_children_transparent(node: Node) -> void:
	for child in node.get_children():
		if child is Control:
			child.mouse_filter = Control.MOUSE_FILTER_IGNORE
		_make_children_transparent(child)


func accent() -> Color:
	return ThemeManager.color(accent_key)


func _refresh() -> void:
	if _title_label == null:
		return  # set before _ready(); _ready() calls back here

	_title_label.text = LocaleManager.display_upper(tr(title_text)) if title_text != "" else ""
	_title_label.add_theme_font_size_override("font_size", 22 if hero else 15)

	_subtitle_label.text = tr(subtitle_text) if subtitle_text != "" else ""
	_subtitle_label.visible = _subtitle_label.text != ""
	_subtitle_label.add_theme_font_size_override("font_size", 12 if hero else 10)

	# Powers of two, so a 16px or 32px source scales by a whole number. A
	# fractional scale is what makes pixel art shimmer and go uneven.
	var icon_size := 64 if hero else 32
	_icon.custom_minimum_size = Vector2(icon_size, icon_size)
	var texture: Texture2D = null
	if icon_path != "" and ResourceLoader.exists(icon_path):
		texture = load(icon_path) as Texture2D
	_icon.texture = texture
	_icon.visible = texture != null

	var default_height := 92 if hero else 64
	custom_minimum_size = Vector2(0, min_height if min_height > 0 else default_height)


func _restyle() -> void:
	if _title_label == null:
		return
	var tint := accent()
	var surface := BASE_FILL
	var mix := FILL_MIX_HERO if hero else FILL_MIX
	var border := BORDER_HERO if hero else BORDER_NORMAL

	add_theme_stylebox_override("normal", _frame(surface.lerp(tint, mix), tint, border, true))
	add_theme_stylebox_override("hover", _frame(surface.lerp(tint, mix + 0.12), tint, border, true))
	add_theme_stylebox_override("focus", _frame(surface.lerp(tint, mix + 0.12), tint, border, true))
	# Pressed drops the shadow and darkens: the tile reads as pushed into the
	# page rather than sitting above it.
	add_theme_stylebox_override(
		"pressed", _frame(surface.lerp(tint, mix).darkened(0.25), tint.lightened(0.2), border, false)
	)
	add_theme_stylebox_override(
		"disabled", _frame(surface.darkened(0.2), ThemeManager.color("surface_border"), border, false)
	)

	# A switched-off tile dims its labels too -- the muted frame alone still
	# reads as an ordinary tile at a glance.
	var dim := 0.45 if disabled else 1.0
	_title_label.add_theme_color_override("font_color", TITLE_COLOR * dim)
	_subtitle_label.add_theme_color_override("font_color", _subtitle_color * dim)


## Button.disabled is a plain property with no signal, so a tile that gets
## switched on or off has to be told to restyle. Screens use this rather than
## assigning `disabled` directly.
func set_tile_disabled(value: bool) -> void:
	disabled = value
	_restyle()


## For a subtitle that carries a state rather than just context -- TeamHub's
## inventory counter goes amber once the club is full, which is the point it
## stops being a fact and starts being a blocker.
func set_subtitle_color(color: Color) -> void:
	_subtitle_color = color
	if _subtitle_label != null:
		_subtitle_label.add_theme_color_override("font_color", color)


func _frame(fill: Color, border_color: Color, border_width: int, lifted: bool) -> StyleBoxFlat:
	return pixel_frame(fill, border_color, border_width, lifted)


## The project's pixel-art panel: hard corners, thick border, hard drop
## shadow, no anti-aliasing. Static so anything that has to sit next to a
## tile -- the menu's account panel -- can wear the same frame.
## `lifted` draws the shadow; a pressed tile passes false so it sits down.
static func pixel_frame(
	fill: Color, border_color: Color, border_width: int, lifted: bool,
	pad: Vector2 = Vector2(14, 8)
) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	# Both of these are what keep the edge crisp -- see the class comment.
	style.anti_aliasing = false
	style.set_corner_radius_all(CORNER_RADIUS)
	style.bg_color = Color(fill.r, fill.g, fill.b, FILL_ALPHA)
	style.border_color = border_color
	style.set_border_width_all(border_width)
	style.content_margin_left = pad.x
	style.content_margin_right = pad.x
	style.content_margin_top = pad.y
	style.content_margin_bottom = pad.y
	if lifted:
		style.shadow_color = Color(0.0, 0.0, 0.0, 0.55)
		style.shadow_size = SHADOW_OFFSET
		style.shadow_offset = Vector2(SHADOW_OFFSET, SHADOW_OFFSET)
	return style


## An ordinary Button in the tiles' frame -- for the controls that sit beside
## them (tabs, Save, Back, a dropdown). `lit` is the selected/primary state.
##
## The labels are set explicitly because the fill is dark in both themes: the
## light Theme paints button text dark, and it vanished against this frame.
static func style_button(
	button: Button, accent: Color, lit: bool = false, pad: Vector2 = Vector2(14, 6)
) -> void:
	var fill := BASE_FILL.lerp(accent, 0.22 if lit else 0.0)
	button.add_theme_stylebox_override("normal", pixel_frame(fill, accent, 3, true, pad))
	var hover := pixel_frame(fill.lerp(accent, 0.14), accent, 3, true, pad)
	button.add_theme_stylebox_override("hover", hover)
	button.add_theme_stylebox_override("focus", hover)
	button.add_theme_stylebox_override(
		"pressed", pixel_frame(fill.darkened(0.25), accent.lightened(0.2), 3, false, pad)
	)
	var muted := ThemeManager.color("surface_border")
	button.add_theme_stylebox_override(
		"disabled", pixel_frame(BASE_FILL.darkened(0.2), muted, 3, false, pad)
	)

	var label := TITLE_COLOR if lit else SUBTITLE_COLOR
	for key in ["font_color", "font_hover_color", "font_pressed_color", "font_focus_color"]:
		button.add_theme_color_override(key, label)
	button.add_theme_color_override("font_disabled_color", muted)


## An OptionButton's drop-down list, which is a PopupMenu and takes none of
## the button's own styling.
static func style_popup(option: OptionButton, accent: Color) -> void:
	var popup := option.get_popup()
	popup.add_theme_stylebox_override("panel", pixel_frame(BASE_FILL, accent, 3, true, Vector2(4, 4)))
	popup.add_theme_stylebox_override(
		"hover", pixel_frame(BASE_FILL.lerp(accent, 0.3), accent, 0, false, Vector2(4, 2))
	)
	popup.add_theme_color_override("font_color", SUBTITLE_COLOR)
	popup.add_theme_color_override("font_hover_color", TITLE_COLOR)
