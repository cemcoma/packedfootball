class_name CurrencyChip
extends PanelContainer

## One currency's balance as a chip -- icon (or a tinted dot until the art
## lands) and the amount, in the tiles' pixel frame tinted by the currency's
## own colour. CurrencyDisplay decides the name, colour and separators, so
## every chip agrees with every other place a currency appears.
##
## The StyleBox is built in code, not baked into the .tscn: its tint depends
## on which currency the chip is showing, so one scene covers all of them.

## Border tint strength. The fill stays near-black like every other panel --
## a tinted fill swallows the number.
const FILL_MIX := 0.14
const BORDER_WIDTH := 2

@onready var _icon: TextureRect = %Icon
@onready var _dot: ColorRect = %Dot
@onready var _amount_label: Label = %AmountLabel
@onready var _name_label: Label = %NameLabel

var _currency_key: String = ""
var _compact: bool = false


func _ready() -> void:
	# Palette colours are baked into a StyleBoxFlat here, so a dark/light
	# swap has to rebuild it.
	ThemeManager.theme_changed.connect(func() -> void:
		if _currency_key != "":
			set_currency(_currency_key)
	)


## currency_key is the BACKEND key ("credits"/"bucks"/"medals"), not the
## display name -- see CurrencyDisplay for why those differ.
func set_currency(currency_key: String) -> void:
	_currency_key = currency_key
	var color := CurrencyDisplay.color_for(currency_key)

	# Real icon when there's art for this currency, a tinted dot when there
	# isn't yet -- exactly one of the two is ever shown.
	var icon := CurrencyDisplay.icon_for(currency_key)
	_icon.texture = icon
	_icon.visible = icon != null
	_dot.visible = icon == null

	_dot.color = color
	_name_label.text = CurrencyDisplay.label_for(currency_key)
	_name_label.add_theme_color_override("font_color", color)
	_apply_sizes()

	add_theme_stylebox_override("panel", MenuTile.pixel_frame(
		MenuTile.BASE_FILL.lerp(color, FILL_MIX),
		color,
		BORDER_WIDTH,
		true,
		Vector2(6, 2) if _compact else Vector2(10, 4)
	))


## The HUD strip runs four of these across the top of the screen, so they
## shrink there; a chip sitting alone in a header keeps the full size.
func set_compact(value: bool) -> void:
	_compact = value
	if _currency_key != "":
		set_currency(_currency_key)
	else:
		_apply_sizes()


func _apply_sizes() -> void:
	if _icon == null:
		return
	var icon_px := 16 if _compact else 30
	_icon.custom_minimum_size = Vector2(icon_px, icon_px)
	_dot.custom_minimum_size = Vector2(8, 8)
	var row: HBoxContainer = _amount_label.get_parent()
	row.add_theme_constant_override("separation", 5 if _compact else 6)
	_amount_label.add_theme_font_size_override("font_size", 13 if _compact else 15)


func set_amount(value: int) -> void:
	_amount_label.text = CurrencyDisplay.format_amount(value)
