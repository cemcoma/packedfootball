extends Control

## Shop: two segments -- Packs (real, backend-driven) and Currency
## (microtransactions/ads, deliberately a "coming soon" placeholder for
## now -- pack mechanics come first).
##
## Packs are fetched fresh from the backend's GET /pack/list every time
## this scene loads (and again after every purchase, so a limited pack's
## remaining count/disappearance stays accurate) rather than cached on
## GameProfile -- unlike the squad, the pack catalog isn't "this account's
## data", it's closer to a live storefront that can change under any
## account at any time (an admin flips a pack inactive, a limited pack
## sells out from someone else buying it, etc).

const PACK_VIEW_SCENE := preload("res://scenes/components/PackView.tscn")

@onready var _credits_label: Label = %CreditsLabel
@onready var _packs_tab_button: Button = %PacksTabButton
@onready var _currency_tab_button: Button = %CurrencyTabButton
@onready var _status_label: Label = %StatusLabel
@onready var _packs_scroll: ScrollContainer = %PacksScroll
@onready var _packs_grid: GridContainer = %PacksGrid
@onready var _currency_panel: VBoxContainer = %CurrencyPanel
@onready var _back_button: Button = %BackButton
@onready var _info_popup: PackInfoPopup = %InfoPopup

var _packs: Array = []  # PackData


func _ready() -> void:
	_packs_tab_button.pressed.connect(_on_packs_tab_pressed)
	_currency_tab_button.pressed.connect(_on_currency_tab_pressed)
	_back_button.pressed.connect(_on_back_pressed)

	_refresh_credits_label()
	await _load_packs()


func _refresh_credits_label() -> void:
	_credits_label.text = "%d credits" % GameProfile.credits


func _on_packs_tab_pressed() -> void:
	_packs_scroll.visible = true
	_currency_panel.visible = false


func _on_currency_tab_pressed() -> void:
	_packs_scroll.visible = false
	_currency_panel.visible = true


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")


func _load_packs() -> void:
	_status_label.text = "Loading packs..."
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/pack/list")
	if not res.ok:
		_status_label.text = "Could not load packs -- try again later."
		return

	var pack_fields: Array = res.data.get("packs", [])
	_packs = []
	for fields in pack_fields:
		_packs.append(PackData.from_fields(fields))

	_status_label.text = ""
	_populate_packs_grid()


func _populate_packs_grid() -> void:
	# Same remove_child()-then-queue_free() pairing Team.gd's bench grid
	# uses: safe even though this can indirectly run from a PackView's own
	# "buy_pressed" signal (see _on_buy_pressed -> _load_packs -> here).
	for child in _packs_grid.get_children():
		_packs_grid.remove_child(child)
		child.queue_free()

	if _packs.is_empty():
		var empty_label := Label.new()
		empty_label.text = "No packs available right now."
		_packs_grid.add_child(empty_label)
		return

	for pack in _packs:
		var typed_pack: PackData = pack
		var view: PackView = PACK_VIEW_SCENE.instantiate()
		_packs_grid.add_child(view)
		view.set_pack(typed_pack)
		view.set_affordable(GameProfile.credits >= typed_pack.price)
		view.buy_pressed.connect(_on_buy_pressed.bind(typed_pack))
		view.info_pressed.connect(_on_info_pressed.bind(typed_pack))


func _on_info_pressed(pack: PackData) -> void:
	_info_popup.open_for(pack)


func _on_buy_pressed(pack: PackData) -> void:
	if GameProfile.credits < pack.price:
		_status_label.text = "Not enough credits for %s." % pack.pack_name
		return

	_status_label.text = "Opening %s..." % pack.pack_name
	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST, "/pack/open", {"pack_id": pack.pack_id}
	)
	if not res.ok:
		_status_label.text = "Could not open %s -- try again." % pack.pack_name
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

	var credits_raw = res.data.get("credits_remaining")
	var credits_remaining: int = credits_raw if typeof(credits_raw) in [TYPE_INT, TYPE_FLOAT] else GameProfile.credits
	GameProfile.add_purchased_cards(cards, credits_remaining)

	_refresh_credits_label()
	var names: Array = []
	for card in cards:
		var typed_card: PlayerCard = card
		names.append(typed_card.display_name())
	_status_label.text = "Got: %s" % ", ".join(names)

	await _load_packs()  # remaining_opens/sold-out state may have changed
