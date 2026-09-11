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
