class_name EnergyProductData
extends RefCounted

## Client-side mirror of one entry from GET /energy/refill/list -- a fixed
## "spend bucks_cost cash, get energy back" refill. Shaped exactly like
## ExchangeRateData because the backend catalog is shaped exactly like the
## credits exchange, deliberately, so both render through CurrencyTileView.
##
## energy_amount is the one thing that differs: the backend sends null for
## the product that fills the bar, because how much that actually grants
## depends on where the bar is when it's bought. -1 is the local stand-in
## for that null (an int field can't hold it), and fills_bar() is what
## callers should ask rather than comparing against the sentinel.

static func _str(fields: Dictionary, key: String, default: String = "") -> String:
	var value = fields.get(key)
	return value if value is String else default


static func _int(fields: Dictionary, key: String, default: int = 0) -> int:
	var value = fields.get(key)
	return value if typeof(value) in [TYPE_INT, TYPE_FLOAT] else default


const FILLS_BAR := -1

var product_id: String = ""
var bucks_cost: int = 0
var energy_amount: int = FILLS_BAR


static func from_fields(fields: Dictionary) -> EnergyProductData:
	var product := EnergyProductData.new()
	product.product_id = _str(fields, "product_id")
	product.bucks_cost = _int(fields, "bucks_cost")
	product.energy_amount = _int(fields, "energy_amount", FILLS_BAR)
	return product


func fills_bar() -> bool:
	return energy_amount <= 0
