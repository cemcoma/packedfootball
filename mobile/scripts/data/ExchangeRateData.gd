class_name ExchangeRateData
extends RefCounted

## Client-side mirror of one entry from GET /currency/exchange/list -- a
## fixed "spend bucks_cost bucks, get credits_reward credits" tier. No
## availability/expiry concept at all (unlike PackData/DealData) -- these
## rates are always on; the only thing that can block a redeem is not
## having enough bucks, checked server-side at redeem time (see
## POST /currency/exchange/redeem in backend/main.py).

static func _str(fields: Dictionary, key: String, default: String = "") -> String:
	var value = fields.get(key)
	return value if value is String else default


static func _int(fields: Dictionary, key: String, default: int = 0) -> int:
	var value = fields.get(key)
	return value if typeof(value) in [TYPE_INT, TYPE_FLOAT] else default


var tier_id: String = ""
var bucks_cost: int = 0
var credits_reward: int = 0


static func from_fields(fields: Dictionary) -> ExchangeRateData:
	var rate := ExchangeRateData.new()
	rate.tier_id = _str(fields, "tier_id")
	rate.bucks_cost = _int(fields, "bucks_cost")
	rate.credits_reward = _int(fields, "credits_reward")
	return rate
