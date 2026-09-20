extends Control

## Account settings: rename, language, color theme, the privacy policy and
## support links, log out, and deleting
## the account. Squad/account details (overall, wins/draws/losses) that used to
## live on this screen (back when it was "Profile") moved to Menu's own
## AccountPanel instead -- glanceable from the hub every visit rather than
## needing a whole screen just to see them, leaving this screen for actual
## settings.
##
## Renaming goes through the backend (names are unique -- see
## backend/services/account.py), so the request can come back refused:
## taken, too short, bad characters. The status line under the field is
## where that lands.
##
## Delete Account is what App Store guideline 5.1.1(v) requires of any app
## with sign-up: the user has to be able to remove the account from inside
## the app. It is deliberately hard to hit by accident -- a flat button
## well below the others, a confirmation panel that spells out what goes,
## and the word DELETE typed before the button enables. The deletion
## itself is one backend call; only once it has succeeded is the session
## dropped, so a failed attempt leaves a signed-in account to retry from.
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

## What has to be typed into the confirmation field, compared
## case-insensitively. Not translated: it's a deliberate speed bump, and a
## fixed word is the same speed bump in every language.
const DELETE_CONFIRM_WORD := "DELETE"

## The store-facing pages, published next to the web build by `make
## deploy-web` from site/ at the repo root. App Store guideline 5.1.1 wants
## the privacy policy reachable from inside the app, not only from the
## listing, which is why they are here and not just in App Store Connect.
## Same URLs as the listing's Privacy Policy / Support fields -- change
## both together.
const PRIVACY_URL := "https://cemcoma.github.io/packedfootball/privacy/"
const SUPPORT_URL := "https://cemcoma.github.io/packedfootball/support/"

@onready var _name_field: LineEdit = %NameField
@onready var _save_name_button: Button = %SaveNameButton
@onready var _status_label: Label = %StatusLabel
@onready var _language_option: OptionButton = %LanguageOption
@onready var _theme_option: OptionButton = %ThemeOption
@onready var _privacy_button: Button = %PrivacyButton
@onready var _support_button: Button = %SupportButton
@onready var _ad_privacy_button: Button = %AdPrivacyButton
@onready var _back_button: Button = %BackButton
@onready var _logout_button: Button = %LogoutButton
@onready var _delete_account_button: Button = %DeleteAccountButton
@onready var _delete_overlay: Control = %DeleteConfirmOverlay
@onready var _delete_footnote: Label = %DeleteConfirmFootnote
@onready var _delete_field: LineEdit = %DeleteConfirmField
@onready var _delete_cancel_button: Button = %DeleteCancelButton
@onready var _delete_confirm_button: Button = %DeleteConfirmButton

var _busy: bool = false


func _ready() -> void:
	_save_name_button.pressed.connect(_on_save_name_pressed)
	_privacy_button.pressed.connect(func() -> void: OS.shell_open(PRIVACY_URL))
	_support_button.pressed.connect(func() -> void: OS.shell_open(SUPPORT_URL))
	# Google UMP: EEA users must be able to revisit their ad consent.
	_ad_privacy_button.visible = AdManager.privacy_options_required()
	_ad_privacy_button.pressed.connect(AdManager.show_privacy_options)
	_back_button.pressed.connect(_on_back_pressed)
	_logout_button.pressed.connect(_on_logout_pressed)
	_delete_account_button.pressed.connect(_on_delete_account_pressed)
	_delete_cancel_button.pressed.connect(_on_delete_cancel_pressed)
	_delete_confirm_button.pressed.connect(_on_delete_confirm_pressed)
	_delete_field.text_changed.connect(_on_delete_field_changed)

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()

	_name_field.text = GameProfile.display_name
	_delete_overlay.visible = false

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


## The delete button is the one thing on this screen that should NOT look
## like the others -- red, quiet, and clearly a different kind of action.
func _apply_theme_colors() -> void:
	_delete_account_button.add_theme_color_override("font_color", ThemeManager.color("warning"))
	_delete_footnote.add_theme_color_override("font_color", ThemeManager.color("text_hint"))


func _set_status(text: String, positive: bool = false) -> void:
	_status_label.text = text
	_status_label.add_theme_color_override(
		"font_color",
		ThemeManager.color("positive") if positive else ThemeManager.color("warning")
	)


func _on_save_name_pressed() -> void:
	var new_name := _name_field.text.strip_edges()
	if new_name == "" or new_name == GameProfile.display_name or _busy:
		return
	_busy = true
	_save_name_button.disabled = true
	_set_status(tr("Saving..."))
	var res: Dictionary = await GameProfile.set_display_name(new_name)
	_busy = false
	_save_name_button.disabled = false
	if res.ok:
		_name_field.text = GameProfile.display_name  # as stored: spacing collapsed
		_set_status(tr("Saved."), true)
		return
	match int(res.status):
		409:
			_set_status(GameProfile.display_name_problem("taken"))
		400:
			# FastAPI's detail is "Display name refused: <reason>" -- the
			# reason code after the colon is what maps to wording.
			var detail := str(res.data.get("detail", ""))
			var reason := detail.get_slice(": ", 1) if detail.contains(": ") else "characters"
			var problem := GameProfile.display_name_problem(reason)
			_set_status(problem if problem != "" else GameProfile.display_name_problem("characters"))
		_:
			_set_status(tr("Could not save the name -- try again."))


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


# -- delete account -------------------------------------------------------------


func _on_delete_account_pressed() -> void:
	_delete_field.text = ""
	_delete_confirm_button.disabled = true
	_delete_overlay.visible = true
	_delete_field.grab_focus()


func _on_delete_cancel_pressed() -> void:
	if _busy:
		return
	_delete_overlay.visible = false


func _on_delete_field_changed(text: String) -> void:
	_delete_confirm_button.disabled = _busy or text.strip_edges().to_upper() != DELETE_CONFIRM_WORD


func _on_delete_confirm_pressed() -> void:
	if _busy or _delete_field.text.strip_edges().to_upper() != DELETE_CONFIRM_WORD:
		return
	_busy = true
	_delete_confirm_button.disabled = true
	_delete_cancel_button.disabled = true
	_delete_confirm_button.text = tr("Deleting...")

	var ok: bool = await GameProfile.delete_account()

	if not ok:
		# The account is still there (the server only removes the Auth user
		# as its very last step), so the session is still good to retry.
		_busy = false
		_delete_cancel_button.disabled = false
		_delete_confirm_button.text = tr("Delete Forever")
		_delete_confirm_button.disabled = false
		_set_status(tr("Could not delete the account -- try again."))
		return

	# Gone server-side; drop the session the same way Log Out does. The
	# saved refresh token would otherwise let the next launch try to
	# resume an account that no longer exists.
	FirebaseAuth.sign_out()
	GameProfile.reset()
	get_tree().change_scene_to_file("res://scenes/Auth.tscn")
