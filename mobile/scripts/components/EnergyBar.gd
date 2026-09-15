class_name EnergyBar
extends PanelContainer

## The energy bar: how many matches you can still play, and when the next
## point lands.
##
## Fed entirely from the server's energy block (`energy`, `energy_max`,
## `seconds_to_next`, `regen_seconds`) and then ticked down LOCALLY

const LOW_FRACTION := 0.25  # at or below this, the bar warns

@onready var _bar: ProgressBar = %Bar
@onready var _amount_label: Label = %AmountLabel
@onready var _timer_label: Label = %TimerLabel

var _energy: int = 0
var _energy_max: int = 1
var _seconds_to_next: float = 0.0
var _regen_seconds: float = 2700.0


func _ready() -> void:
	ThemeManager.theme_changed.connect(_restyle)
	_restyle()
	_refresh()


## Takes the server's energy block verbatim. Every field is read defensively:
## `.get(key, default)` doesn't guard a present-but-null value, which is the
## bug PackData/GameProfile already carry this pattern for.
func set_energy(block: Dictionary) -> void:
	_energy = _int(block, "energy", _energy)
	_energy_max = maxi(1, _int(block, "energy_max", _energy_max))
	_seconds_to_next = float(_int(block, "seconds_to_next", int(_seconds_to_next)))
	_regen_seconds = float(maxi(1, _int(block, "regen_seconds", int(_regen_seconds))))
	_refresh()


static func _int(data: Dictionary, key: String, default: int) -> int:
	var value = data.get(key)
	return int(value) if typeof(value) in [TYPE_INT, TYPE_FLOAT] else default


func is_full() -> bool:
	return _energy >= _energy_max


func energy() -> int:
	return _energy


func _process(delta: float) -> void:
	if is_full():
		return
	_seconds_to_next -= delta
	if _seconds_to_next > 0.0:
		_refresh_timer()
		return

	# The point has (almost certainly) landed server-side. Credit it and start
	# the next interval; whatever the next response says wins.
	_energy = mini(_energy_max, _energy + 1)
	_seconds_to_next = 0.0 if is_full() else _regen_seconds
	_refresh()


func _refresh() -> void:
	if _bar == null:
		return  # set_energy() before _ready(); _ready() calls this again
	_bar.max_value = _energy_max
	_bar.value = _energy
	_amount_label.text = "%d/%d" % [_energy, _energy_max]
	_refresh_timer()
	_restyle()


func _refresh_timer() -> void:
	if _timer_label == null:
		return
	_timer_label.text = TimeFormat.next_energy_in(int(ceil(_seconds_to_next)), is_full())


## Amber when the bar is nearly out, because that is the state that stops you
## playing -- the same "warn on the thing that blocks you" rule the Shop's
## bench counter and the Squad screen's unsaved marker use.
func _restyle() -> void:
	if _bar == null:
		return
	var low: bool = float(_energy) / float(_energy_max) <= LOW_FRACTION
	var accent := ThemeManager.color("warning") if low else ThemeManager.color("positive")

	var panel := StyleBoxFlat.new()
	panel.bg_color = Color(accent.r, accent.g, accent.b, 0.14)
	panel.border_color = Color(accent.r, accent.g, accent.b, 0.55)
	panel.set_border_width_all(1)
	panel.set_corner_radius_all(10)
	panel.content_margin_left = 10.0
	panel.content_margin_right = 10.0
	panel.content_margin_top = 4.0
	panel.content_margin_bottom = 4.0
	add_theme_stylebox_override("panel", panel)

	var fill := StyleBoxFlat.new()
	fill.bg_color = accent
	fill.set_corner_radius_all(3)
	_bar.add_theme_stylebox_override("fill", fill)

	var track := StyleBoxFlat.new()
	track.bg_color = Color(accent.r, accent.g, accent.b, 0.18)
	track.set_corner_radius_all(3)
	_bar.add_theme_stylebox_override("background", track)

	# The labels are deliberately left alone, so they take the Theme's ordinary
	# Label colour like text anywhere else.
	#
	# They used to carry font_color overrides -- and a per-node override beats
	# every theme in the lookup, so nothing downstream could change them back.
	# It was also wrong twice over now that panels are the green card: the
	# timer's "text_hint" is near-black in light mode, and the accent washed
	# out against the panel tint.
	#
	# The low-energy signal lives in the BAR and the panel border instead,
	# which is where colour belongs -- a number that changes colour reads as a
	# different number, a bar that changes colour reads as a warning.
