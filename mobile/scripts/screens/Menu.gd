extends Control

## Main navigation hub. Every button here now opens a real feature scene --
## Leaderboard (last to get one) was the final holdout; Tournament is still
## a stub, but one level deeper, behind Play.
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
@onready var _leaderboard_button: Button = %LeaderboardButton
@onready var _settings_button: Button = %SettingsButton

@onready var _account_name_label: Label = %AccountNameLabel
@onready var _account_overall_label: Label = %AccountOverallLabel
@onready var _account_wins_label: Label = %AccountWinsLabel
@onready var _account_draws_label: Label = %AccountDrawsLabel
@onready var _account_losses_label: Label = %AccountLossesLabel
@onready var _account_credits_chip: CurrencyChip = %AccountCreditsChip
@onready var _account_bucks_chip: CurrencyChip = %AccountBucksChip
@onready var _account_medals_chip: CurrencyChip = %AccountMedalsChip


func _ready() -> void:
	_play_button.pressed.connect(_on_play_pressed)
	_shop_button.pressed.connect(_on_shop_pressed)
	_team_button.pressed.connect(_on_team_pressed)
	_leaderboard_button.pressed.connect(_on_leaderboard_pressed)
	_settings_button.pressed.connect(_on_settings_pressed)

	_account_credits_chip.set_currency("credits")
	_account_bucks_chip.set_currency("bucks")
	_account_medals_chip.set_currency("medals")

	_refresh_account_panel()


func _refresh_account_panel() -> void:
	_account_name_label.text = GameProfile.display_name
	_account_overall_label.text = "Squad Overall: %d" % GameProfile.average_overall()
	_account_wins_label.text = "Wins: %d" % GameProfile.wins
	_account_draws_label.text = "Draws: %d" % GameProfile.draws
	_account_losses_label.text = "Losses: %d" % GameProfile.losses
	_account_credits_chip.set_amount(GameProfile.credits)
	_account_bucks_chip.set_amount(GameProfile.bucks)
	_account_medals_chip.set_amount(GameProfile.medals)


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
