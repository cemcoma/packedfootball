class_name PackView
extends Control

## Reusable pack "box" visual -- a tier-colored (by type) rectangle showing
## name/type/price/cards-per-pack and, for a limited pack, how many are
## left. "They will have their own image like the cards but for now it can
## be a box." -- same seam PlayerCardView.gd draws: only this file needs to
## change once real per-pack art exists, every screen that lists packs
## already goes through it.
##
## Unlike PlayerCardView (tap-anywhere, since selecting a card is a low-
## stakes, reversible action), this uses a real labeled "Buy" button --
## spending credits deserves a deliberate tap, not "anywhere on the box".

signal buy_pressed
signal info_pressed  ## "i" button tapped -- see Shop.gd, which opens PackInfoPopup for this pack.

@onready var _background: ColorRect = %Background
@onready var _type_label: Label = %TypeLabel
@onready var _name_label: Label = %NameLabel
@onready var _cards_label: Label = %CardsLabel
@onready var _limited_label: Label = %LimitedLabel
@onready var _price_label: Label = %PriceLabel
@onready var _tag_label: Label = %TagLabel
@onready var _buy_button: Button = %BuyButton
@onready var _info_button: Button = %InfoButton

var _pack: PackData = null
var _affordable: bool = true


func _ready() -> void:
	_buy_button.pressed.connect(_on_buy_button_pressed)
	_info_button.pressed.connect(_on_info_button_pressed)


func _on_buy_button_pressed() -> void:
	buy_pressed.emit()


func _on_info_button_pressed() -> void:
	info_pressed.emit()


func set_pack(pack: PackData) -> void:
	_pack = pack
	_background.color = PackData.type_color(pack.type)
	_type_label.text = pack.type.capitalize()
	_name_label.text = pack.pack_name
	_cards_label.text = "%d cards" % pack.cards_per_pack
	_limited_label.text = pack.limited_label()
	_limited_label.visible = pack.is_limited()
	_price_label.text = "%d credits" % pack.price
	_refresh_buy_button()


func set_affordable(can_afford: bool) -> void:
	_affordable = can_afford
	_refresh_buy_button()


## Single source of truth for the Buy-button-vs-tag decision, since both
## set_pack() (pack just loaded/changed) and set_affordable() (credits
## balance changed, pack unchanged) need to re-derive it. "Unavailable"
## always wins over "can't afford" -- a teased pack shows its tag
## regardless of whether the player could otherwise afford it.
func _refresh_buy_button() -> void:
	if _pack == null:
		return
	if not _pack.available:
		_tag_label.text = _pack.tag_text()
		_tag_label.visible = true
		_buy_button.visible = false
		return
	_tag_label.visible = false
	_buy_button.visible = true
	_buy_button.disabled = not _affordable
