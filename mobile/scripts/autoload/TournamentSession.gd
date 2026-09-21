extends Node

## Which tournament format the tournament screen should open, and the few
## sentences that differ between them.
##
## The same hand-off pattern as ManagerSession and PlayerSession: a scene
## can't take arguments, so the hub leaves the choice here before changing
## scene. It survives the trip out to a match and back, which is what makes
## MatchSession.return_scene land on the format the player was actually
## playing rather than always on the daily one.
##
## ONE SCREEN, TWO LEAGUES. The backend's daily and weekly leagues return
## the same payload shape from the same handlers (see its
## routers/tournaments.py), so TournamentScreen.tscn renders both. Only
## three things genuinely differ: the URL prefix, the claim type, and the
## handful of strings that say "today" where the other says "this week".
##
## What is deliberately NOT here: how many matches, how big a group, how
## many go up or down, what a position pays. All of that arrives in the
## payload, so tuning the backend's config never needs a client release.
##
## Strings below are raw English keys, translated where they are DISPLAYED
## -- a `const` can't call `tr()`, the same rule PlayerCard's ATTR_ROWS
## follows.

const SCREEN_SCENE := "res://scenes/TournamentScreen.tscn"
const HUB_SCENE := "res://scenes/Tournament.tscn"

const DAILY := "daily"
const WEEKLY := "weekly"

const FORMATS := {
	DAILY: {
		"endpoint": "/tournament",
		"claim_type": "tournament_full_day",
		"loading": "Loading today's tournament...",
		"joining": "Entering today's tournament...",
		"join": "Enter today's tournament",
		"closed_window": "Entries are closed near the end of the day -- the next tournament starts in %s.",
		"closed_now": "Entries are closed for today -- try again after the reset.",
		"all_played": "You're done for today. Come back when the day resets.",
		"all_played_short": "You've played all your matches for today.",
		"last_result": "Yesterday: finished %d%s\n\n%s%s",
		"claim_last": "Claim yesterday's full-day bonus",
	},
	WEEKLY: {
		"endpoint": "/tournament/weekly",
		"claim_type": "tournament_full_week",
		"loading": "Loading this week's tournament...",
		"joining": "Entering this week's tournament...",
		"join": "Enter this week's tournament",
		"closed_window": "Entries are closed near the end of the week -- the next tournament starts in %s.",
		"closed_now": "Entries are closed for this week -- try again after the reset.",
		"all_played": "You're done for this week. Come back when the week resets.",
		"all_played_short": "You've played all your matches for this week.",
		"last_result": "Last week: finished %d%s\n\n%s%s",
		"claim_last": "Claim last week's full-week bonus",
	},
}

var format: String = DAILY


## Open the tournament screen on `which` format. An unknown name falls back
## to daily rather than opening a screen that would call a URL that doesn't
## exist.
func open(which: String) -> void:
	format = which if FORMATS.has(which) else DAILY
	get_tree().change_scene_to_file(SCREEN_SCENE)


## One of the format's strings, still untranslated -- the caller wraps it.
func text(key: String) -> String:
	var table: Dictionary = FORMATS.get(format, FORMATS[DAILY])
	return str(table.get(key, ""))


## The full URL for one of this format's endpoints: endpoint("/today") is
## "/tournament/today" or "/tournament/weekly/today".
func endpoint(suffix: String) -> String:
	return text("endpoint") + suffix


## What POST /claim's `type` has to be for this format's play-everything
## reward.
func claim_type() -> String:
	return text("claim_type")
