extends Control

## Account settings: rename, language, color theme, plus log out. Squad/account details (overall, wins/draws/losses) that used to
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
## Color Theme swaps ThemeManager between its dark and light palettes,
## which restyles every screen (and persists the choice). Language does the
## same through LocaleManager, then reloads this scene: auto-translated
## scene text follows the locale on its own, but the dropdown entries and
## anything a script filled via tr() were worded in the old language and
## need rebuilding -- and this is the one screen open at the moment of the
## switch.

## Dropdown index -> ThemeManager mode key. Keep in step with the
## add_item() order in _ready().
const THEME_MODES := ["dark", "light"]

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

	# Index order follows LocaleManager.codes().
	for code in LocaleManager.codes():
		_language_option.add_item(LocaleManager.LANGUAGES[code])
	_language_option.select(LocaleManager.codes().find(LocaleManager.language))
	_language_option.item_selected.connect(_on_language_selected)

	# Index order must match THEME_MODES below.
	_theme_option.add_item(tr("Dark"))
	_theme_option.add_item(tr("Light"))
	_theme_option.select(THEME_MODES.find(ThemeManager.mode))
	_theme_option.item_selected.connect(_on_theme_selected)


func _on_language_selected(index: int) -> void:
	var codes: Array = LocaleManager.codes()
	if index < 0 or index >= codes.size() or codes[index] == LocaleManager.language:
		return
	LocaleManager.set_language(codes[index])
	get_tree().reload_current_scene()


func _on_theme_selected(index: int) -> void:
	if index >= 0 and index < THEME_MODES.size():
		ThemeManager.set_mode(THEME_MODES[index])


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
