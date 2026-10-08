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
## button that explains nothing. TapButton covers the whole box, frame and
## price included; the odds ("i") button lives in that popup.

## 600 width 800 height px

signal pressed  ## anywhere on the box was tapped -- see Shop.gd, which opens the buy confirmation.

@onready var _name_label: Label = %NameLabel
@onready var _cards_label: Label = %CardsLabel
@onready var _limited_label: Label = %LimitedLabel
@onready var _price_amount: CurrencyAmount = %PriceAmount
@onready var _price_panel: PanelContainer = %PricePanel
@onready var _status_bar: PanelContainer = %StatusBar
@onready var _status_label: Label = %StatusLabel
@onready var _tap_button: Button = %TapButton
@onready var _pack_texture: TextureRect = %PackTexture

var _pack: PackData = null
var _shortfall: String = ""


func _ready() -> void:
	_tap_button.pressed.connect(_on_tap_button_pressed)
	ThemeManager.theme_changed.connect(_restyle)
	RemoteArt.art_ready.connect(_on_art_ready)
	_restyle()


func _on_art_ready(kind: String, key: String, texture: Texture2D) -> void:
	if kind == "packs" and _pack != null and key == _pack.sprite_key:
		_pack_texture.texture = texture


func _on_tap_button_pressed() -> void:
	pressed.emit()


func set_pack(pack: PackData) -> void:
	_pack = pack
	_name_label.text = pack.pack_name
	_cards_label.text = tr("%d cards") % pack.contents_count()
	_limited_label.text = pack.limited_label()
	_limited_label.visible = pack.is_limited()
	_price_amount.set_amount(pack.price_currency, pack.price)
	_price_amount.set_sizes(20, 18)
	_pack_texture.texture = pack.get_texture()
	_restyle()
	_refresh_state()


## The box and its price wear the menu's pixel frame, tinted with whatever
## currency the pack costs -- so a Cash pack reads as a different kind of
## purchase from a Credits one before you read the number.
func _restyle() -> void:
	if _price_panel == null:
		return
	var accent := (
		CurrencyDisplay.color_for(_pack.price_currency) if _pack != null
		else ThemeManager.color("surface_border")
	)
	# No content margin: Pad holds the inset, so TapButton reaches the frame's edge.
	add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, accent, 3, true, Vector2.ZERO)
	)
	_price_panel.add_theme_stylebox_override(
		"panel",
		MenuTile.pixel_frame(MenuTile.BASE_FILL.lightened(0.06), accent, 2, false, Vector2(4, 2))
	)
	var warning := ThemeManager.color("warning")
	_status_bar.add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, warning, 2, true, Vector2(4, 6))
	)
	_status_label.add_theme_color_override("font_color", warning)


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
