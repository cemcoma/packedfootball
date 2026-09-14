class_name CurrencyAmount
extends HBoxContainer

## "<icon> 1,250" -- an amount next to its currency's art, for everywhere a
## price or reward is shown (pack price, deal cost/reward). One component
## rather than each screen hand-rolling its own icon+label pair, so a
## currency reads identically wherever it appears.
##
## Falls back to naming the currency in text when it has no art yet
## (medals today) -- a missing sprite degrades to something readable
## instead of leaving a bare number with no idea what it's counting.

@onready var _icon: TextureRect = %Icon
@onready var _label: Label = %Label

var _currency_key: String = "credits"
var _amount: int = 0
var _icon_size: int = 18
var _font_size: int = 14


func _ready() -> void:
	ThemeManager.theme_changed.connect(_refresh)
	_refresh()


func set_amount(currency_key: String, amount: int) -> void:
	_currency_key = currency_key
	_amount = amount
	_refresh()


## Both scale together -- a price on a pack box wants to be bigger than one
## in a deal's fine print, but the icon should never dwarf its number.
func set_sizes(icon_size: int, font_size: int) -> void:
	_icon_size = icon_size
	_font_size = font_size
	_refresh()


func _refresh() -> void:
	if _icon == null:
		return  # set_amount() before _ready(); _refresh() runs again there

	var icon := CurrencyDisplay.icon_for(_currency_key)
	_icon.texture = icon
	_icon.visible = icon != null
	_icon.custom_minimum_size = Vector2(_icon_size, _icon_size)

	var amount_text := CurrencyDisplay.format_amount(_amount)
	_label.text = amount_text if icon != null else "%s %s" % [
		amount_text, CurrencyDisplay.lowercase_label_for(_currency_key)
	]
	_label.add_theme_font_size_override("font_size", _font_size)
	_label.add_theme_color_override("font_color", CurrencyDisplay.color_for(_currency_key))
