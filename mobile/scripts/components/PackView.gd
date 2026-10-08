class_name PackView
extends PanelContainer

## Reusable pack "box" visual -- the pack's art with name/type/price/
## cards-per-pack over it and, for a limited pack, how many are left. Same
## seam PlayerCardView.gd draws: only this file needs to change once the
## art changes, every screen that lists packs already goes through it.
##
## TAP THE PACK TO BUY. There used to be a labelled "Buy" button under the
## art, on the theory that spending credits deserves a deliberate tap;
## playtesters kept tapping the pack itself and finding nothing happened.
## So the pack is the button now, and the deliberate step moved to where
## it belongs -- a confirmation popup (Shop.gd's BuyConfirm) that shows
## the price and asks. That's also what lets an unaffordable or not-yet-
## available pack stay tappable: the popup explains instead of a greyed
## button that explains nothing. The tap is read by the Shop's CardCarousel,
## which hit-tests the whole box; the odds ("i") button lives in that popup.

## 600 width 800 height px

## The scene's own height; past it the text grows with the box.
const DESIGN_HEIGHT := 280.0

@onready var _name_label: Label = %NameLabel
@onready var _cards_label: Label = %CardsLabel
@onready var _limited_label: Label = %LimitedLabel
@onready var _price_amount: CurrencyAmount = %PriceAmount
@onready var _price_panel: PanelContainer = %PricePanel
@onready var _status_bar: PanelContainer = %StatusBar
@onready var _status_label: Label = %StatusLabel
@onready var _art_ratio: AspectRatioContainer = %PackArtRatio
@onready var _footer: Control = %Footer
@onready var _pack_texture: TextureRect = %PackTexture
@onready var _pack_shadow: TextureRect = %PackShadow

var _pack: PackData = null
var _shortfall: String = ""
var _text_scale := 1.0
## Below 1 when the text had to step down to fit the box (see _check_fit).
var _text_fit := 1.0


func _ready() -> void:
	ThemeManager.theme_changed.connect(_restyle)
	RemoteArt.art_ready.connect(_on_art_ready)
	_restyle()


func _on_art_ready(kind: String, key: String, texture: Texture2D) -> void:
	if kind == "packs" and _pack != null and key == _pack.sprite_key:
		_set_art(texture)


func set_pack(pack: PackData) -> void:
	_pack = pack
	_name_label.text = pack.pack_name
	_cards_label.text = tr("%d cards") % pack.contents_count()
	_limited_label.text = pack.limited_label()
	_limited_label.visible = pack.is_limited()
	_price_amount.set_amount(pack.price_currency, pack.price)
	_set_art(pack.get_texture())
	_restyle()
	_refresh_state()


## The art's silhouette, darkened and offset, is its drop shadow.
func _set_art(texture: Texture2D) -> void:
	_pack_texture.texture = texture
	_pack_shadow.texture = texture


## No box behind the pack: the art floats on its own shadow. The price wears
## the menu's pixel frame, tinted with whatever currency the pack costs -- so
## a Cash pack reads as a different kind of purchase from a Credits one.
func _restyle() -> void:
	if _price_panel == null:
		return
	var accent := (
		CurrencyDisplay.color_for(_pack.price_currency) if _pack != null
		else ThemeManager.color("surface_border")
	)
	add_theme_stylebox_override("panel", StyleBoxEmpty.new())
	_price_panel.add_theme_stylebox_override(
		"panel",
		MenuTile.pixel_frame(MenuTile.BASE_FILL.lightened(0.06), accent, 2, true, Vector2(4, 2))
	)
	var warning := ThemeManager.color("warning")
	_status_bar.add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, warning, 2, true, Vector2(4, 6))
	)
	_status_label.add_theme_color_override("font_color", warning)
	_apply_text_sizes()


## Off the theme's default font size, so the Large Text setting grows these too.
func _apply_text_sizes() -> void:
	var base := _base_text_size()
	_cards_label.add_theme_font_size_override("font_size", roundi(base * 0.9))
	_limited_label.add_theme_font_size_override("font_size", roundi(base * 0.85))
	_status_label.add_theme_font_size_override("font_size", roundi(base * 0.9))
	_price_amount.set_sizes(roundi(base * 1.5), roundi(base * 1.35))
	_fit_name()


func _base_text_size() -> float:
	return get_theme_default_font_size() * _text_scale * _text_fit


## Shrinks the name until its longest word fits on a line, so wrapping never splits a word.
func _fit_name() -> void:
	var target := roundi(_base_text_size() * 1.25)
	var font: Font = _name_label.get_theme_font("font")
	var row := _name_label.get_parent() as HBoxContainer
	var room: float = (
		custom_minimum_size.x - get_theme_stylebox("panel").get_minimum_size().x
		- row.get_theme_constant("separation") * (row.get_child_count() - 1)
	)
	for spacer: Control in row.get_children():
		if spacer != _name_label:
			room -= spacer.custom_minimum_size.x
	var words := _name_label.text.split(" ", false)
	var font_size := target
	while font_size > roundi(target * 0.6):
		var widest := 0.0
		for word in words:
			widest = maxf(widest, font.get_string_size(word, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x)
		if widest <= room:
			break
		font_size -= 1
	_name_label.add_theme_font_size_override("font_size", font_size)


## Sizes the box to `height`, just wide enough for the art to fill it.
func fit_height(height: float) -> void:
	_text_scale = height / DESIGN_HEIGHT
	_text_fit = 1.0
	_apply_text_sizes()
	var frame: Vector2 = get_theme_stylebox("panel").get_minimum_size()
	var art_height: float = (
		height - frame.y - $Layout.get_theme_constant("separation") - _footer.get_combined_minimum_size().y
	)
	custom_minimum_size = Vector2(roundf(art_height * _art_ratio.ratio + frame.x), height)
	_fit_name()
	_queue_fit_check()


func _queue_fit_check() -> void:
	if not get_tree().process_frame.is_connected(_check_fit):
		get_tree().process_frame.connect(_check_fit, CONNECT_ONE_SHOT)


## Large Text on a short screen can stack more wrapped lines than the art
## holds. Wrapping only settles after layout, so this checks a frame later
## and steps the text down until the box is back to its fitted height.
func _check_fit() -> void:
	if get_combined_minimum_size().y <= custom_minimum_size.y + 0.5 or _text_fit <= 0.6:
		return
	_text_fit *= 0.9
	_apply_text_sizes()
	_queue_fit_check()


## Why the player can't open this pack right now ("Not enough cash", "Bench
## full"), or "" when they can -- see Shop.gd's _shortfall_for.
func set_shortfall(reason: String) -> void:
	_shortfall = reason
	_refresh_state()


## An unbuyable pack wears a bar across its art saying why; "unavailable"
## wins over a shortfall. The tap stays live: the buy popup spells it out.
func _refresh_state() -> void:
	if _pack == null:
		return
	var reason := _pack.tag_text() if not _pack.available else _shortfall
	_status_label.text = reason
	_status_bar.visible = reason != ""
