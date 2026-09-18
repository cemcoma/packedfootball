extends Node

## Which manager the Manager screen (ManagerView.tscn) should show, and
## where Back goes afterwards. The same hand-off pattern as PlayerSession
## and PackSession: a scene can't take arguments, so whoever navigates
## there leaves what it needs here first.
##
## Two ways onto that screen:
##   - a leaderboard row: `uid` is set and the screen fetches
##     GET /manager/{uid};
##   - "View Opponent" before a match: `uid` is "" and the screen reads
##     the away side straight out of MatchSession, which already holds the
##     opponent's roster, name and record from the match response.

const DEFAULT_RETURN_SCENE := "res://scenes/Leaderboard.tscn"

var uid: String = ""
var return_scene: String = DEFAULT_RETURN_SCENE


## Point the Manager screen at `manager_uid`, coming back to `back_to`.
func open(manager_uid: String, back_to: String) -> void:
	uid = manager_uid
	return_scene = back_to
	get_tree().change_scene_to_file("res://scenes/ManagerView.tscn")


## Show the current match's opponent instead (no fetch), coming back to `back_to`.
func open_match_opponent(back_to: String) -> void:
	open("", back_to)


func clear() -> void:
	uid = ""
	return_scene = DEFAULT_RETURN_SCENE
