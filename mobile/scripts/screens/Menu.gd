extends Control

## Main navigation hub. Each button opens either a real feature scene or a
## placeholder stub scene until the real functionality behind it gets built.
##
## AccountPanel (left side) shows the signed-in manager's own account
## details at a glance -- display name, squad overall, wins/draws/losses --
## the same fields the old Profile screen used to show as its whole reason
## to exist. That screen is Settings now (rename, plus language/color-theme
## stubs), so this is the only place those squad stats are glanceable from
## without a screen visit. Populated fresh in _ready() straight off the
## already-loaded GameProfile cache (see Auth.gd's _go_to_menu -- squad
## data is fetched once at sign-in), same as Settings.gd used to do for
## its own now-removed stats block.

@onready var _play_button: Button = %PlayButton
@onready var _shop_button: Button = %ShopButton
@onready var _team_button: Button = %TeamButton
@onready var _pvp_button: Button = %PvpButton
@onready var _settings_button: Button = %SettingsButton

@onready var _account_name_label: Label = %AccountNameLabel
@onready var _account_overall_label: Label = %AccountOverallLabel
@onready var _account_wins_label: Label = %AccountWinsLabel
@onready var _account_draws_label: Label = %AccountDrawsLabel
@onready var _account_losses_label: Label = %AccountLossesLabel


func _ready() -> void:
	_play_button.pressed.connect(_on_play_pressed)
	_shop_button.pressed.connect(_on_shop_pressed)
	_team_button.pressed.connect(_on_team_pressed)
	_pvp_button.pressed.connect(_on_pvp_pressed)
	_settings_button.pressed.connect(_on_settings_pressed)

	_refresh_account_panel()


func _refresh_account_panel() -> void:
	_account_name_label.text = GameProfile.display_name
	_account_overall_label.text = "Squad Overall: %d" % GameProfile.average_overall()
	_account_wins_label.text = "Wins: %d" % GameProfile.wins
	_account_draws_label.text = "Draws: %d" % GameProfile.draws
	_account_losses_label.text = "Losses: %d" % GameProfile.losses


func _on_play_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Play.tscn")


func _on_shop_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Shop.tscn")


func _on_team_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Team.tscn")


func _on_pvp_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Pvp.tscn")


func _on_settings_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Settings.tscn")
