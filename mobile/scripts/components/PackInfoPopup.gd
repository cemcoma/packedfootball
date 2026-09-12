class_name PackInfoPopup
extends Control

## Full-screen modal disclosing a pack's odds -- App Store Guideline 3.1.1 /
## Google Play's loot box policy both require showing the probability of
## obtaining each item tier before purchase, not just after. Opened from
## PackView's "i" button (see Shop.gd); a single instance lives statically
## in Shop.tscn (embedded like PitchView is in Team.tscn) rather than being
## instantiated per-pack the way PackView itself is, since only one can
## ever be open at a time.
##
## Three pages, paged with Prev/Next rather than shown all at once so the
## odds tables (which can run long once more tiers/positions exist) don't
## have to compete with the flavor text for space:
##   0. Description -- name/type/flavor text, same description PackView
##      already shows on the box itself.
##   1. Rates -- card tier odds (bronze/silver/... -> %), from PackData.rates.
##   2. Position rates -- goalkeeper/defender/midfielder/attacker -> %,
##      from PackData.pos_rates.
##
## Row order on both odds pages is a fixed client-side list, NOT dictionary
## iteration order -- Firestore/JSON round-tripping doesn't guarantee a map
## field's key order survives, so relying on it would let row order jitter
## from one load to the next. Tier order reuses PlayerCard.TIER_COLORS'
## key order (already the project's one canonical tier ordering); position
## category order is this file's own POSITION_CATEGORY_ORDER, since nothing
## else client-side needs those four names today.

const POSITION_CATEGORY_ORDER := ["goalkeeper", "defender", "midfielder", "attacker"]
const PAGE_COUNT := 3

@onready var _panel_title: Label = %PanelTitle
@onready var _type_label: Label = %TypeLabel
@onready var _pages: TabContainer = %Pages
@onready var _description_label: Label = %DescriptionLabel
@onready var _rates_grid: GridContainer = %RatesGrid
@onready var _rates_empty_label: Label = %RatesEmptyLabel
@onready var _position_rates_grid: GridContainer = %PositionRatesGrid
@onready var _position_rates_empty_label: Label = %PositionRatesEmptyLabel
@onready var _page_label: Label = %PageLabel
@onready var _prev_button: Button = %PrevButton
@onready var _next_button: Button = %NextButton
@onready var _close_button: Button = %CloseButton

var _page: int = 0


func _ready() -> void:
	visible = false
	_prev_button.pressed.connect(_on_prev_pressed)
	_next_button.pressed.connect(_on_next_pressed)
	_close_button.pressed.connect(_on_close_pressed)


func open_for(pack: PackData) -> void:
	_panel_title.text = pack.pack_name
	_type_label.text = pack.type.capitalize()
	_description_label.text = pack.description if pack.description != "" else "No description available."
	_populate_grid(_rates_grid, _rates_empty_label, _odds_rows(pack.rates, PlayerCard.TIER_COLORS.keys()))
	_populate_grid(_position_rates_grid, _position_rates_empty_label, _odds_rows(pack.pos_rates, POSITION_CATEGORY_ORDER))
	_page = 0
	_refresh_page()
	visible = true


## [[label, percent_int], ...] for every key in `order` whose rate is > 0,
## in that fixed order -- zero-chance tiers/positions aren't "obtainable"
## so they're left off rather than cluttering the disclosure with 0% rows.
func _odds_rows(rates: Dictionary, order: Array) -> Array:
	var rows: Array = []
	for key in order:
		var rate: float = rates.get(key, 0.0)
		if rate > 0.0:
			rows.append([String(key).capitalize(), int(round(rate * 100.0))])
	return rows


func _populate_grid(grid: GridContainer, empty_label: Label, rows: Array) -> void:
	for child in grid.get_children():
		grid.remove_child(child)
		child.queue_free()

	grid.visible = not rows.is_empty()
	empty_label.visible = rows.is_empty()
	for row in rows:
		var name_label := Label.new()
		name_label.text = row[0]
		grid.add_child(name_label)
		var value_label := Label.new()
		value_label.text = "%d%%" % row[1]
		value_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		grid.add_child(value_label)


func _refresh_page() -> void:
	_pages.current_tab = _page
	_page_label.text = "%d / %d" % [_page + 1, PAGE_COUNT]
	_prev_button.disabled = _page == 0
	_next_button.disabled = _page == PAGE_COUNT - 1


func _on_prev_pressed() -> void:
	_page = maxi(0, _page - 1)
	_refresh_page()


func _on_next_pressed() -> void:
	_page = mini(PAGE_COUNT - 1, _page + 1)
	_refresh_page()


func _on_close_pressed() -> void:
	visible = false
