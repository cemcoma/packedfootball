extends Control

## First scene the app opens to. Ports packedfootball/firebase_client.py's
## auth flow (via the FirebaseAuth autoload) using real Control nodes --
## text input specifically benefits from Godot's native LineEdit, the same
## reason the pygame client needed native_form.py's whole HTML-overlay
## workaround to get reliable text entry on mobile Safari; here it's just
## there already, so no equivalent hack is needed.
##
## Two panels sharing one StatusLabel, toggled by _show_sign_in()/
## _show_register(): SignInPanel (email/password, matches an existing
## account) and RegisterPanel (a genuinely separate form -- display name in
## addition to email/password, since a brand new manager needs a name
## before anyone's squad/leaderboard entry means anything).
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
@onready var _guest_button: Button = %GuestButton

@onready var _register_panel: VBoxContainer = %RegisterPanel
@onready var _register_panel_actual: PanelContainer = %RegisterPanelActual
@onready var _display_name_field: LineEdit = %DisplayNameField
@onready var _register_email_field: LineEdit = %RegisterEmailField
@onready var _register_password_field: LineEdit = %RegisterPasswordField
@onready var _create_account_button: Button = %CreateAccountButton
@onready var _back_to_sign_in_button: Button = %BackToSignInButton

@onready var _status_label: Label = %StatusLabel


func _ready() -> void:
	_sign_in_button.pressed.connect(_on_sign_in_pressed)
	_show_register_button.pressed.connect(_on_show_register_pressed)
	_guest_button.pressed.connect(_on_guest_pressed)
	_create_account_button.pressed.connect(_on_create_account_pressed)
	_back_to_sign_in_button.pressed.connect(_on_back_to_sign_in_pressed)

	_status_label.text = "Checking for a saved session..."
	_set_busy(true)
	var resumed: bool = await FirebaseAuth.try_resume_session()
	if resumed:
		_go_to_menu()
		return
	_status_label.text = ""
	_set_busy(false)


func _set_busy(busy: bool) -> void:
	var enabled := not busy
	_email_field.editable = enabled
	_password_field.editable = enabled
	_sign_in_button.disabled = not enabled
	_show_register_button.disabled = not enabled
	_guest_button.disabled = not enabled
	_display_name_field.editable = enabled
	_register_email_field.editable = enabled
	_register_password_field.editable = enabled
	_create_account_button.disabled = not enabled
	_back_to_sign_in_button.disabled = not enabled


func _show_sign_in() -> void:
	_status_label.text = ""
	_register_panel.visible = false
	_register_panel_actual.visible = false
	_sign_in_panel.visible = true
	_sign_in_panel_actual.visible = true
	


func _show_register() -> void:
	_status_label.text = ""
	_sign_in_panel.visible = false
	_sign_in_panel_actual.visible = false
	_register_panel.visible = true
	_register_panel_actual.visible = true


## Loads the signed-in user's squad/inventory/profile once, right here at
## login, and caches it in the GameProfile autoload -- every scene that
## needs it afterward (Team, etc.) just reads it instantly instead of
## re-fetching from Firestore on every visit. `chosen_display_name`, when
## non-empty, is applied right after (see class docstring for why not
## before).
func _go_to_menu(chosen_display_name: String = "") -> void:
	_status_label.text = "Loading your squad..."
	await GameProfile.load_all()
	IapClient.initialize_for_signed_in_user(FirebaseAuth.uid)
	if chosen_display_name != "":
		await GameProfile.set_display_name(chosen_display_name)
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")


func _on_sign_in_pressed() -> void:
	_set_busy(true)
	_status_label.text = "Signing in..."
	var res: Dictionary = await FirebaseAuth.sign_in_with_email(_email_field.text, _password_field.text)
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
		_status_label.text = "Please enter a manager name."
		return

	_set_busy(true)
	_status_label.text = "Creating account..."
	var res: Dictionary = await FirebaseAuth.register_with_email(_register_email_field.text, _register_password_field.text)
	if res.ok:
		_go_to_menu(display_name)
		return
	_status_label.text = res.error
	_set_busy(false)


func _on_guest_pressed() -> void:
	_set_busy(true)
	_status_label.text = "Signing in..."
	var res: Dictionary = await FirebaseAuth.sign_in_anonymously()
	if res.ok:
		_go_to_menu()
		return
	_status_label.text = res.error
	_set_busy(false)
