class_name Formations
extends RefCounted

## GDScript port of packedfootball/formations.py -- same named formations,
## same base coordinates/roles for the player's own XI (indices 0-10; unlike
## the Python side, this never needs the mirrored opponent half, since the
## Team scene only ever lays out the signed-in user's own squad, never a
## match's full 22). Kept in lockstep with the Python source by hand, the
## same way FirebaseAuth.gd hand-ports firebase_client.py -- Godot can't
## import Python directly.

const FORMATION_NAMES: Array[String] = ["4-4-2", "4-3-3", "3-5-2", "4-2-3-1"]

const _BASES := {
	"4-4-2": [
		{"pos": Vector2(35.0, 5.0), "role": "GK"},
		{"pos": Vector2(12.0, 20.0), "role": "LB"},
		{"pos": Vector2(27.0, 15.0), "role": "CB"},
		{"pos": Vector2(43.0, 15.0), "role": "CB"},
		{"pos": Vector2(58.0, 20.0), "role": "RB"},
		{"pos": Vector2(12.0, 40.0), "role": "CM"},
		{"pos": Vector2(27.0, 35.0), "role": "CM"},
		{"pos": Vector2(43.0, 35.0), "role": "CM"},
		{"pos": Vector2(58.0, 40.0), "role": "CM"},
		{"pos": Vector2(27.0, 47.0), "role": "ST"},
		{"pos": Vector2(43.0, 47.0), "role": "ST"},
	],
	"4-3-3": [
		{"pos": Vector2(35.0, 5.0), "role": "GK"},
		{"pos": Vector2(12.0, 20.0), "role": "LB"},
		{"pos": Vector2(27.0, 15.0), "role": "CB"},
		{"pos": Vector2(43.0, 15.0), "role": "CB"},
		{"pos": Vector2(58.0, 20.0), "role": "RB"},
		{"pos": Vector2(35.0, 23.0), "role": "CDM"},
		{"pos": Vector2(25.0, 30.0), "role": "CM"},
		{"pos": Vector2(45.0, 30.0), "role": "CM"},
		{"pos": Vector2(15.0, 44.0), "role": "LW"},
		{"pos": Vector2(55.0, 44.0), "role": "RW"},
		{"pos": Vector2(35.0, 47.0), "role": "ST"},
	],
	"3-5-2": [
		{"pos": Vector2(35.0, 5.0), "role": "GK"},
		{"pos": Vector2(18.0, 15.0), "role": "CB"},
		{"pos": Vector2(35.0, 12.0), "role": "CB"},
		{"pos": Vector2(52.0, 15.0), "role": "CB"},
		{"pos": Vector2(35.0, 22.0), "role": "CDM"},
		{"pos": Vector2(10.0, 32.0), "role": "WB"},
		{"pos": Vector2(25.0, 32.0), "role": "CM"},
		{"pos": Vector2(45.0, 32.0), "role": "CM"},
		{"pos": Vector2(60.0, 32.0), "role": "WB"},
		{"pos": Vector2(27.0, 47.0), "role": "ST"},
		{"pos": Vector2(43.0, 47.0), "role": "ST"},
	],
	"4-2-3-1": [
		{"pos": Vector2(35.0, 5.0), "role": "GK"},
		{"pos": Vector2(12.0, 20.0), "role": "LB"},
		{"pos": Vector2(27.0, 15.0), "role": "CB"},
		{"pos": Vector2(43.0, 15.0), "role": "CB"},
		{"pos": Vector2(58.0, 20.0), "role": "RB"},
		{"pos": Vector2(27.0, 28.0), "role": "CDM"},
		{"pos": Vector2(43.0, 28.0), "role": "CDM"},
		{"pos": Vector2(15.0, 38.0), "role": "LW"},
		{"pos": Vector2(35.0, 38.0), "role": "CAM"},
		{"pos": Vector2(55.0, 38.0), "role": "RW"},
		{"pos": Vector2(35.0, 47.0), "role": "ST"},
	],
}


## Returns an Array of 11 {"pos": Vector2, "role": String} slots, indices 0-10.
static func get_formation(name: String) -> Array:
	return _BASES.get(name, _BASES["4-4-2"])


## Position "similarity" groups -- a player can fill a formation slot whose
## role differs from their own card position if the two share a group here
## (at a penalty -- see backend/../gameEngine.py's OUT_OF_POSITION_PENALTY,
## which actually applies it during match simulation; this side only needs
## it to decide what the Team scene's bench picker allows and tags).
## Groups, not a flat pairwise list, so adding a position later only means
## joining a group, not wiring up every new pair by hand. Deliberately NOT
## transitive across groups (CDM and CAM share no group -- both border CM,
## but CDM->CAM is a bigger stretch than either individual step) and NOT
## exhaustive (GK and CB are in no group at all, so neither ever substitutes
## for anything). Mirrors packedfootball/formations.py's own POSITION_GROUPS
## -- keep the two in lockstep if either changes.
const POSITION_GROUPS: Array = [
	["CDM", "CM"],
	["CM", "CAM"],
	["LB", "WB", "LM", "LW"],
	["RB", "WB", "RM", "RW"],
	["LW", "RW", "ST"],
]


## True if position_a can fill a position_b slot at a penalty rather than
## being blocked outright -- i.e. they're different but share at least one
## POSITION_GROUPS entry. False for an exact match (that's not "similar",
## it's just correct) and for any pairing that shares no group.
static func is_similar_position(position_a: String, position_b: String) -> bool:
	if position_a == position_b:
		return false
	for group in POSITION_GROUPS:
		if group.has(position_a) and group.has(position_b):
			return true
	return false
