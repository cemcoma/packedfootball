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
## Tournament is a stub for now (Tournament.tscn) -- 1-day, 10-match
## brackets across 4 skill categories (promotion by winning), not built yet.

@onready var _status_label: Label = %StatusLabel
@onready var _quick_match_button: Button = %QuickMatchButton
@onready var _tournament_button: Button = %TournamentButton
@onready var _back_button: Button = %BackButton


func _ready() -> void:
	_quick_match_button.pressed.connect(_on_quick_match_pressed)
	_tournament_button.pressed.connect(_on_tournament_pressed)
	_back_button.pressed.connect(_on_back_pressed)


func _on_quick_match_pressed() -> void:
	_quick_match_button.disabled = true
	_tournament_button.disabled = true
	_status_label.text = "Finding an opponent..."

	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_POST, "/match/quick")

	if not res.ok:
		_status_label.text = "Could not start a match -- try again."
		_quick_match_button.disabled = false
		_tournament_button.disabled = false
		return

	MatchSession.set_from_match_response(res.data)
	if not MatchSession.has_pending():
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
	get_tree().change_scene_to_file("res://scenes/Match.tscn")


static func _int(data: Dictionary, key: String, default: int) -> int:
	var value = data.get(key)
	return value if typeof(value) in [TYPE_INT, TYPE_FLOAT] else default


func _on_tournament_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Tournament.tscn")


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")
