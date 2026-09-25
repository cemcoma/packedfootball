class_name ItemView
extends Control

## One equipment item, drawn as a card: the same size and rarity background as
## PlayerCardView, with a per-stat sprite where the portrait goes.
## Art paths: sprites/player_cards/<rarity>.png and sprites/items/<stat>.png,
## both ResourceLoader.exists()-guarded, falling back to text.

signal pressed

## Must match PlayerCardView.tscn's size -- CardCarousel spaces the strip off
## the widest view it holds.
const CARD_SIZE := Vector2(110, 150)

## Player Detail's slot row: five full-size cards would be 550px against a
## 180px card column.
const COMPACT_SIZE := Vector2(52, 70)

const ITEM_SPRITE_DIR := "res://sprites/items/"
const CARD_SPRITE_DIR := "res://sprites/player_cards/"

## Keeps the labels readable over the busier card backs.
const SCRIM := Color(0, 0, 0, 0.35)
const SELECTED_ALPHA := 0.5

@onready var _background: TextureRect = %BackgroundTexture
@onready var _scrim: ColorRect = %Scrim
@onready var _value_label: Label = %ValueLabel
@onready var _kind_label: Label = %KindLabel
@onready var _sprite: TextureRect = %ItemSprite
@onready var _sprite_fallback: Label = %SpriteFallback
@onready var _stat_label: Label = %StatLabel
@onready var _rarity_label: Label = %RarityLabel
@onready var _frame: Panel = %Frame
@onready var _frame_inner: Panel = %FrameInner
@onready var _tap_button: Button = %TapButton
@onready var _selection: Panel = %Selection

var _item: Dictionary = {}
var _is_empty: bool = false
var _selected: bool = false
var _compact: bool = false


func _ready() -> void:
	custom_minimum_size = CARD_SIZE
	_tap_button.pressed.connect(func() -> void: pressed.emit())
	ThemeManager.theme_changed.connect(_restyle)
	_scrim.color = SCRIM
	_restyle()


## Clears the selection too, so a recycled tile can't keep the last one's.
func set_item(item: Dictionary) -> void:
	_item = item
	_is_empty = false
	_selected = false
	if not is_node_ready():
		await ready

	_value_label.text = "+%d" % (
		ItemData.SLOT_EXTENDER_BONUS if ItemData.is_slot_extender(item) else ItemData.value(item)
	)
	_kind_label.text = ItemData.kind_badge(item)
	_stat_label.text = ItemData.stat_label(item)
	_rarity_label.text = PlayerCard.tier_label(ItemData.rarity(item))
	_apply_background(ItemData.rarity(item))
	_apply_sprite(ItemData.stat(item))
	_restyle()


## An unfilled socket: same shape, no art.
func set_empty() -> void:
	_item = {}
	_is_empty = true
	_selected = false
	if not is_node_ready():
		await ready

	_value_label.text = ""
	_kind_label.text = ""
	_stat_label.text = tr("Empty")
	_rarity_label.text = ""
	_background.texture = null
	_sprite.visible = false
	_sprite_fallback.visible = true
	_sprite_fallback.text = "+"
	_restyle()


## Small enough for a row of sockets. Safe to call before or after set_item.
func set_compact(compact: bool) -> void:
	_compact = compact
	if not is_node_ready():
		await ready
	custom_minimum_size = COMPACT_SIZE if compact else CARD_SIZE
	size = custom_minimum_size
	_kind_label.visible = not compact
	_rarity_label.visible = not compact
	_stat_label.visible = not compact
	_value_label.add_theme_font_size_override("font_size", 13 if compact else 24)
	_sprite_fallback.add_theme_font_size_override("font_size", 13 if compact else 26)


func set_selected(selected: bool) -> void:
	_selected = selected
	if not is_node_ready():
		await ready
	_selection.visible = selected
	modulate.a = SELECTED_ALPHA if selected else 1.0


func item() -> Dictionary:
	return _item


func set_tappable(tappable: bool) -> void:
	if not is_node_ready():
		await ready
	_tap_button.disabled = not tappable


## The same card back a player of this rarity gets.
func _apply_background(rarity: String) -> void:
	var path := CARD_SPRITE_DIR + PlayerCard.tier_family(rarity) + ".png"
	_background.texture = load(path) if ResourceLoader.exists(path) else null
	_scrim.visible = _background.texture != null


## The stat's own art, or its name in large type until that art exists.
func _apply_sprite(stat: String) -> void:
	var path := ITEM_SPRITE_DIR + stat + ".png"
	var texture: Texture2D = load(path) if ResourceLoader.exists(path) else null
	_sprite.texture = texture
	_sprite.visible = texture != null
	_sprite_fallback.visible = texture == null
	if texture == null:
		_sprite_fallback.text = ItemData.stat_glyph(_item)


func _restyle() -> void:
	if not is_node_ready():
		return
	var accent := ThemeManager.color("accent")
	var muted := ThemeManager.color("surface_border")
	var edge: Color = muted if _is_empty else ItemData.color(_item)

	var on_art: bool = _background.texture != null
	_apply_frame(on_art, edge)
	var title: Color = MenuTile.TITLE_COLOR if on_art else edge
	_value_label.add_theme_color_override("font_color", muted if _is_empty else title)
	_sprite_fallback.add_theme_color_override("font_color", muted if _is_empty else title)
	_stat_label.add_theme_color_override(
		"font_color", muted if _is_empty else MenuTile.TITLE_COLOR
	)
	_kind_label.add_theme_color_override("font_color", MenuTile.SUBTITLE_COLOR)
	_rarity_label.add_theme_color_override("font_color", MenuTile.SUBTITLE_COLOR)
	# Border-only: MenuTile.pixel_frame forces its own FILL_ALPHA on, which
	# painted the whole tile black over the art.
	_selection.add_theme_stylebox_override(
		"panel", PlayerCardView._ring_style(3, PlayerCardView.CARD_CORNER + 2, accent)
	)
	_selection.visible = _selected
	modulate.a = SELECTED_ALPHA if _selected else 1.0


## Border-only over card art: MenuTile.pixel_frame forces its own FILL_ALPHA
## on, which paints an opaque rectangle over the art. Two-tone because a bare
## rarity edge vanishes on its own rarity -- gold on gold.
func _apply_frame(on_art: bool, edge: Color) -> void:
	if not on_art:
		_frame.add_theme_stylebox_override("panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, edge, 3, true))
		_frame_inner.visible = false
		return
	_frame.add_theme_stylebox_override(
		"panel", PlayerCardView._ring_style(3, PlayerCardView.CARD_CORNER, PlayerCardView.RING_SHADE)
	)
	_frame_inner.add_theme_stylebox_override(
		"panel", PlayerCardView._ring_style(2, PlayerCardView.CARD_CORNER - 2, edge)
	)
	_frame_inner.visible = true
