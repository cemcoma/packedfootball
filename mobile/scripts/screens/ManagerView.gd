extends Control

## Another manager: name, win/draw/loss record, league, and the XI they
## field laid out on the pitch, with each player's overall and career
## statistics. Two ways in, decided by ManagerSession:
##
##   - a leaderboard row (ManagerSession.uid set): the squad comes from
##     GET /manager/{uid};
##   - "View Opponent" on Match.tscn's pre-match popup (uid ""): the away
##     side is read straight out of MatchSession, which already holds the
##     opponent's roster, name and record from the match response -- no
##     request, and a bot opponent (which has no profile) works too.
##
## Back goes to ManagerSession.return_scene. Match.tscn re-reads the same
## MatchSession on the way back, so the pre-match popup is exactly where
## it was left.
##
## A read-only cut of Team.tscn, on purpose: same pitch, same card grid,
## same stats panel, minus everything that edits (formation buttons, Auto
## Pick, the bench picker, Replace/Clear/Kit/Save) and minus the attributes
## page -- overall and stats are what you get to see of someone else's
## player, never the numbers underneath.
##
## The 11 are in formation slot order (a match response's indices 11-21,
## or /manager's roster as sent), wrapped in PlayerCards keyed
## "slot_<i>" purely so PitchView and PlayerCardView can be reused as-is:
## both take a card, not roster fields.

const PLAYER_CARD_SCENE := preload("res://scenes/components/PlayerCardView.tscn")

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
var _cards: Dictionary = {}  # "slot_<i>" -> PlayerCard
var _slot_ids: Array = []  # slot-indexed, "" where the roster had no entry
var selected_slot: int = -1  # -1 = nothing focused
var _manager_name: String = ""
var _record: Dictionary = {}  # wins/draws/losses, {} when unknown (a bot)
var _league_name: String = ""
var _kit: String = ""

@onready var _title_label: Label = %TitleLabel
@onready var _record_label: Label = %RecordLabel
@onready var _league_label: Label = %LeagueLabel
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
	_pitch_view.slot_pressed.connect(_on_slot_tapped)
	_close_button.pressed.connect(_on_close_stats_pressed)
	_back_button.pressed.connect(_on_back_pressed)

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()

	if ManagerSession.uid == "":
		_load_match_opponent()
		_refresh_all()
	else:
		_title_label.text = tr("Loading...")
		await _load_manager(ManagerSession.uid)
		_refresh_all()


## The away side of MatchSession's roster. A missing or malformed entry
## leaves its slot empty rather than failing the whole screen -- PitchView
## draws an empty marker with just the role.
func _load_match_opponent() -> void:
	var roster := MatchSession.roster()
	_manager_name = str(roster.get("away_name", tr("Opponent")))
	_record = MatchSession.opponent_record
	_kit = str(roster.get("away_kit", ""))
	_league_name = ""
	var fields_list: Array = []
	for index in MatchSession.team_indices(MatchSession.TEAM_AWAY):
		fields_list.append(MatchSession.player_fields(index))
	_set_squad(MatchSession.away_formation(), fields_list)


## GET /manager/{uid}: the squad as that manager has it saved right now.
func _load_manager(uid: String) -> void:
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/manager/" + uid.uri_encode())
	if not res.ok:
		_manager_name = tr("Manager")
		_record = {}
		_set_squad(Formations.FORMATION_NAMES[0], [])
		_panel_header.text = tr("Could not load this manager -- try again later.")
		return
	var data: Dictionary = res.data
	var name_raw = data.get("display_name")
	_manager_name = name_raw if name_raw is String and name_raw != "" else tr("Manager")
	_record = {"wins": data.get("wins", 0), "draws": data.get("draws", 0), "losses": data.get("losses", 0)}
	var kit_raw = data.get("kit")
	_kit = kit_raw if kit_raw is String else ""
	var league_raw = data.get("tier_name")
	_league_name = league_raw if league_raw is String else ""
	var formation_raw = data.get("formation")
	var roster_raw = data.get("roster")
	_set_squad(
		formation_raw if formation_raw is String and Formations.FORMATION_NAMES.has(formation_raw) else Formations.FORMATION_NAMES[0],
		roster_raw if roster_raw is Array else [],
	)


## This manager's shirt for the portraits -- every card view defaults to
## the signed-in manager's own kit, which is the wrong one here. Null when
## none was sent, which the view treats as the default kit.
func _kit_design() -> KitDesign:
	return KitDesign.parse(_kit) if _kit != "" else null


## Wraps a list of player-field dictionaries (formation slot order) in
## PlayerCards, one per slot.
func _set_squad(formation: String, fields_list: Array) -> void:
	_formation = formation
	_cards.clear()
	_slot_ids.clear()
	var slot_count := Formations.get_formation(formation).size()
	for slot in range(slot_count):
		var fields = fields_list[slot] if slot < fields_list.size() else null
		if not (fields is Dictionary) or fields.is_empty():
			_slot_ids.append("")
			continue
		var id := "slot_%d" % slot
		_cards[id] = PlayerCard.from_fields(fields, id)
		_slot_ids.append(id)


## Same reasoning as Team.gd: StatsPanel sits straight on the screen
## background, so the labels that carry their own colour override have to
## be recoloured by hand when the theme flips.
func _apply_theme_colors() -> void:
	_title_label.add_theme_color_override("font_color", ThemeManager.color("heading"))
	_overall_label.add_theme_color_override("font_color", ThemeManager.color("heading"))
	_formation_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	_league_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
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
	_title_label.text = _manager_name
	# A bot has no record; the label stays out of the way rather than
	# claiming 0-0-0.
	_record_label.visible = not _record.is_empty()
	if not _record.is_empty():
		_record_label.text = tr("%d W  %d D  %d L") % [
			int(_record.get("wins", 0)), int(_record.get("draws", 0)), int(_record.get("losses", 0))
		]
	_league_label.visible = _league_name != ""
	_league_label.text = _league_name
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
		empty_label.text = tr("No squad to show.")
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
		view.set_kit(_kit_design())
		view.set_out_of_position(card.position != formation_slots[slot]["role"])
		view.pressed.connect(_on_card_view_pressed.bind(slot))


func _populate_stats_panel() -> void:
	var card: PlayerCard = _cards[_slot_ids[selected_slot]]
	_stats_card_view.set_card(card)
	_stats_card_view.set_kit(_kit_design())

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


## Back to wherever ManagerSession says: the leaderboard, or the pre-match
## popup (nothing to save or discard -- this screen never touches
## MatchSession, and Match.tscn rebuilds itself from it).
func _on_back_pressed() -> void:
	var destination := ManagerSession.return_scene
	ManagerSession.clear()
	get_tree().change_scene_to_file(destination)
