extends Node

## Carries one just-opened pack's cards from Shop.gd to PackReveal.gd --
## the same "shared autoload blackboard" idea MatchSession.gd already is
## for a just-played match, since change_scene_to_file() can't carry data
## itself. Simpler than MatchSession needs to be: Shop.gd already builds
## the typed Array[PlayerCard] locally (for GameProfile.add_purchased_cards),
## so this just holds that same array directly -- no raw-dict/base64
## decoding step the way replay bytes need.

var _cards: Array = []  # PlayerCard
var pack_name: String = ""
## The pack art PackReveal.gd shakes open -- the same texture the Shop tile
## showed, so the reveal opens the pack the player actually tapped.
var pack_texture: Texture2D = null


func has_pending() -> bool:
	return not _cards.is_empty()


func set_pending(name: String, cards: Array, texture: Texture2D = null) -> void:
	pack_name = name
	_cards = cards
	pack_texture = texture


func cards() -> Array:
	return _cards


## Called once PackReveal.gd has consumed a pending session -- so
## navigating back there directly (with nothing pending) falls back
## gracefully instead of replaying a stale pack.
func clear() -> void:
	pack_name = ""
	_cards = []
	pack_texture = null
