extends Node

## Higher-level profile/roster/inventory operations on top of Firestore.gd --
## GDScript counterpart to packedfootball/game_state.py's GameState class.
##
## Also the single LIVE model of the signed-in user's squad: `formation` and
## `slot_assignment` are the in-progress lineup, shared by every scene that
## touches it (Team scene edits them directly; other scenes can just read
## them), the same way FirebaseAuth.uid is one shared global rather than
## something each scene fetches for itself. This is deliberately fetched
## ONCE -- see load_all() -- and cached here for the rest of the session,
## rather than every scene re-hitting Firestore on every visit.
##
## Schema (see game_state.py's own module docstring -- unchanged here):
##   users/{uid}                -> {..., roster_player_ids: [id, ...], formation}
##   users/{uid}/inventory/{id} -> {player_id} pointer, one per benched card
##   players/{player_id}        -> the actual card fields
##
## "formation" is a new field this Team scene introduces (packedfootball's
## Python side doesn't read or write it yet) -- a plain string, one of
## Formations.FORMATION_NAMES, defaulting to DEFAULT_FORMATION when absent
## so older profile documents keep working unchanged.

const DEFAULT_FORMATION := "4-4-2"

var is_loaded: bool = false

# Profile fields (mirrors game_state.py's load_or_create_profile shape).
var display_name: String = ""
var credits: int = 0
var wins: int = 0
var losses: int = 0
var draws: int = 0
var elo: int = 0
var campaign_level: int = 0

# Squad state -- the live, possibly-unsaved lineup.
var formation: String = DEFAULT_FORMATION
var slot_assignment: Array = []  # player_ids, "" where empty, index == formation slot index
var all_cards: Dictionary = {}  # player_id -> PlayerCard, every owned card (roster + bench)

# Snapshot of what's actually saved in Firestore, refreshed by load_all() and
# by a successful save_team() -- comparing against the live fields above is
# how is_dirty() tells the Team scene "you have unsaved changes".
var saved_formation: String = DEFAULT_FORMATION
var saved_slot_assignment: Array = []


func is_dirty() -> bool:
	return formation != saved_formation or slot_assignment != saved_slot_assignment


func _user_doc_path() -> String:
	return "users/%s" % FirebaseAuth.uid


## Fetches everything needed to populate the cache above in one go. Called
## once right after sign-in (see Auth.gd) so every later scene reads
## instantly from memory instead of re-hitting Firestore every time it opens.
func load_all() -> void:
	var doc = await Firestore.get_document(_user_doc_path())
	var ids: Array = []
	if doc != null:
		display_name = doc.get("display_name", "")
		credits = doc.get("credits", 0)
		wins = doc.get("wins", 0)
		losses = doc.get("losses", 0)
		draws = doc.get("draws", 0)
		elo = doc.get("elo", 0)
		campaign_level = doc.get("campaign_level", 0)
		formation = doc.get("formation", DEFAULT_FORMATION)
		ids = doc.get("roster_player_ids", [])

	var slots: Array = Formations.get_formation(formation)
	slot_assignment.resize(slots.size())
	slot_assignment.fill("")

	all_cards.clear()
	var roster_cards: Array = await _load_cards(ids)
	for i in range(mini(roster_cards.size(), slots.size())):
		var card: PlayerCard = roster_cards[i]
		all_cards[card.player_id] = card
		slot_assignment[i] = card.player_id

	var inventory: Array = await load_inventory()
	for card in inventory:
		var typed_card: PlayerCard = card
		all_cards[typed_card.player_id] = typed_card

	saved_formation = formation
	saved_slot_assignment = slot_assignment.duplicate()
	is_loaded = true


## Returns benched cards, each tagged with a .doc_id for later updates.
func load_inventory() -> Array:
	var pointers: Array = await Firestore.list_collection("users/%s/inventory" % FirebaseAuth.uid)
	var cards: Array = []
	for pointer in pointers:
		var player_id: String = pointer.get("player_id", "")
		if player_id == "":
			continue
		var fields = await Firestore.get_document("players/%s" % player_id)
		if fields == null:
			continue  # dangling pointer (players/{id} doc missing) -- skip
		var card := PlayerCard.from_fields(fields, player_id)
		card.doc_id = pointer["id"]
		cards.append(card)
	return cards


func _load_cards(ids: Array) -> Array:
	var cards: Array = []
	for id in ids:
		var fields = await Firestore.get_document("players/%s" % id)
		if fields == null:
			continue
		cards.append(PlayerCard.from_fields(fields, id))
	return cards


## Switches the LIVE (possibly unsaved) formation, carrying a card over to a
## new slot with the same role it was already playing (e.g. a CB stays a CB
## moving 4-4-2 -> 3-5-2). A slot whose role doesn't exist in the new
## formation (or that was empty already) ends up unassigned, and its old
## card (if any) simply falls back into the bench pool -- bench membership
## is always derived (see bench_ids()), never tracked separately.
func switch_formation(new_name: String) -> void:
	var old_slots: Array = Formations.get_formation(formation)
	var new_slots: Array = Formations.get_formation(new_name)
	var new_assignment: Array = []
	new_assignment.resize(new_slots.size())
	new_assignment.fill("")

	var used_old_indices: Dictionary = {}
	for new_i in range(new_slots.size()):
		var new_role: String = new_slots[new_i]["role"]
		for old_i in range(old_slots.size()):
			if used_old_indices.has(old_i):
				continue
			var old_player_id: String = slot_assignment[old_i]
			if old_player_id == "":
				continue
			var old_role: String = old_slots[old_i]["role"]
			if old_role == new_role:
				new_assignment[new_i] = old_player_id
				used_old_indices[old_i] = true
				break

	formation = new_name
	slot_assignment = new_assignment


## Reverts the live formation/slot_assignment back to the last-saved
## snapshot, discarding any in-progress edits -- used when leaving Team
## without saving (see Team.gd's back-button handler). A no-op when nothing
## is dirty.
func discard_changes() -> void:
	formation = saved_formation
	slot_assignment = saved_slot_assignment.duplicate()


## Every id in all_cards not currently occupying a slot.
func bench_ids() -> Array:
	var assigned: Dictionary = {}
	for player_id in slot_assignment:
		if player_id != "":
			assigned[player_id] = true
	var ids: Array = []
	for player_id in all_cards.keys():
		if not assigned.has(player_id):
			ids.append(player_id)
	return ids


## Persists the current live formation/slot_assignment to Firestore (mirrors
## game_state.py's save_team): a roster card that still carries a .doc_id
## just moved bench->roster, so its stale bench pointer document gets
## deleted; a bench card with no .doc_id just moved roster->bench, so it
## gets a fresh one created. On success, refreshes saved_formation/
## saved_slot_assignment so is_dirty() goes false again. Returns false
## (writing nothing) if any slot is still empty -- callers should already
## be blocking that in their own UI, this is just a last-resort guard.
func save_team() -> bool:
	for player_id in slot_assignment:
		if player_id == "":
			return false

	var ok := await Firestore.set_document(
		_user_doc_path(), {"roster_player_ids": slot_assignment, "formation": formation}, true
	)
	if not ok:
		return false

	var uid: String = FirebaseAuth.uid
	for player_id in slot_assignment:
		var card: PlayerCard = all_cards[player_id]
		if card.doc_id != "":
			await Firestore.delete_document("users/%s/inventory/%s" % [uid, card.doc_id])
			card.doc_id = ""

	for player_id in bench_ids():
		var card: PlayerCard = all_cards[player_id]
		if card.doc_id == "":
			var new_doc_id := await Firestore.add_document("users/%s/inventory" % uid, {"player_id": card.player_id})
			card.doc_id = new_doc_id

	saved_formation = formation
	saved_slot_assignment = slot_assignment.duplicate()
	return true
