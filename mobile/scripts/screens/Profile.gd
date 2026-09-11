extends Control

## Manager profile: rename, and see squad overall/wins/losses/draws.
## Deliberately a 1:1 port of packedfootball/main.py's PROFILE scene --
## same fields shown (squad overall, wins, losses, draws; notably NOT elo
## or campaign_level, even though main.py loads those too -- the Python
## screen just never displays them, so neither does this one), same rename
## behavior (only writes if the trimmed name is non-empty and actually
## changed, then republishes the public lobby entry so PvP-visible stats
## stay in sync -- see main.py's _publish_lobby()).
##
## One deliberate difference: main.py branches on _IS_EMSCRIPTEN for the
## rename field (a real LineEdit on desktop, a native HTML form overlay in
## the browser build) purely because pygame/pygbag has no reliable native
## text entry on mobile Safari -- see native_form.py's docstring. Godot's
## LineEdit works natively on every export target, so there's only one path
## here, the same reason Auth.gd never needed that branch either.

@onready var _name_field: LineEdit = %NameField
@onready var _save_name_button: Button = %SaveNameButton
@onready var _overall_label: Label = %OverallLabel
@onready var _wins_label: Label = %WinsLabel
@onready var _losses_label: Label = %LossesLabel
@onready var _draws_label: Label = %DrawsLabel
@onready var _back_button: Button = %BackButton
@onready var _logout_button: Button = %LogoutButton


func _ready() -> void:
	_save_name_button.pressed.connect(_on_save_name_pressed)
	_back_button.pressed.connect(_on_back_pressed)
	_logout_button.pressed.connect(_on_logout_pressed)
	_refresh()


func _refresh() -> void:
	_name_field.text = GameProfile.display_name
	_overall_label.text = "Squad Overall: %d" % GameProfile.average_overall()
	_wins_label.text = "Wins: %d" % GameProfile.wins
	_draws_label.text = "Draws: %d" % GameProfile.draws
	_losses_label.text = "Losses: %d" % GameProfile.losses


func _on_save_name_pressed() -> void:
	var new_name := _name_field.text.strip_edges()
	if new_name == "" or new_name == GameProfile.display_name:
		return
	await GameProfile.set_display_name(new_name)
	await GameProfile.publish_lobby_entry()


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")


func _on_logout_pressed() -> void:
	# The only way back to the login screen: boot always tries a silent
	# resume first, so without this a device with a saved session can never
	# reach Auth again to register or switch accounts (see main.py's own
	# Log Out button for the same reasoning).
	FirebaseAuth.sign_out()
	GameProfile.reset()
	get_tree().change_scene_to_file("res://scenes/Auth.tscn")
