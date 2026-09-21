extends Control

## Main navigation hub. Every button here now opens a real feature scene --
## Leaderboard (last to get one) was the final holdout; Tournament is still
## a stub, but one level deeper, behind Play.
##
## AccountPanel (left side) shows the signed-in manager's own account
## record at a glance -- display name, squad overall, wins/draws/losses. The
## balances that used to sit under it are CurrencyHud's strip now, top right
## of this and every other screen --
## the same fields the old Profile screen used to show as its whole reason
## to exist. That screen is Settings now (rename, plus language/color-theme
## stubs), so this is the only place those squad stats are glanceable from
## without a screen visit. Populated fresh in _ready() straight off the
## already-loaded GameProfile cache (see Auth.gd's _go_to_menu -- squad
## data is fetched once at sign-in), same as Settings.gd used to do for
## its own now-removed stats block.

@onready var _play_button: MenuTile = %PlayTile
@onready var _shop_button: MenuTile = %ShopTile
@onready var _team_button: MenuTile = %TeamTile
@onready var _leaderboard_button: MenuTile = %LeaderboardTile
@onready var _settings_button: MenuTile = %SettingsTile

@onready var _account_name_label: Label = %AccountNameLabel
@onready var _account_overall_label: Label = %AccountOverallLabel
@onready var _account_wins_label: Label = %AccountWinsLabel
@onready var _account_draws_label: Label = %AccountDrawsLabel
@onready var _account_losses_label: Label = %AccountLossesLabel
@onready var _account_panel: PanelContainer = %AccountPanel


func _ready() -> void:
	_play_button.pressed.connect(_on_play_pressed)
	_shop_button.pressed.connect(_on_shop_pressed)
	_team_button.pressed.connect(_on_team_pressed)
	_leaderboard_button.pressed.connect(_on_leaderboard_pressed)
	_settings_button.pressed.connect(_on_settings_pressed)

	ThemeManager.theme_changed.connect(_restyle_account_panel)
	_restyle_account_panel()
	_refresh_account_panel()


## The panel wears the tiles' frame, or it reads as a leftover from the old
## rounded look sitting next to them.
func _restyle_account_panel() -> void:
	_account_panel.add_theme_stylebox_override(
		"panel",
		MenuTile.pixel_frame(MenuTile.BASE_FILL, ThemeManager.color("surface_border"), 3, true)
	)


func _refresh_account_panel() -> void:
	_account_name_label.text = GameProfile.display_name
	_account_overall_label.text = tr("Squad Overall: %d") % GameProfile.average_overall()
	_account_wins_label.text = tr("Wins: %d") % GameProfile.wins
	_account_draws_label.text = tr("Draws: %d") % GameProfile.draws
	_account_losses_label.text = tr("Losses: %d") % GameProfile.losses


func _on_play_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Play.tscn")


func _on_shop_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Shop.tscn")


## Lands on the Team hub (Squad or Inventory), not straight on the squad
## editor the way it used to -- see TeamHub.gd.
func _on_team_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/TeamHub.tscn")


func _on_leaderboard_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Leaderboard.tscn")


func _on_settings_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Settings.tscn")
