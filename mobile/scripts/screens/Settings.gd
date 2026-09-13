extends Control

## Account settings: rename, and (stubs for now) language/color theme, plus
## log out. Squad/account details (overall, wins/draws/losses) that used to
## live on this screen (back when it was "Profile") moved to Menu's own
## AccountPanel instead -- glanceable from the hub every visit rather than
## needing a whole screen just to see them, leaving this screen for actual
## settings. Rename behavior is unchanged from that screen (only writes if
## the trimmed name is non-empty and actually changed).
##
## GameProfile.gd (unlike game_state.py's own profile shape) has no elo
## field at all -- by design decision, elo was removed from the active
## Godot+backend system entirely. There is also no `lobby` collection
## publish anywhere anymore -- leaderboards will read straight from
## `users`/`players` docs instead of a separate snapshot.
##
## Language/Color Theme are explicit stubs -- disabled OptionButtons with a
## single placeholder entry each, no functionality behind them yet (see
## mobile/README.md).

@onready var _name_field: LineEdit = %NameField
@onready var _save_name_button: Button = %SaveNameButton
@onready var _language_option: OptionButton = %LanguageOption
@onready var _theme_option: OptionButton = %ThemeOption
@onready var _back_button: Button = %BackButton
@onready var _logout_button: Button = %LogoutButton


func _ready() -> void:
	_save_name_button.pressed.connect(_on_save_name_pressed)
	_back_button.pressed.connect(_on_back_pressed)
	_logout_button.pressed.connect(_on_logout_pressed)

	_name_field.text = GameProfile.display_name

	_language_option.add_item("English")
	_language_option.disabled = true
	_theme_option.add_item("Default")
	_theme_option.disabled = true


func _on_save_name_pressed() -> void:
	var new_name := _name_field.text.strip_edges()
	if new_name == "" or new_name == GameProfile.display_name:
		return
	await GameProfile.set_display_name(new_name)


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
