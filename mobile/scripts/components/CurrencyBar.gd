class_name CurrencyBar
extends HBoxContainer

## Every balance the account has in one strip -- credits, cash, medals and the
## energy bar. CurrencyHud puts one of these top right of every screen, so no
## screen carries its own copy of any of them any more.
##
## Reads the GameProfile cache and never fetches: everything that moves a
## balance emits GameProfile.currencies_changed, which lands here.

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

	# Display only -- a tap has to reach the screen underneath the strip.
	_ignore_mouse(self)

	GameProfile.currencies_changed.connect(refresh)
	refresh()


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
