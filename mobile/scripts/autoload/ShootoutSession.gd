extends Node

## The daily shootout's hand-off, and the one place that talks to
## /shootout/daily.
##
## Same pattern as MatchSession and TournamentSession: a scene can't take
## arguments, so the hub leaves the state here before changing scene. Unlike
## a match, though, a shootout is not simulated in one call -- the player
## picks a corner at a time, so this holds a LIVE session and each kick is
## its own request.
##
## The server owns everything that decides the result. It never sends the
## seed while the shootout is live, because the seed reproduces every corner
## the bot has left; so there is nothing here to read ahead with, and nothing
## worth tampering with locally.

const SCREEN_SCENE := "res://scenes/Shootout.tscn"
const HUB_SCENE := "res://scenes/Minigames.tscn"

## Which ad buys a second attempt. Mirrors services/ads.track_caps().
const RETRY_TRACK := "shootout_retry"

## Whose kick it is next, as the backend reports it.
const NEXT_KICK := "kick"      # yours: pick a corner
const NEXT_KEEP := "keep"      # theirs: guess the dive

## The live shootout as the last response left it: score, kicks so far, whose
## turn, and once it is over the rewards.
var state: Dictionary = {}
var last_kick: Dictionary = {}
var return_scene: String = HUB_SCENE
## The hub found a shootout already under way. Its kick order is locked in,
## so the screen skips the picker and resumes it.
var resume: bool = false
## The kick order the player sent: squad indexes, first kick to last. Kept so
## an ad retry reopens the picker with it already filled in.
var takers: Array = []


func open(resume_live: bool = false) -> void:
	clear()
	resume = resume_live
	get_tree().change_scene_to_file(SCREEN_SCENE)


func clear() -> void:
	state = {}
	last_kick = {}
	return_scene = HUB_SCENE
	resume = false
	takers = []


func is_live() -> bool:
	return not state.is_empty() and not state.get("finished", false)


func is_finished() -> bool:
	return state.get("finished", false)


func won() -> bool:
	return state.get("won", false)


func my_turn() -> bool:
	return state.get("next", "") == NEXT_KICK


## Every kick so far, oldest first. The scoreboard reads it for its marks.
func kicks() -> Array:
	var value = state.get("kicks", [])
	return value if value is Array else []


## Who takes the next one, named -- the backend sends it because before the
## first kick there is no history to read it from.
func upcoming() -> Dictionary:
	var value = state.get("upcoming", {})
	return value if value is Dictionary else {}


func score() -> Array:
	var value = state.get("score", [0, 0])
	return value if value is Array else [0, 0]


## Your XI for the picker: {"players": [{idx, name, position, score}],
## "suggested": [idx, ...] best first}. {} when it could not be fetched.
func load_squad() -> Dictionary:
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/shootout/daily/takers")
	if not res.ok or not (res.data is Dictionary):
		push_error("shootout squad failed: %d %s" % [res.get("status", 0), res.get("data", {})])
		return {}
	return res.data


## Open today's shootout with the picked order, or resume one already in
## progress (whose order the server keeps). Returns the error message to
## show, or "" when it worked.
func start() -> String:
	var body := {}
	if not takers.is_empty():
		body["takers"] = takers
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_POST, "/shootout/daily/start", body)
	if not res.ok:
		# The status and body go to the log: the player gets a sentence, but a
		# 500 that only ever says "try again" is a bug nobody can diagnose.
		push_error("shootout start failed: %d %s" % [res.get("status", 0), res.get("data", {})])
		# 409 is the one refusal worth its own sentence: it is not a failure,
		# it is the daily allowance being spent.
		return (
			tr("Today's shootout is done. Watch an ad to try again, or come back tomorrow.")
			if res.status == 409
			else tr("Couldn't start the shootout -- try again.")
		)
	state = res.data
	last_kick = {}
	return ""


## One penalty. `side` is -1, 0 or 1; it is sent as your aim on your own kick
## and as your guess at the dive on theirs, which is what the backend expects
## -- sending the wrong one is refused there rather than quietly honoured.
func kick(side: int) -> String:
	var body := {"kick": int(state.get("kick_index", 0))}
	if my_turn():
		body["aim"] = side
	else:
		body["dive"] = side

	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST, "/shootout/daily/kick", body
	)
	if not res.ok:
		push_error("shootout kick failed: %d %s" % [res.get("status", 0), res.get("data", {})])
		return tr("That kick didn't go through -- try again.")

	last_kick = res.data.get("kick", {})
	state = res.data
	if is_finished():
		_apply_rewards(res.data)
	return ""


## Balances the settle moved, straight into the profile so the currency strip
## is right the moment the player leaves the screen.
func _apply_rewards(data: Dictionary) -> void:
	GameProfile.apply_currency_balances(
		data.get("credits_remaining"), data.get("bucks_remaining"), data.get("medals_remaining")
	)
