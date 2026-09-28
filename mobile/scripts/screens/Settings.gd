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
## A guest (anonymous account) gets Secure Account, which links an email and
## password to the same uid; until then Log Out needs a second tap.
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
## Color Theme swaps ThemeManager between its dark and light palettes, and
## Font swaps the face every screen renders in; both restyle the whole app
## on the spot and persist the choice. Language does the same through
## LocaleManager, then reloads this scene: auto-translated
## scene text follows the locale on its own, but the dropdown entries and
## anything a script filled via tr() were worded in the old language and
## need rebuilding -- and this is the one screen open at the moment of the
## switch.

## Dropdown index -> ThemeManager mode key. Keep in step with the
## add_item() order in _ready().
const THEME_MODES := ["dark", "light"]

## Dropdown index -> ThemeManager.FONTS key, same rule. "Pixel" is what the
## art is drawn for and stays the default; "Rounded" is there because it is
## easier to read at small sizes, which matters more to some players than
## the look does.
const FONT_KEYS := ["pixel", "rounded"]

## What has to be typed into the confirmation field, compared
## case-insensitively. Not translated: it's a deliberate speed bump, and a
## fixed word is the same speed bump in every language.
const DELETE_CONFIRM_WORD := "DELETE"

## How long a guest's first Log Out tap stays armed.
const LOGOUT_ARM_SEC := 5.0

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
@onready var _font_option: OptionButton = %FontOption
@onready var _large_text_button: CheckButton = %ScaleOption
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
@onready var _settings_panel: PanelContainer = %SettingsPanel
@onready var _delete_panel: PanelContainer = %Panel
@onready var _guest_hint_label: Label = %GuestHintLabel
@onready var _secure_account_button: Button = %SecureAccountButton
@onready var _secure_overlay: Control = %SecureOverlay
@onready var _secure_panel: PanelContainer = %SecurePanel
@onready var _secure_hint_label: Label = %SecureHintLabel
@onready var _link_email_field: LineEdit = %LinkEmailField
@onready var _link_password_field: LineEdit = %LinkPasswordField
@onready var _link_confirm_field: LineEdit = %LinkConfirmField
@onready var _show_link_password_button: Button = %ShowLinkPasswordButton
@onready var _secure_status_label: Label = %SecureStatusLabel
@onready var _secure_cancel_button: Button = %SecureCancelButton
@onready var _secure_confirm_button: Button = %SecureConfirmButton
@onready var _section_headers: Array[Label] = [
	%AccountHeader, %DisplayHeader, %LinksHeader, %SessionHeader,
]

## Deep enough to read as a danger against the light theme's white buttons.
const DANGER_ON_LIGHT := Color(0.70, 0.13, 0.10)

var _busy: bool = false
var _logout_armed: bool = false


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
	_setup_secure_form()
	KeyboardDock.attach($DeleteConfirmOverlay/Center)
	KeyboardDock.attach($SecureOverlay/Center)

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()

	_name_field.text = GameProfile.display_name
	_delete_overlay.visible = false
	_secure_overlay.visible = false
	_refresh_guest_ui()

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

	# Index order must match FONT_KEYS.
	_font_option.add_item(tr("Pixel"))
	_font_option.add_item(tr("Rounded"))
	_font_option.select(FONT_KEYS.find(ThemeManager.font_key))
	_font_option.item_selected.connect(_on_font_selected)
	
	# Initialize the toggle state
	_large_text_button.button_pressed = ThemeManager.large_text
	_large_text_button.toggled.connect(ThemeManager.set_large_text)


func _on_language_selected(index: int) -> void:
	var codes: Array = LocaleManager.codes()
	if index < 0 or index >= codes.size() or codes[index] == LocaleManager.language:
		return
	LocaleManager.set_language(codes[index])
	get_tree().reload_current_scene()


func _on_theme_selected(index: int) -> void:
	if index >= 0 and index < THEME_MODES.size():
		ThemeManager.set_mode(THEME_MODES[index])


func _on_font_selected(index: int) -> void:
	if index >= 0 and index < FONT_KEYS.size():
		ThemeManager.set_font(FONT_KEYS[index])

## The delete button is the one thing on this screen that should NOT look
## like the others -- red, quiet, and clearly a different kind of action.
func _apply_theme_colors() -> void:
	# The light theme's buttons are white, and "warning" is a pale amber picked
	# for dark ones -- on white it stops reading as a danger at all.
	var danger := (
		DANGER_ON_LIGHT if ThemeManager.is_light() else ThemeManager.color("warning")
	)
	_delete_account_button.add_theme_color_override("font_color", danger)
	_delete_footnote.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	_guest_hint_label.add_theme_color_override("font_color", ThemeManager.color("warning"))
	_secure_hint_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	_secure_panel.add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, ThemeManager.color("accent"), 3, true)
	)

	# The form sits on the tiles' frame instead of straight on the background
	# photo, where every control had to fight the crowd behind it.
	_settings_panel.add_theme_stylebox_override(
		"panel",
		MenuTile.pixel_frame(MenuTile.BASE_FILL, ThemeManager.color("surface_border"), 3, true)
	)
	# Opaque, unlike the theme's default panel: the form was showing through
	# the one dialog that must not be misread.
	_delete_panel.add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, ThemeManager.color("warning"), 3, true)
	)
	MenuTile.style_button(_back_button, ThemeManager.color("surface_border"))
	var heading := ThemeManager.color("heading")
	for header in _section_headers:
		header.add_theme_color_override("font_color", heading)


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
	if _busy:
		return
	# A guest has no email to sign back in with, so the first tap only warns.
	if FirebaseAuth.is_guest and not _logout_armed:
		_logout_armed = true
		_logout_button.text = tr("Log Out Anyway")
		_set_status(tr("Guest account: logging out deletes this club and its purchases for good. Secure it first to keep it."))
		get_tree().create_timer(LOGOUT_ARM_SEC).timeout.connect(_disarm_logout)
		return
	# Nobody can reach a guest's club once it's signed out, so it's deleted
	# rather than left on leaderboards and holding its name.
	if FirebaseAuth.is_guest:
		_busy = true
		_logout_button.disabled = true
		_set_status(tr("Deleting..."))
		var ok: bool = await GameProfile.delete_account()
		_busy = false
		_logout_button.disabled = false
		if not ok:
			_disarm_logout()
			_set_status(tr("Could not delete the account -- try again."))
			return
	_leave_to_auth()


## Drops the session and returns to Auth. Boot always tries a silent resume
## first, so this is the only way back there to switch accounts.
func _leave_to_auth() -> void:
	FirebaseAuth.sign_out()
	GameProfile.reset()
	get_tree().change_scene_to_file("res://scenes/Auth.tscn")


func _disarm_logout() -> void:
	_logout_armed = false
	_logout_button.text = tr("Log Out / Switch Account")


func _refresh_guest_ui() -> void:
	_guest_hint_label.visible = FirebaseAuth.is_guest
	_secure_account_button.visible = FirebaseAuth.is_guest


# -- secure account -------------------------------------------------------------


func _setup_secure_form() -> void:
	_secure_account_button.pressed.connect(_on_secure_account_pressed)
	_secure_cancel_button.pressed.connect(_on_secure_cancel_pressed)
	_secure_confirm_button.pressed.connect(_on_secure_confirm_pressed)
	_show_link_password_button.toggled.connect(_on_show_link_password_toggled)
	_link_email_field.virtual_keyboard_type = LineEdit.KEYBOARD_TYPE_EMAIL_ADDRESS
	_link_password_field.virtual_keyboard_type = LineEdit.KEYBOARD_TYPE_PASSWORD
	_link_confirm_field.virtual_keyboard_type = LineEdit.KEYBOARD_TYPE_PASSWORD
	_link_email_field.text_submitted.connect(func(_t): _link_password_field.grab_focus())
	_link_password_field.text_submitted.connect(func(_t): _link_confirm_field.grab_focus())
	_link_confirm_field.text_submitted.connect(func(_t): _on_secure_confirm_pressed())


func _on_secure_account_pressed() -> void:
	for field in [_link_email_field, _link_password_field, _link_confirm_field]:
		field.text = ""
	_secure_status_label.text = ""
	_secure_overlay.visible = true
	_link_email_field.grab_focus()


func _on_secure_cancel_pressed() -> void:
	if _busy:
		return
	get_viewport().gui_release_focus()
	_secure_overlay.visible = false


## One toggle for both fields: the same secret typed twice.
func _on_show_link_password_toggled(shown: bool) -> void:
	_link_password_field.secret = not shown
	_link_confirm_field.secret = not shown
	_show_link_password_button.text = tr("Hide") if shown else tr("Show")


func _on_secure_confirm_pressed() -> void:
	if _busy:
		return
	get_viewport().gui_release_focus()
	var email := _link_email_field.text.strip_edges()
	var problem := FirebaseAuth.credentials_problem(email, _link_password_field.text)
	if problem == "" and _link_confirm_field.text != _link_password_field.text:
		problem = tr("Passwords do not match.")
	if problem != "":
		_secure_status_label.text = problem
		return

	_set_secure_busy(true)
	_secure_status_label.text = tr("Securing your account...")
	var res: Dictionary = await FirebaseAuth.link_email(email, _link_password_field.text)
	_set_secure_busy(false)
	if not res.ok:
		_secure_status_label.text = res.error
		return
	_secure_overlay.visible = false
	_refresh_guest_ui()
	_set_status(tr("Account secured. Sign in with %s on any device.") % email, true)


func _set_secure_busy(busy: bool) -> void:
	_busy = busy
	for field in [_link_email_field, _link_password_field, _link_confirm_field]:
		field.editable = not busy
	_secure_cancel_button.disabled = busy
	_secure_confirm_button.disabled = busy


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

	# Gone server-side; the saved refresh token would otherwise let the next
	# launch try to resume an account that no longer exists.
	_leave_to_auth()
