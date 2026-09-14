class_name CurrencyPanel
extends Control

## The Currency tab's own 3 sub-tabs -- Exchange (spend bucks for credits),
## Bucks (real-money IAP), Deals (DB-based timed offers) -- instanced
## inside Shop.tscn's CurrencyPanel node, replacing the old "Coming soon."
## placeholder. Same ButtonGroup + toggle-Button + lazy-load-once-per-tab
## pattern Leaderboard.gd already established, one tab wider.
##
## Emits currency_changed after any successful redeem so Shop.gd can
## refresh its header labels -- this panel never touches Shop's header
## directly, keeping the two only coupled through one signal.

signal currency_changed

const CURRENCY_TILE_SCENE := preload("res://scenes/components/CurrencyTileView.tscn")
const DEAL_VIEW_SCENE := preload("res://scenes/components/DealView.tscn")

@onready var _exchange_tab_button: Button = %ExchangeTabButton
@onready var _bucks_tab_button: Button = %BucksTabButton
@onready var _deals_tab_button: Button = %DealsTabButton

@onready var _status_label: Label = %StatusLabel

@onready var _exchange_scroll: ScrollContainer = %ExchangeScroll
@onready var _exchange_grid: HBoxContainer = %ExchangeGrid
@onready var _bucks_scroll: ScrollContainer = %BucksScroll
@onready var _bucks_grid: HBoxContainer = %BucksGrid
@onready var _deals_scroll: ScrollContainer = %DealsScroll
@onready var _deals_grid: HBoxContainer = %DealsGrid

var _exchange_loaded: bool = false
var _bucks_loaded: bool = false
var _deals_loaded: bool = false

var _exchange_rates: Array = []  # ExchangeRateData
var _bucks_products: Array = []  # BucksProductData
var _deals: Array = []  # DealData


func _ready() -> void:
	_exchange_tab_button.pressed.connect(_on_exchange_tab_pressed)
	_bucks_tab_button.pressed.connect(_on_bucks_tab_pressed)
	_deals_tab_button.pressed.connect(_on_deals_tab_pressed)
	IapClient.purchase_completed.connect(_on_iap_purchase_completed)
	IapClient.purchase_failed.connect(_on_iap_purchase_failed)

	await _load_exchange()


func _on_exchange_tab_pressed() -> void:
	_exchange_scroll.visible = true
	_bucks_scroll.visible = false
	_deals_scroll.visible = false
	if not _exchange_loaded:
		await _load_exchange()


func _on_bucks_tab_pressed() -> void:
	_exchange_scroll.visible = false
	_bucks_scroll.visible = true
	_deals_scroll.visible = false
	if not _bucks_loaded:
		await _load_bucks()


func _on_deals_tab_pressed() -> void:
	_exchange_scroll.visible = false
	_bucks_scroll.visible = false
	_deals_scroll.visible = true
	if not _deals_loaded:
		await _load_deals()


# ============================================================ Exchange tab

func _load_exchange() -> void:
	_status_label.text = "Loading..."
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/currency/exchange/list")
	if not res.ok:
		_status_label.text = "Could not load exchange rates -- try again later."
		return
	_exchange_loaded = true
	_status_label.text = ""

	_exchange_rates = []
	for fields in res.data.get("rates", []):
		_exchange_rates.append(ExchangeRateData.from_fields(fields))
	_populate_exchange_grid()


## Same remove_child()-then-queue_free() pairing Shop.gd's pack grid and
## Leaderboard.gd's lists both use. Re-run (with no re-fetch) after a
## successful exchange to re-derive affordability against the now-updated
## GameProfile.bucks -- the rate catalog itself never changes.
func _populate_exchange_grid() -> void:
	for child in _exchange_grid.get_children():
		_exchange_grid.remove_child(child)
		child.queue_free()

	if _exchange_rates.is_empty():
		var empty_label := Label.new()
		empty_label.text = "No exchange rates available right now."
		_exchange_grid.add_child(empty_label)
		return

	for rate in _exchange_rates:
		var typed_rate: ExchangeRateData = rate
		var tile: CurrencyTileView = CURRENCY_TILE_SCENE.instantiate()
		_exchange_grid.add_child(tile)
		tile.set_tile(
			"%d %s" % [typed_rate.bucks_cost, CurrencyDisplay.lowercase_label_for("bucks")],
			"%d %s" % [typed_rate.credits_reward, CurrencyDisplay.lowercase_label_for("credits")],
			"Exchange"
		)
		tile.set_affordable(GameProfile.bucks >= typed_rate.bucks_cost)
		tile.action_pressed.connect(_on_exchange_tile_pressed.bind(typed_rate))


func _on_exchange_tile_pressed(rate: ExchangeRateData) -> void:
	if GameProfile.bucks < rate.bucks_cost:
		_status_label.text = "Not enough %s for this exchange." % CurrencyDisplay.lowercase_label_for("bucks")
		return
	_status_label.text = "Exchanging..."
	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST, "/currency/exchange/redeem", {"tier_id": rate.tier_id}
	)
	if not res.ok:
		_status_label.text = "Could not exchange -- try again."
		return
	_status_label.text = ""
	GameProfile.apply_currency_balances(res.data.get("credits_remaining"), res.data.get("bucks_remaining"))
	currency_changed.emit()
	_populate_exchange_grid()


# ============================================================ Bucks tab

func _load_bucks() -> void:
	_status_label.text = "Loading..."
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/currency/bucks/list")
	if not res.ok:
		_status_label.text = "Could not load the %s catalog -- try again later." % CurrencyDisplay.lowercase_label_for("bucks")
		return
	_bucks_loaded = true
	_status_label.text = ""

	_bucks_products = []
	for fields in res.data.get("products", []):
		_bucks_products.append(BucksProductData.from_fields(fields))
	_populate_bucks_grid()


## Unlike Exchange/Deals, a bucks tile never carries a per-tile affordability
## check (a real-money purchase has no "insufficient balance" concept
## client-side) -- what it DOES carry is whether IapClient.is_available()
## at all, which is false on every platform until a real plugin exists (see
## IapClient.gd), so tiles show real content but stay disabled/relabeled
## rather than pretending a purchase would work.
func _populate_bucks_grid() -> void:
	for child in _bucks_grid.get_children():
		_bucks_grid.remove_child(child)
		child.queue_free()

	if _bucks_products.is_empty():
		var empty_label := Label.new()
		empty_label.text = "No %s packages available right now." % CurrencyDisplay.lowercase_label_for("bucks")
		_bucks_grid.add_child(empty_label)
		return

	var available := IapClient.is_available()
	for product in _bucks_products:
		var typed_product: BucksProductData = product
		var tile: CurrencyTileView = CURRENCY_TILE_SCENE.instantiate()
		_bucks_grid.add_child(tile)
		tile.set_tile(
			typed_product.reference_price_text(),
			"%d %s" % [typed_product.bucks_amount, CurrencyDisplay.lowercase_label_for("bucks")],
			"Buy" if available else "Coming Soon"
		)
		tile.set_affordable(available)
		tile.action_pressed.connect(_on_bucks_tile_pressed.bind(typed_product))


func _on_bucks_tile_pressed(product: BucksProductData) -> void:
	_status_label.text = "Starting purchase..."
	IapClient.purchase(product.product_id)


## IapClient.purchase() is fire-and-forget (a real platform purchase sheet
## is an OS-level async UI flow, not something a single function call can
## meaningfully await) -- these two connect once in _ready() instead, and
## do the actual follow-up work whenever a purchase eventually resolves.
##
## Unlike the old direct-Apple-verification design, THIS client never
## calls the backend to redeem the purchase at all -- RevenueCat verifies
## it and notifies the backend directly via a server-to-server webhook
## (POST /webhooks/revenuecat), independent of whether this client is
## even still running by the time that lands. There's no receipt data
## here to forward anywhere; all this does is give the player honest
## feedback and refresh the cached balance once it's had a moment to land.
func _on_iap_purchase_completed(product_id: String) -> void:
	_status_label.text = "Purchase successful! Updating your balance..."
	await get_tree().create_timer(2.0).timeout  # give the webhook a moment to land before refetching
	await GameProfile.load_all()
	_status_label.text = "Purchase successful!"
	currency_changed.emit()


func _on_iap_purchase_failed(product_id: String, reason: String) -> void:
	_status_label.text = reason


# ============================================================ Deals tab

func _load_deals() -> void:
	_status_label.text = "Loading..."
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/deals/list")
	if not res.ok:
		_status_label.text = "Could not load deals -- try again later."
		return
	_deals_loaded = true
	_status_label.text = ""

	_deals = []
	for fields in res.data.get("deals", []):
		_deals.append(DealData.from_fields(fields))
	_populate_deals_grid()


func _populate_deals_grid() -> void:
	for child in _deals_grid.get_children():
		_deals_grid.remove_child(child)
		child.queue_free()

	if _deals.is_empty():
		var empty_label := Label.new()
		empty_label.text = "No deals available right now."
		_deals_grid.add_child(empty_label)
		return

	for deal in _deals:
		var typed_deal: DealData = deal
		var view: DealView = DEAL_VIEW_SCENE.instantiate()
		_deals_grid.add_child(view)
		view.set_deal(typed_deal)
		var balance: int = GameProfile.bucks if typed_deal.cost_currency == "bucks" else GameProfile.credits
		view.set_affordable(balance >= typed_deal.cost_amount)
		view.redeem_pressed.connect(_on_deal_redeem_pressed.bind(typed_deal))


func _on_deal_redeem_pressed(deal: DealData) -> void:
	var balance: int = GameProfile.bucks if deal.cost_currency == "bucks" else GameProfile.credits
	if balance < deal.cost_amount:
		_status_label.text = "Not enough %s for %s." % [CurrencyDisplay.lowercase_label_for(deal.cost_currency), deal.deal_name]
		return
	_status_label.text = "Redeeming %s..." % deal.deal_name
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_POST, "/deals/redeem", {"deal_id": deal.deal_id})
	if not res.ok:
		_status_label.text = "Could not redeem %s -- try again." % deal.deal_name
		return
	_status_label.text = ""
	GameProfile.apply_currency_balances(res.data.get("credits_remaining"), res.data.get("bucks_remaining"))
	currency_changed.emit()
	# Re-fetch rather than locally patch -- this deal's own remaining
	# redemptions (both global and per-account) just changed server-side.
	await _load_deals()
