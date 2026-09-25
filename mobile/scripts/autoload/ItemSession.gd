extends Node

## Which item is waiting to be socketed -- the same "shared autoload
## blackboard" PlayerSession.gd is, for the one flow that spans three screens:
## pick an item on Items, pick a card on Inventory, confirm on Player Detail.
##
## Only the ID is held, never the item Dictionary: GameProfile.all_items is
## the live copy, and a cached entry would go stale the moment the item was
## socketed or scrapped. item() resolves against that pool on every call and
## returns {} once the id stops existing -- which is exactly what happens
## after a successful equip, and is how Player Detail knows to drop back to
## its ordinary buttons.

var item_id: String = ""

## Where the flow returns to once the item is placed (or the pick is
## abandoned). Items is the only entry point today, but the same flow would
## work straight off a pack reveal.
var return_scene: String = "res://scenes/Items.tscn"


func open(id: String, back_to: String = "res://scenes/Items.tscn") -> void:
	item_id = id
	return_scene = back_to


## The live item, or {} if nothing is pending / it is no longer in the pool.
func item() -> Dictionary:
	if item_id == "":
		return {}
	for entry in GameProfile.all_items:
		if entry is Dictionary and ItemData.item_id(entry) == item_id:
			return entry
	return {}


func is_pending() -> bool:
	return not item().is_empty()


func clear() -> void:
	item_id = ""
