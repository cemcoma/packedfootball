class_name EquipPopup
extends Control

## Card-first equipping: the card's slots, every spare item that fits it, and
## one Equip button. Opened by the Equip button on a card's detail view (the
## Squad screen's stats panel, PlayerDetail). PlayerDetail's Socket button is
## the item-first way round; both go through ItemData.equip_blocker.

signal equipped(player_id: String)

const SCENE_PATH := "res://scenes/components/EquipPopup.tscn"
const ITEM_VIEW_SCENE := preload("res://scenes/components/ItemView.tscn")

@onready var _panel: PanelContainer = %Panel
@onready var _title_label: Label = %TitleLabel
@onready var _slots_row: HBoxContainer = %SlotsRow
@onready var _item_scroll: ScrollContainer = %ItemScroll
@onready var _item_row: HBoxContainer = %ItemRow
@onready var _empty_label: Label = %EmptyLabel
@onready var _footnote_label: Label = %FootnoteLabel
@onready var _close_button: Button = %CloseButton
@onready var _equip_button: Button = %EquipButton

var _card: PlayerCard = null
var _selected_id: String = ""
## The equipped item the new one overwrites. It is destroyed, so the server is
## told which rather than left to guess.
var _replacing_id: String = ""
var _busy: bool = false
## The last request's outcome; replaces the footnote until the next pick.
var _status: String = ""
var _status_positive: bool = false


## Opens over `host` (normally the current screen) for one of your own cards.
static func open(host: Node, card: PlayerCard) -> EquipPopup:
	var popup: EquipPopup = load(SCENE_PATH).instantiate()
	host.add_child(popup)
	popup._show_for(card)
	return popup


func _ready() -> void:
	_close_button.pressed.connect(_on_close_pressed)
	_equip_button.pressed.connect(_on_equip_pressed)
	ThemeManager.theme_changed.connect(_style)
	_style()


func _show_for(card: PlayerCard) -> void:
	_card = card
	_title_label.text = tr("Equip an item on %s") % card.full_name()
	_rebuild()


func _style() -> void:
	var warning := ThemeManager.color("warning")
	_panel.add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, warning, 3, true)
	)
	MenuTile.style_button(_equip_button, warning)
	MenuTile.style_button(_close_button, ThemeManager.color("surface_border"))
	_title_label.add_theme_color_override("font_color", MenuTile.TITLE_COLOR)
	_empty_label.add_theme_color_override("font_color", MenuTile.SUBTITLE_COLOR)
	_refresh_footer()


# -- state -> UI --------------------------------------------------------------


func _rebuild() -> void:
	_populate_slots()
	_populate_items()
	_refresh_footer()


## Filled slots are tappable to pick the one a new item overwrites -- the only
## way onto a full card, same as PlayerDetail's slot row.
func _populate_slots() -> void:
	_clear(_slots_row)
	for i in range(_card.item_capacity()):
		var view: ItemView = ITEM_VIEW_SCENE.instantiate()
		_slots_row.add_child(view)
		view.set_compact(true)
		if i < _card.items.size():
			var worn: Dictionary = _card.items[i]
			view.set_item(worn)
			view.set_selected(ItemData.item_id(worn) == _replacing_id)
			view.pressed.connect(_on_slot_pressed.bind(ItemData.item_id(worn)))
		else:
			view.set_empty()
			view.set_tappable(false)


func _populate_items() -> void:
	_clear(_item_row)
	var shown: Array = []
	for item in ItemData.sort_best_first(GameProfile.all_items):
		if ItemData.fits(item, _card.position):
			shown.append(item)

	_item_scroll.visible = not shown.is_empty()
	_empty_label.visible = shown.is_empty()
	_empty_label.text = tr("No spare items fit this card. Equipment Packs are in the Shop.")
	for item in shown:
		var view: ItemView = ITEM_VIEW_SCENE.instantiate()
		_item_row.add_child(view)
		view.set_item(item)
		view.set_selected(ItemData.item_id(item) == _selected_id)
		view.pressed.connect(_on_item_pressed.bind(ItemData.item_id(item)))


## Selection only -- no rebuild, so the item strip keeps its scroll position.
func _refresh_selection() -> void:
	for child in _item_row.get_children():
		var view := child as ItemView
		view.set_selected(ItemData.item_id(view.item()) == _selected_id)
	for child in _slots_row.get_children():
		var view := child as ItemView
		var id := ItemData.item_id(view.item())
		if id != "":
			view.set_selected(id == _replacing_id)
	_refresh_footer()


func _refresh_footer() -> void:
	if _card == null:
		return
	var blocker := _blocker()
	_equip_button.disabled = _busy or _selected_id == "" or blocker != ""
	_close_button.disabled = _busy

	var text := tr("Items can never be taken back off a card.")
	var color := MenuTile.SUBTITLE_COLOR
	if _status != "":
		text = _status
		color = ThemeManager.color("positive") if _status_positive else ThemeManager.color("warning")
	elif blocker != "":
		text = blocker
		color = ThemeManager.color("warning")
	elif _selected_id != "" and _replacing_id != "":
		text = (
			tr("%s is destroyed to make room. Neither item can be taken back off.")
			% ItemData.label(_find(_card.items, _replacing_id))
		)
		color = ThemeManager.color("warning")
	_footnote_label.text = text
	_footnote_label.add_theme_color_override("font_color", color)


## Why the picked item can't go on, or "". A full card that only needs a slot
## chosen says so rather than showing the raw "no free slots".
func _blocker() -> String:
	var item := _find(GameProfile.all_items, _selected_id)
	if item.is_empty():
		return ""
	var kit: Array = _card.items.filter(func(i): return ItemData.item_id(i) != _replacing_id)
	var blocker := ItemData.equip_blocker(kit, item, _card.position, _card.contract)
	if blocker != "" and _replacing_id == "" and _card.free_item_slots() <= 0 and not ItemData.is_contract(item):
		return tr("Tap a slot to replace")
	return blocker


# -- input handlers -----------------------------------------------------------


func _on_item_pressed(id: String) -> void:
	if _busy:
		return
	_selected_id = "" if _selected_id == id else id
	_status = ""
	_refresh_selection()


func _on_slot_pressed(id: String) -> void:
	if _busy:
		return
	# A second tap clears the choice -- nothing is destroyed until Equip.
	_replacing_id = "" if _replacing_id == id else id
	_status = ""
	_refresh_selection()


## Stays open afterwards, so a second item can go straight on.
func _on_equip_pressed() -> void:
	if _busy or _selected_id == "" or _blocker() != "":
		return
	_busy = true
	_status = tr("Socketing...")
	_status_positive = false
	_refresh_footer()

	var body := {"player_id": _card.player_id, "item_id": _selected_id}
	if _replacing_id != "":
		body["replaces_item_id"] = _replacing_id
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_POST, "/item/equip", body)
	_busy = false

	if not res.ok:
		# 409 is items.py's can_equip rejection; the server's wording is the accurate one.
		var detail = res.data.get("detail")
		_status = (
			str(detail) if res.status == 409 and detail != null
			else tr("Could not socket that item -- try again.")
		)
		_refresh_footer()
		return

	GameProfile.apply_equip_result(
		_card.player_id, res.data.get("items"), res.data.get("item_pool"), res.data.get("contract")
	)
	_selected_id = ""
	_replacing_id = ""
	_status = tr("Socketed.")
	_status_positive = true
	_close_button.text = tr("Done")
	_rebuild()
	equipped.emit(_card.player_id)


func _on_close_pressed() -> void:
	if not _busy:
		queue_free()


# -- helpers ------------------------------------------------------------------


static func _find(items: Array, id: String) -> Dictionary:
	if id == "":
		return {}
	for item in items:
		if item is Dictionary and ItemData.item_id(item) == id:
			return item
	return {}


func _clear(container: Node) -> void:
	for child in container.get_children():
		container.remove_child(child)
		child.queue_free()
