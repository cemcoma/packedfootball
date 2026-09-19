class_name DealData
extends RefCounted

## Client-side deal listing data -- mirrors the shape backend/main.py's
## GET /deals/list returns. Closely mirrors PackData.gd (deals genuinely
## have availability/expiry/teasing, same as packs), but reward_credits/
## reward_bucks/cost_currency/cost_amount replace price/cards_per_pack/
## rates/pos_rates -- a deal's reward is fixed and known upfront, so there's
## nothing to disclose the way packs' randomized rates need PackInfoPopup
## for. Display-only, same boundary PackData.gd draws: no redeeming logic
## lives here (see DealView.gd's action_pressed signal / CurrencyPanel.gd's
## handler, which calls POST /deals/redeem).
##
## "deal_id" is a string slug (e.g. "welcome_bundle"), the same arrangement
## as PackData.pack_id -- an id an admin can recognise in the Firestore
## console, and one the console lists in a meaningful order.

static func _str(fields: Dictionary, key: String, default: String = "") -> String:
	var value = fields.get(key)
	return value if value is String else default


static func _int(fields: Dictionary, key: String, default: int = 0) -> int:
	var value = fields.get(key)
	return value if typeof(value) in [TYPE_INT, TYPE_FLOAT] else default


static func _bool(fields: Dictionary, key: String, default: bool) -> bool:
	var value = fields.get(key)
	return value if value is bool else default


var deal_id: String = ""
var deal_name: String = ""
var description: String = ""
var cost_currency: String = "credits"
var cost_amount: int = 0
var reward_credits: int = 0
var reward_bucks: int = 0
var max_redemptions = null  # int or null (no global cap)
var times_redeemed: int = 0
var remaining_redemptions = null  # int or null (unlimited)
var expires_at: String = ""

var available: bool = true  # can THIS account actually redeem this right now?
var unavailable_reason: String = ""  # e.g. "You've already redeemed this deal" -- only meaningful when !available
var available_at: String = ""  # e.g. a not-yet-active deal's planned on-sale date -- purely a display hint


static func from_fields(fields: Dictionary) -> DealData:
	var deal := DealData.new()
	deal.deal_id = _str(fields, "deal_id")
	deal.deal_name = _str(fields, "name")
	deal.description = _str(fields, "description")
	deal.cost_currency = _str(fields, "cost_currency", "credits")
	deal.cost_amount = _int(fields, "cost_amount")
	deal.reward_credits = _int(fields, "reward_credits")
	deal.reward_bucks = _int(fields, "reward_bucks")
	deal.max_redemptions = fields.get("max_redemptions")  # untyped var -- null is a valid value here, no coercion needed
	deal.times_redeemed = _int(fields, "times_redeemed")
	deal.remaining_redemptions = fields.get("remaining_redemptions")
	deal.expires_at = _str(fields, "expires_at")

	deal.available = _bool(fields, "available", true)
	deal.unavailable_reason = _str(fields, "unavailable_reason")
	deal.available_at = _str(fields, "available_at")
	return deal


func is_limited() -> bool:
	return max_redemptions != null


func limited_label() -> String:
	if not is_limited():
		return ""
	return "%d left!" % remaining_redemptions


## What to show in place of (or alongside) the redeem button when this deal
## isn't redeemable right now for THIS account. "" means it is -- show the
## normal redeem button instead. Identical priority order to PackData's own
## tag_text(): a planned on-sale date beats the raw reason (more useful to
## a player), which beats a generic fallback.
func tag_text() -> String:
	if available:
		return ""
	if available_at != "":
		return TranslationServer.translate("Available %s") % available_at.split("T")[0]
	if unavailable_reason != "":
		return unavailable_reason
	return TranslationServer.translate("Not available")
