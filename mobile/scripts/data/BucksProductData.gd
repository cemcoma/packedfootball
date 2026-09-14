class_name BucksProductData
extends RefCounted

## Client-side mirror of one entry from GET /currency/bucks/list -- a
## real-money product: pay (roughly) usd_reference_price_cents, get
## bucks_amount bucks. usd_reference_price_cents is a display fallback
## only -- once IapClient's platform plugin is actually wired, prefer its
## own localized price string per product_id over this field (see
## CurrencyPanel.gd's Bucks tab), since Apple/Google own actual regional
## pricing, not this server.

static func _str(fields: Dictionary, key: String, default: String = "") -> String:
	var value = fields.get(key)
	return value if value is String else default


static func _int(fields: Dictionary, key: String, default: int = 0) -> int:
	var value = fields.get(key)
	return value if typeof(value) in [TYPE_INT, TYPE_FLOAT] else default


var product_id: String = ""
var bucks_amount: int = 0
var usd_reference_price_cents: int = 0


static func from_fields(fields: Dictionary) -> BucksProductData:
	var product := BucksProductData.new()
	product.product_id = _str(fields, "product_id")
	product.bucks_amount = _int(fields, "bucks_amount")
	product.usd_reference_price_cents = _int(fields, "usd_reference_price_cents")
	return product


## "$X.XX" from cents -- e.g. 500 -> "$5.00". Display fallback only, see
## this class's own doc comment above.
func reference_price_text() -> String:
	return "$%.2f" % (usd_reference_price_cents / 100.0)
