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

const DEFAULT_INVENTORY_CAP := 100

## The live limit: DEFAULT_INVENTORY_CAP until the server says otherwise.
## Read this, never the constant.
var inventory_cap: int = DEFAULT_INVENTORY_CAP

## The energy bar, exactly as the server describes it -- amount, max, and the
## SECONDS until the next point. Cached here because four screens show it and
## none of them should have to fetch it for themselves.
var energy: Dictionary = {}

var is_loaded: bool = false

# Profile fields (mirrors game_state.py's load_or_create_profile shape).
var display_name: String = ""
var credits: int = 0
var bucks: int = 0
var medals: int = 0
var wins: int = 0
var losses: int = 0
var draws: int = 0

# The manager's shirt, as the raw string stored on users/{uid}.kit -- see
# KitDesign.gd for the format and why it's one string rather than a set of
# fields. Kept raw here (not as a parsed KitDesign) so a value written by a
# newer client survives a round trip through an older one untouched: parse
# it with kit_design() when you need to draw it.
var kit: String = ""

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


## Dictionary.get(key, default) only falls back to `default` when the key
## is entirely absent -- a present key holding JSON null comes back as null
## regardless, and assigning null into a statically-typed String/int/Array
## var is a hard runtime error (see PackData.gd's version of this, hit in
## practice first). Nothing currently writes null into any of these
## users/{uid} fields, but load_all() runs on every single login, so it's
## worth the same defensiveness PackData/PlayerCard already have rather
## than a malformed doc taking down sign-in entirely.
static func _str(doc: Dictionary, key: String, default: String = "") -> String:
	var value = doc.get(key)
	return value if value is String else default


static func _int(doc: Dictionary, key: String, default: int = 0) -> int:
	var value = doc.get(key)
	return value if typeof(value) in [TYPE_INT, TYPE_FLOAT] else default


static func _array(doc: Dictionary, key: String, default: Array) -> Array:
	var value = doc.get(key)
	return value if value is Array else default


## Fetches everything needed to populate the cache above in one go. Called
## once right after sign-in (see Auth.gd) so every later scene reads
## instantly from memory instead of re-hitting Firestore every time it opens.
##
## Calls the backend's /account/bootstrap first, which creates a profile +
## a full bronze starter roster if (and only if) this uid has never signed
## in before -- a no-op otherwise, safe to call on every login. Without
## this, a brand new account created straight through this Godot client had
## no cards and no roster at all (packedfootball/main.py's own client
## builds its own local starter squad instead of needing this, which is why
## this gap only ever existed on the Godot side).
func load_all() -> void:
	var bootstrap: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_POST, "/account/bootstrap")
	if bootstrap.ok:
		apply_inventory_cap(bootstrap.data.get("inventory_cap"))
		apply_energy(bootstrap.data.get("energy"))

	var doc = await Firestore.get_document(_user_doc_path())
	var ids: Array = []
	if doc != null:
		display_name = _str(doc, "display_name")
		credits = _int(doc, "credits")
		bucks = _int(doc, "bucks")
		medals = _int(doc, "medals")
		wins = _int(doc, "wins")
		losses = _int(doc, "losses")
		draws = _int(doc, "draws")
		formation = _str(doc, "formation", DEFAULT_FORMATION)
		kit = _str(doc, "kit", "")
		ids = _array(doc, "roster_player_ids", [])

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


func refresh_currencies() -> bool:
	var doc = await Firestore.get_document(_user_doc_path())
	if doc == null:
		return false
	credits = _int(doc, "credits", credits)
	bucks = _int(doc, "bucks", bucks)
	medals = _int(doc, "medals", medals)
	return true

func load_inventory() -> Array:
	var pointers: Array = await Firestore.list_collection("users/%s/inventory" % FirebaseAuth.uid)
	var cards: Array = []
	for pointer in pointers:
		var player_id: String = _str(pointer, "player_id")
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

func discard_changes() -> void:
	formation = saved_formation
	slot_assignment = saved_slot_assignment.duplicate()

func inventory_count() -> int:
	var count := 0
	for player_id in all_cards.keys():
		var card: PlayerCard = all_cards[player_id]
		if card.doc_id != "":
			count += 1
	return count

func inventory_space() -> int:
	return maxi(0, inventory_cap - inventory_count())

func apply_inventory_cap(value) -> void:
	if typeof(value) in [TYPE_INT, TYPE_FLOAT] and int(value) > 0:
		inventory_cap = int(value)


## Folds an energy block in from any response that carries one --
## /account/bootstrap, /match/quick, /tournament/match, /energy/refill. Every
## endpoint that SPENDS energy returns the bar afterwards, so the common case
## needs no extra request at all.
func apply_energy(block) -> void:
	if block is Dictionary and block.has("energy"):
		energy = block

func refresh_energy() -> bool:
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/energy")
	if not res.ok:
		return false
	apply_energy(res.data)
	return true

func release_card(player_id: String) -> void:
	all_cards.erase(player_id)
	for i in range(slot_assignment.size()):
		if slot_assignment[i] == player_id:
			slot_assignment[i] = ""

func set_card_appearance(player_id: String, appearance: Dictionary) -> void:
	if not all_cards.has(player_id):
		return
	var card: PlayerCard = all_cards[player_id]
	card.appearance = appearance

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


## Squad Overall: the average of what the XI is worth IN THE SLOTS THEY ARE
## STANDING IN, not the average of their cards.
##
## Those differ whenever someone is played out of position, and the
## difference is real -- the match engine drops their attributes 10% (see
## SquadOptimizer.OUT_OF_POSITION_FACTOR), so a squad full of square pegs is
## genuinely weaker than the sum of its cards. Counting the cards instead
## would overstate it, and would also mean the Squad screen's Auto button
## could rearrange the team into something stronger and show a LOWER number,
## which is the kind of thing that reads as a bug.
##
## Empty slots are skipped rather than counted as zero, so a part-built
## lineup shows the strength of what's in it.
func average_overall() -> int:
	return SquadOptimizer.squad_overall(formation, slot_assignment, all_cards)

func set_display_name(new_name: String) -> bool:
	var ok := await Firestore.set_document(_user_doc_path(), {"display_name": new_name}, true)
	if ok:
		display_name = new_name
	return ok

func kit_design() -> KitDesign:
	return KitDesign.parse(kit)

func set_kit(design: KitDesign) -> bool:
	var encoded := design.serialize()
	var ok := await Firestore.set_document(_user_doc_path(), {"kit": encoded}, true)
	if ok:
		kit = encoded
	return ok


## Clears the cached profile/squad state -- called on sign-out (mirrors
## main.py setting its own game_state = None) so a second account signing
## in on the same running app never briefly sees the previous account's
## data before the next load_all() completes.
func reset() -> void:
	is_loaded = false
	display_name = ""
	credits = 0
	bucks = 0
	medals = 0
	wins = 0
	losses = 0
	draws = 0
	kit = ""
	inventory_cap = DEFAULT_INVENTORY_CAP
	energy = {}
	formation = DEFAULT_FORMATION
	slot_assignment = []
	all_cards = {}
	saved_formation = DEFAULT_FORMATION
	saved_slot_assignment = []

func add_purchased_cards(cards: Array) -> void:
	for card in cards:
		var typed_card: PlayerCard = card
		all_cards[typed_card.player_id] = typed_card

func apply_currency_balances(new_credits = null, new_bucks = null, new_medals = null) -> void:
	if typeof(new_credits) in [TYPE_INT, TYPE_FLOAT]:
		credits = new_credits
	if typeof(new_bucks) in [TYPE_INT, TYPE_FLOAT]:
		bucks = new_bucks
	if typeof(new_medals) in [TYPE_INT, TYPE_FLOAT]:
		medals = new_medals
