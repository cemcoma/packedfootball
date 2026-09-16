extends Control

## Shop: two segments -- Packs (real, backend-driven, split by pack type via
## a dropdown -- see _rebuild_pack_type_dropdown) and Currency (its own
## sub-tabs -- Exchange/Cash/Deals/Energy/Free, see CurrencyPanel.gd -- instanced
## into the CurrencyPanel node below rather than built inline here, keeping
## this file focused on the pack catalog it already owned).
##
## The two segment buttons share a ButtonGroup (see Shop.tscn) so exactly
## one ever reads as selected -- without it both stayed visibly toggled at
## once, since a bare toggle_mode Button has no idea its sibling exists.
##
## Packs are fetched fresh from the backend's GET /pack/list every time
## this scene loads (and again after every purchase, so a limited pack's
## remaining count/disappearance stays accurate) rather than cached on
## GameProfile -- unlike the squad, the pack catalog isn't "this account's
## data", it's closer to a live storefront that can change under any
## account at any time (an admin flips a pack inactive, a limited pack
## sells out from someone else buying it, etc).

const PACK_VIEW_SCENE := preload("res://scenes/components/PackView.tscn")

@onready var _credits_chip: CurrencyChip = %CreditsChip
@onready var _bucks_chip: CurrencyChip = %BucksChip
@onready var _medals_chip: CurrencyChip = %MedalsChip
@onready var _inventory_label: Label = %InventoryLabel
@onready var _energy_bar: EnergyBar = %EnergyBar
@onready var _currency_tabs: CurrencyPanel = %CurrencyTabs
@onready var _packs_tab_button: Button = %PacksTabButton
@onready var _currency_tab_button: Button = %CurrencyTabButton
@onready var _status_label: Label = %StatusLabel
@onready var _packs_panel: VBoxContainer = %PacksPanel
@onready var _pack_type_dropdown: OptionButton = %PackTypeDropdown
@onready var _packs_grid: HBoxContainer = %PacksGrid
@onready var _currency_panel: VBoxContainer = %CurrencyPanel
@onready var _back_button: Button = %BackButton
@onready var _info_popup: PackInfoPopup = %InfoPopup
@onready var _busy_popup: Control = %BusyPopup

var _packs: Array = []  # PackData, every pack the backend returned
var _pack_types: Array[String] = []  # dropdown item index -> pack type

## The pack type last looked at, remembered ACROSS scene loads.
##
## static so it outlives this scene instance: buying a pack leaves for
## PackReveal.tscn and comes back to a brand NEW Shop, whose dropdown starts
## empty -- so the "keep the selection across a refresh" logic below had
## nothing to keep, and every purchase dumped you back on the first type.
##
## Kept here rather than on PackSession (which carries the just-opened
## cards between the two screens) because this isn't about the pack: it's
## the Shop's own view state, and it should hold however you arrive --
## from the Menu just as much as from a reveal.
##
## Never cleared on sign-out, deliberately: it's a UI preference, not
## account data, and a type that no longer exists falls back to the first
## one on its own (see the find() below).
static var _last_pack_type: String = ""
var _busy: bool = false


func _ready() -> void:
	_packs_tab_button.pressed.connect(_on_packs_tab_pressed)
	_currency_tab_button.pressed.connect(_on_currency_tab_pressed)
	_pack_type_dropdown.item_selected.connect(_on_pack_type_selected)
	_back_button.pressed.connect(_on_back_pressed)
	_currency_tabs.currency_changed.connect(_refresh_currency_labels)

	_credits_chip.set_currency("credits")
	_bucks_chip.set_currency("bucks")
	_medals_chip.set_currency("medals")

	# Entering the Shop refreshes the balances before showing anything
	# priced: bucks bought through RevenueCat are granted by a webhook
	# rather than by this client (see CurrencyPanel), so the cached numbers
	# can be behind by a whole purchase, and this is the one screen where
	# being wrong about them actually costs the player something.
	_refresh_currency_labels()
	await _refresh_and_load()


func _refresh_currency_labels() -> void:
	_credits_chip.set_amount(GameProfile.credits)
	_bucks_chip.set_amount(GameProfile.bucks)
	_medals_chip.set_amount(GameProfile.medals)
	_energy_bar.set_energy(GameProfile.energy)
	_refresh_inventory_label()

func _refresh_inventory_label() -> void:
	var count := GameProfile.inventory_count()
	var full: bool = GameProfile.inventory_space() <= 0
	_inventory_label.text = "Bench %d / %d" % [count, GameProfile.inventory_cap]
	_inventory_label.add_theme_color_override(
		"font_color",
		ThemeManager.color("warning") if full else ThemeManager.color("text_hint")
	)


func _on_packs_tab_pressed() -> void:
	_packs_panel.visible = true
	_currency_panel.visible = false


func _on_currency_tab_pressed() -> void:
	_packs_panel.visible = false
	_currency_panel.visible = true
	await _refresh_currencies("Updating your balance...")


# -- fetching ------------------------------------------------------------------


## Shows the wait popup, re-reads the balances, updates the header. Returns
## once the balances on screen are the server's.
##
## Failure is deliberately quiet: the cached numbers are still the last ones
## the server gave us, so the screen stays usable and priced correctly in
## almost every case -- and the two things that actually spend money
## (/pack/open, the redeem endpoints) re-check the real balance server-side
## regardless of what was on screen.
func _refresh_currencies(status: String) -> bool:
	if _busy:
		return false
	_busy = true
	_busy_popup.set_status(status)
	_busy_popup.visible = true

	var ok: bool = await GameProfile.refresh_currencies()
	_refresh_currency_labels()

	_busy_popup.visible = false
	_busy = false
	if not ok:
		_status_label.text = "Could not refresh your balance -- showing the last known one."
	return ok


## Balances first, then the catalog, under one popup -- both are real
## awaits, so the status text moving is the request actually progressing
## rather than a timer pretending it is.
func _refresh_and_load() -> void:
	_busy = true
	_busy_popup.set_status("Updating your balance...")
	_busy_popup.visible = true

	var ok: bool = await GameProfile.refresh_currencies()
	await GameProfile.refresh_energy()
	_refresh_currency_labels()

	_busy_popup.set_status("Loading packs...")
	await _load_packs()

	_busy_popup.visible = false
	_busy = false
	if not ok and _status_label.text == "":
		_status_label.text = "Could not refresh your balance -- showing the last known one."


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")


func _load_packs() -> void:
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/pack/list")
	if not res.ok:
		_status_label.text = "Could not load packs -- try again later."
		return
	var pack_fields: Array = res.data.get("packs", [])
	_packs = []
	for fields in pack_fields:
		_packs.append(PackData.from_fields(fields))

	_status_label.text = ""
	_rebuild_pack_type_dropdown()
	_populate_packs_grid()


## The dropdown's entries come from the types actually present in what the
## backend returned, NOT a hardcoded list -- add a fourth pack type
## server-side
func _rebuild_pack_type_dropdown() -> void:
	var previous_type := _selected_pack_type()
	if previous_type == "":
		previous_type = _last_pack_type

	var present: Dictionary = {}
	for pack in _packs:
		present[(pack as PackData).type] = true

	var unique_types: Array[String] = []
	for pack_type in present.keys():
		unique_types.append(pack_type)
				
	_pack_types = unique_types

	_pack_type_dropdown.clear()
	for pack_type in _pack_types:
		_pack_type_dropdown.add_item(pack_type.capitalize())
	_pack_type_dropdown.disabled = _pack_types.size() <= 1

	var restored := _pack_types.find(previous_type)
	if not _pack_types.is_empty():
		_pack_type_dropdown.select(restored if restored != -1 else 0)
		_last_pack_type = _selected_pack_type()


func _selected_pack_type() -> String:
	var index := _pack_type_dropdown.selected
	if index < 0 or index >= _pack_types.size():
		return ""
	return _pack_types[index]


func _on_pack_type_selected(_index: int) -> void:
	_last_pack_type = _selected_pack_type()
	_populate_packs_grid()


func _populate_packs_grid() -> void:
	# Same remove_child()-then-queue_free() pairing Team.gd's bench grid
	# uses: safe even though this can indirectly run from a PackView's own
	# "buy_pressed" signal (see _on_buy_pressed -> _load_packs -> here).
	for child in _packs_grid.get_children():
		_packs_grid.remove_child(child)
		child.queue_free()
	var selected_type := _selected_pack_type()
	var visible_packs: Array = []
	for pack in _packs:
		if (pack as PackData).type == selected_type:
			visible_packs.append(pack)

	if visible_packs.is_empty():
		var empty_label := Label.new()
		empty_label.text = (
			"No packs available right now." if _packs.is_empty()
			else "No %s packs available right now." % selected_type.capitalize()
		)
		_packs_grid.add_child(empty_label)
		return

	for pack in visible_packs:
		var typed_pack: PackData = pack
		var view: PackView = PACK_VIEW_SCENE.instantiate()
		_packs_grid.add_child(view)
		view.set_pack(typed_pack)
		view.set_affordable(
			_balance_for(typed_pack.price_currency) >= typed_pack.price and _has_room_for(typed_pack)
		)
		view.buy_pressed.connect(_on_buy_pressed.bind(typed_pack))
		view.info_pressed.connect(_on_info_pressed.bind(typed_pack))


func _on_info_pressed(pack: PackData) -> void:
	_info_popup.open_for(pack)


## A pack is priced in exactly one currency (see PackData.price_currency) --
## this is the local mirror of whichever balance that is. The server
## re-checks it regardless; this only decides what the Buy button looks
## like and what the error says.
func _balance_for(currency_key: String) -> int:
	match currency_key:
		"bucks":
			return GameProfile.bucks
		"medals":
			return GameProfile.medals
		_:
			return GameProfile.credits


## Whether the WHOLE pack fits on the bench. Deliberately not "are we under
## the cap right now": a 5-card pack opened at 48/50 would put the club over
## it, so the backend refuses that outright (see its INVENTORY_CAP) and this
## greys the button out to match rather than letting the user find out after
## they commit.
func _has_room_for(pack: PackData) -> bool:
	return GameProfile.inventory_space() >= maxi(1, pack.cards_per_pack)


func _on_buy_pressed(pack: PackData) -> void:
	if not _has_room_for(pack):
		_status_label.text = (
			"Your inventory is full (%d / %d) -- release players from the Team screen to make room for %s."
			% [GameProfile.inventory_count(), GameProfile.inventory_cap, pack.pack_name]
		)
		return

	if _balance_for(pack.price_currency) < pack.price:
		# Deliberately doesn't name the currency: the pack box right there
		# shows its price with that currency's logo (see PackView's
		# CurrencyAmount), which is the only place it needs saying.
		_status_label.text = "You can't afford %s." % pack.pack_name
		return

	# The popup is a full-screen scrim, so putting it up BEFORE the request
	# also stops a second Buy tap from firing a second /pack/open (which
	# would charge for, and open, a second pack) while this one is in
	# flight -- same reason Play.gd shows its matchmaking popup up front.
	_status_label.text = ""
	_busy_popup.set_status("Opening %s..." % pack.pack_name)
	_busy_popup.visible = true

	# Not awaited -- moves the status along on its own if the request is
	# slow, and simply never fires visibly if it isn't. Same non-awaited
	# staged-status trick as Play.gd's matchmaking midpoint; no artificial
	# delay is added to a fast response.
	get_tree().create_timer(0.6).timeout.connect(_on_pack_open_midpoint)

	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST, "/pack/open", {"pack_id": pack.pack_id}
	)
	if not res.ok:
		_busy_popup.visible = false
		# 409 is the backend's inventory cap. _has_room_for above should have
		# caught it, so reaching here means the local card cache disagrees
		# with Firestore -- say what's actually wrong rather than "try again",
		# which would be advice that can't work.
		_status_label.text = (
			"Your inventory is full -- release players from the Team screen first."
			if res.status == 409
			else "Could not open %s -- try again." % pack.pack_name
		)
		return

	# .get(key, default) only falls back to `default` when the key is
	# entirely absent -- a present-but-null value (which a malformed
	# response could send) comes back as null regardless, and null can't go
	# into a statically-typed String/int var. See PackData.gd's own version
	# of this same defensive pattern for the bug this avoids.
	var card_fields_list: Array = res.data.get("cards", [])
	var cards: Array = []
	for card_fields in card_fields_list:
		var player_id_raw = card_fields.get("player_id")
		var player_id: String = player_id_raw if player_id_raw is String else ""
		var card := PlayerCard.from_fields(card_fields, player_id)
		var doc_id_raw = card_fields.get("doc_id")
		card.doc_id = doc_id_raw if doc_id_raw is String else ""
		cards.append(card)

	# /pack/open returns every balance now, not just credits -- a pack can be
	# priced in any one of them, and apply_currency_balances ignores whichever
	# keys are absent, so this is safe against an older backend too.
	GameProfile.add_purchased_cards(cards)
	GameProfile.apply_inventory_cap(res.data.get("inventory_cap"))
	GameProfile.apply_currency_balances(
		res.data.get("credits_remaining"),
		res.data.get("bucks_remaining"),
		res.data.get("medals_remaining"),
	)

	# The reveal screen is the actual "you got these" moment now -- see
	# PackReveal.gd. No need to refresh credits/status/the pack grid here:
	# Shop.tscn's own _ready() reloads all of that fresh (including
	# remaining_opens/sold-out state) the next time this scene is entered,
	# which is exactly when it'll matter again.
	PackSession.set_pending(pack.pack_name, cards)
	get_tree().change_scene_to_file("res://scenes/PackReveal.tscn")


## Only meaningful while a pack request is actually still in flight -- the
## popup being hidden means it already came back (or failed), so this does
## nothing rather than overwriting a fresh status on a closed popup.
func _on_pack_open_midpoint() -> void:
	if _busy_popup.visible:
		_busy_popup.set_status("Shuffling the pack...")
