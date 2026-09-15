extends Node

## Which card the Player Details / Customize Player screens are looking at --
## the same "shared autoload blackboard" PackSession.gd and MatchSession.gd
## already are, since change_scene_to_file() can't carry an argument.
##
## Only the ID is held, never the PlayerCard itself: GameProfile.all_cards is
## the live copy, and a card object cached here would go stale the moment it
## was restyled or released. card() resolves against that cache on every
## call, and returns null once the id stops existing -- which is exactly what
## happens after a release, and is how PlayerDetail knows to bounce back to
## the inventory instead of showing a card that's gone.

var player_id: String = ""

## Where this card's screens send you "back" to. Player Details is reachable
## from the inventory today and nowhere else, but it's a natural destination
## for a pack reveal or the squad screen too, and none of those should have
## to leave you somewhere you didn't come from.
var return_scene: String = "res://scenes/Inventory.tscn"


func open(id: String, back_to: String = "res://scenes/Inventory.tscn") -> void:
	player_id = id
	return_scene = back_to


## The live card, or null if nothing is selected / it no longer exists.
func card() -> PlayerCard:
	if player_id == "" or not GameProfile.all_cards.has(player_id):
		return null
	return GameProfile.all_cards[player_id]


func clear() -> void:
	player_id = ""
