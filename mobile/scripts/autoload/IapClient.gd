extends Node

## Thin wrapper around the GodotxRevenueCat plugin
## (res://addons/godotx_revenue_cat/) -- nothing outside this one file
## should ever touch that singleton directly. API confirmed from the
## plugin's own README: singleton name "GodotxRevenueCat",
## initialize(api_key, user_id, debug) / login(user_id) / logout() /
## purchase(product_id) / fetch_products(ids), a purchase_result(data:
## Dictionary) signal carrying an "error" key ("" on success), and a
## products(data: Dictionary) signal answering fetch_products.
##
## The actual purchase GRANT does not happen through this client at all --
## RevenueCat verifies the purchase with Apple/Google itself and notifies
## the backend directly via a server-to-server webhook (see
## backend/main.py's POST /webhooks/revenuecat), independent of whether
## this client is even still running by the time that lands. This file's
## signals are for UI feedback only ("thanks!" / "that didn't work"), not
## for granting anything -- there's no receipt data to forward anywhere
## anymore, unlike the pre-RevenueCat design this replaced.

signal purchase_completed(product_id: String)
signal purchase_failed(product_id: String, reason: String)
## The store answered fetch_localized_prices(); localized_price() now has
## something for the ids it knew. Never fires when the plugin isn't there.
signal prices_updated

var _revenuecat = null

## product_id -> the price string the store itself shows for it, in the
## storefront's own currency and formatting ("₺49,99", "$4.99", "4,99 €").
## Apple/Google own regional pricing, so this is the only honest number to
## put on a Buy button; the backend's usd_reference_price_cents is just the
## fallback for a build with no store plugin (see BucksProductData). Kept
## across shop visits, since the store's answer doesn't change mid-session.
var _localized_prices: Dictionary = {}

# Only one purchase can realistically be in flight at a time (the purchase
# sheet is modal -- the player can't start a second one before this
# resolves), so a single pending id is enough; matches every other
# "one thing in flight" flow already in this client (packs, deals).
var _pending_product_id: String = ""


func _ready() -> void:
	if Engine.has_singleton("GodotxRevenueCat"):
		_revenuecat = Engine.get_singleton("GodotxRevenueCat")
		_revenuecat.purchase_result.connect(_on_purchase_result)
		_revenuecat.products.connect(_on_products_received)


func is_available() -> bool:
	return _revenuecat != null


## Call once, right after sign-in succeeds (see Auth.gd's _go_to_menu) --
## uid becomes RevenueCat's app_user_id, which is what the backend webhook
## uses to know which account to credit.
func initialize_for_signed_in_user(uid: String) -> void:
	if not is_available():
		return
	var api_key: String = (
		RevenueCatConfig.REVENUECAT_IOS_API_KEY if OS.get_name() == "iOS"
		else RevenueCatConfig.REVENUECAT_ANDROID_API_KEY
	)
	if api_key == "":
		return  # this platform's key isn't set up yet -- see RevenueCatConfig.gd
	_revenuecat.initialize(api_key, uid, false)


func purchase(product_id: String) -> void:
	if not is_available():
		purchase_failed.emit(product_id, "In-app purchases are not available on this build")
		return
	_pending_product_id = product_id
	_revenuecat.purchase(product_id)


## Asks the store for these products' details -- really just for their
## localized price strings. Fire-and-forget like purchase(): the answer
## arrives on prices_updated. Ids already known are still re-requested; the
## store's answer is cheap and this keeps a stale miss from sticking.
func fetch_localized_prices(product_ids: Array) -> void:
	if not is_available() or product_ids.is_empty():
		return
	_revenuecat.fetch_products(product_ids)


## What the store shows for this product, or "" when it hasn't answered
## (yet, or at all -- no plugin on this build, or an id the store doesn't
## know). Callers fall back to BucksProductData.reference_price_text().
func localized_price(product_id: String) -> String:
	return _localized_prices.get(product_id, "")


## "products" comes back as a native Array on iOS but a JavaObject
## (java.util.List) on Android -- the plugin's README documents both and
## the unwrapping below is lifted from its own example.
func _on_products_received(data: Dictionary) -> void:
	var error: String = data.get("error", "")
	if error != "":
		push_warning("RevenueCat fetch_products failed: %s" % error)
		return

	var raw_products = data.get("products")
	var products: Array = []
	if raw_products is Array:
		products = raw_products
	elif raw_products != null and raw_products is JavaObject:
		var count: int = raw_products.call("size")
		for i in range(count):
			products.append(raw_products.call("get", i))

	var changed := false
	for product in products:
		if not (product is Dictionary):
			continue
		var id = product.get("id")
		var price = product.get("price")
		if id is String and id != "" and price is String and price != "":
			_localized_prices[id] = price
			changed = true
	if changed:
		prices_updated.emit()


func _on_purchase_result(data: Dictionary) -> void:
	var product_id := _pending_product_id
	_pending_product_id = ""
	var error: String = data.get("error", "")
	if error == "":
		purchase_completed.emit(product_id)
	else:
		purchase_failed.emit(product_id, error)
