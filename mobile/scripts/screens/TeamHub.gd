extends Control

## Team hub, between Menu and the five team screens. Squad is the hero; the
## grid pairs how the side plays (Tactics, Kit) with what the club owns
## (Inventory, Items). Each tile's subtitle shows that screen's current state.

@onready var _squad_button: MenuTile = %SquadTile
@onready var _tactics_button: MenuTile = %TacticsTile
@onready var _kit_button: MenuTile = %KitTile
@onready var _inventory_button: MenuTile = %InventoryTile
@onready var _items_button: MenuTile = %ItemsTile
@onready var _back_button: Button = %BackButton


func _ready() -> void:
	_squad_button.pressed.connect(_on_squad_pressed)
	_tactics_button.pressed.connect(_on_tactics_pressed)
	_kit_button.pressed.connect(_on_kit_pressed)
	_inventory_button.pressed.connect(_on_inventory_pressed)
	_items_button.pressed.connect(_on_items_pressed)
	_back_button.pressed.connect(_on_back_pressed)

	# The shirt and the XI's shape on their tiles; IGNORE so taps still land on the tile.
	var swatch := KitSwatch.new()
	swatch.custom_minimum_size = Vector2(40, 46)
	swatch.mouse_filter = Control.MOUSE_FILTER_IGNORE
	swatch.set_design(GameProfile.kit_design())
	_kit_button.add_side_control(swatch)
	var sketch := FormationSketch.new()
	sketch.custom_minimum_size = Vector2(0, 140)
	sketch.mouse_filter = Control.MOUSE_FILTER_IGNORE
	sketch.formation = GameProfile.formation
	sketch.kit = GameProfile.kit_design()
	_squad_button.add_body_control(sketch)

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
	_squad_button.subtitle_text = tr("Pick your formation and choose who starts.")
	_tactics_button.subtitle_text = tr("Playing %s. Choose how your side plays.") % Tactics.display_name(GameProfile.tactic_style())
	_kit_button.subtitle_text = tr("Design your club's shirt: pattern and colours.")
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
	var spare: int = GameProfile.all_items.size()
	if spare == 0:
		_items_button.subtitle_text = tr("No spare equipment. Equipment Packs are in the Shop.")
	else:
		_items_button.subtitle_text = (
			tr("%d spare items waiting for a card. Socketing one is permanent.") % spare
		)
	_apply_theme_colors()


func _on_squad_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Team.tscn")


func _on_tactics_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Tactics.tscn")


func _on_kit_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/CustomizeKit.tscn")


func _on_inventory_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Inventory.tscn")


func _on_items_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Items.tscn")


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")


## The XI's shape in the club's shirts, own goal at the bottom -- one half in
## Formations' coordinates. Hard squares and lines, per MenuTile's pixel-art rules.
class FormationSketch extends Control:
	const HALF := Vector2(70.0, 50.0)
	const LINE := Color(1.0, 1.0, 1.0, 0.22)
	const DOT := 10.0

	var formation := ""
	var kit: KitDesign = null

	func _draw() -> void:
		var scale := minf(size.x / HALF.x, size.y / HALF.y)
		var pitch := Rect2((size - HALF * scale) / 2.0, HALF * scale)
		var at := func(p: Vector2) -> Vector2:
			return Vector2(pitch.position.x + p.x * scale, pitch.end.y - p.y * scale)
		draw_rect(pitch, LINE, false, 2.0)
		draw_rect(Rect2(at.call(Vector2(14.0, 18.0)), Vector2(42.0, 18.0) * scale), LINE, false, 2.0)
		draw_arc(at.call(Vector2(35.0, 50.0)), 9.15 * scale, 0.0, PI, 16, LINE, 2.0)
		for slot in Formations.get_formation(formation):
			var shirt: KitDesign = kit.for_position(slot["role"])
			var centre: Vector2 = at.call(slot["pos"])
			draw_rect(Rect2(centre - Vector2.ONE * DOT / 2.0, Vector2.ONE * DOT), shirt.secondary_color())
			draw_rect(Rect2(centre - Vector2.ONE * (DOT / 2.0 - 2.0), Vector2.ONE * (DOT - 4.0)), shirt.primary_color())
