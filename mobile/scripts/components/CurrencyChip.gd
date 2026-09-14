class_name CurrencyChip
extends PanelContainer

## One currency's balance as a tinted pill -- a colored dot, the amount, and
## the currency's name -- replacing the bare "0 credits" Labels the Shop
## header used to show. Everything about how a currency reads (its name, its
## accent color, thousand separators) comes from CurrencyDisplay, so all
## three chips stay consistent with each other and with every other place a
## currency appears.
##
## The panel StyleBox is built in code rather than baked into the .tscn,
## because its tint depends on which currency the chip is showing -- one
## scene, three different looks, no per-currency scene duplication.

@onready var _icon: TextureRect = %Icon
@onready var _dot: ColorRect = %Dot
@onready var _amount_label: Label = %AmountLabel
@onready var _name_label: Label = %NameLabel

var _currency_key: String = ""


func _ready() -> void:
	# Palette colors are baked into a StyleBoxFlat here, so a dark/light
	# swap has to rebuild it -- widgets that only use themed Button/Panel
	# styles get restyled for free, but this one doesn't.
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

	var style := StyleBoxFlat.new()
	style.bg_color = Color(color.r, color.g, color.b, 0.14)
	style.border_color = Color(color.r, color.g, color.b, 0.55)
	style.set_border_width_all(1)
	style.set_corner_radius_all(10)
	style.content_margin_left = 10.0
	style.content_margin_right = 10.0
	style.content_margin_top = 4.0
	style.content_margin_bottom = 4.0
	add_theme_stylebox_override("panel", style)


func set_amount(value: int) -> void:
	_amount_label.text = CurrencyDisplay.format_amount(value)
