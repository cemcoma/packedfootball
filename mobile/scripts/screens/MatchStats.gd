extends Control

## Per-player breakdown of the match just played, reached from
## MatchResult.tscn's "Detailed Stats" button.
##
## Same shape as the Team screen -- a roster list on the left, a detail panel
## on the right -- but tapping a player never CHANGES anything here, it only
## shows their numbers. Both squads are listed, since seeing what the
## opponent's players did is half the point of a post-match screen.
##
## The bottom button toggles between what happened in THIS match and the
## card's career totals plus its attributes.
##
## Everything comes off the MatchSession autoload, which MatchResult
## deliberately leaves populated (it clears only on the way back to Menu),
## so this screen never re-fetches anything.

const RESULT_SCENE := "res://scenes/MatchResult.tscn"

## [label, key, format] for this match. "pct"/"rating" are derived below
## rather than read straight off the stats dictionary.
const MATCH_ROWS := [
	["Rating", "rating", "rating"],
	["Goals", "goals", "int"],
	["Assists", "assists", "int"],
	["Shots", "shots", "int"],
	["On target", "shots_on_target", "int"],
	["Passes", "passes", "int"],
	["Completed", "passes_completed", "int"],
	["Pass accuracy", "_pass_accuracy", "pct"],
	["Tackles", "tackles", "int"],
	["Tackles won", "tackles_won", "int"],
]

## Only shown for a goalkeeper -- an outfielder's zeroes here are noise.
const MATCH_KEEPER_ROWS := [
	["Saves", "saves", "int"],
	["Conceded", "goals_conceded", "int"],
	["Clean sheet", "clean_sheets", "bool"],
]

const CAREER_ROWS := [
	["Matches", "matches_played", "int"],
	["Goals", "goals", "int"],
	["Assists", "assists", "int"],
	["Shots", "shots", "int"],
	["On target", "shots_on_target", "int"],
	["Passes", "passes", "int"],
	["Completed", "passes_completed", "int"],
	["Tackles won", "tackles_won", "int"],
	["Saves", "saves", "int"],
	["Clean sheets", "clean_sheets", "int"],
]

## Mirrors Team.gd's ATTR_ROWS, plus height (centimetres, not a 0-100 skill
## -- see player.py's PHYSICAL_FIELDS).
const ATTR_ROWS := [
	["Height", "height"], ["Stamina", "stamina"], ["Speed", "speed"], ["Agility", "agility"],
	["Passing", "passing"], ["Ball Ctrl", "ballcontrol"], ["Defending", "defending"],
	["Tackling", "tackling"], ["Dribbling", "dribbling"], ["Shooting", "shooting"],
	["Power", "power"], ["Accuracy", "accuracy"], ["Vision", "vision"],
	["Heading", "heading"],
]

var _selected_index: int = -1
var _show_career: bool = false
var _row_buttons: Dictionary = {}  # global player index -> Button

@onready var _title_label: Label = %TitleLabel
@onready var _back_button: Button = %BackButton
@onready var _home_header: Label = %HomeHeader
@onready var _away_header: Label = %AwayHeader
@onready var _home_list: VBoxContainer = %HomeList
@onready var _away_list: VBoxContainer = %AwayList
@onready var _detail_name: Label = %DetailName
@onready var _detail_sub: Label = %DetailSub
@onready var _detail_grid: GridContainer = %DetailGrid
@onready var _mode_button: Button = %ModeButton


func _ready() -> void:
	_back_button.pressed.connect(_on_back_pressed)
	_mode_button.pressed.connect(_on_mode_pressed)

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()

	var score: Array = MatchSession.score
	var my_score: int = score[0] if score.size() == 2 else 0
	var opp_score: int = score[1] if score.size() == 2 else 0
	var opponent_name: String = MatchSession.opponent_display_name if MatchSession.opponent_display_name != "" else tr("Opponent")
	_title_label.text = tr("Match Statistics   %d - %d") % [my_score, opp_score]
	_home_header.text = tr("You")
	_away_header.text = opponent_name

	_populate_list(MatchSession.TEAM_HOME, _home_list)
	_populate_list(MatchSession.TEAM_AWAY, _away_list)
	_update_mode_button()

	# Open on whoever had the best match on your side -- more interesting
	# than always landing on the goalkeeper.
	_select_player(_best_rated(MatchSession.TEAM_HOME))


func _best_rated(team: int) -> int:
	var best := -1
	var best_rating := -1.0
	for index in MatchSession.team_indices(team):
		var rating: float = float(MatchSession.match_stats_for(index).get("rating", 0.0))
		if rating > best_rating:
			best_rating = rating
			best = index
	return best


## One tappable row per player: name, position, and their rating for the
## match so the list itself is readable at a glance.
func _populate_list(team: int, into: VBoxContainer) -> void:
	for child in into.get_children():
		into.remove_child(child)
		child.queue_free()

	for index in MatchSession.team_indices(team):
		var fields: Dictionary = MatchSession.player_fields(index)
		var stats: Dictionary = MatchSession.match_stats_for(index)
		var position_raw = fields.get("position")
		var position: String = position_raw if position_raw is String else "--"

		var button := Button.new()
		button.custom_minimum_size = Vector2(0, 30)
		button.toggle_mode = true
		button.alignment = HORIZONTAL_ALIGNMENT_LEFT
		button.add_theme_font_size_override("font_size", 13)
		button.clip_text = true

		var rating_text := ""
		if not stats.is_empty():
			rating_text = "  %.1f" % float(stats.get("rating", 0.0))
		var goals: int = int(stats.get("goals", 0))
		var goal_mark := ""
		for i in range(goals):
			goal_mark += " *"
		button.text = "%-4s %s%s%s" % [position, MatchSession.player_name(index), goal_mark, rating_text]

		button.pressed.connect(_select_player.bind(index))
		into.add_child(button)
		_row_buttons[index] = button


func _select_player(index: int) -> void:
	if index < 0:
		return
	_selected_index = index
	for row_index in _row_buttons.keys():
		(_row_buttons[row_index] as Button).button_pressed = row_index == index
	_refresh_detail()


func _refresh_detail() -> void:
	for child in _detail_grid.get_children():
		_detail_grid.remove_child(child)
		child.queue_free()

	if _selected_index < 0:
		_detail_name.text = tr("Select a player")
		_detail_sub.text = ""
		return

	var fields: Dictionary = MatchSession.player_fields(_selected_index)
	var position_raw = fields.get("position")
	var position: String = position_raw if position_raw is String else "--"
	var tier_raw = fields.get("tier")
	var tier: String = tier_raw if tier_raw is String else ""

	_detail_name.text = MatchSession.player_name(_selected_index)
	var side := tr("You") if _selected_index < MatchSession.PLAYERS_PER_TEAM else _away_header.text
	_detail_sub.text = "%s  -  %s  -  %s" % [position, PlayerCard.tier_label(tier), side]

	if _show_career:
		_build_career_rows(fields, position)
	else:
		_build_match_rows(position)


func _build_match_rows(position: String) -> void:
	var stats: Dictionary = MatchSession.match_stats_for(_selected_index)
	if stats.is_empty():
		_add_note(tr("No match stats for this player."))
		return

	_add_section(tr("This Match"))
	for row in MATCH_ROWS:
		_add_row(tr(row[0]), _stat_text(stats, row[1], row[2]))
	if position == "GK":
		for row in MATCH_KEEPER_ROWS:
			_add_row(tr(row[0]), _stat_text(stats, row[1], row[2]))


func _build_career_rows(fields: Dictionary, position: String) -> void:
	var stats_raw = fields.get("statistics")
	var stats: Dictionary = stats_raw if stats_raw is Dictionary else {}

	_add_section(tr("Career"))
	if stats.is_empty():
		_add_note(tr("No career stats recorded."))
	else:
		# rating_sum/rating_count are storage, not a stat -- show the average
		# the same way player.py's average_rating() derives it.
		var count: float = float(stats.get("rating_count", 0))
		var avg: float = (float(stats.get("rating_sum", 0.0)) / count) if count > 0 else 0.0
		_add_row(tr("Avg rating"), "%.2f" % avg if count > 0 else "-")
		for row in CAREER_ROWS:
			if row[1] in ["saves", "clean_sheets"] and position != "GK":
				continue
			_add_row(tr(row[0]), str(int(stats.get(row[1], 0))))

	var attributes_raw = fields.get("attributes")
	var attributes: Dictionary = attributes_raw if attributes_raw is Dictionary else {}
	_add_section(tr("Attributes"))
	if attributes.is_empty():
		_add_note(tr("No attributes recorded."))
		return
	for row in ATTR_ROWS:
		var value: int = int(attributes.get(row[1], 0))
		var text := "%d cm" % value if row[1] == "height" else str(value)
		_add_row(tr(row[0]), text)


func _stat_text(stats: Dictionary, key: String, kind: String) -> String:
	if key == "_pass_accuracy":
		var passes: float = float(stats.get("passes", 0))
		if passes <= 0.0:
			return "-"
		return "%d%%" % int(round(100.0 * float(stats.get("passes_completed", 0)) / passes))

	var value = stats.get(key, 0)
	match kind:
		"rating":
			return "%.1f" % float(value)
		"bool":
			return tr("Yes") if int(value) > 0 else tr("No")
		_:
			return str(int(value))


## The two squad columns are plain VBoxContainers -- no panel behind them --
## so their headers sit directly on the screen background and the Theme's
## Label color never reaches them. Their pale blue/pink read well on the dark
## backdrop and washed out completely on the light one. The detail panel is a
## different case: it has its own permanently-dark stylebox, so the colors in
## _add_section/_add_row/_add_note stay light in both modes on purpose.
func _apply_theme_colors() -> void:
	_home_header.add_theme_color_override("font_color", ThemeManager.color("heading"))
	_away_header.add_theme_color_override("font_color", ThemeManager.color("heading_away"))


func _add_section(title: String) -> void:
	var heading := Label.new()
	heading.text = title
	heading.add_theme_font_size_override("font_size", 13)
	heading.add_theme_color_override("font_color", Color(0.75, 0.85, 1.0))
	_detail_grid.add_child(heading)
	# The grid is two columns; keep the heading on its own line.
	_detail_grid.add_child(Control.new())


func _add_row(label_text: String, value_text: String) -> void:
	var name_label := Label.new()
	name_label.text = label_text
	name_label.add_theme_font_size_override("font_size", 13)
	name_label.add_theme_color_override("font_color", Color(0.7, 0.7, 0.75))
	_detail_grid.add_child(name_label)

	var value_label := Label.new()
	value_label.text = value_text
	value_label.add_theme_font_size_override("font_size", 13)
	value_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	value_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_detail_grid.add_child(value_label)


func _add_note(text: String) -> void:
	var note := Label.new()
	note.text = text
	note.add_theme_font_size_override("font_size", 12)
	note.add_theme_color_override("font_color", Color(0.65, 0.65, 0.65))
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_detail_grid.add_child(note)
	_detail_grid.add_child(Control.new())


func _on_mode_pressed() -> void:
	_show_career = not _show_career
	_update_mode_button()
	_refresh_detail()


func _update_mode_button() -> void:
	_mode_button.text = tr("Show Match Statistics") if _show_career else tr("Show All Statistics")


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file(RESULT_SCENE)
