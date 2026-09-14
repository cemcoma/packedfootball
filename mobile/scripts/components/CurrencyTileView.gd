class_name CurrencyTileView
extends PanelContainer

## Reusable "pay X, get Y" tile for the Currency tab's Exchange and Cash
## sub-tabs. Leads with what you GET -- big icon, big number -- with the
## cost underneath in smaller muted text, since the reward is the thing
## worth reading first on a shop tile.
##
## Both sides show real currency art via CurrencyDisplay.icon_for() where
## it exists, falling back to the currency's name in text where it doesn't
## (medals today), so a missing sprite degrades to something readable
## rather than an empty gap. The Cash tab's cost is real money rather than
## a currency, so it uses set_cost_text() instead of set_cost_currency().
##
## The panel is tinted by the reward currency and rebuilt on
## ThemeManager.theme_changed, so it follows a dark/light swap rather than
## baking one palette into the scene.

signal action_pressed

@onready var _reward_icon: TextureRect = %RewardIcon
@onready var _reward_amount: Label = %RewardAmount
@onready var _cost_prefix: Label = %CostPrefixLabel
@onready var _cost_icon: TextureRect = %CostIcon
@onready var _cost_label: Label = %CostLabel
@onready var _action_button: Button = %ActionButton

var _reward_currency: String = "credits"


func _ready() -> void:
	_action_button.pressed.connect(func() -> void: action_pressed.emit())
	ThemeManager.theme_changed.connect(_restyle)
	_restyle()


func set_reward(currency_key: String, amount: int) -> void:
	_reward_currency = currency_key
	_reward_amount.text = _amount_with_name(currency_key, amount)
	_apply_icon(_reward_icon, currency_key)
	_restyle()


## Exchange tab: the cost is another in-game currency, shown with its icon.
func set_cost_currency(currency_key: String, amount: int) -> void:
	_cost_label.text = _amount_with_name(currency_key, amount)
	_apply_icon(_cost_icon, currency_key)


## Cash tab: the cost is real money, so there's no currency icon for it --
## just the localized/reference price string as-is.
func set_cost_text(text: String) -> void:
	_cost_label.text = text
	_cost_icon.visible = false


func set_action_text(text: String) -> void:
	_action_button.text = text


## Only meaningful for Exchange (spending cash can fail affordability) --
## Cash tiles pass whether a purchase is possible at all instead, since a
## real-money purchase has no client-side "insufficient balance" concept.
func set_affordable(can_afford: bool) -> void:
	_action_button.disabled = not can_afford


## Icon when there's art for this currency; when there isn't, fall back to
## naming the currency in the label rather than leaving a blank space.
func _apply_icon(target: TextureRect, currency_key: String) -> void:
	var icon := CurrencyDisplay.icon_for(currency_key)
	target.texture = icon
	target.visible = icon != null


func _amount_with_name(currency_key: String, amount: int) -> String:
	var amount_text := CurrencyDisplay.format_amount(amount)
	if CurrencyDisplay.icon_for(currency_key) != null:
		return amount_text  # the icon already says which currency this is
	return "%s %s" % [amount_text, CurrencyDisplay.lowercase_label_for(currency_key)]


func _restyle() -> void:
	var accent := CurrencyDisplay.color_for(_reward_currency)
	var surface: Color = ThemeManager.color("surface")

	var style := StyleBoxFlat.new()
	style.bg_color = surface.lerp(accent, 0.16)
	style.border_color = Color(accent.r, accent.g, accent.b, 0.6)
	style.set_border_width_all(2)
	style.set_corner_radius_all(12)
	# A soft drop shadow is what stops these reading as flat rectangles.
	style.shadow_color = Color(0, 0, 0, 0.35 if not ThemeManager.is_light() else 0.18)
	style.shadow_size = 4
	style.shadow_offset = Vector2(0, 2)
	add_theme_stylebox_override("panel", style)

	_reward_amount.add_theme_color_override("font_color", accent)
	_cost_prefix.add_theme_color_override("font_color", ThemeManager.color("text_muted"))
	_cost_label.add_theme_color_override("font_color", ThemeManager.color("text_muted"))
