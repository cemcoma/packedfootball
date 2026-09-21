extends CanvasLayer

## The balances strip, top right of every screen -- credits, cash, medals and
## the energy bar.
##
## An autoload rather than a node in each scene, so a new screen can't forget
## it and a scene change doesn't rebuild it.

## Fired when the strip appears or disappears, so every SafeMargin on screen
## re-reserves.
signal reserve_changed

const BAR_SCENE := preload("res://scenes/components/CurrencyBar.tscn")

## Above the screens, below AdManager's grant blocker (layer 128) -- that one
## has to stay the thing nothing draws over.
const LAYER := 64

## Screens with no balances to show: no profile loaded yet, or a live match.
const HIDDEN_SCENES := ["Splash", "Auth", "Match"]

## What the strip costs the screen below it. A measured height would be read
## before the bar has been laid out, and a header that jumps once the real
## number arrives is worse than a fixed one.
const BAR_HEIGHT := 34
const GAP := 8

## The screen-edge gap, matching SafeMargin's own BASE_H/BASE_V so the strip
## lines up with the header underneath it.
const MARGIN_H := 16
const MARGIN_V := 12

var _anchor: Control = null
var _bar: CurrencyBar = null
var _shown: bool = false


func _ready() -> void:
	layer = LAYER

	_anchor = Control.new()
	_anchor.set_anchors_preset(Control.PRESET_FULL_RECT)
	_anchor.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_anchor.visible = false
	add_child(_anchor)

	_bar = BAR_SCENE.instantiate()
	_anchor.add_child(_bar)
	# Pinned to the top right corner and grown leftward, so a balance going
	# from 999 to 1,000 pushes the strip left instead of off the screen.
	_bar.anchor_left = 1.0
	_bar.anchor_right = 1.0
	_bar.anchor_top = 0.0
	_bar.anchor_bottom = 0.0
	_bar.minimum_size_changed.connect(_place)

	get_tree().get_root().size_changed.connect(_place)
	_refresh_visibility()


## The strip follows the scene, and nothing reports a scene change -- one
## pointer comparison a frame is cheaper than hooking every scene's _ready.
func _process(_delta: float) -> void:
	if _shown != _should_show():
		_refresh_visibility()


## What SafeMargin keeps clear at the top. Computed from the current scene
## rather than cached, because a screen's SafeMargin runs its _ready before
## this node's next _process tick.
func reserved_height() -> int:
	return BAR_HEIGHT + GAP if _should_show() else 0


func _should_show() -> bool:
	if not GameProfile.is_loaded:
		return false
	var scene := get_tree().current_scene
	return scene != null and not (String(scene.name) in HIDDEN_SCENES)


func _refresh_visibility() -> void:
	_shown = _should_show()
	_anchor.visible = _shown
	if _shown:
		_bar.refresh()
		_place()
		# load_all() fetches the bar at sign-in; this only covers a miss.
		if GameProfile.energy.is_empty():
			_fetch_energy()
	reserve_changed.emit()


func _fetch_energy() -> void:
	await GameProfile.refresh_energy()


func _place() -> void:
	if _bar == null:
		return
	var inset := ScreenInsets.of(get_viewport())
	var right: float = MARGIN_H + inset["right"]
	var top: float = MARGIN_V + inset["top"]
	var bar_size := _bar.get_combined_minimum_size()
	_bar.offset_left = -right - bar_size.x
	_bar.offset_right = -right
	_bar.offset_top = top
	_bar.offset_bottom = top + bar_size.y


## The live energy reading, for screens that gate on it. Ticks whether or not
## the strip is on screen, so a hidden HUD still reports the right number.
func energy() -> int:
	return _bar.energy() if _bar != null else 0
