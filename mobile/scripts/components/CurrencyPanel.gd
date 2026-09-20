class_name CurrencyPanel
extends Control

## The Currency tab's own sub-tabs -- Exchange (spend cash for credits),
## Cash (real-money IAP), Deals (DB-based timed offers), Energy (buy the
## match bar back with cash), and Free (rewarded ads, a deliberate stub --
## see _on_ads_tab_pressed) -- instanced inside Shop.tscn's CurrencyPanel
## node, replacing the old "Coming soon." placeholder. Same ButtonGroup +
## toggle-Button + lazy-load-once-per-tab pattern Leaderboard.gd already
## established, a couple of tabs wider.
##
## Free stays LAST deliberately: it's the only tab that sells nothing, so it
## reads as the footnote to the real storefront rather than an option among
## it. Energy sits just before it, next to the other things bought with cash.
##
## "Cash" is the display name; "bucks" stays the backend/field name
## everywhere in code -- see CurrencyDisplay.gd for why those differ.
##
## Emits currency_changed after anything that moves a number in Shop's
## header -- a redeem, an IAP landing, or an energy re-read -- so Shop.gd can
## refresh its labels AND its energy bar. This panel never touches Shop's
## header directly, keeping the two only coupled through one signal.

signal currency_changed

const CURRENCY_TILE_SCENE := preload("res://scenes/components/CurrencyTileView.tscn")
const DEAL_VIEW_SCENE := preload("res://scenes/components/DealView.tscn")
const AD_VIEW_SCENE := preload("res://scenes/components/AdView.tscn")

@onready var _exchange_tab_button: Button = %ExchangeTabButton
@onready var _bucks_tab_button: Button = %BucksTabButton
@onready var _deals_tab_button: Button = %DealsTabButton
@onready var _energy_tab_button: Button = %EnergyTabButton
@onready var _ads_tab_button: Button = %AdsTabButton

@onready var _status_label: Label = %StatusLabel

@onready var _exchange_scroll: ScrollContainer = %ExchangeScroll
@onready var _exchange_grid: HBoxContainer = %ExchangeGrid
@onready var _bucks_scroll: ScrollContainer = %BucksScroll
@onready var _bucks_grid: HBoxContainer = %BucksGrid
@onready var _deals_scroll: ScrollContainer = %DealsScroll
@onready var _deals_grid: HBoxContainer = %DealsGrid
@onready var _energy_scroll: ScrollContainer = %EnergyScroll
@onready var _energy_grid: HBoxContainer = %EnergyGrid
@onready var _ads_scroll: ScrollContainer = %AdsScroll
@onready var _ads_grid: HBoxContainer = %AdsGrid

var _exchange_loaded: bool = false
var _bucks_loaded: bool = false
var _deals_loaded: bool = false

var _exchange_rates: Array = []  # ExchangeRateData
var _bucks_products: Array = []  # BucksProductData
var _deals: Array = []  # DealData
var _energy_products: Array = []  # EnergyProductData
var _ads_deals: Array = [] #AdData

## The cap the refill catalog was priced against. Comes from
## /energy/refill/list rather than being hardcoded, so raising ENERGY_MAX
## server-side doesn't quietly desync what this tab thinks "full" means.
var _energy_max: int = 10


func _ready() -> void:
	_exchange_tab_button.pressed.connect(_on_exchange_tab_pressed)
	_bucks_tab_button.pressed.connect(_on_bucks_tab_pressed)
	_deals_tab_button.pressed.connect(_on_deals_tab_pressed)
	_energy_tab_button.pressed.connect(_on_energy_tab_pressed)
	_ads_tab_button.pressed.connect(_on_ads_tab_pressed)
	IapClient.purchase_completed.connect(_on_iap_purchase_completed)
	IapClient.purchase_failed.connect(_on_iap_purchase_failed)
	IapClient.prices_updated.connect(_on_iap_prices_updated)

	await _load_exchange()
	if Engine.has_singleton("AdManager") or has_node("/root/AdManager"):
		AdManager.ad_reward_completed.connect(_on_ad_completed)

## One list to extend when a tab is added, rather than every handler having
## to remember to hide every sibling (which is exactly how a tab gets left
## visible underneath another one).
func _show_only(panel: Control) -> void:
	for candidate in [_exchange_scroll, _bucks_scroll, _deals_scroll, _energy_scroll, _ads_scroll]:
		candidate.visible = candidate == panel


func _on_exchange_tab_pressed() -> void:
	_show_only(_exchange_scroll)
	if not _exchange_loaded:
		await _load_exchange()


func _on_bucks_tab_pressed() -> void:
	_show_only(_bucks_scroll)
	if not _bucks_loaded:
		await _load_bucks()


func _on_deals_tab_pressed() -> void:
	_show_only(_deals_scroll)
	if not _deals_loaded:
		await _load_deals()


## Unlike every other tab, this one reloads on EVERY visit rather than once.
## The catalog itself is static, but the bar it's priced against refills on
## wall-clock time and every affordability check below is against that bar:
## a cached 10/10 from four minutes ago would offer refills the server then
## refuses, and a cached 3/10 would hide ones it would happily sell.
func _on_energy_tab_pressed() -> void:
	_show_only(_energy_scroll)
	await _load_energy()

func _on_ads_tab_pressed() -> void:
	_show_only(_ads_scroll)
	await _load_ads()


# ============================================================ Exchange tab

func _load_exchange() -> void:
	_status_label.text = tr("Loading...")
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/currency/exchange/list")
	if not res.ok:
		_status_label.text = tr("Could not load exchange rates -- try again later.")
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
		empty_label.text = tr("No exchange rates available right now.")
		_exchange_grid.add_child(empty_label)
		return

	for rate in _exchange_rates:
		var typed_rate: ExchangeRateData = rate
		var tile: CurrencyTileView = CURRENCY_TILE_SCENE.instantiate()
		_exchange_grid.add_child(tile)
		tile.set_reward("credits", typed_rate.credits_reward)
		tile.set_cost_currency("bucks", typed_rate.bucks_cost)
		tile.set_action_text(tr("Exchange"))
		tile.set_affordable(GameProfile.bucks >= typed_rate.bucks_cost)
		tile.action_pressed.connect(_on_exchange_tile_pressed.bind(typed_rate))


func _on_exchange_tile_pressed(rate: ExchangeRateData) -> void:
	if GameProfile.bucks < rate.bucks_cost:
		_status_label.text = tr("Not enough %s for this exchange.") % CurrencyDisplay.lowercase_label_for("bucks")
		return
	_status_label.text = tr("Exchanging...")
	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST, "/currency/exchange/redeem", {"tier_id": rate.tier_id}
	)
	if not res.ok:
		_status_label.text = tr("Could not exchange -- try again.")
		return
	_status_label.text = ""
	GameProfile.apply_currency_balances(res.data.get("credits_remaining"), res.data.get("bucks_remaining"))
	currency_changed.emit()
	_populate_exchange_grid()


# ============================================================ Bucks tab

func _load_bucks() -> void:
	_status_label.text = tr("Loading...")
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/currency/bucks/list")
	if not res.ok:
		_status_label.text = tr("Could not load the %s catalog -- try again later.") % CurrencyDisplay.lowercase_label_for("bucks")
		return
	_bucks_loaded = true
	_status_label.text = ""

	_bucks_products = []
	var product_ids: Array = []
	for fields in res.data.get("products", []):
		var product := BucksProductData.from_fields(fields)
		_bucks_products.append(product)
		product_ids.append(product.product_id)
	_populate_bucks_grid()
	# Tiles go up with the USD reference price first; the store's own
	# localized prices land on prices_updated and repaint them.
	IapClient.fetch_localized_prices(product_ids)


## Unlike Exchange/Deals, a bucks tile never carries a per-tile affordability
## check (a real-money purchase has no "insufficient balance" concept
## client-side) -- what it DOES carry is whether IapClient.is_available()
## at all, which is false on every platform until a real plugin exists (see
## IapClient.gd), so tiles show real content but stay disabled/relabeled
## rather than pretending a purchase would work.
##
## The price on each tile is the store's own localized string whenever
## IapClient has one ("₺49,99" on the Turkish App Store, say), and the
## backend's USD reference only until then / on a build with no store.
func _populate_bucks_grid() -> void:
	for child in _bucks_grid.get_children():
		_bucks_grid.remove_child(child)
		child.queue_free()

	if _bucks_products.is_empty():
		var empty_label := Label.new()
		empty_label.text = tr("No %s packages available right now.") % CurrencyDisplay.lowercase_label_for("bucks")
		_bucks_grid.add_child(empty_label)
		return

	var available := IapClient.is_available()
	for product in _bucks_products:
		var typed_product: BucksProductData = product
		var tile: CurrencyTileView = CURRENCY_TILE_SCENE.instantiate()
		_bucks_grid.add_child(tile)
		tile.set_reward("bucks", typed_product.bucks_amount)
		var store_price := IapClient.localized_price(typed_product.product_id)
		tile.set_cost_text(store_price if store_price != "" else typed_product.reference_price_text())
		tile.set_action_text(tr("Buy") if available else tr("Coming Soon"))
		tile.set_affordable(available)
		tile.action_pressed.connect(_on_bucks_tile_pressed.bind(typed_product))


## Repaints with the store's prices once they arrive -- only if the tab has
## been built, since the grid is populated from _load_bucks and a repaint
## before that would just draw an empty catalog.
func _on_iap_prices_updated() -> void:
	if _bucks_loaded:
		_populate_bucks_grid()


func _on_bucks_tile_pressed(product: BucksProductData) -> void:
	_status_label.text = tr("Starting purchase...")
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
	_status_label.text = tr("Purchase successful! Updating your balance...")
	await get_tree().create_timer(2.0).timeout  # give the webhook a moment to land before refetching
	await GameProfile.refresh_currencies()
	_status_label.text = tr("Purchase successful!")
	currency_changed.emit()


func _on_iap_purchase_failed(product_id: String, reason: String) -> void:
	_status_label.text = reason


# ============================================================ Deals tab

func _load_deals() -> void:
	_status_label.text = tr("Loading...")
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/deals/list")
	if not res.ok:
		_status_label.text = tr("Could not load deals -- try again later.")
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
		empty_label.text = tr("No deals available right now.")
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
		_status_label.text = tr("Not enough %s for %s.") % [CurrencyDisplay.lowercase_label_for(deal.cost_currency), deal.deal_name]
		return
	_status_label.text = tr("Redeeming %s...") % deal.deal_name
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_POST, "/deals/redeem", {"deal_id": deal.deal_id})
	if not res.ok:
		_status_label.text = tr("Could not redeem %s -- try again.") % deal.deal_name
		return
	_status_label.text = ""
	GameProfile.apply_currency_balances(res.data.get("credits_remaining"), res.data.get("bucks_remaining"))
	currency_changed.emit()
	# Re-fetch rather than locally patch -- this deal's own remaining
	# redemptions (both global and per-account) just changed server-side.
	await _load_deals()


# ============================================================ Energy tab

## Two requests, both needed: the catalog (what's for sale) and the bar
## itself (what any of it is worth right now). The bar is re-read rather
## than taken from the cached GameProfile.energy because it regenerates on
## wall-clock time -- see _on_energy_tab_pressed.
func _load_energy() -> void:
	_status_label.text = tr("Loading...")
	await GameProfile.refresh_energy()
	# The header's bar is now behind whatever we just read; Shop.gd listens
	# for this and re-reads GameProfile.
	currency_changed.emit()

	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/energy/refill/list")
	if not res.ok:
		_status_label.text = tr("Could not load refills -- try again later.")
		return
	_status_label.text = ""

	var max_raw = res.data.get("energy_max")
	if typeof(max_raw) in [TYPE_INT, TYPE_FLOAT] and int(max_raw) > 0:
		_energy_max = int(max_raw)

	_energy_products = []
	for fields in res.data.get("products", []):
		_energy_products.append(EnergyProductData.from_fields(fields))
	_populate_energy_grid()


func _populate_energy_grid() -> void:
	for child in _energy_grid.get_children():
		_energy_grid.remove_child(child)
		child.queue_free()

	if _energy_products.is_empty():
		var empty_label := Label.new()
		empty_label.text = tr("No refills available right now.")
		_energy_grid.add_child(empty_label)
		return

	var room: int = maxi(0, _energy_max - _current_energy())
	if room <= 0:
		_status_label.text = tr("Your energy is already full.")

	for product in _energy_products:
		var typed_product: EnergyProductData = product
		var tile: CurrencyTileView = CURRENCY_TILE_SCENE.instantiate()
		_energy_grid.add_child(tile)
		if typed_product.fills_bar():
			tile.set_reward_text("energy", tr("Full"))
		else:
			tile.set_reward("energy", typed_product.energy_amount)
		tile.set_cost_currency("bucks", typed_product.bucks_cost)
		tile.set_action_text(tr("Refill"))
		# Mirrors both 409s POST /energy/refill can return -- a full bar, and
		# a fixed top-up bigger than the room left -- so a refill the server
		# would refuse is greyed out here rather than costing a tap. The
		# server still re-checks; this is only what the button looks like.
		var fits: bool = room > 0 and (typed_product.fills_bar() or typed_product.energy_amount <= room)
		tile.set_affordable(fits and GameProfile.bucks >= typed_product.bucks_cost)
		tile.action_pressed.connect(_on_energy_tile_pressed.bind(typed_product))


## Reads the current bar out of the server's opaque energy block. `.get()`
## alone doesn't guard a present-but-null value, hence the type check -- the
## same defensive shape EnergyBar._int and PackData use.
func _current_energy() -> int:
	var value = GameProfile.energy.get("energy")
	return int(value) if typeof(value) in [TYPE_INT, TYPE_FLOAT] else 0


func _on_energy_tile_pressed(product: EnergyProductData) -> void:
	if GameProfile.bucks < product.bucks_cost:
		_status_label.text = tr("Not enough %s for this refill.") % CurrencyDisplay.lowercase_label_for("bucks")
		return
	_status_label.text = tr("Refilling...")
	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST, "/energy/refill", {"product_id": product.product_id}
	)
	if not res.ok:
		# 409 is the server refusing to sell energy that would evaporate, and
		# _populate_energy_grid greys those tiles out -- so getting one here
		# means the local bar was behind. Re-read and rebuild rather than
		# telling the player to retry something that cannot work.
		if res.status == 409:
			_status_label.text = tr("Your energy moved -- refills updated.")
			await _load_energy()
			return
		_status_label.text = tr("Could not refill -- try again.")
		return

	_status_label.text = ""
	# /energy/refill returns the whole bar plus the new balance, so there is
	# nothing left to re-fetch.
	GameProfile.apply_energy(res.data)
	GameProfile.apply_currency_balances(null, res.data.get("bucks_remaining"))
	currency_changed.emit()
	_populate_energy_grid()
	

# ============================================================ Ads tab

func _load_ads() -> void:
	_status_label.text = tr("Loading...")
	await GameProfile.refresh_energy()
	
	_ads_deals = AdManager.get_ad_deals()
	_status_label.text = ""
	_populate_ads_grid()

func _populate_ads_grid() -> void:
	for child in _ads_grid.get_children():
		_ads_grid.remove_child(child)
		child.queue_free()

	if _ads_deals.is_empty():
		var empty_label := Label.new()
		empty_label.text = tr("No ads available right now.")
		_ads_grid.add_child(empty_label)
		return

	for ad in _ads_deals:
		var typed_ad: AdData = ad
		var view: ShopAdView = AD_VIEW_SCENE.instantiate()
		_ads_grid.add_child(view)
		view.set_ad_data(typed_ad)
		view.watch_pressed.connect(_on_watch_ad_pressed.bind(typed_ad))


func _on_watch_ad_pressed(ad: AdData) -> void:
	if not ad.available:
		_status_label.text = ad.unavailable_reason
		return
		
	_status_label.text = ""
	if not AdManager.show_ad_for_track(ad.track):
		_status_label.text = tr("Ad not ready -- try again in a moment.")


func _on_ad_completed(_track: String, status: String) -> void:
	match status:
		"granted":
			_status_label.text = tr("Reward claimed!")
			await _load_ads()
			currency_changed.emit()
		"pending":
			# AdMob pays through the backend on its own clock; the balance
			# shows on the next profile load if it hasn't yet.
			_status_label.text = tr("Reward is on its way -- it lands within a minute.")
			await _load_ads()
		_:
			_status_label.text = tr("Ad was closed early or failed to verify.")
			await _load_ads()
