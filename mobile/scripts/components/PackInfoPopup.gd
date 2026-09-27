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
##   1. Rates -- card tier odds, one labelled block per card slot, scrollable.
##      Every block lists the same tiers so they can be read against each other.
##   2. Position rates -- goalkeeper/defender/midfielder/attacker -> %,
##      from PackData.pos_rates.
##   3. Items -- item rarity odds, and how many drop. Its own page rather than
##      more rows on page 1: an item and a card are different things and
##      merging them into one table would read as one pool.
##   4. Availability -- If there is any limitations on the pack it is shown here
##
## Row order on both odds pages is a fixed client-side list, NOT dictionary
## iteration order -- Firestore/JSON round-tripping doesn't guarantee a map
## field's key order survives, so relying on it would let row order jitter
## from one load to the next. Tier order reuses PlayerCard.TIER_COLORS'
## key order (already the project's one canonical tier ordering); position
## category order is this file's own POSITION_CATEGORY_ORDER, since nothing
## else client-side needs those four names today.

const POSITION_CATEGORY_ORDER := ["goalkeeper", "defender", "midfielder", "attacker"]
const PAGE_COUNT := 5

@onready var _panel_title: Label = %PanelTitle
@onready var _type_label: Label = %TypeLabel
@onready var _pages: TabContainer = %Pages
@onready var _description_label: Label = %DescriptionLabel
@onready var _rates_grid: GridContainer = %RatesGrid
@onready var _rates_empty_label: Label = %RatesEmptyLabel
@onready var _position_rates_grid: GridContainer = %PositionRatesGrid
@onready var _position_rates_empty_label: Label = %PositionRatesEmptyLabel
@onready var _item_rates_grid: GridContainer = %ItemRatesGrid
@onready var _item_rates_empty_label: Label = %ItemRatesEmptyLabel
@onready var _item_count_label: Label = %ItemCountLabel
@onready var _availability_label: Label = %AvailabilityLabel
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
	_type_label.text = tr(pack.type.capitalize())
	_description_label.text = pack.description if pack.description != "" else tr("No description available.")
	_populate_grid(_rates_grid, _rates_empty_label, _card_rates_rows(pack))
	_populate_grid(_position_rates_grid, _position_rates_empty_label, _odds_rows(pack.pos_rates, POSITION_CATEGORY_ORDER))
	_populate_grid(
		_item_rates_grid, _item_rates_empty_label,
		_odds_rows(pack.item_rates, PlayerCard.TIER_COLORS.keys())
	)
	_item_count_label.text = (
		tr("This pack contains %d items.") % pack.items_per_pack
		if pack.items_per_pack > 0
		else tr("This pack contains no items.")
	)
	if pack.remaining_opens != null or pack.expires_at != "":
		_availability_text(pack.remaining_opens,pack.expires_at)
	else:
		_availability_label.text = tr("Always available")
	_page = 0
	_refresh_page()
	visible = true


## [[label, float .2f], ...] for every key in `order` whose rate is > 0,
## in that fixed order -- zero-chance tiers/positions aren't "obtainable"
## so they're left off rather than cluttering the disclosure with 0% rows.
##
## `order` is by tier FAMILY (TIER_COLORS' keys), while a pack's rates are
## keyed by the exact tier it rolls -- "special_champ", not "special" -- so
## each family slot collects every rate key that belongs to it. Without
## that the special row was never matched and the 2% simply went missing
## from the disclosure, which is the one thing this popup exists to show.
## Position keys ("goalkeeper", ...) have no family and pass through as
## themselves, so the same function serves both tables.
## One decimal under 10%, whole numbers above -- a 1% icon slot must not round
## away to "0%". A real zero is plain "0%", since the zero rows only exist to
## line the blocks up and should be the quietest thing on the page.
func _percent(p: float) -> String:
	var pct := p * 100.0
	if pct <= 0.0:
		return "0%"
	return ("%.1f%%" % pct) if pct < 10.0 else ("%d%%" % roundi(pct))


## Every card slot, under its own heading. Consecutive slots sharing one table
## collapse into a range ("Cards 2-3") so a six-card pack is one block rather
## than six copies, but every slot number is accounted for.
##
## EVERY BLOCK LISTS THE SAME TIERS, 0% included. The Diamond pack's first
## slot cannot roll a gold and the other two cannot roll its diamond rate, so
## dropping the zero rows left two blocks with different rows that could not be
## read against each other.
func _card_rates_rows(pack: PackData) -> Array:
	if pack.cards_per_pack <= 0:
		return []
	var families := _tier_families(pack)
	if families.is_empty():
		return []
	var rows: Array = []
	var group_start := 0
	while group_start < pack.cards_per_pack:
		var table: Dictionary = pack.slot_rates.get(str(group_start), pack.rates)
		var group_end := group_start
		while group_end + 1 < pack.cards_per_pack:
			var next_table: Dictionary = pack.slot_rates.get(str(group_end + 1), pack.rates)
			if next_table != table:
				break
			group_end += 1
		rows.append([
			tr("Card %d") % (group_start + 1) if group_start == group_end
			else tr("Cards %d-%d") % [group_start + 1, group_end + 1],
			"", true,
		])
		for family in families:
			rows.append(["    %s" % PlayerCard.tier_label(family), _percent(_family_rate(table, family))])
		group_start = group_end + 1
	return rows


## Which tier families this pack can produce ANYWHERE, in canonical order. The
## union across `rates` and every slot_rates table, so all blocks share a shape.
func _tier_families(pack: PackData) -> Array:
	var seen := {}
	var tables: Array = [pack.rates]
	for key in pack.slot_rates.keys():
		tables.append(pack.slot_rates[key])
	for table in tables:
		for tier in table.keys():
			if float(table[tier]) > 0.0:
				seen[PlayerCard.tier_family(String(tier))] = true
	var out: Array = []
	for family in PlayerCard.TIER_COLORS.keys():
		if seen.has(family):
			out.append(family)
	return out


## One table's total chance for a family, summing its variants ("special" plus
## "special_champ"). 0.0 when this slot cannot roll that family at all.
func _family_rate(table: Dictionary, family: String) -> float:
	var total := 0.0
	for tier in table.keys():
		if PlayerCard.tier_family(String(tier)) == family:
			total += float(table[tier])
	return total


func _odds_rows(rates: Dictionary, order: Array) -> Array:
	var rows: Array = []
	for family in order:
		for key in rates.keys():
			var tier := String(key)
			if PlayerCard.tier_family(tier) != family:
				continue
			var rate: float = rates.get(key, 0.0)
			if rate > 0.0:
				rows.append([PlayerCard.tier_label(tier), _percent(rate)])
	return rows


func _populate_grid(grid: GridContainer, empty_label: Label, rows: Array) -> void:
	for child in grid.get_children():
		grid.remove_child(child)
		child.queue_free()

	grid.visible = not rows.is_empty()
	empty_label.visible = rows.is_empty()
	for row in rows:
		# [text, already-formatted value, is_heading]. A heading row carries no
		# value and is dimmed, so a slot's block is visually its own group.
		var is_heading: bool = row.size() > 2 and bool(row[2])
		var name_label := Label.new()
		name_label.text = row[0]
		if is_heading:
			name_label.add_theme_color_override("font_color", Color(0.75, 0.75, 0.75))
		grid.add_child(name_label)
		var value_label := Label.new()
		value_label.text = String(row[1])
		value_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		grid.add_child(value_label)

func _availability_text(remaining_opens,expires_at:String) -> void:
	var remaining_opens_text :=  ""
	var expires_at_text :=  ""
	if remaining_opens != null:
		remaining_opens_text = tr("Remaining opens: %d") % remaining_opens
	if expires_at != "":
		expires_at_text = tr("Expires at: %s") % TimeFormat.local_datetime(expires_at)
		
	_availability_label.text = "%s\n%s" % [remaining_opens_text,expires_at_text]

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
