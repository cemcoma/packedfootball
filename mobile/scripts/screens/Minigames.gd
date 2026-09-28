extends Control

## Minigames hub: the once-a-day modes. Shootout is the only real one; the
## rest are declared but disabled, so the shape of what's coming is visible
## without pretending it exists -- same arrangement as TournamentHub.
##
## The hint under the title is where the daily-login framing is spelled out,
## since the screen is named after what these ARE rather than how often they
## come round.
##
## The Shootout tile's subtitle is the streak: which day of the cycle is next,
## what it pays, and how long is left to claim it. That all comes from
## GET /shootout/daily -- the day rollover is derived server-side, so nothing
## here has to know when noon in Istanbul is.

const MENU_TILE_SCENE := preload("res://scenes/components/MenuTile.tscn")

## Modes that don't exist yet. A disabled tile with a reason reads as a
## roadmap; a silent absence reads as a missing feature.
const COMING_SOON := [
	{"name": "Free Kicks", "hint": "Beat the wall and the keeper from range."},
	{"name": "Keepy-Uppy", "hint": "One touch at a time, for as long as you last."},
]

@onready var _hint_label: Label = %HintLabel
@onready var _shootout_button: MenuTile = %ShootoutTile
@onready var _coming_soon_box: VBoxContainer = %ComingSoonBox
@onready var _status_label: Label = %StatusLabel
@onready var _back_button: Button = %BackButton

var _daily: Dictionary = {}
## On the right end of the Shootout tile once today's go is lost and spent:
## an ad buys another. Only there while the tile itself is switched off.
var _retry_ad_button: Button


func _ready() -> void:
	_shootout_button.pressed.connect(_on_shootout_pressed)
	_back_button.pressed.connect(_on_back_pressed)

	_retry_ad_button = Button.new()
	_retry_ad_button.text = tr("Watch ad: +1 life")
	_retry_ad_button.custom_minimum_size = Vector2(0, 44)
	_retry_ad_button.add_theme_font_size_override("font_size", 12)
	_retry_ad_button.visible = false
	_retry_ad_button.pressed.connect(_on_retry_ad_pressed)
	_shootout_button.add_side_control(_retry_ad_button)
	# Global signal -- the shop listens to the same one, so the track is checked.
	AdManager.ad_reward_completed.connect(_on_ad_completed)

	_build_coming_soon()

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()

	_load_daily()


## The tiles restyle themselves; the Back button and the two labels sit
## straight on the background and would otherwise stay flat.
func _apply_theme_colors() -> void:
	MenuTile.style_button(_back_button, ThemeManager.color("surface_border"))
	MenuTile.style_button(_retry_ad_button, ThemeManager.color("bucks"), true, Vector2(10, 4))
	_hint_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	_status_label.add_theme_color_override("font_color", ThemeManager.color("warning"))


func _build_coming_soon() -> void:
	for entry in COMING_SOON:
		var tile: MenuTile = MENU_TILE_SCENE.instantiate()
		_coming_soon_box.add_child(tile)
		tile.title_text = entry["name"]
		tile.subtitle_text = tr("Coming soon. %s") % tr(entry["hint"])
		tile.accent_key = "surface_border"
		tile.set_tile_disabled(true)


func _load_daily() -> void:
	_shootout_button.subtitle_text = tr("Loading...")
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/shootout/daily")
	if not res.ok:
		_shootout_button.subtitle_text = tr("Couldn't reach the shootout -- try again.")
		_retry_ad_button.visible = false
		return

	_daily = res.data
	var can_play := bool(_daily.get("can_play", false))
	_shootout_button.subtitle_text = _subtitle_for(_daily)
	_shootout_button.set_tile_disabled(not can_play)
	# Set both ways: after an ad buys another go this reloads, and a muted
	# subtitle on a live tile would still read as "done for today".
	_shootout_button.set_subtitle_color(
		MenuTile.SUBTITLE_COLOR if can_play else ThemeManager.color("text_muted")
	)
	# The server's call: a loss, the last attempt spent, today's retry ad
	# not yet watched.
	_retry_ad_button.visible = not can_play and bool(_daily.get("retry_available", false))
	_retry_ad_button.disabled = false


## What the tile says about the streak. Three states: mid-shootout, ready to
## play, or done for today.
func _subtitle_for(daily: Dictionary) -> String:
	var day: int = int(daily.get("day", 1))
	var days: int = int(daily.get("cycle_days", 15))
	var prestige: int = int(daily.get("prestige", 0))
	var reward: Dictionary = daily.get("reward", {})

	if daily.get("in_progress", false):
		return tr("Shootout in progress -- pick up where you left off.")

	if not daily.get("can_play", false):
		return tr("Played today. Day %d of %d unlocks in %s.") % [
			day + 1, days, _countdown(int(daily.get("seconds_until_reset", 0)))
		]

	var line := tr("Day %d of %d") % [day, days]
	if prestige > 0:
		line += tr(" · Prestige %d") % prestige
	line += tr(" · %s to win, %s to play") % [
		CurrencyDisplay.format_amount(int(reward.get("win", 0))),
		CurrencyDisplay.format_amount(int(reward.get("loss", 0))),
	]
	if day >= days:
		line += tr(" · Finish the cycle for a bonus")
	return line


## Hours and minutes, never a timestamp -- the backend hands over seconds so
## the client never has to parse a date or trust the device clock.
func _countdown(seconds: int) -> String:
	if seconds <= 0:
		return tr("a moment")
	var hours := seconds / 3600
	var minutes := (seconds % 3600) / 60
	if hours > 0:
		return tr("%dh %dm") % [hours, minutes]
	return tr("%dm") % max(1, minutes)


func _on_shootout_pressed() -> void:
	if not _daily.get("can_play", false):
		_status_label.text = tr("You've played today's shootout. Come back after the reset.")
		return
	# A fresh shootout opens on the kick-order picker; one already under way
	# resumes straight onto the pitch, since its order is already locked in.
	ShootoutSession.open(bool(_daily.get("in_progress", false)))


func _on_retry_ad_pressed() -> void:
	_retry_ad_button.disabled = true
	_set_status("", false)
	if not AdManager.show_ad_for_track(ShootoutSession.RETRY_TRACK):
		_set_status(tr("Ad not ready -- try again in a moment."), false)
		_retry_ad_button.disabled = false


## A granted ad has already moved the server's attempt count, so reloading
## the streak is what switches the tile back on.
func _on_ad_completed(track: String, status: String) -> void:
	if track != ShootoutSession.RETRY_TRACK:
		return
	match status:
		"granted":
			_set_status(tr("You've got another life -- tap Shootout to play."), true)
			_load_daily()
		"pending":
			_set_status(tr("Reward is on its way -- it lands within a minute."), false)
			_retry_ad_button.disabled = false
		_:
			_set_status(tr("Ad was closed early or failed to verify."), false)
			_retry_ad_button.disabled = false


func _set_status(text: String, good: bool) -> void:
	_status_label.text = text
	_status_label.add_theme_color_override(
		"font_color", ThemeManager.color("positive" if good else "warning")
	)


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Play.tscn")
