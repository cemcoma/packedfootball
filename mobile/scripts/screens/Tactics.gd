extends Control

## Tactics: how the side plays. The play style on the left; the captain and
## set-piece takers on the right, each picked from the XI in a popup that
## ranks them by the stats the engine uses for that job.
##
## Everything is saved the moment it is picked (GameProfile.set_tactic_style /
## set_tactic_role), the way the kit is: nothing to forget to save on the way out.

const MENU_TILE := preload("res://scenes/components/MenuTile.tscn")

const PICKER_ROW_HEIGHT := 52
const AUTO := ""

@onready var _style_list: VBoxContainer = %StyleList
@onready var _role_list: VBoxContainer = %RoleList
@onready var _lineup_note: Label = %LineupNote
@onready var _status_label: Label = %StatusLabel
@onready var _back_button: Button = %BackButton
@onready var _picker: Control = %Picker
@onready var _picker_panel: PanelContainer = %PickerPanel
@onready var _picker_title: Label = %PickerTitle
@onready var _picker_hint: Label = %PickerHint
@onready var _picker_list: VBoxContainer = %PickerList
@onready var _picker_cancel: Button = %PickerCancel

var _tiles: Dictionary = {}  # style id -> MenuTile
var _role_tiles: Dictionary = {}  # role key -> MenuTile
var _role_badges: Dictionary = {}  # role key -> its tile's rating badge
var _picker_rows: Array = []
var _saving := false


func _ready() -> void:
	for style in Tactics.STYLE_IDS:
		var tile: MenuTile = MENU_TILE.instantiate()
		tile.title_text = Tactics.display_name(style)
		tile.subtitle_text = Tactics.description(style)
		tile.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		# PASS, or a finger landing on a tile can't drag the list.
		tile.mouse_filter = Control.MOUSE_FILTER_PASS
		tile.pressed.connect(_on_style_pressed.bind(style))
		_style_list.add_child(tile)
		_tiles[style] = tile
	_build_role_tiles()
	_back_button.pressed.connect(_on_back_pressed)
	_picker_cancel.pressed.connect(_close_picker)
	$Picker/Scrim.gui_input.connect(_on_scrim_input)
	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()
	_refresh_selection()
	_refresh_roles()


func _apply_theme_colors() -> void:
	MenuTile.style_button(_back_button, ThemeManager.color("surface_border"))
	MenuTile.style_button(_picker_cancel, ThemeManager.color("surface_border"))
	_picker_panel.add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, ThemeManager.color("accent"), 3, true)
	)
	_picker_title.add_theme_color_override("font_color", MenuTile.TITLE_COLOR)
	_picker_hint.add_theme_color_override("font_color", MenuTile.SUBTITLE_COLOR)


## The picked style is the hero tile; the rest sit back.
func _refresh_selection() -> void:
	var current := GameProfile.tactic_style()
	for style in _tiles:
		var tile: MenuTile = _tiles[style]
		tile.hero = style == current
		tile.accent_key = "heading" if style == current else "accent"
		tile.set_tile_disabled(_saving)


func _on_style_pressed(style: String) -> void:
	if _saving or style == GameProfile.tactic_style():
		return
	_saving = true
	_status_label.text = ""
	_refresh_selection()
	var ok: bool = await GameProfile.set_tactic_style(style)
	_saving = false
	if not ok:
		_status_label.text = tr("Couldn't save your tactics -- check your connection and try again.")
	_refresh_selection()


# ------------------------------------------------------- captain and takers

func _build_role_tiles() -> void:
	for role in Tactics.ROLE_KEYS:
		var tile: MenuTile = MENU_TILE.instantiate()
		tile.title_text = Tactics.role_name(role)
		tile.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		tile.mouse_filter = Control.MOUSE_FILTER_PASS
		tile.pressed.connect(_open_picker.bind(role))
		_role_list.add_child(tile)
		var badge := _rating_badge()
		tile.add_side_control(badge)
		_role_tiles[role] = tile
		_role_badges[role] = badge


## Each tile names who does the job and how good they are at it -- "Auto" when
## the side picks for itself, which is also what a pick who left the XI falls back to.
func _refresh_roles() -> void:
	var xi := GameProfile.lineup_cards()
	var complete := xi.size() == 11 and not xi.has(null)
	_lineup_note.visible = not complete
	_role_list.visible = complete
	if not complete:
		return
	var slots := Formations.get_formation(GameProfile.formation)
	for role in _role_tiles:
		var tile: MenuTile = _role_tiles[role]
		var slot := Tactics.assigned_slot(GameProfile.tactics, role, GameProfile.formation, xi)
		var picked := Tactics.picked_slot(GameProfile.tactics, role, GameProfile.formation, xi) >= 0
		var card: PlayerCard = xi[slot] if slot >= 0 else null
		var who := "%s (%s)" % [card.full_name(), slots[slot]["role"]] if card != null else "-"
		tile.subtitle_text = who if picked else tr("Auto: %s") % who
		tile.accent_key = "heading" if picked else "accent"
		tile.set_tile_disabled(_saving)
		var rating := Tactics.rating(card, slots[slot]["role"], role) if card != null else 0.0
		_set_badge(_role_badges[role], rating, role)


func _rating_badge() -> VBoxContainer:
	var box := VBoxContainer.new()
	box.custom_minimum_size = Vector2(44, 0)
	box.add_theme_constant_override("separation", -2)
	var number := Label.new()
	number.add_theme_font_size_override("font_size", 22)
	number.add_theme_color_override("font_color", MenuTile.TITLE_COLOR)
	var tag := Label.new()
	tag.add_theme_font_size_override("font_size", 10)
	tag.add_theme_color_override("font_color", MenuTile.SUBTITLE_COLOR)
	for label in [number, tag]:
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		box.add_child(label)
	# Added after the tile's click-through pass, so it has to go deaf itself.
	for node in [box, number, tag]:
		node.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return box


func _set_badge(badge: VBoxContainer, rating: float, role: String) -> void:
	(badge.get_child(0) as Label).text = str(roundi(rating))
	(badge.get_child(1) as Label).text = Tactics.rating_tag(role)


# ------------------------------------------------------------------ picker

## Auto first, then everyone who can do the job, best at it first.
func _open_picker(role: String) -> void:
	if _saving:
		return
	var xi := GameProfile.lineup_cards()
	var slots := Formations.get_formation(GameProfile.formation)
	_picker_title.text = Tactics.role_name(role)
	_picker_hint.text = Tactics.role_description(role)
	for row in _picker_rows:
		row.queue_free()
	_picker_rows.clear()

	var current := Tactics.picked_slot(GameProfile.tactics, role, GameProfile.formation, xi)
	var auto_slot := Tactics.auto_slot(role, GameProfile.formation, xi)
	var auto_card: PlayerCard = xi[auto_slot]
	_add_picker_row(
		role, AUTO, tr("Auto"), tr("Let the side choose -- %s right now.") % auto_card.full_name(),
		Tactics.rating(auto_card, slots[auto_slot]["role"], role), current < 0
	)

	var candidates: Array = []
	for i in range(xi.size()):
		if Tactics.eligible(role, slots[i]["role"]):
			candidates.append([i, Tactics.rating(xi[i], slots[i]["role"], role)])
	candidates.sort_custom(func(a, b): return a[1] > b[1] or (a[1] == b[1] and a[0] < b[0]))
	for entry in candidates:
		var slot: int = entry[0]
		var card: PlayerCard = xi[slot]
		var slot_role: String = slots[slot]["role"]
		var where := slot_role if card.position == slot_role else tr("%s, out of position") % slot_role
		_add_picker_row(role, card.player_id, card.full_name(), where, entry[1], slot == current)
	_picker.visible = true


func _add_picker_row(role: String, player_id: String, title: String, subtitle: String, rating: float, chosen: bool) -> void:
	var tile: MenuTile = MENU_TILE.instantiate()
	tile.title_text = title
	tile.subtitle_text = subtitle
	tile.min_height = PICKER_ROW_HEIGHT
	tile.accent_key = "heading" if chosen else "accent"
	tile.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	tile.mouse_filter = Control.MOUSE_FILTER_PASS
	tile.pressed.connect(_on_pick.bind(role, player_id))
	_picker_list.add_child(tile)
	var badge := _rating_badge()
	tile.add_side_control(badge)
	_set_badge(badge, rating, role)
	_picker_rows.append(tile)


func _on_pick(role: String, player_id: String) -> void:
	if _saving:
		return
	if player_id == str(GameProfile.tactics.get(role, AUTO)):
		_close_picker()
		return
	_saving = true
	_status_label.text = ""
	for row in _picker_rows:
		(row as MenuTile).set_tile_disabled(true)
	var ok: bool = await GameProfile.set_tactic_role(role, player_id)
	_saving = false
	if not ok:
		_status_label.text = tr("Couldn't save your tactics -- check your connection and try again.")
	_close_picker()


func _close_picker() -> void:
	if _saving:
		return
	_picker.visible = false
	_refresh_roles()


func _on_scrim_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed:
		_close_picker()


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/TeamHub.tscn")
