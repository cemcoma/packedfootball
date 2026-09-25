extends Control

## Every unequipped item this account owns, in one grid -- the equipment
## counterpart to Inventory.gd, and built the same way: straight off the
## already-loaded GameProfile cache (GameProfile.all_items), a full rebuild on
## any change, and the result of every request folded back into that cache so
## coming back here shows it without a reload.
##
## Two things you can do with an item:
##
##   TAP ONE      -- pick a card to socket it into. That is one-way: the item
##                   is consumed, and replacing one already on the card
##                   destroys THAT one. The confirm overlay says so, because
##                   it cannot be undone.
##   SCRAP        -- multi-select spares for credits, the same batch flow
##                   Inventory uses for quick-selling cards.
##
## Items already on a card are NOT here -- they live on the card (see
## PlayerDetail's slot row), because that is literally where they are stored.

const ITEM_VIEW_SCENE := preload("res://scenes/components/ItemView.tscn")

## The filter dropdown, as [label, matcher]. Same shape as Inventory.FILTERS:
## the label alone decides for the first three, a rarity list for the rest.
const FILTERS: Array = [
	["All items", []],
	["Outfield", []],
	["Goalkeeper", []],
	["Gold and up", ["gold", "platinum", "diamond", "special", "icon"]],
	["Diamond and up", ["diamond", "special", "icon"]],
]

## Mirrors backend/config.py's ITEM_SCRAP_BATCH_MAX -- that end rejects a
## longer list, so the grid stops selecting before it can be refused.
const SCRAP_BATCH_MAX := 30

var _batch_mode: bool = false
var _selected_ids: Array = []
var _is_processing: bool = false

@onready var _title_label: Label = %TitleLabel
@onready var _hint_label: Label = %HintLabel
@onready var _grid_backdrop: PanelContainer = %GridBackdrop
@onready var _confirm_panel: PanelContainer = %Panel
@onready var _count_label: Label = %CountLabel
@onready var _filter_dropdown: OptionButton = %FilterDropdown
@onready var _grid: GridContainer = %ItemGrid
@onready var _empty_label: Label = %EmptyLabel
@onready var _back_button: Button = %BackButton
@onready var _toggle_batch_button: Button = %ToggleBatchButton
@onready var _cancel_batch_button: Button = %CancelBatchButton
@onready var _execute_batch_button: Button = %ExecuteBatchButton
@onready var _batch_action_row: HBoxContainer = %BatchActionRow

@onready var _batch_confirm_overlay: Control = %BatchConfirmOverlay
@onready var _batch_confirm_label: Label = %BatchConfirmLabel
@onready var _batch_confirm_reward_label: Label = %BatchConfirmRewardLabel
@onready var _batch_confirm_reward_icon: TextureRect = %BatchConfirmRewardIcon
@onready var _confirm_footnote: Label = %ConfirmFootnote
@onready var _confirm_execute_button: Button = %ConfirmExecuteButton
@onready var _confirm_cancel_button: Button = %ConfirmCancelButton


func _ready() -> void:
	_back_button.pressed.connect(_on_back_pressed)
	_filter_dropdown.item_selected.connect(func(_i: int) -> void: _populate_grid())

	_toggle_batch_button.pressed.connect(_on_toggle_batch_pressed)
	_cancel_batch_button.pressed.connect(_disable_batch_mode)
	_execute_batch_button.pressed.connect(_on_execute_batch_pressed)
	_confirm_cancel_button.pressed.connect(_on_cancel_confirm_pressed)
	_confirm_execute_button.pressed.connect(_on_confirm_scrap_pressed)

	_batch_confirm_overlay.visible = false

	for entry in FILTERS:
		_filter_dropdown.add_item(tr(entry[0]))
	_filter_dropdown.select(0)

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	GameProfile.items_changed.connect(_refresh)
	_refresh()


func _refresh() -> void:
	_refresh_count()
	_populate_grid()
	_apply_theme_colors()


func _refresh_count() -> void:
	var equipped := 0
	for player_id in GameProfile.all_cards.keys():
		var card: PlayerCard = GameProfile.all_cards[player_id]
		equipped += card.items.size()
	_count_label.text = tr("%d spare  ·  %d socketed") % [GameProfile.all_items.size(), equipped]


func _apply_theme_colors() -> void:
	_count_label.add_theme_color_override("font_color", ThemeManager.color("heading"))
	_title_label.add_theme_color_override("font_color", MenuTile.TITLE_COLOR)
	_empty_label.add_theme_color_override("font_color", MenuTile.SUBTITLE_COLOR)
	_hint_label.add_theme_color_override("font_color", MenuTile.SUBTITLE_COLOR)
	_style_chrome()


func _style_chrome() -> void:
	var accent := ThemeManager.color("accent")
	var muted := ThemeManager.color("surface_border")
	_grid_backdrop.add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, muted, 3, true, Vector2(10, 8))
	)
	_confirm_panel.add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, ThemeManager.color("warning"), 3, true)
	)
	MenuTile.style_button(_filter_dropdown, accent)
	MenuTile.style_popup(_filter_dropdown, accent)
	MenuTile.style_button(_toggle_batch_button, accent)
	MenuTile.style_button(_execute_batch_button, ThemeManager.color("warning"))
	MenuTile.style_button(_confirm_execute_button, ThemeManager.color("warning"))
	for button in [_back_button, _cancel_batch_button, _confirm_cancel_button]:
		MenuTile.style_button(button, muted)


func _passes_filter(item: Dictionary) -> bool:
	var index: int = _filter_dropdown.selected
	if index <= 0 or index >= FILTERS.size():
		return true
	var label: String = FILTERS[index][0]
	if label == "Outfield":
		return ItemData.kind(item) != ItemData.KIND_KEEPER
	if label == "Goalkeeper":
		return ItemData.kind(item) != ItemData.KIND_OUTFIELD
	var rarities: Array = FILTERS[index][1]
	return rarities.has(PlayerCard.tier_family(ItemData.rarity(item)))


func _populate_grid() -> void:
	for child in _grid.get_children():
		_grid.remove_child(child)
		child.queue_free()

	var shown: Array = []
	for item in ItemData.sort_best_first(GameProfile.all_items):
		if _passes_filter(item):
			shown.append(item)

	_empty_label.visible = shown.is_empty()
	if shown.is_empty():
		_empty_label.text = (
			tr("You don't own any items yet -- open an Equipment Pack in the Shop.")
			if GameProfile.all_items.is_empty()
			else tr("No items match this filter.")
		)
		return

	for item in shown:
		var view: ItemView = ITEM_VIEW_SCENE.instantiate()
		_grid.add_child(view)
		view.set_item(item)
		view.set_selected(_batch_mode and _selected_ids.has(ItemData.item_id(item)))
		view.pressed.connect(_on_item_pressed.bind(item))


func _on_item_pressed(item: Dictionary) -> void:
	var id := ItemData.item_id(item)
	if _batch_mode:
		if _selected_ids.has(id):
			_selected_ids.erase(id)
		elif _selected_ids.size() < SCRAP_BATCH_MAX:
			_selected_ids.append(id)
		_populate_grid()
		_update_batch_ui()
		return
	# Equipping is done from the card's own screen, where the slots and what
	# would be destroyed are both visible. This just carries the choice over.
	ItemSession.open(id, "res://scenes/Items.tscn")
	get_tree().change_scene_to_file("res://scenes/Inventory.tscn")


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/TeamHub.tscn")


func _on_toggle_batch_pressed() -> void:
	_batch_mode = true
	_selected_ids.clear()
	_toggle_batch_button.visible = false
	_back_button.visible = false
	_filter_dropdown.disabled = true
	_batch_action_row.visible = true
	_update_batch_ui()
	_populate_grid()


func _disable_batch_mode() -> void:
	_batch_mode = false
	_selected_ids.clear()
	_toggle_batch_button.visible = true
	_back_button.visible = true
	_filter_dropdown.disabled = false
	_batch_action_row.visible = false
	_populate_grid()


func _selected_items() -> Array:
	var chosen: Array = []
	for item in GameProfile.all_items:
		if _selected_ids.has(ItemData.item_id(item)):
			chosen.append(item)
	return chosen


func _scrap_total() -> int:
	var total := 0
	for item in _selected_items():
		total += ItemData.scrap_credits(item)
	return total


func _update_batch_ui() -> void:
	_execute_batch_button.disabled = _selected_ids.is_empty()
	CurrencyDisplay.set_button_price(_execute_batch_button, tr("Scrap"), _scrap_total())


func _on_execute_batch_pressed() -> void:
	if _selected_ids.is_empty():
		return
	_batch_confirm_label.text = tr("Scrap %d selected items?\n\nYou get") % _selected_ids.size()
	_batch_confirm_reward_label.text = "+%s" % CurrencyDisplay.format_amount(_scrap_total())
	_batch_confirm_reward_icon.texture = CurrencyDisplay.icon_for("credits")
	_batch_confirm_reward_label.add_theme_color_override(
		"font_color", CurrencyDisplay.color_for("credits")
	)
	_confirm_footnote.text = tr("These items are gone for good.")
	_batch_confirm_overlay.visible = true


func _on_cancel_confirm_pressed() -> void:
	if not _is_processing:
		_batch_confirm_overlay.visible = false


func _on_confirm_scrap_pressed() -> void:
	if _is_processing or _selected_ids.is_empty():
		return

	_is_processing = true
	_confirm_execute_button.disabled = true
	_confirm_cancel_button.disabled = true

	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST, "/item/scrap", {"item_ids": _selected_ids}
	)

	_is_processing = false
	_confirm_execute_button.disabled = false
	_confirm_cancel_button.disabled = false
	_batch_confirm_overlay.visible = false

	if res.ok:
		# The SERVER's pool, not a local guess at what is left.
		GameProfile.apply_item_pool(res.data.get("item_pool"))
		GameProfile.apply_currency_balances(res.data.get("credits_remaining"))
		_disable_batch_mode()
		_refresh()
	else:
		push_warning("Item scrap failed. Status: %d" % res.status)
