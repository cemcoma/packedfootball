extends Node

## Thin wrapper around the GodotxRevenueCat plugin
## (res://addons/godotx_revenue_cat/) -- nothing outside this one file
## should ever touch that singleton directly. API confirmed from the
## plugin's own README: singleton name "GodotxRevenueCat",
## initialize(api_key, user_id, debug) / login(user_id) / logout() /
## purchase(product_id), and a purchase_result(data: Dictionary) signal
## carrying an "error" key ("" on success).
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

var _revenuecat = null

# Only one purchase can realistically be in flight at a time (the purchase
# sheet is modal -- the player can't start a second one before this
# resolves), so a single pending id is enough; matches every other
# "one thing in flight" flow already in this client (packs, deals).
var _pending_product_id: String = ""


func _ready() -> void:
	if Engine.has_singleton("GodotxRevenueCat"):
		_revenuecat = Engine.get_singleton("GodotxRevenueCat")
		_revenuecat.purchase_result.connect(_on_purchase_result)


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


func _on_purchase_result(data: Dictionary) -> void:
	var product_id := _pending_product_id
	_pending_product_id = ""
	var error: String = data.get("error", "")
	if error == "":
		purchase_completed.emit(product_id)
	else:
		purchase_failed.emit(product_id, error)
