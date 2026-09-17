extends Control

## Team hub: Squad or Inventory. Sits between Menu and the two screens that
## actually do something, the same way Play.tscn sits in front of Quick
## Match/Tournament -- Menu's "Team" button used to go straight to the squad
## editor, and now lands here first.
##
## The split is what the two screens are FOR, not just where they live:
## Squad is the eleven you play with (formation, who starts, the kit), and
## Inventory is everything you own (browse, release, restyle). Only the
## second has a size limit, which is why the counter belongs here and not on
## the squad screen.

@onready var _squad_button: Button = %SquadButton
@onready var _inventory_button: Button = %InventoryButton
@onready var _back_button: Button = %BackButton

@onready var _squad_hint: Label = %SquadHint
@onready var _inventory_hint: Label = %InventoryHint


func _ready() -> void:
	_squad_button.pressed.connect(_on_squad_pressed)
	_inventory_button.pressed.connect(_on_inventory_pressed)
	_back_button.pressed.connect(_on_back_pressed)

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()
	_refresh_hints()


## Both hints sit straight on the screen background with no panel behind
## them, so the Theme's Label color doesn't reach them -- see ThemeManager's
## note on text_hint. The inventory one goes amber once the club is full,
## since that's the point it stops being a fact and starts being a blocker.
func _apply_theme_colors() -> void:
	var hint := ThemeManager.color("text_hint")
	_squad_hint.add_theme_color_override("font_color", hint)
	var full: bool = GameProfile.inventory_space() <= 0
	_inventory_hint.add_theme_color_override(
		"font_color", ThemeManager.color("warning") if full else hint
	)


func _refresh_hints() -> void:
	var count := GameProfile.inventory_count()
	var owned: int = GameProfile.all_cards.size()
	_squad_hint.text = tr("Pick your formation, choose who starts, and design your kit.")
	if count >= GameProfile.inventory_cap:
		_inventory_hint.text = (
			tr("Full: %d / %d. Release players here to open packs again. %d owned in total.")
			% [count, GameProfile.inventory_cap, owned]
		)
	else:
		_inventory_hint.text = (
			tr("Every player you own -- %d of them. Release or restyle any of them. Bench space %d / %d.")
			% [owned, count, GameProfile.inventory_cap]
		)
	_apply_theme_colors()


func _on_squad_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Team.tscn")


func _on_inventory_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Inventory.tscn")


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")
