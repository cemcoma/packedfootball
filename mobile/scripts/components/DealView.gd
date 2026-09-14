class_name DealView
extends PanelContainer

## Reusable deal "box" visual for the Deals sub-tab -- closely mirrors
## PackView.gd (deals genuinely have availability/expiry/teasing, same as
## packs: a real "Redeem" button that swaps for a tag label when
## !available), but deliberately has NO info/odds-popup button. PackView's
## info button exists specifically for App Store Guideline 3.1.1's
## randomized-reward odds disclosure (see PackInfoPopup.gd's own doc
## comment) -- a deal's reward is fixed and fully known upfront (shown
## directly on the tile), so there's nothing to disclose.

const CURRENCY_AMOUNT_SCENE := preload("res://scenes/components/CurrencyAmount.tscn")

signal redeem_pressed

@onready var _name_label: Label = %NameLabel
@onready var _description_label: Label = %DescriptionLabel
@onready var _cost_prefix: Label = %CostPrefixLabel
@onready var _cost_amount: CurrencyAmount = %CostAmount
@onready var _reward_row: HBoxContainer = %RewardRow
@onready var _limited_label: Label = %LimitedLabel
@onready var _tag_label: Label = %TagLabel
@onready var _redeem_button: Button = %RedeemButton

var _deal: DealData = null
var _affordable: bool = true


func _ready() -> void:
	_redeem_button.pressed.connect(_on_redeem_button_pressed)
	ThemeManager.theme_changed.connect(_restyle)
	_restyle()


## Deals are promotional rather than tied to one currency, so they take the
## palette's accent color rather than a per-currency tint -- same rounded,
## bordered, softly-shadowed panel the currency tiles use, so the two read
## as the same family. Rebuilt on theme_changed like everything else that
## draws with palette colors.
func _restyle() -> void:
	var accent: Color = ThemeManager.color("accent")
	var surface: Color = ThemeManager.color("surface")

	var style := StyleBoxFlat.new()
	style.bg_color = surface.lerp(accent, 0.14)
	style.border_color = Color(accent.r, accent.g, accent.b, 0.6)
	style.set_border_width_all(2)
	style.set_corner_radius_all(12)
	style.shadow_color = Color(0, 0, 0, 0.18 if ThemeManager.is_light() else 0.35)
	style.shadow_size = 4
	style.shadow_offset = Vector2(0, 2)
	add_theme_stylebox_override("panel", style)

	_name_label.add_theme_color_override("font_color", accent)
	_description_label.add_theme_color_override("font_color", ThemeManager.color("text_muted"))
	_cost_prefix.add_theme_color_override("font_color", ThemeManager.color("text_muted"))


func _on_redeem_button_pressed() -> void:
	redeem_pressed.emit()


func set_deal(deal: DealData) -> void:
	_deal = deal
	_name_label.text = deal.deal_name
	_description_label.text = deal.description
	_cost_amount.set_amount(deal.cost_currency, deal.cost_amount)
	_populate_rewards(deal)
	_limited_label.text = deal.limited_label()
	_limited_label.visible = deal.is_limited()
	_refresh_redeem_button()


## A deal can pay out in more than one currency at once, so the reward line
## is however many CurrencyAmounts it takes -- same disposable-child
## repopulation pattern every grid in this project uses, since set_deal()
## can run again on the same view.
func _populate_rewards(deal: DealData) -> void:
	for child in _reward_row.get_children():
		_reward_row.remove_child(child)
		child.queue_free()

	for pair in [["credits", deal.reward_credits], ["bucks", deal.reward_bucks]]:
		var amount: int = pair[1]
		if amount <= 0:
			continue
		var reward: CurrencyAmount = CURRENCY_AMOUNT_SCENE.instantiate()
		_reward_row.add_child(reward)
		reward.set_amount(pair[0], amount)
		reward.set_sizes(26, 20)


## GET /deals/list's own "available" only covers active/expiry/redemption
## caps -- like PackData.available, it says nothing about whether THIS
## account can afford cost_amount right now. That's a separate client-side
## check (mirrors Shop.gd calling PackView.set_affordable()), re-validated
## server-side regardless at redeem time either way.
func set_affordable(can_afford: bool) -> void:
	_affordable = can_afford
	_refresh_redeem_button()


## Same "unavailable always wins" rule PackView.gd's own version of this
## follows -- a teased/exhausted deal shows its tag regardless of whether
## the player could otherwise afford it.
func _refresh_redeem_button() -> void:
	if _deal == null:
		return
	if not _deal.available:
		_tag_label.text = _deal.tag_text()
		_tag_label.visible = true
		_redeem_button.visible = false
		return
	_tag_label.visible = false
	_redeem_button.visible = true
	_redeem_button.disabled = not _affordable
