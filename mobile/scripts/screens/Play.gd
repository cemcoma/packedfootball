extends Control

## Play hub: pick a match mode. Sits between Menu and the actual match --
## Menu's own "Play Match" button used to go straight to Match.tscn (always
## the bundled local demo replay); now it lands here first.
##
## Quick Match calls the backend's new POST /match/quick, which always
## finds *someone* to play (a real random signed-up user if one's around,
## otherwise a freshly-rolled bot -- see backend/main.py's
## _pick_opponent_profile) for a small flat credit reward, then hands the
## result to the MatchSession autoload before navigating to the real
## playback scene (MatchSession.gd's own docstring explains why an
## autoload is how that handoff works, since change_scene_to_file() can't
## carry data itself).
##
## The whole /match/quick call is one request-response round trip -- the
## backend picks an opponent AND simulates the match AND persists the
## result before it ever replies -- so "Finding an opponent..." ->
## "Simulating match..." below isn't the server reporting real progress,
## it's a scripted status narrative shown while that one request is still
## in flight, so the wait doesn't read as a stuck/frozen button.
##
## Tournament leads to the tournament hub (Tournament.tscn), which offers the
## daily league -- ten matches a day in a group of six, drawn from your own
## tier, with promotion and relegation settled overnight.
##
## Both modes cost energy now (see backend config's QUICK_MATCH_ENERGY_COST),
## which is why the failure branch below has to tell 402 apart from everything
## else: "try again" is the one piece of advice that cannot work when the bar
## is empty.

@onready var _status_label: Label = %StatusLabel
@onready var _quick_match_button: Button = %QuickMatchButton
@onready var _tournament_button: Button = %TournamentButton
@onready var _back_button: Button = %BackButton

@onready var _quick_match_hint: Label = %QuickMatchHint
@onready var _tournament_hint: Label = %TournamentHint

@onready var _energy_bar: EnergyBar = %EnergyBar
@onready var _matchmaking_popup: Control = %MatchmakingPopup

var _matchmaking_active: bool = false


func _ready() -> void:
	_quick_match_button.pressed.connect(_on_quick_match_pressed)
	_tournament_button.pressed.connect(_on_tournament_pressed)
	_back_button.pressed.connect(_on_back_pressed)

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()
	_refresh_energy()


func _refresh_energy() -> void:
	_energy_bar.set_energy(GameProfile.energy)
	if GameProfile.energy.is_empty():
		await GameProfile.refresh_energy()
		_energy_bar.set_energy(GameProfile.energy)


## The two hints sit straight on the screen background with no panel behind
## them, so the Theme's Label color doesn't reach them (they carry their own
## override) -- on light mode their pale grey was invisible. See
## ThemeManager's note on text_hint.
func _apply_theme_colors() -> void:
	var hint := ThemeManager.color("text_hint")
	_quick_match_hint.add_theme_color_override("font_color", hint)
	_tournament_hint.add_theme_color_override("font_color", hint)


func _show_matchmaking_popup(status: String) -> void:
	_matchmaking_active = true
	_matchmaking_popup.set_status(status)
	_matchmaking_popup.visible = true


func _set_matchmaking_status(status: String) -> void:
	if not _matchmaking_active:
		return  # the request already finished (or failed) before this fired
	_matchmaking_popup.set_status(status)


func _hide_matchmaking_popup() -> void:
	_matchmaking_active = false
	_matchmaking_popup.visible = false


func _on_quick_match_pressed() -> void:
	_quick_match_button.disabled = true
	_tournament_button.disabled = true
	_status_label.text = ""
	_show_matchmaking_popup("Finding an opponent...")

	# Not awaited -- fires on its own while the request below is in flight,
	# purely to move the status text along; see class docstring.
	get_tree().create_timer(0.6).timeout.connect(_on_matchmaking_midpoint)

	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_POST, "/match/quick")

	if not res.ok:
		_hide_matchmaking_popup()
		_status_label.text = ( # 402 is "out of energy"
			"You're out of energy -- it refills over time, or top up in the Shop."
			if res.status == 402
			else "Could not start a match -- try again."
		)
		_quick_match_button.disabled = false
		_tournament_button.disabled = false
		return

	GameProfile.apply_energy(res.data.get("energy"))
	_energy_bar.set_energy(GameProfile.energy)

	MatchSession.set_from_match_response(res.data)
	if not MatchSession.has_pending():
		_hide_matchmaking_popup()
		_status_label.text = "Match finished, but the replay couldn't be loaded -- try again."
		_quick_match_button.disabled = false
		_tournament_button.disabled = false
		return

	# .get(key, default) only falls back to `default` when the key is
	# entirely absent -- a present-but-null value comes back as null
	# regardless, and null can't go into a statically-typed int var (same
	# concern PackData.gd's own _int() helper guards against). Updated here
	# (rather than waiting for a future full GameProfile reload) so Profile
	# screen reflects this match immediately.
	GameProfile.credits = _int(res.data, "credits_remaining", GameProfile.credits)
	GameProfile.wins = _int(res.data, "wins", GameProfile.wins)
	GameProfile.losses = _int(res.data, "losses", GameProfile.losses)
	GameProfile.draws = _int(res.data, "draws", GameProfile.draws)

	_set_matchmaking_status("Match found!")
	await get_tree().create_timer(0.4).timeout
	_hide_matchmaking_popup()
	get_tree().change_scene_to_file("res://scenes/Match.tscn")


func _on_matchmaking_midpoint() -> void:
	_set_matchmaking_status("Simulating match...")


static func _int(data: Dictionary, key: String, default: int) -> int:
	var value = data.get(key)
	return value if typeof(value) in [TYPE_INT, TYPE_FLOAT] else default


func _on_tournament_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Tournament.tscn")


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")
