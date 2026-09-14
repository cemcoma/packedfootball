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
## Color Theme is real now: it swaps ThemeManager between its dark and light
## palettes, which restyles every screen (and persists the choice). Language
## is still an explicit stub -- a disabled OptionButton with one placeholder
## entry, nothing behind it yet (see mobile/README.md).

## Dropdown index -> ThemeManager mode key. Keep in step with the
## add_item() order in _ready().
const THEME_MODES := ["dark", "light"]

@onready var _name_field: LineEdit = %NameField
@onready var _save_name_button: Button = %SaveNameButton
@onready var _language_option: OptionButton = %LanguageOption
@onready var _theme_option: OptionButton = %ThemeOption
@onready var _back_button: Button = %BackButton
@onready var _logout_button: Button = %LogoutButton

@onready var _language_hint: Label = %LanguageHint
@onready var _theme_hint: Label = %ThemeHint


func _ready() -> void:
	_save_name_button.pressed.connect(_on_save_name_pressed)
	_back_button.pressed.connect(_on_back_pressed)
	_logout_button.pressed.connect(_on_logout_pressed)

	_name_field.text = GameProfile.display_name

	_language_option.add_item("English")
	_language_option.disabled = true

	# Index order must match THEME_MODES below.
	_theme_option.add_item("Dark")
	_theme_option.add_item("Light")
	_theme_option.select(THEME_MODES.find(ThemeManager.mode))
	_theme_option.item_selected.connect(_on_theme_selected)

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()


## Both hints sit straight on the screen background with no panel behind
## them, so they carry their own color override and the Theme's Label color
## never reaches them -- which left them a pale, near-invisible grey in light
## mode. Doubly worth getting right here: this is the screen you flip the
## theme ON, so it recolors live. See ThemeManager's note on text_hint.
func _apply_theme_colors() -> void:
	var hint := ThemeManager.color("text_hint")
	_language_hint.add_theme_color_override("font_color", hint)
	_theme_hint.add_theme_color_override("font_color", hint)


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
