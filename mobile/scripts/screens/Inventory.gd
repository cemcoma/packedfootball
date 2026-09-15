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
	["Defenders", ["CB", "LB", "RB", "WB"]],
	["Midfielders", ["CDM", "CM", "CAM", "LM", "RM"]],
	["Attackers", ["LW", "RW", "ST"]],
]

@onready var _count_label: Label = %CountLabel
@onready var _credits_chip: CurrencyChip = %CreditsChip
@onready var _filter_dropdown: OptionButton = %FilterDropdown
@onready var _grid: GridContainer = %InventoryGrid
@onready var _empty_label: Label = %EmptyLabel
@onready var _back_button: Button = %BackButton


func _ready() -> void:
	_back_button.pressed.connect(_on_back_pressed)
	_filter_dropdown.item_selected.connect(_on_filter_selected)
	_credits_chip.set_currency("credits")

	for entry in FILTERS:
		_filter_dropdown.add_item(entry[0])
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
	_count_label.text = "%d owned  ·  bench %d / %d" % [
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
	# Same remove_child()-then-queue_free() pairing Team.gd's bench grid uses:
	# this can run from inside a card view's own "pressed" signal, and a plain
	# free() is only safe once that signal has finished dispatching.
	for child in _grid.get_children():
		_grid.remove_child(child)
		child.queue_free()

	var starting := _starting_ids()
	var ids: Array = []
	for player_id in GameProfile.all_cards.keys():
		var card: PlayerCard = GameProfile.all_cards[player_id]
		if _passes_filter(card, starting.has(player_id)):
			ids.append(player_id)

	# Best first, the same ordering the Squad screen's bench already uses.
	ids.sort_custom(
		func(a, b): return GameProfile.all_cards[a].overall() > GameProfile.all_cards[b].overall()
	)

	_empty_label.visible = ids.is_empty()
	if ids.is_empty():
		_empty_label.text = (
			"You don't own any players yet -- open a pack in the Shop."
			if GameProfile.all_cards.is_empty()
			else "No players match this filter."
		)
		return

	for player_id in ids:
		var card: PlayerCard = GameProfile.all_cards[player_id]
		var view: PlayerCardView = PLAYER_CARD_SCENE.instantiate()
		_grid.add_child(view)
		view.set_card(card)
		# The only visual difference between an XI card and a bench one, and
		# the reason Player Details will refuse to release this one.
		view.set_badge("XI" if starting.has(player_id) else "")
		view.pressed.connect(_on_card_pressed.bind(player_id))


func _on_filter_selected(_index: int) -> void:
	_populate_grid()


func _on_card_pressed(player_id: String) -> void:
	PlayerSession.open(player_id, "res://scenes/Inventory.tscn")
	get_tree().change_scene_to_file("res://scenes/PlayerDetail.tscn")


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/TeamHub.tscn")
