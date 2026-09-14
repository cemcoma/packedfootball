class_name DealView
extends Control

## Reusable deal "box" visual for the Deals sub-tab -- closely mirrors
## PackView.gd (deals genuinely have availability/expiry/teasing, same as
## packs: a real "Redeem" button that swaps for a tag label when
## !available), but deliberately has NO info/odds-popup button. PackView's
## info button exists specifically for App Store Guideline 3.1.1's
## randomized-reward odds disclosure (see PackInfoPopup.gd's own doc
## comment) -- a deal's reward is fixed and fully known upfront (shown
## directly on the tile), so there's nothing to disclose.

signal redeem_pressed

@onready var _name_label: Label = %NameLabel
@onready var _description_label: Label = %DescriptionLabel
@onready var _cost_label: Label = %CostLabel
@onready var _reward_label: Label = %RewardLabel
@onready var _limited_label: Label = %LimitedLabel
@onready var _tag_label: Label = %TagLabel
@onready var _redeem_button: Button = %RedeemButton

var _deal: DealData = null
var _affordable: bool = true


func _ready() -> void:
	_redeem_button.pressed.connect(_on_redeem_button_pressed)


func _on_redeem_button_pressed() -> void:
	redeem_pressed.emit()


func set_deal(deal: DealData) -> void:
	_deal = deal
	_name_label.text = deal.deal_name
	_description_label.text = deal.description
	_cost_label.text = "%d %s" % [deal.cost_amount, CurrencyDisplay.lowercase_label_for(deal.cost_currency)]
	_reward_label.text = _reward_text(deal)
	_limited_label.text = deal.limited_label()
	_limited_label.visible = deal.is_limited()
	_refresh_redeem_button()


static func _reward_text(deal: DealData) -> String:
	var parts: Array[String] = []
	if deal.reward_credits > 0:
		parts.append("%d %s" % [deal.reward_credits, CurrencyDisplay.lowercase_label_for("credits")])
	if deal.reward_bucks > 0:
		parts.append("%d %s" % [deal.reward_bucks, CurrencyDisplay.lowercase_label_for("bucks")])
	return " + ".join(parts) if not parts.is_empty() else "--"


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
