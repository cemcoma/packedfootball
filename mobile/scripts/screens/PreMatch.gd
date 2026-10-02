extends Control

## Before kick-off: both sides at a glance with VS between them, and each one's
## full XI a tap away on ManagerView. Reads MatchSession only, so coming back
## from ManagerView rebuilds it exactly as it was left.
##
## The two panels are the same subtree under different names, filled by one
## _fill_side() through relative paths.

const MATCH_SCENE := "res://scenes/Match.tscn"

@onready var _home_panel: PanelContainer = %HomePanel
@onready var _away_panel: PanelContainer = %AwayPanel
@onready var _vs_label: Label = %VsLabel
@onready var _start_button: Button = %StartButton


func _ready() -> void:
	_start_button.pressed.connect(_on_start_pressed)
	_fill_side(_home_panel, MatchSession.TEAM_HOME)
	_fill_side(_away_panel, MatchSession.TEAM_AWAY)
	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()


func _fill_side(panel: PanelContainer, team: int) -> void:
	# The kit as picked, even when Match.tscn puts the away side in a change kit.
	panel.get_node("Box/NameKitContainer/KitSwatch").set_design(KitDesign.parse(MatchSession.team_kit(team)))
	panel.get_node("Box/NameKitContainer/NameLabel").text = MatchSession.team_name(team)

	# A bot has no record.
	var record := MatchSession.record(team)
	panel.get_node("Box/InfoBox/RecordRow/Value").text = tr("%d W  %d D  %d L") % [0,0,0] if record.is_empty() else tr("%d W  %d D  %d L") % [
		int(record.get("wins", 0)), int(record.get("draws", 0)), int(record.get("losses", 0))
	]
	panel.get_node("Box/InfoBox/FormationRow/Value").text = MatchSession.formation(team)
	var overall := MatchSession.team_overall(team)
	panel.get_node("Box/InfoBox/OverallRow/Value").text = str(overall) if overall > 0 else "--"

	var view_button: Button = panel.get_node("Box/ViewTeamButton")
	# The bundled demo replay carries names only -- nothing to lay out.
	view_button.disabled = not MatchSession.has_pending()
	view_button.pressed.connect(_on_view_team_pressed.bind(team))


## The panels are dark in both themes (MenuTile.BASE_FILL), so their text keeps
## the tiles' fixed colours; only the frames and the VS follow the palette.
func _apply_theme_colors() -> void:
	var accent := ThemeManager.color("accent")
	var muted := ThemeManager.color("surface_border")
	for panel in [_home_panel, _away_panel]:
		panel.add_theme_stylebox_override(
			"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, muted, 3, true, Vector2(18, 14))
		)
		panel.get_node("Box/NameKitContainer/NameLabel").add_theme_color_override("font_color", MenuTile.TITLE_COLOR)
		# Every InfoBox row is a Caption + Value pair.
		for row in panel.get_node("Box/InfoBox").get_children():
			if row.get_node("Caption"):
				row.get_node("Caption").add_theme_color_override("font_color", MenuTile.SUBTITLE_COLOR)
			row.get_node("Value").add_theme_color_override("font_color", MenuTile.TITLE_COLOR)
		MenuTile.style_button(panel.get_node("Box/ViewTeamButton"), muted)
	MenuTile.style_button(_start_button, accent, true)
	_vs_label.add_theme_color_override("font_color", accent)


func _on_view_team_pressed(team: int) -> void:
	ManagerSession.open_match_team(team, scene_file_path)


func _on_start_pressed() -> void:
	get_tree().change_scene_to_file(MATCH_SCENE)
