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
## button that explains nothing.

## 600 width 800 height px

signal pressed  ## the pack itself was tapped -- see Shop.gd, which opens the buy confirmation.
signal info_pressed  ## "i" button tapped -- see Shop.gd, which opens PackInfoPopup for this pack.

## How faded a pack draws when it can't be bought right now (not on sale
## yet, sold out, can't afford it, no room). Still tappable -- see above.
const UNAVAILABLE_ALPHA := 0.55

@onready var _name_label: Label = %NameLabel
@onready var _cards_label: Label = %CardsLabel
@onready var _limited_label: Label = %LimitedLabel
@onready var _price_amount: CurrencyAmount = %PriceAmount
@onready var _price_panel: PanelContainer = %PricePanel
@onready var _tag_label: Label = %TagLabel
@onready var _tap_button: Button = %TapButton
@onready var _info_button: Button = %InfoButton
@onready var _pack_texture: TextureRect = %PackTexture

var _pack: PackData = null
var _affordable: bool = true


func _ready() -> void:
	_tap_button.pressed.connect(_on_tap_button_pressed)
	_info_button.pressed.connect(_on_info_button_pressed)
	ThemeManager.theme_changed.connect(_restyle)
	_restyle()


func _on_tap_button_pressed() -> void:
	pressed.emit()


func _on_info_button_pressed() -> void:
	info_pressed.emit()


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
	add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, accent, 3, true, Vector2(6, 6))
	)
	_price_panel.add_theme_stylebox_override(
		"panel",
		MenuTile.pixel_frame(MenuTile.BASE_FILL.lightened(0.06), accent, 2, false, Vector2(4, 2))
	)


func set_affordable(can_afford: bool) -> void:
	_affordable = can_afford
	_refresh_state()


## Single source of truth for how the box reads, since both set_pack()
## (pack just loaded/changed) and set_affordable() (balance changed, pack
## unchanged) need to re-derive it. "Unavailable" always wins over "can't
## afford" -- a teased pack shows its tag regardless of whether the player
## could otherwise afford it. Neither state disables the tap: the
## confirmation popup is where the reason is spelled out.
func _refresh_state() -> void:
	if _pack == null:
		return
	_tag_label.visible = not _pack.available
	if not _pack.available:
		_tag_label.text = _pack.tag_text()
	var buyable := _pack.available and _affordable
	_pack_texture.modulate.a = 1.0 if buyable else UNAVAILABLE_ALPHA
