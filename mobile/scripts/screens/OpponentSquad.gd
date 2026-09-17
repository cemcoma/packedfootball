extends Control

## A look at the opposition before kickoff: their formation laid out on the
## pitch, and each player's overall and career statistics. Reached from
## Match.tscn's pre-match popup ("View Opponent") and only ever goes back
## there -- Match.tscn re-reads the same MatchSession on the way back, so
## the popup is exactly where it was left.
##
## A read-only cut of Team.tscn, on purpose: same pitch, same card grid,
## same stats panel, minus everything that edits (formation buttons, Auto
## Pick, the bench picker, Replace/Clear/Kit/Save) and minus the attributes
## page -- overall and stats are what you get to see of someone else's
## player, never the numbers underneath.
##
## The opponent's 11 are roster indices 11-21 (see MatchSession), in their
## formation's slot order, so slot i of MatchSession.away_formation() is
## roster index 11 + i. They're wrapped in PlayerCards keyed "away_<slot>"
## purely so PitchView and PlayerCardView can be reused as-is: both take a
## card, not roster fields.

const PLAYER_CARD_SCENE := preload("res://scenes/components/PlayerCardView.tscn")
const MATCH_SCENE := "res://scenes/Match.tscn"

## Career totals, same rows Team.gd's statistics page shows. Keys are the
## ones player.py's DEFAULT_STATISTICS defines; "_pass_accuracy" is
## derived. Keeper-only rows are filtered out for outfielders.
const STAT_ROWS := [
	["Matches", "matches_played"],
	["Goals", "goals"],
	["Assists", "assists"],
	["Shots", "shots"],
	["On target", "shots_on_target"],
	["Passes", "passes"],
	["Completed", "passes_completed"],
	["Pass acc.", "_pass_accuracy"],
	["Tackles won", "tackles_won"],
]

const KEEPER_STAT_ROWS := [
	["Saves", "saves"],
	["Clean sheets", "clean_sheets"],
	["Conceded", "goals_conceded"],
]

var _formation: String = Formations.FORMATION_NAMES[0]
var _cards: Dictionary = {}  # "away_<slot>" -> PlayerCard
var _slot_ids: Array = []  # slot-indexed, "" where the roster had no entry
var selected_slot: int = -1  # -1 = nothing focused

@onready var _title_label: Label = %TitleLabel
@onready var _formation_label: Label = %FormationLabel
@onready var _overall_label: Label = %OverallLabel
@onready var _back_button: Button = %BackButton

@onready var _pitch_view: PitchView = %Pitch
@onready var _panel_header: Label = %PanelHeader
@onready var _squad_scroll: ScrollContainer = %SquadScroll
@onready var _squad_grid: GridContainer = %SquadGrid
@onready var _stats_panel: VBoxContainer = %StatsPanel
@onready var _out_of_position_label: Label = %OutOfPositionLabel
@onready var _stats_card_view: PlayerCardView = %StatsCard
@onready var _stats_extra_country: Label = %StatsExtraCountry
@onready var _stats_extra_rating: Label = %StatsExtraRating
@onready var _stats_page_label: Label = %StatsPageLabel
@onready var _stats_attr_grid: GridContainer = %StatsAttrGrid
@onready var _close_button: Button = %CloseButton


func _ready() -> void:
	_load_opponent()

	_pitch_view.slot_pressed.connect(_on_slot_tapped)
	_close_button.pressed.connect(_on_close_stats_pressed)
	_back_button.pressed.connect(_on_back_pressed)

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()

	_refresh_all()


## Wraps the away side of MatchSession's roster in PlayerCards. A missing
## or malformed entry leaves its slot empty rather than failing the whole
## screen -- PitchView draws an empty marker with just the role.
func _load_opponent() -> void:
	_formation = MatchSession.away_formation()
	_cards.clear()
	_slot_ids.clear()
	var indices: Array = MatchSession.team_indices(MatchSession.TEAM_AWAY)
	for slot in range(indices.size()):
		var fields: Dictionary = MatchSession.player_fields(indices[slot])
		if fields.is_empty():
			_slot_ids.append("")
			continue
		var id := "away_%d" % slot
		_cards[id] = PlayerCard.from_fields(fields, id)
		_slot_ids.append(id)


## Same reasoning as Team.gd: StatsPanel sits straight on the screen
## background, so the labels that carry their own colour override have to
## be recoloured by hand when the theme flips.
func _apply_theme_colors() -> void:
	_title_label.add_theme_color_override("font_color", ThemeManager.color("heading"))
	_overall_label.add_theme_color_override("font_color", ThemeManager.color("heading"))
	_formation_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	_stats_page_label.add_theme_color_override("font_color", ThemeManager.color("heading"))
	_stats_extra_country.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	_out_of_position_label.add_theme_color_override("font_color", ThemeManager.color("warning"))


# -- state -> UI --------------------------------------------------------------


func _refresh_all() -> void:
	_refresh_header()
	_refresh_pitch()
	_refresh_right_panel()


## The same penalty-aware number Team.gd shows for your own squad (see
## SquadOptimizer.squad_overall), so the two are directly comparable.
func _refresh_header() -> void:
	_title_label.text = MatchSession.roster().get("away_name", tr("Opponent"))
	_formation_label.text = _formation
	if _cards.is_empty():
		_overall_label.text = tr("Overall --")
	else:
		_overall_label.text = tr("Overall %d") % SquadOptimizer.squad_overall(_formation, _slot_ids, _cards)


func _refresh_pitch() -> void:
	var slots := Formations.get_formation(_formation)
	_pitch_view.set_formation(slots, _slot_ids, _cards, selected_slot)


func _refresh_right_panel() -> void:
	var showing_stats: bool = selected_slot != -1
	_stats_panel.visible = showing_stats
	_squad_scroll.visible = not showing_stats

	if showing_stats:
		_panel_header.text = tr("Player")
		_populate_stats_panel()
	else:
		_panel_header.text = tr("Starting XI (tap a player for stats)")
		_populate_squad_grid()


## Every opponent card, best first -- the whole side at a glance, since
## unlike Team.tscn there's no bench to browse here.
func _populate_squad_grid() -> void:
	# Can run from inside a card view's own "pressed" signal (tap a card ->
	# _on_card_view_pressed -> _refresh_all() -> here), so the old views are
	# detached now and freed later -- see Team.gd's _populate_bench_grid.
	for child in _squad_grid.get_children():
		_squad_grid.remove_child(child)
		child.queue_free()

	var slots: Array = []
	for slot in range(_slot_ids.size()):
		if _slot_ids[slot] != "":
			slots.append(slot)
	if slots.is_empty():
		var empty_label := Label.new()
		empty_label.text = tr("No opponent squad to show.")
		_squad_grid.add_child(empty_label)
		return
	slots.sort_custom(
		func(a, b): return _cards[_slot_ids[a]].overall() > _cards[_slot_ids[b]].overall()
	)

	var formation_slots := Formations.get_formation(_formation)
	for slot in slots:
		var card: PlayerCard = _cards[_slot_ids[slot]]
		var view: PlayerCardView = PLAYER_CARD_SCENE.instantiate()
		_squad_grid.add_child(view)
		view.set_card(card)
		view.set_out_of_position(card.position != formation_slots[slot]["role"])
		view.pressed.connect(_on_card_view_pressed.bind(slot))


func _populate_stats_panel() -> void:
	var card: PlayerCard = _cards[_slot_ids[selected_slot]]
	_stats_card_view.set_card(card)

	var slots := Formations.get_formation(_formation)
	var role: String = slots[selected_slot]["role"]
	var out_of_position: bool = card.position != role
	_stats_card_view.set_out_of_position(out_of_position)
	_out_of_position_label.visible = out_of_position
	if out_of_position:
		_out_of_position_label.text = tr("Out of position: a %s playing %s -- attributes reduced 10%% in matches.") % [card.position, role]

	_stats_extra_country.text = "%s\n%s" % [card.hometown, card.country]

	for child in _stats_attr_grid.get_children():
		_stats_attr_grid.remove_child(child)
		child.queue_free()

	_stats_page_label.text = tr("Career Statistics")
	for row in STAT_ROWS:
		_add_stat_row(tr(row[0]), _career_stat_text(card, row[1]))
	if card.position == "GK":
		for row in KEEPER_STAT_ROWS:
			_add_stat_row(tr(row[0]), _career_stat_text(card, row[1]))

	# rating_sum/rating_count are storage rather than a stat -- derive the
	# average the same way player.py's average_rating() does.
	var count: float = float(card.statistics.get("rating_count", 0))
	if count > 0.0:
		var avg: float = float(card.statistics.get("rating_sum", 0.0)) / count
		_stats_extra_rating.text = tr("\nAvg rating\n%.2f") % avg
	else:
		_stats_extra_rating.text = tr("\nAvg rating\n-")


func _career_stat_text(card: PlayerCard, key: String) -> String:
	if key == "_pass_accuracy":
		var passes: float = float(card.statistics.get("passes", 0))
		if passes <= 0.0:
			return "-"
		return "%d%%" % int(round(100.0 * float(card.statistics.get("passes_completed", 0)) / passes))
	return str(int(card.statistics.get(key, 0)))


func _add_stat_row(label_text: String, value_text: String) -> void:
	var name_label := Label.new()
	name_label.text = label_text
	_stats_attr_grid.add_child(name_label)
	var value_label := Label.new()
	value_label.text = value_text
	_stats_attr_grid.add_child(value_label)


# -- input handlers -----------------------------------------------------------


func _on_slot_tapped(i: int) -> void:
	if selected_slot == i or _slot_ids[i] == "":
		selected_slot = -1  # tap again to deselect; nothing to show for an empty slot
	else:
		selected_slot = i
	_refresh_all()


func _on_card_view_pressed(slot: int) -> void:
	selected_slot = slot
	_refresh_all()


func _on_close_stats_pressed() -> void:
	selected_slot = -1
	_refresh_all()


## Back to the pre-match popup. Nothing to save or discard -- this screen
## never touches MatchSession, and Match.tscn rebuilds itself from it.
func _on_back_pressed() -> void:
	get_tree().change_scene_to_file(MATCH_SCENE)
