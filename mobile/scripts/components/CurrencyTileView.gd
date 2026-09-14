class_name CurrencyTileView
extends Control

## Reusable "pay X, get Y" tile for the Currency tab's Exchange and Bucks
## sub-tabs -- both are simple fixed-price offers with no availability/
## expiry concept (unlike packs/deals), so this deliberately skips
## PackView's tag/unavailable machinery entirely. A real labeled action
## button (mirrors PackView's own "Buy" button, not tap-anywhere) -- same
## reasoning: spending a currency is a real decision, not a "just browsing"
## tap.

signal action_pressed

@onready var _give_label: Label = %GiveLabel
@onready var _get_label: Label = %GetLabel
@onready var _action_button: Button = %ActionButton


func _ready() -> void:
	_action_button.pressed.connect(_on_action_button_pressed)


func _on_action_button_pressed() -> void:
	action_pressed.emit()


func set_tile(give_text: String, get_text: String, action_text: String) -> void:
	_give_label.text = give_text
	_get_label.text = get_text
	_action_button.text = action_text


## Only meaningful for Exchange (spending bucks can fail affordability) --
## Bucks tiles never call this, since a real-money purchase has no
## client-side "insufficient balance" concept (StoreKit handles payment
## failure on its own).
func set_affordable(can_afford: bool) -> void:
	_action_button.disabled = not can_afford
