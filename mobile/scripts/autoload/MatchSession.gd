extends Node

## Carries one just-finished real match's result from wherever it was
## triggered (today: Play.gd's Quick Match button) to MatchPlayback.gd,
## the same "shared autoload blackboard" idea GameProfile.gd already is for
## squad state -- Godot has no built-in way to pass data between scenes via
## change_scene_to_file(), so something has to hold it in between.
##
## MatchPlayback.gd checks has_pending() on _ready(): true means play THIS
## match (decoded from a real /match/quick or /match/simulate response);
## false means fall back to the bundled local test replay, same as before
## this existed -- so the offline demo path (no backend, no signed-in
## account needed) keeps working unchanged.

var _replay: Dictionary = {}
var _roster: Dictionary = {}
var score: Array = [0, 0]
var opponent_display_name: String = ""
var opponent_is_bot: bool = false
var credits_earned: int = 0


func has_pending() -> bool:
	return not _replay.is_empty()


func replay() -> Dictionary:
	return _replay


func roster() -> Dictionary:
	return _roster


## `data` is a /match/quick (or /match/simulate) response body verbatim --
## must have at least "replay" (base64 string) and "roster" (Array of
## player-field Dictionaries, 22 entries, caller's 11 then opponent's 11 --
## see backend/main.py's _run_match). Silently leaves has_pending() false
## if "replay" is missing/malformed, so a caller that forgets to check
## res.ok first just falls back to the demo replay instead of crashing.
func set_from_match_response(data: Dictionary) -> void:
	var replay_b64 = data.get("replay")
	if not (replay_b64 is String) or replay_b64 == "":
		return
	var bytes := Marshalls.base64_to_raw(replay_b64)
	var decoded := ReplayReader.load_from_bytes(bytes)
	if decoded.is_empty():
		return

	_replay = decoded

	var name_raw = data.get("opponent_display_name")
	opponent_display_name = name_raw if name_raw is String and name_raw != "" else "Opponent"

	var players_raw = data.get("roster")
	_roster = {
		"home_name": GameProfile.display_name,
		"away_name": opponent_display_name,
		"players": players_raw if players_raw is Array else [],
	}

	var score_raw = data.get("score")
	score = score_raw if score_raw is Array and score_raw.size() == 2 else [0, 0]

	opponent_is_bot = bool(data.get("opponent_is_bot"))

	var credits_raw = data.get("credits_earned")
	credits_earned = credits_raw if typeof(credits_raw) in [TYPE_INT, TYPE_FLOAT] else 0


## Called once MatchPlayback has consumed a pending session (or the player
## backs out without starting it) -- so navigating to Match.tscn a second
## time (e.g. the bundled "test replay" path from Menu, if that's still
## reachable) doesn't replay a stale result.
func clear() -> void:
	_replay = {}
	_roster = {}
	score = [0, 0]
	opponent_display_name = ""
	opponent_is_bot = false
	credits_earned = 0
