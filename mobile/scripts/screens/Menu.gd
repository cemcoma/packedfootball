extends Control

## Main navigation hub. Each button opens either a real feature scene or a
## placeholder stub scene until the real functionality behind it gets built.

@onready var _play_button: Button = %PlayButton
@onready var _shop_button: Button = %ShopButton
@onready var _team_button: Button = %TeamButton
@onready var _pvp_button: Button = %PvpButton
@onready var _profile_button: Button = %ProfileButton


func _ready() -> void:
	_play_button.pressed.connect(_on_play_pressed)
	_shop_button.pressed.connect(_on_shop_pressed)
	_team_button.pressed.connect(_on_team_pressed)
	_pvp_button.pressed.connect(_on_pvp_pressed)
	_profile_button.pressed.connect(_on_profile_pressed)


func _on_play_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Play.tscn")


func _on_shop_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Shop.tscn")


func _on_team_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Team.tscn")


func _on_pvp_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Pvp.tscn")


func _on_profile_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Profile.tscn")
