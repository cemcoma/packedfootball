extends Control

## Before kick-off: both sides at a glance with VS between them, and each one's
## full XI a tap away on ManagerView. Reads MatchSession only, so coming back
## from ManagerView rebuilds it exactly as it was left.
##
## Each side is a TeamInfoPanel; _fill_side() fills one and adds its View Team.

const MATCH_SCENE := "res://scenes/Match.tscn"

@onready var _home_panel: TeamInfoPanel = %HomePanel
@onready var _away_panel: TeamInfoPanel = %AwayPanel
@onready var _vs_label: Label = %VsLabel
@onready var _start_button: Button = %StartButton

var _view_buttons: Array[Button] = []


func _ready() -> void:
	_start_button.pressed.connect(_on_start_pressed)
	_fill_side(_home_panel, MatchSession.TEAM_HOME)
	_fill_side(_away_panel, MatchSession.TEAM_AWAY)
	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()


func _fill_side(panel: TeamInfoPanel, team: int) -> void:
	# The kit as picked, even when Match.tscn puts the away side in a change kit.
	panel.set_team(
		MatchSession.team_name(team), MatchSession.team_kit(team), MatchSession.record(team),
		MatchSession.formation(team), MatchSession.tactic_style(team), MatchSession.team_overall(team),
	)

	var view_button := Button.new()
	view_button.text = tr("View Team")
	view_button.custom_minimum_size = Vector2(180, 40)
	view_button.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	view_button.add_theme_font_size_override("font_size", 15)
	# The bundled demo replay carries names only -- nothing to lay out.
	view_button.disabled = not MatchSession.has_pending()
	view_button.pressed.connect(_on_view_team_pressed.bind(team))
	panel.extra.add_child(view_button)
	_view_buttons.append(view_button)


## The panels style themselves; the View Team buttons and the VS follow the palette.
func _apply_theme_colors() -> void:
	var accent := ThemeManager.color("accent")
	for button in _view_buttons:
		MenuTile.style_button(button, ThemeManager.color("surface_border"))
	MenuTile.style_button(_start_button, accent, true)
	_vs_label.add_theme_color_override("font_color", accent)


func _on_view_team_pressed(team: int) -> void:
	ManagerSession.open_match_team(team, scene_file_path)


func _on_start_pressed() -> void:
	get_tree().change_scene_to_file(MATCH_SCENE)
