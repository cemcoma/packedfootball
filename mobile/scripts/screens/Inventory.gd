extends Control

## Every player this account owns -- the starting XI and the bench together,
## in one grid. Tap one to open Player Details (release, restyle, the full
## attribute sheet).
##
## "Inventory" means two slightly different things and both are on screen at
## once, so the header spells both out: the SCREEN shows every card owned,
## while the CAP counts only the benched ones (the XI sits outside it -- see
## GameProfile.inventory_cap). A player in the XI wears an "XI" badge and
## can't be released, which is the one place the distinction actually bites.
##
## Cards come straight off the already-loaded GameProfile cache, not a fresh
## fetch -- same as the Squad screen's bench grid. Releasing or restyling
## folds its result back into that cache, so coming back here shows the
## change without a reload.

const PLAYER_CARD_SCENE := preload("res://scenes/components/PlayerCardView.tscn")

## The filter dropdown, as [label, matcher]. A matcher of "" means "no
## position test" and the label alone decides (see _passes_filter). Lines
## rather than exact positions: picking between LB and LM is what the grid
## is for, narrowing 111 cards to the defenders is what this is for.
const FILTERS: Array = [
	["All players", []],
	["Starting XI", []],
	["Bench", []],
	["Goalkeepers", ["GK"]],
	["Defenders", ["CB", "LB", "RB", "LWB", "RWB"]],
	["Midfielders", ["CDM", "CM", "CAM", "LM", "RM"]],
	["Attackers", ["LW", "RW", "ST"]],
]

const RELEASE_BATCH_MAX := 50 

var _batch_mode: bool = false
var _selected_ids: Array = []
var _is_processing: bool = false

@onready var _count_label: Label = %CountLabel
@onready var _credits_chip: CurrencyChip = %CreditsChip
@onready var _filter_dropdown: OptionButton = %FilterDropdown
@onready var _grid: GridContainer = %InventoryGrid
@onready var _empty_label: Label = %EmptyLabel
@onready var _back_button: Button = %BackButton
@onready var _toggle_batch_button: Button = %ToggleBatchButton
@onready var _cancel_batch_button: Button = %CancelBatchButton
@onready var _execute_batch_button: Button = %ExecuteBatchButton
@onready var _batch_action_row: HBoxContainer = %BatchActionRow

# Confirmation Overlay UI References
@onready var _batch_confirm_overlay: Control = %BatchConfirmOverlay
@onready var _batch_confirm_label: Label = %BatchConfirmLabel
@onready var _batch_confirm_reward_label: Label = %BatchConfirmRewardLabel
@onready var _batch_confirm_reward_icon: TextureRect = %BatchConfirmRewardIcon
@onready var _confirm_footnote: Label = %ConfirmFootnote # Brought over from PlayerDetail
@onready var _confirm_execute_button: Button = %ConfirmExecuteButton
@onready var _confirm_cancel_button: Button = %ConfirmCancelButton


func _ready() -> void:
	_back_button.pressed.connect(_on_back_pressed)
	_filter_dropdown.item_selected.connect(_on_filter_selected)
	_credits_chip.set_currency("credits")
	
	_toggle_batch_button.pressed.connect(_on_toggle_batch_pressed)
	_cancel_batch_button.pressed.connect(_disable_batch_mode)
	_execute_batch_button.pressed.connect(_on_execute_batch_pressed)
	_confirm_cancel_button.pressed.connect(_on_cancel_confirm_pressed)
	_confirm_execute_button.pressed.connect(_on_confirm_batch_release_pressed)
	
	_batch_confirm_overlay.visible = false

	for entry in FILTERS:
		_filter_dropdown.add_item(tr(entry[0]))
	_filter_dropdown.select(0)


	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_refresh()


func _refresh() -> void:
	_credits_chip.set_amount(GameProfile.credits)
	_refresh_count()
	_populate_grid()
	_apply_theme_colors()


func _refresh_count() -> void:
	var benched := GameProfile.inventory_count()
	_count_label.text = tr("%d owned  ·  bench %d / %d") % [
		GameProfile.all_cards.size(), benched, GameProfile.inventory_cap
	]


## The count goes amber once the bench is full, because that's the state
## that stops packs opening. Labels here sit straight on the screen
## background, so they need the palette rather than the Theme's Label color
## -- see ThemeManager's note on text_hint.
func _apply_theme_colors() -> void:
	var full: bool = GameProfile.inventory_space() <= 0
	_count_label.add_theme_color_override(
		"font_color", ThemeManager.color("warning") if full else ThemeManager.color("heading")
	)
	_empty_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))


func _starting_ids() -> Dictionary:
	var starting: Dictionary = {}
	for player_id in GameProfile.slot_assignment:
		if player_id != "":
			starting[player_id] = true
	return starting


func _passes_filter(card: PlayerCard, is_starting: bool) -> bool:
	var index: int = _filter_dropdown.selected
	if index <= 0 or index >= FILTERS.size():
		return true
	var label: String = FILTERS[index][0]
	if label == "Starting XI":
		return is_starting
	if label == "Bench":
		return not is_starting
	var positions: Array = FILTERS[index][1]
	return positions.has(card.position)


func _populate_grid() -> void:
	for child in _grid.get_children():
		_grid.remove_child(child)
		child.queue_free()

	var starting := _starting_ids()
	var ids: Array = []
	for player_id in GameProfile.all_cards.keys():
		var card: PlayerCard = GameProfile.all_cards[player_id]
		if _passes_filter(card, starting.has(player_id)):
			ids.append(player_id)

	ids.sort_custom(
		func(a, b): return GameProfile.all_cards[a].overall() > GameProfile.all_cards[b].overall()
	)

	_empty_label.visible = ids.is_empty()
	if ids.is_empty():
		_empty_label.text = (
			tr("You don't own any players yet -- open a pack in the Shop.")
			if GameProfile.all_cards.is_empty()
			else tr("No players match this filter.")
		)
		return

	for player_id in ids:
		var card: PlayerCard = GameProfile.all_cards[player_id]
		var view: PlayerCardView = PLAYER_CARD_SCENE.instantiate()
		_grid.add_child(view)
		view.set_card(card)
		
		var is_xi := starting.has(player_id)
		view.set_badge("XI" if is_xi else "")
		
		if _batch_mode:
			if _selected_ids.has(player_id):
				view.modulate = Color(0.5, 1.0, 0.5) # Selected (Green tint)
			elif is_xi:
				view.modulate = Color(0.4, 0.4, 0.4) # Darken XI cards (unselectable)
			else:
				view.modulate = Color(1, 1, 1)
		else:
			view.modulate = Color(1, 1, 1)

		view.pressed.connect(_on_card_pressed.bind(player_id, is_xi))


func _on_filter_selected(_index: int) -> void:
	_populate_grid()


func _on_card_pressed(player_id: String, is_xi: bool) -> void:
	if _batch_mode:
		if is_xi: 
			return # The backend aborts batches with XI players, block them here.
			
		if _selected_ids.has(player_id):
			_selected_ids.erase(player_id)
		elif _selected_ids.size() < RELEASE_BATCH_MAX:
			_selected_ids.append(player_id)
			
		_populate_grid()
		_update_batch_ui()
	else:
		PlayerSession.open(player_id, "res://scenes/Inventory.tscn")
		get_tree().change_scene_to_file("res://scenes/PlayerDetail.tscn")


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

func _update_batch_ui() -> void:
	var total_credits: int = 0
	for pid in _selected_ids:
		var card: PlayerCard = GameProfile.all_cards[pid]
		total_credits += PlayerCard.release_credits(card.tier)
		
	_execute_batch_button.disabled = _selected_ids.is_empty()
	CurrencyDisplay.set_button_price(_execute_batch_button, tr("Release"), total_credits)

func _on_execute_batch_pressed() -> void:
	if _selected_ids.is_empty():
		return
		
	var total_credits: int = 0
	for pid in _selected_ids:
		total_credits += PlayerCard.release_credits(GameProfile.all_cards[pid].tier)
		
	_batch_confirm_label.text = tr("Release %d selected players?\n\nYou get") % _selected_ids.size()
	_batch_confirm_reward_label.text = "+%s" % CurrencyDisplay.format_amount(total_credits)
	_batch_confirm_reward_icon.texture = CurrencyDisplay.icon_for("credits")
	_batch_confirm_reward_label.add_theme_color_override(
		"font_color", CurrencyDisplay.color_for("credits")
	)
	_batch_confirm_overlay.visible = true

func _on_cancel_confirm_pressed() -> void:
	if not _is_processing:
		_batch_confirm_overlay.visible = false

func _on_confirm_batch_release_pressed() -> void:
	if _is_processing or _selected_ids.is_empty():
		return
		
	_is_processing = true
	_confirm_execute_button.disabled = true
	_confirm_cancel_button.disabled = true
	
	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST, "/player/release/batch", {"player_ids": _selected_ids}
	)
	
	_is_processing = false
	_confirm_execute_button.disabled = false
	_confirm_cancel_button.disabled = false
	_batch_confirm_overlay.visible = false
	
	if res.ok:
		for pid in _selected_ids:
			GameProfile.release_card(pid)
		GameProfile.apply_inventory_cap(res.data.get("inventory_cap"))
		GameProfile.apply_currency_balances(res.data.get("credits_remaining"))
		
		_disable_batch_mode()
		_refresh()
	else:
		print("Batch release failed. Status: ", res.status)
