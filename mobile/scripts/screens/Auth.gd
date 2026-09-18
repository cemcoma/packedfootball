extends Control

## First scene the app opens to. Ports packedfootball/firebase_client.py's
## auth flow (via the FirebaseAuth autoload) using real Control nodes --
## text input specifically benefits from Godot's native LineEdit, the same
## reason the pygame client needed native_form.py's whole HTML-overlay
## workaround to get reliable text entry on mobile Safari; here it's just
## there already, so no equivalent hack is needed.
##
## Three panels sharing one StatusLabel, toggled by _show_sign_in()/
## _show_register()/_show_reset(): SignInPanel (email/password, matches an
## existing account), RegisterPanel (a genuinely separate form -- display
## name in addition to email/password, since a brand new manager needs a
## name before anyone's squad/leaderboard entry means anything) and
## ResetPanel (email only -- FirebaseAuth.send_password_reset has Firebase
## mail a reset link; the new password is set on that link's page, never
## here).
##
## The obvious mistakes -- an empty field, a password under Firebase's
## minimum -- are caught here before any request goes out (see
## _validate_credentials); everything else comes back from Firebase as a
## code that FirebaseAuth already turns into a readable message.
##
## Registration order matters: FirebaseAuth.register_with_email() only
## creates the Firebase Auth account, then _go_to_menu() -> GameProfile.
## load_all() calls the backend's /account/bootstrap, which is what
## actually creates the users/{uid} Firestore doc (with a full starter
## roster) -- but ONLY if that doc doesn't already exist yet (see
## backend/main.py's bootstrap_account docstring). Writing the chosen
## display name straight after register_with_email(), before bootstrap,
## would make bootstrap see an existing (partial) doc and skip starter-
## roster creation entirely. So the display name is applied via
## GameProfile.set_display_name() AFTER load_all() has run bootstrap and
## populated the cache -- see _go_to_menu()'s chosen_display_name param.

@onready var _sign_in_panel: VBoxContainer = %SignInPanel
@onready var _sign_in_panel_actual: PanelContainer = %PanelSignActual
@onready var _email_field: LineEdit = %EmailField
@onready var _password_field: LineEdit = %PasswordField
@onready var _sign_in_button: Button = %SignInButton
@onready var _show_register_button: Button = %ShowRegisterButton
@onready var _forgot_password_button: Button = %ForgotPasswordButton

@onready var _register_panel: VBoxContainer = %RegisterPanel
@onready var _register_panel_actual: PanelContainer = %RegisterPanelActual
@onready var _display_name_field: LineEdit = %DisplayNameField
@onready var _register_email_field: LineEdit = %RegisterEmailField
@onready var _register_password_field: LineEdit = %RegisterPasswordField
@onready var _create_account_button: Button = %CreateAccountButton
@onready var _back_to_sign_in_button: Button = %BackToSignInButton

@onready var _reset_panel: VBoxContainer = %ResetPanel
@onready var _reset_panel_actual: PanelContainer = %ResetPanelActual
@onready var _reset_email_field: LineEdit = %ResetEmailField
@onready var _send_reset_button: Button = %SendResetButton
@onready var _back_from_reset_button: Button = %BackFromResetButton

@onready var _status_label: Label = %StatusLabel
@onready var _working_spinner: Control = %WorkingSpinner
@onready var _center: CenterContainer = $CenterContainer

# -- keyboard avoidance ----------------------------------------------------------
#
# On a phone the on-screen keyboard covers the lower half of a landscape
# screen, and this form sits in the middle of it: focus the password field
# and the keyboard lands right on top of it. Godot doesn't move anything
# for you, so _process watches the keyboard's height and slides the whole
# centred column up just far enough that the focused field clears it,
# then back down when the keyboard goes. The title scrolls off the top in
# the process, which is the right thing to lose.

## Gap kept between the focused field's bottom edge and the keyboard.
const KEYBOARD_CLEARANCE := 16.0
var _keyboard_shift: float = 0.0


func _ready() -> void:
	_sign_in_button.pressed.connect(_on_sign_in_pressed)
	_show_register_button.pressed.connect(_on_show_register_pressed)
	_forgot_password_button.pressed.connect(_on_forgot_password_pressed)
	_create_account_button.pressed.connect(_on_create_account_pressed)
	_back_to_sign_in_button.pressed.connect(_on_back_to_sign_in_pressed)
	_send_reset_button.pressed.connect(_on_send_reset_pressed)
	_back_from_reset_button.pressed.connect(_on_back_to_sign_in_pressed)

	# A saved session resumes silently: no form on screen while it's being
	# checked, just the spinner -- testers kept typing their credentials
	# into a form that was about to disappear on its own. The form only
	# appears once we know there's nothing to resume.
	_show_form(false)
	_status_label.text = tr("Checking for a saved session...")
	_set_busy(true)
	var resumed: bool = await FirebaseAuth.try_resume_session()
	if resumed:
		_go_to_menu()
		return
	_status_label.text = ""
	_set_busy(false)
	_show_form(true)


func _process(_delta: float) -> void:
	_avoid_keyboard()


## Slides the centred column so the focused field sits above the keyboard.
## Keyboard height comes back in screen pixels; the canvas is scaled
## (canvas_items stretch), so it's converted through the ratio of the
## visible canvas to the window before comparing against control rects.
func _avoid_keyboard() -> void:
	var keyboard_px := DisplayServer.virtual_keyboard_get_height()
	var wanted := 0.0
	if keyboard_px > 0:
		var focused := get_viewport().gui_get_focus_owner()
		if focused is LineEdit and is_ancestor_of(focused):
			var canvas_height := get_viewport().get_visible_rect().size.y
			var window_height := float(DisplayServer.window_get_size().y)
			var keyboard := keyboard_px * canvas_height / maxf(window_height, 1.0)
			# The field's bottom as it would be with no shift applied.
			var field_bottom: float = focused.get_global_rect().end.y + _keyboard_shift
			wanted = maxf(0.0, field_bottom + KEYBOARD_CLEARANCE - (canvas_height - keyboard))
	if not is_equal_approx(wanted, _keyboard_shift):
		_keyboard_shift = wanted
		_center.position.y = -_keyboard_shift


## The whole sign-in/register/reset form, as opposed to the spinner and
## status line that stand in for it while a saved session is being
## resumed or a signed-in manager's squad is loading.
func _show_form(shown: bool) -> void:
	if shown:
		_show_sign_in()
	else:
		for pair in [
			[_sign_in_panel_actual, _sign_in_panel],
			[_register_panel_actual, _register_panel],
			[_reset_panel_actual, _reset_panel],
		]:
			pair[0].visible = false
			pair[1].visible = false


func _set_busy(busy: bool) -> void:
	_working_spinner.visible = busy
	var enabled := not busy
	_email_field.editable = enabled
	_password_field.editable = enabled
	_sign_in_button.disabled = not enabled
	_show_register_button.disabled = not enabled
	_forgot_password_button.disabled = not enabled
	_display_name_field.editable = enabled
	_register_email_field.editable = enabled
	_register_password_field.editable = enabled
	_create_account_button.disabled = not enabled
	_back_to_sign_in_button.disabled = not enabled
	_reset_email_field.editable = enabled
	_send_reset_button.disabled = not enabled
	_back_from_reset_button.disabled = not enabled


func _show_sign_in() -> void:
	_show_panel(_sign_in_panel_actual, _sign_in_panel)


func _show_register() -> void:
	_show_panel(_register_panel_actual, _register_panel)


func _show_reset() -> void:
	_show_panel(_reset_panel_actual, _reset_panel)


## Exactly one panel visible at a time. Both the PanelContainer and the
## VBox inside it are toggled, since both start hidden in Auth.tscn.
func _show_panel(panel_actual: PanelContainer, panel: VBoxContainer) -> void:
	_status_label.text = ""
	for pair in [
		[_sign_in_panel_actual, _sign_in_panel],
		[_register_panel_actual, _register_panel],
		[_reset_panel_actual, _reset_panel],
	]:
		var shown: bool = pair[0] == panel_actual
		pair[0].visible = shown
		pair[1].visible = shown


## The checks that don't need Firebase to answer: an empty field, or a
## password under the minimum signUp would reject anyway. Returns the
## message to show, or "" when the pair is worth sending.
func _validate_credentials(email: String, password: String) -> String:
	if email.strip_edges() == "":
		return tr("Please enter your email.")
	if password == "":
		return tr("Please enter your password.")
	if password.length() < FirebaseAuth.MIN_PASSWORD_LENGTH:
		return tr("Password must be at least %d characters.") % FirebaseAuth.MIN_PASSWORD_LENGTH
	return ""


## Loads the signed-in user's squad/inventory/profile once, right here at
## login, and caches it in the GameProfile autoload -- every scene that
## needs it afterward (Team, etc.) just reads it instantly instead of
## re-fetching from Firestore on every visit. `chosen_display_name`, when
## non-empty, is applied right after (see class docstring for why not
## before).
func _go_to_menu(chosen_display_name: String = "") -> void:
	# Signed in: the form has done its job, so it goes and the spinner
	# carries the wait -- a visible email field under "Loading your
	# squad..." reads as "still needs filling in".
	_show_form(false)
	_working_spinner.visible = true
	_status_label.text = tr("Loading your squad...")
	await GameProfile.load_all()
	IapClient.initialize_for_signed_in_user(FirebaseAuth.uid)
	if chosen_display_name != "":
		await GameProfile.set_display_name(chosen_display_name)
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")


func _on_sign_in_pressed() -> void:
	var email := _email_field.text.strip_edges()
	var problem := _validate_credentials(email, _password_field.text)
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


func _on_show_register_pressed() -> void:
	_show_register()


func _on_back_to_sign_in_pressed() -> void:
	_show_sign_in()


func _on_create_account_pressed() -> void:
	var display_name := _display_name_field.text.strip_edges()
	if display_name == "":
		_status_label.text = tr("Please enter a manager name.")
		return
	var email := _register_email_field.text.strip_edges()
	var problem := _validate_credentials(email, _register_password_field.text)
	if problem != "":
		_status_label.text = problem
		return

	_set_busy(true)
	
	_status_label.text = tr("Checking name...")
	var check: Dictionary = await GameProfile.check_display_name(display_name)
	if not check.available:
		_status_label.text = GameProfile.display_name_problem(check.reason)
		_set_busy(false)
		return

	_status_label.text = tr("Creating account...")
	var res: Dictionary = await FirebaseAuth.register_with_email(email, _register_password_field.text)
	if res.ok:
		_go_to_menu(display_name)
		return
	_status_label.text = res.error
	_set_busy(false)


## Carries whatever was typed into the sign-in email across, since that's
## almost always the address the reset is for.
func _on_forgot_password_pressed() -> void:
	if _email_field.text.strip_edges() != "":
		_reset_email_field.text = _email_field.text.strip_edges()
	_show_reset()


func _on_send_reset_pressed() -> void:
	var email := _reset_email_field.text.strip_edges()
	if email == "":
		_status_label.text = tr("Please enter your email.")
		return

	_set_busy(true)
	_status_label.text = tr("Sending reset email...")
	var res: Dictionary = await FirebaseAuth.send_password_reset(email)
	_set_busy(false)
	if res.ok:
		# Stays on this panel so the message is read; Back returns to sign-in
		# once the new password is set from the link.
		_status_label.text = tr("Reset email sent to %s -- check your inbox (and spam folder), then sign in with your new password.") % email
		return
	_status_label.text = res.error
