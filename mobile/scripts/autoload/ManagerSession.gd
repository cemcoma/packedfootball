extends Node

## Which manager the Manager screen (ManagerView.tscn) should show, and
## where Back goes afterwards. The same hand-off pattern as PlayerSession
## and PackSession: a scene can't take arguments, so whoever navigates
## there leaves what it needs here first.
##
## Two ways onto that screen:
##   - a leaderboard row: `uid` is set and the screen fetches
##     GET /manager/{uid};
##   - "View Team" on PreMatch.tscn: `uid` is "" and the screen reads
##     `match_team`'s side straight out of MatchSession, which already holds
##     both rosters, names and records from the match response.

const DEFAULT_RETURN_SCENE := "res://scenes/Leaderboard.tscn"

var uid: String = ""
var match_team: int = 0  # MatchSession.TEAM_*, read when uid is ""
var return_scene: String = DEFAULT_RETURN_SCENE


## Point the Manager screen at `manager_uid`, coming back to `back_to`.
func open(manager_uid: String, back_to: String) -> void:
	uid = manager_uid
	return_scene = back_to
	get_tree().change_scene_to_file("res://scenes/ManagerView.tscn")


## Show one side of the current match instead (no fetch), coming back to `back_to`.
func open_match_team(team: int, back_to: String) -> void:
	match_team = team
	open("", back_to)


func clear() -> void:
	uid = ""
	match_team = 0
	return_scene = DEFAULT_RETURN_SCENE
