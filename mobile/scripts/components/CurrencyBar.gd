class_name CurrencyBar
extends HBoxContainer

## Every balance the account has in one strip -- credits, cash, medals and the
## energy bar. CurrencyHud puts one of these top right of every screen, so no
## screen carries its own copy of any of them any more.
##
## Reads the GameProfile cache and never fetches: everything that moves a
## balance emits GameProfile.currencies_changed, which lands here.

## A tap on the energy bar; CurrencyHud decides where it goes.
signal energy_pressed

@onready var _credits_chip: CurrencyChip = %CreditsChip
@onready var _bucks_chip: CurrencyChip = %BucksChip
@onready var _medals_chip: CurrencyChip = %MedalsChip
@onready var _energy_bar: EnergyBar = %EnergyBar


func _ready() -> void:
	_credits_chip.set_currency("credits")
	_bucks_chip.set_currency("bucks")
	_medals_chip.set_currency("medals")
	for chip in [_credits_chip, _bucks_chip, _medals_chip]:
		chip.set_compact(true)
	_energy_bar.set_compact(true)

	# Display only -- a tap has to reach the screen underneath the strip --
	# except the energy bar, which opens the Shop's Energy tab.
	_ignore_mouse(self)
	_energy_bar.mouse_filter = Control.MOUSE_FILTER_STOP
	_energy_bar.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	_energy_bar.gui_input.connect(_on_energy_bar_input)

	GameProfile.currencies_changed.connect(refresh)
	refresh()


## Fires on release inside the bar, like a Button, so a finger that slides
## off cancels the tap.
func _on_energy_bar_input(event: InputEvent) -> void:
	var click := event as InputEventMouseButton
	if click == null or click.button_index != MOUSE_BUTTON_LEFT or click.pressed:
		return
	if Rect2(Vector2.ZERO, _energy_bar.size).has_point(click.position):
		energy_pressed.emit()


func _ignore_mouse(node: Node) -> void:
	if node is Control:
		node.mouse_filter = Control.MOUSE_FILTER_IGNORE
	for child in node.get_children():
		_ignore_mouse(child)


func refresh() -> void:
	if _credits_chip == null:
		return  # refreshed before _ready(); _ready() calls back here
	_credits_chip.set_amount(GameProfile.credits)
	_bucks_chip.set_amount(GameProfile.bucks)
	_medals_chip.set_amount(GameProfile.medals)
	_energy_bar.set_energy(GameProfile.energy)


## The live bar, ticked down locally between server reads -- the only reading
## that is right in the seconds after a point lands.
func energy() -> int:
	return _energy_bar.energy() if _energy_bar != null else 0
