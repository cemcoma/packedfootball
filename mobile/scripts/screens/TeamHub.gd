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

@onready var _squad_button: MenuTile = %SquadTile
@onready var _inventory_button: MenuTile = %InventoryTile
@onready var _back_button: Button = %BackButton


func _ready() -> void:
	_squad_button.pressed.connect(_on_squad_pressed)
	_inventory_button.pressed.connect(_on_inventory_pressed)
	_back_button.pressed.connect(_on_back_pressed)

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()
	_refresh_hints()


## The hints are the tiles' own subtitles now, so they sit on the tile's dark
## frame and take its colour -- they used to sit straight on the background
## photo, where they were barely readable. The inventory one still goes amber
## once the club is full, since that's the point it stops being a fact and
## starts being a blocker.
func _apply_theme_colors() -> void:
	# A plain Button beside the tiles, so it needs the frame applied by hand.
	# It used to carry MenuTile's SCRIPT without MenuTile's scene, which left
	# it with no title label to fill and no styling at all -- see MenuTile.
	MenuTile.style_button(_back_button, ThemeManager.color("surface_border"))
	var full: bool = GameProfile.inventory_space() <= 0
	if full:
		_inventory_button.set_subtitle_color(ThemeManager.color("warning"))
	else:
		_inventory_button.set_subtitle_color(MenuTile.SUBTITLE_COLOR)


func _refresh_hints() -> void:
	var count := GameProfile.inventory_count()
	var owned: int = GameProfile.all_cards.size()
	_squad_button.subtitle_text = tr("Pick your formation, choose who starts, and design your kit.")
	if count >= GameProfile.inventory_cap:
		_inventory_button.subtitle_text = (
			tr("Full: %d / %d. Release players here to open packs again. %d owned in total.")
			% [count, GameProfile.inventory_cap, owned]
		)
	else:
		_inventory_button.subtitle_text = (
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
