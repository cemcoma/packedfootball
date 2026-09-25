class_name ItemView
extends Control

## Reusable tile for one equipment item -- the ItemView.tscn template filled
## in and made tappable, exactly the arrangement PlayerCardView uses for
## cards. Used by the Items grid, the Player Detail slot row and the pack
## reveal, so there is one tile to redesign rather than three.
##
## An item is a plain Dictionary in this project (see ItemData.gd), not a
## class, so this takes one and reads it through ItemData's accessors rather
## than reaching into the short keys itself.
##
## Rarity colour comes from PlayerCard.TIER_COLORS: items and cards share one
## rarity scale, so a gold item has to read as a gold at a glance.

signal pressed

## Matches PlayerCardView's, so an item tile and a card tile have the same
## corner radius when they sit next to each other.
const CORNER := 8
const BORDER_WIDTH := 3

## The empty-slot tile Player Detail shows for a socket with nothing in it.
const EMPTY_STAT := ""

@onready var _frame: Panel = %Frame
@onready var _value_label: Label = %ValueLabel
@onready var _stat_label: Label = %StatLabel
@onready var _rarity_label: Label = %RarityLabel
@onready var _tap_button: Button = %TapButton
@onready var _selection: Panel = %Selection

var _item: Dictionary = {}
var _is_empty: bool = false
var _selected: bool = false


func _ready() -> void:
	_tap_button.pressed.connect(func() -> void: pressed.emit())
	# The frame colour is baked into a StyleBoxFlat, so a dark/light swap has
	# to rebuild it -- same reason PlayerCardView listens.
	ThemeManager.theme_changed.connect(_restyle)
	_restyle()


## The item this tile shows. Clears the per-context state (selection) so a
## recycled tile can't keep the previous item's tint, the same contract
## PlayerCardView.set_card has.
func set_item(item: Dictionary) -> void:
	_item = item
	_is_empty = false
	_selected = false
	if not is_node_ready():
		await ready
	_value_label.text = "+%d" % (
		ItemData.SLOT_EXTENDER_BONUS if ItemData.is_slot_extender(item) else ItemData.value(item)
	)
	_stat_label.text = ItemData.stat_label(item)
	_rarity_label.text = PlayerCard.tier_label(ItemData.rarity(item))
	_restyle()


## An unfilled socket. Drawn as the same tile so a card's three slots line up
## whether or not they are filled.
func set_empty() -> void:
	_item = {}
	_is_empty = true
	_selected = false
	if not is_node_ready():
		await ready
	_value_label.text = "+"
	_stat_label.text = tr("Empty")
	_rarity_label.text = ""
	_restyle()


func set_selected(selected: bool) -> void:
	_selected = selected
	if not is_node_ready():
		await ready
	_selection.visible = selected


func item() -> Dictionary:
	return _item


func set_tappable(tappable: bool) -> void:
	if not is_node_ready():
		await ready
	_tap_button.disabled = not tappable


func _restyle() -> void:
	if not is_node_ready():
		return
	var accent := ThemeManager.color("accent")
	var heading := ThemeManager.color("heading")
	var muted := ThemeManager.color("surface_border")

	# An empty socket is drawn muted and hollow so a full card and a card with
	# room are told apart without reading a number.
	var edge: Color = muted if _is_empty else ItemData.color(_item)
	var fill: Color = MenuTile.BASE_FILL
	if not _is_empty:
		# A wash of the rarity colour, not the colour itself: the labels have
		# to stay readable on all seven.
		fill = MenuTile.BASE_FILL.lerp(edge, 0.18)
	_frame.add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(fill, edge, BORDER_WIDTH, true)
	)
	_selection.add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(Color(0, 0, 0, 0), accent, BORDER_WIDTH, true)
	)
	_selection.visible = _selected

	_value_label.add_theme_color_override("font_color", muted if _is_empty else edge)
	_stat_label.add_theme_color_override("font_color", muted if _is_empty else heading)
	_rarity_label.add_theme_color_override("font_color", MenuTile.SUBTITLE_COLOR)
