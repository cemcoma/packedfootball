extends Control

## First scene the app opens to. Ports packedfootball/firebase_client.py's
## auth flow (via the FirebaseAuth autoload) using real Control nodes --
## text input specifically benefits from Godot's native LineEdit, the same
## reason the pygame client needed native_form.py's whole HTML-overlay
## workaround to get reliable text entry on mobile Safari; here it's just
## there already, so no equivalent hack is needed.

@onready var email_field: LineEdit = $CenterContainer/VBoxContainer/EmailField
@onready var password_field: LineEdit = $CenterContainer/VBoxContainer/PasswordField
@onready var sign_in_button: Button = $CenterContainer/VBoxContainer/ButtonRow/SignInButton
@onready var register_button: Button = $CenterContainer/VBoxContainer/ButtonRow/RegisterButton
@onready var guest_button: Button = $CenterContainer/VBoxContainer/GuestButton
@onready var status_label: Label = $CenterContainer/VBoxContainer/StatusLabel


func _ready() -> void:
	sign_in_button.pressed.connect(_on_sign_in_pressed)
	register_button.pressed.connect(_on_register_pressed)
	guest_button.pressed.connect(_on_guest_pressed)

	status_label.text = "Checking for a saved session..."
	_set_form_enabled(false)
	var resumed: bool = await FirebaseAuth.try_resume_session()
	if resumed:
		_go_to_menu()
		return
	status_label.text = ""
	_set_form_enabled(true)


func _set_form_enabled(enabled: bool) -> void:
	email_field.editable = enabled
	password_field.editable = enabled
	sign_in_button.disabled = not enabled
	register_button.disabled = not enabled
	guest_button.disabled = not enabled


func _go_to_menu() -> void:
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")


func _on_sign_in_pressed() -> void:
	_set_form_enabled(false)
	status_label.text = "Signing in..."
	var res: Dictionary = await FirebaseAuth.sign_in_with_email(email_field.text, password_field.text)
	if res.ok:
		_go_to_menu()
		return
	status_label.text = res.error
	_set_form_enabled(true)


func _on_register_pressed() -> void:
	_set_form_enabled(false)
	status_label.text = "Creating account..."
	var res: Dictionary = await FirebaseAuth.register_with_email(email_field.text, password_field.text)
	if res.ok:
		_go_to_menu()
		return
	status_label.text = res.error
	_set_form_enabled(true)


func _on_guest_pressed() -> void:
	_set_form_enabled(false)
	status_label.text = "Signing in..."
	var res: Dictionary = await FirebaseAuth.sign_in_anonymously()
	if res.ok:
		_go_to_menu()
		return
	status_label.text = res.error
	_set_form_enabled(true)
