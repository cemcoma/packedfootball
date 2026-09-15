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
##
## Three screens read this now -- MatchPlayback, MatchResult and MatchStats --
## so clear() happens on the way back to the Menu, not on first read. The
## per-match aggregation lives here rather than in any one screen, since two
## of them need the same numbers.

## Where the post-match screens go when the player is done. Quick Match
## leaves it alone; a tournament match sets it so Continue returns to the
## tournament instead of dumping the player on the Menu mid-run.
##
## Same indirection PlayerSession.return_scene already uses. NOTE for
## callers: clear() resets this, and both exit paths call clear() BEFORE
## navigating -- so read it into a local first.
const DEFAULT_RETURN_SCENE := "res://scenes/Menu.tscn"

const TEAM_HOME := 0
const TEAM_AWAY := 1
const PLAYERS_PER_TEAM := 11

var _replay: Dictionary = {}
var _roster: Dictionary = {}
var score: Array = [0, 0]
var opponent_display_name: String = ""
var opponent_is_bot: bool = false
var credits_earned: int = 0
## THIS match's per-player numbers, 22 entries, same index order as the
## roster (caller's 11 then opponent's 11). Distinct from each card's
## `statistics`, which are career totals. Empty for the bundled demo replay
## and for any response from a backend older than this field.
var player_match_stats: Array = []

var return_scene: String = DEFAULT_RETURN_SCENE
var tournament: Dictionary = {}


func has_pending() -> bool:
	return not _replay.is_empty()


func replay() -> Dictionary:
	return _replay


func roster() -> Dictionary:
	return _roster


func has_match_stats() -> bool:
	return player_match_stats.size() == PLAYERS_PER_TEAM * 2


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

	# Both sides' shirts, as the raw strings the backend passed through from
	# each profile (see backend/main.py's _run_match). Kept as strings and
	# handed to whoever draws them -- MatchPlayback parses them with
	# KitDesign, which turns anything missing or unparseable into the
	# default kit, so an older backend that doesn't send "kits" at all just
	# means both sides wear the default.
	var kits_raw = data.get("kits")
	var kits: Array = kits_raw if kits_raw is Array else []

	var players_raw = data.get("roster")
	_roster = {
		"home_name": GameProfile.display_name,
		"away_name": opponent_display_name,
		"home_kit": kits[0] if kits.size() > 0 and kits[0] is String else "",
		"away_kit": kits[1] if kits.size() > 1 and kits[1] is String else "",
		"players": players_raw if players_raw is Array else [],
	}

	var score_raw = data.get("score")
	score = score_raw if score_raw is Array and score_raw.size() == 2 else [0, 0]

	opponent_is_bot = bool(data.get("opponent_is_bot"))

	var credits_raw = data.get("credits_earned")
	credits_earned = credits_raw if typeof(credits_raw) in [TYPE_INT, TYPE_FLOAT] else 0

	var stats_raw = data.get("player_match_stats")
	player_match_stats = stats_raw if stats_raw is Array else []

	var tournament_raw = data.get("tournament")
	tournament = tournament_raw if tournament_raw is Dictionary else {}


# ------------------------------------------------------------- lookups

## Roster field dictionary for a global player index (0-21), or {}.
func player_fields(index: int) -> Dictionary:
	var players: Array = _roster.get("players", [])
	if index < 0 or index >= players.size():
		return {}
	var entry = players[index]
	return entry if entry is Dictionary else {}


func player_name(index: int) -> String:
	var fields := player_fields(index)
	var lname = fields.get("lname")
	if lname is String and lname != "":
		return lname
	var fname = fields.get("fname")
	return fname if fname is String else "Player %d" % index


## THIS match's stats for one player, or {} when the backend didn't send any.
func match_stats_for(index: int) -> Dictionary:
	if not has_match_stats() or index < 0 or index >= player_match_stats.size():
		return {}
	var entry = player_match_stats[index]
	return entry if entry is Dictionary else {}


func team_indices(team: int) -> Array:
	var base: int = 0 if team == TEAM_HOME else PLAYERS_PER_TEAM
	var out: Array = []
	for i in range(PLAYERS_PER_TEAM):
		out.append(base + i)
	return out


# ---------------------------------------------------------- aggregation

## Whole-team totals for one side. Keys mirror the per-player stat names,
## plus "avg_rating" and "pass_accuracy" (0-100).
##
## "shots_on_target" is summed from what the engine tracked per player,
## which is exactly goals + the opposing keeper's saves -- a shot counts as
## on target when it actually reached the frame.
func team_summary(team: int) -> Dictionary:
	var totals := {
		"goals": 0, "assists": 0, "shots": 0, "shots_on_target": 0,
		"passes": 0, "passes_completed": 0, "tackles": 0, "tackles_won": 0,
		"saves": 0,
	}
	var rating_sum := 0.0
	var rated := 0

	for index in team_indices(team):
		var stats := match_stats_for(index)
		if stats.is_empty():
			continue
		for key in totals.keys():
			var value = stats.get(key, 0)
			if typeof(value) in [TYPE_INT, TYPE_FLOAT]:
				totals[key] = int(totals[key]) + int(value)
		var rating = stats.get("rating")
		if typeof(rating) in [TYPE_INT, TYPE_FLOAT]:
			rating_sum += float(rating)
			rated += 1

	totals["avg_rating"] = (rating_sum / rated) if rated > 0 else 0.0
	var passes: int = totals["passes"]
	totals["pass_accuracy"] = (100.0 * float(totals["passes_completed"]) / float(passes)) if passes > 0 else 0.0
	return totals


## Everyone on `team` who scored, as [{"name", "minute", "goals"}], ordered
## by when the first goal went in.
##
## Minutes come from the replay's GOAL events rather than the stat counters,
## since only the replay knows WHEN. The engine's clock runs at two ticks per
## second (see gameEngine.FRAMES_PER_CLOCK_SECOND).
func scorers(team: int) -> Array:
	var events: Array = _replay.get("events", [])
	var order: Array = []
	var by_player: Dictionary = {}
	# Goal minutes are shown on the same clock the playback screen shows, so
	# a 90th-minute winner doesn't read as 92' here just because the first
	# half ran long. See ReplayReader.display_tick.
	var halftime := ReplayReader.halftime_tick(_replay)

	for event in events:
		if not (event is Dictionary):
			continue
		if int(event.get("type", -1)) != ReplayReader.ActionType.GOAL:
			continue
		var idx: int = int(event.get("player_idx", -1))
		if idx < 0:
			continue  # own goal / unattributed
		var scorer_team: int = TEAM_HOME if idx < PLAYERS_PER_TEAM else TEAM_AWAY
		if scorer_team != team:
			continue

		var shown := ReplayReader.display_tick(float(event.get("tick", 0)), halftime)
		var minute: int = int(shown / 2.0 / 60.0) + 1
		if by_player.has(idx):
			by_player[idx]["goals"] += 1
			by_player[idx]["minutes"].append(minute)
		else:
			by_player[idx] = {"name": player_name(idx), "goals": 1, "minutes": [minute]}
			order.append(idx)

	var out: Array = []
	for idx in order:
		out.append(by_player[idx])
	return out


## Called once the player is genuinely done with this result (heading back
## to the Menu), NOT on first read -- MatchResult and MatchStats both read
## it, and MatchStats is reached from MatchResult.
func clear() -> void:
	_replay = {}
	_roster = {}
	score = [0, 0]
	opponent_display_name = ""
	opponent_is_bot = false
	credits_earned = 0
	player_match_stats = []
	tournament = {}
	# Back to the default, or a tournament return would leak into the next
	# Quick Match and send it somewhere it never came from.
	return_scene = DEFAULT_RETURN_SCENE
