class_name EnergyBar
extends PanelContainer

## The energy bar: how many matches you can still play, and when the next
## point lands.
##
## Fed entirely from the server's energy block (`energy`, `energy_max`,
## `seconds_to_next`, `regen_seconds`) and then ticked down LOCALLY

const LOW_FRACTION := 0.25  # at or below this, the bar warns

## The bar's own frame. Its fill is the same colour as the chip's border, so
## without a dark edge between them the two read as one block.
const BAR_OUTLINE := Color(0.04, 0.04, 0.05)

@onready var _row: HBoxContainer = %Row
@onready var _icon: TextureRect = %Icon
@onready var _bar_frame: PanelContainer = %BarFrame
@onready var _bar: ProgressBar = %Bar
@onready var _amount_label: Label = %AmountLabel
@onready var _timer_label: Label = %TimerLabel

var _energy: int = 0
var _energy_max: int = 1
var _seconds_to_next: float = 0.0
## Only until the first energy block arrives -- the server sends
## `regen_seconds` with every one, so ENERGY_REGEN_SECONDS is never mirrored
## here, only guessed at for the frame before the first response.
var _regen_seconds: float = 900.0 # 60 * 15, 15minutes 
var _compact: bool = false


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


## Shrinks the bar for the HUD strip, where it sits beside three chips
## rather than alone in a header.
func set_compact(value: bool) -> void:
	_compact = value
	_apply_sizes()
	_restyle()


func _apply_sizes() -> void:
	if _bar == null:
		return
	var icon_px := 16 if _compact else 30
	_icon.custom_minimum_size = Vector2(icon_px, icon_px)
	_bar.custom_minimum_size = Vector2(48 if _compact else 96, 5 if _compact else 8)
	_amount_label.add_theme_font_size_override("font_size", 13 if _compact else 15)
	_timer_label.add_theme_font_size_override("font_size", 9 if _compact else 10)
	_row.add_theme_constant_override("separation", 5 if _compact else 8)


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


## "+1 in 14m 04s" in a header; just "14m 04s" in the HUD strip, where the
## bar beside it already says what is counting up and the sentence was wider
## than the rest of the strip put together.
func _refresh_timer() -> void:
	if _timer_label == null:
		return
	var seconds := int(ceil(_seconds_to_next))
	if not _compact:
		_timer_label.text = TimeFormat.next_energy_in(seconds, is_full())
	elif is_full():
		_timer_label.text = TranslationServer.translate("Full")
	else:
		_timer_label.text = TimeFormat.duration(seconds)


## Amber when the bar is nearly out, because that is the state that stops you
## playing -- the same "warn on the thing that blocks you" rule the Shop's
## bench counter and the Squad screen's unsaved marker use.
func _restyle() -> void:
	if _bar_frame == null:
		return
	var low: bool = float(_energy) / float(_energy_max) <= LOW_FRACTION
	var accent := ThemeManager.color("warning") if low else ThemeManager.color("energy")

	add_theme_stylebox_override("panel", MenuTile.pixel_frame(
		MenuTile.BASE_FILL.lerp(accent, CurrencyChip.FILL_MIX),
		accent,
		CurrencyChip.BORDER_WIDTH,
		true,
		Vector2(6, 2) if _compact else Vector2(10, 4)
	))

	# The bar sits in its own black frame rather than carrying a border on the
	# fill: ProgressBar draws the fill OVER the background style, so a border
	# there is covered wherever the bar is full.
	var frame := StyleBoxFlat.new()
	frame.anti_aliasing = false
	frame.set_corner_radius_all(0)
	frame.bg_color = BAR_OUTLINE
	frame.border_color = BAR_OUTLINE
	frame.set_border_width_all(1)
	frame.content_margin_left = 1.0
	frame.content_margin_right = 1.0
	frame.content_margin_top = 1.0
	frame.content_margin_bottom = 1.0
	_bar_frame.add_theme_stylebox_override("panel", frame)

	# Hard-edged like every other panel: a rounded, smoothed fill is the one
	# thing that reads as "not pixel art".
	var fill := StyleBoxFlat.new()
	fill.anti_aliasing = false
	fill.set_corner_radius_all(0)
	fill.bg_color = accent
	_bar.add_theme_stylebox_override("fill", fill)

	var track := StyleBoxFlat.new()
	track.anti_aliasing = false
	track.set_corner_radius_all(0)
	track.bg_color = Color(accent.r, accent.g, accent.b, 0.18)
	_bar.add_theme_stylebox_override("background", track)

	# The labels take the Theme's ordinary Label colour on purpose; the
	# low-energy signal lives in the bar and the border, where colour belongs.
