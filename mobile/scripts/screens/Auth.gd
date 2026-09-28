extends Control

## First scene for anyone without a saved session. Landing offers Play Now (an
## anonymous guest, secured later from Settings) or signing in to an existing
## account; Reset has Firebase mail a password-reset link.

@onready var _landing_panel: PanelContainer = %LandingPanelActual
@onready var _play_now_button: Button = %PlayNowButton
@onready var _have_account_button: Button = %HaveAccountButton

@onready var _sign_in_panel: PanelContainer = %PanelSignActual
@onready var _email_field: LineEdit = %EmailField
@onready var _password_field: LineEdit = %PasswordField
@onready var _show_password_button: Button = %ShowPasswordButton
@onready var _sign_in_button: Button = %SignInButton
@onready var _back_from_sign_in_button: Button = %BackFromSignInButton
@onready var _forgot_password_button: Button = %ForgotPasswordButton

@onready var _reset_panel: PanelContainer = %ResetPanelActual
@onready var _reset_email_field: LineEdit = %ResetEmailField
@onready var _send_reset_button: Button = %SendResetButton
@onready var _back_from_reset_button: Button = %BackFromResetButton

@onready var _status_label: Label = %StatusLabel
@onready var _working_spinner: Control = %WorkingSpinner
@onready var _title: Control = %titleTexture
@onready var _center: CenterContainer = $CenterContainer

## Set by Splash when it resumed a session but the squad wouldn't load;
## shown once on the status line, then cleared.
static var startup_notice: String = ""


func _ready() -> void:
	_play_now_button.pressed.connect(_on_play_now_pressed)
	_have_account_button.pressed.connect(_show_panel.bind(_sign_in_panel))
	_sign_in_button.pressed.connect(_on_sign_in_pressed)
	_back_from_sign_in_button.pressed.connect(_show_panel.bind(_landing_panel))
	_forgot_password_button.pressed.connect(_on_forgot_password_pressed)
	_send_reset_button.pressed.connect(_on_send_reset_pressed)
	_back_from_reset_button.pressed.connect(_show_panel.bind(_sign_in_panel))

	_setup_fields()
	KeyboardDock.attach(_center, [_title])
	ThemeManager.theme_changed.connect(_restyle_panels)
	_restyle_panels()

	# A saved session resumes silently, with only the spinner on screen. Splash
	# normally does this check first; it's repeated when it hasn't (editor runs).
	_show_form(false)
	if not FirebaseAuth.resume_attempted:
		_status_label.text = tr("Checking for a saved session...")
		_set_busy(true)
		var resumed: bool = await FirebaseAuth.try_resume_session()
		if resumed:
			_go_to_menu()
			return
	_status_label.text = ""
	_set_busy(false)
	_show_form(true)
	if startup_notice != "":
		_status_label.text = startup_notice
		startup_notice = ""


func _restyle_panels() -> void:
	var border := ThemeManager.color("surface_border")
	for panel in _panels():
		panel.add_theme_stylebox_override(
			"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, border, 3, true, Vector2(18, 16))
		)


## Keyboard layout per field, and Return walking down the form.
## virtual_keyboard_type is what stops iOS auto-capitalising an address.
func _setup_fields() -> void:
	for field in [_email_field, _reset_email_field]:
		field.virtual_keyboard_type = LineEdit.KEYBOARD_TYPE_EMAIL_ADDRESS
	_password_field.virtual_keyboard_type = LineEdit.KEYBOARD_TYPE_PASSWORD

	_email_field.text_submitted.connect(func(_t): _password_field.grab_focus())
	_password_field.text_submitted.connect(func(_t): _on_sign_in_pressed())
	_reset_email_field.text_submitted.connect(func(_t): _on_send_reset_pressed())
	_show_password_button.toggled.connect(_on_show_password_toggled)


func _on_show_password_toggled(shown: bool) -> void:
	_password_field.secret = not shown
	_show_password_button.text = tr("Hide") if shown else tr("Show")


func _panels() -> Array[PanelContainer]:
	return [_landing_panel, _sign_in_panel, _reset_panel]


## The landing/sign-in/reset form, as opposed to the spinner and status line
## that stand in for it while a session resumes or a squad loads.
func _show_form(shown: bool) -> void:
	if shown:
		_show_panel(_landing_panel)
	else:
		for panel in _panels():
			panel.visible = false


func _show_panel(shown_panel: PanelContainer) -> void:
	_status_label.text = ""
	for panel in _panels():
		panel.visible = panel == shown_panel


func _set_busy(busy: bool) -> void:
	_working_spinner.visible = busy
	for field in [_email_field, _password_field, _reset_email_field]:
		field.editable = not busy
	for button in [
		_play_now_button, _have_account_button, _sign_in_button, _back_from_sign_in_button,
		_forgot_password_button, _send_reset_button, _back_from_reset_button,
	]:
		button.disabled = busy


## Loads the signed-in user's squad into GameProfile once, here, so every
## later scene reads it from the cache.
func _go_to_menu() -> void:
	_show_form(false)
	_working_spinner.visible = true
	_status_label.text = tr("Loading your squad...")
	var loaded: bool = await GameProfile.load_all()
	if not loaded:
		# Back to the form with the reason, not a Menu with a blank squad.
		_working_spinner.visible = false
		_set_busy(false)
		_show_form(true)
		_status_label.text = tr("Could not load your squad. Check your connection and sign in again.")
		return
	IapClient.initialize_for_signed_in_user(FirebaseAuth.uid)
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")


func _on_play_now_pressed() -> void:
	_set_busy(true)
	_status_label.text = tr("Setting up your club...")
	var res: Dictionary = await FirebaseAuth.sign_in_as_guest()
	if res.ok:
		_go_to_menu()
		return
	_status_label.text = res.error
	_set_busy(false)


func _on_sign_in_pressed() -> void:
	# The keyboard goes first, so the status line below the form is visible.
	get_viewport().gui_release_focus()
	var email := _email_field.text.strip_edges()
	var problem := FirebaseAuth.credentials_problem(email, _password_field.text)
	if problem != "":
		_status_label.text = problem
		return

	_set_busy(true)
	_status_label.text = tr("Signing in...")
	var res: Dictionary = await FirebaseAuth.sign_in_with_email(email, _password_field.text)
	if res.ok:
		_go_to_menu()
		return
	_status_label.text = res.error
	_set_busy(false)


## Carries the sign-in email across, since that's almost always the one.
func _on_forgot_password_pressed() -> void:
	if _email_field.text.strip_edges() != "":
		_reset_email_field.text = _email_field.text.strip_edges()
	_show_panel(_reset_panel)


func _on_send_reset_pressed() -> void:
	get_viewport().gui_release_focus()
	var email := _reset_email_field.text.strip_edges()
	if email == "":
		_status_label.text = tr("Please enter your email.")
		return

	_set_busy(true)
	_status_label.text = tr("Sending reset email...")
	var res: Dictionary = await FirebaseAuth.send_password_reset(email)
	_set_busy(false)
	if res.ok:
		_status_label.text = tr("Reset email sent to %s -- check your inbox (and spam folder), then sign in with your new password.") % email
		return
	_status_label.text = res.error
