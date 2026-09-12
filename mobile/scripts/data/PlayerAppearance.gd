class_name PlayerAppearance
extends RefCounted

## Layered "pixelated character" appearance: 5 independent slots, 5 options
## each -- skin tone, hair style (shape), hair color (tint), face (mouth
## shape), shoe color. 5^5 = 3125 distinct-looking combinations from just
## 25 stored choices. Rendered by PlayerModelView.gd's _draw(); that's the
## only place that needs to change once real per-option art exists (each
## slot would pick a texture instead of a shape/color).
##
## mock_from_id() is a TEMPORARY stand-in: it derives all 5 indices
## deterministically from a player_id alone (same player always looks the
## same during this preview), without storing or changing anything. The
## point right now is to see the layered look in the Team screen before
## committing to real data. Once that's approved, the real version stores
## these 5 indices on players/{id} (rolled once at pack-open time, same as
## tier/attributes/name already are) and PlayerCard.gd reads them back
## like every other field -- this function goes away, and its one call
## site in PlayerModelView.set_card() switches to reading card.appearance
## directly.

const OPTION_COUNT := 5

const SKIN_TONES := [
	Color(0.96, 0.80, 0.65),
	Color(0.87, 0.65, 0.45),
	Color(0.76, 0.52, 0.34),
	Color(0.55, 0.36, 0.22),
	Color(0.36, 0.24, 0.16),
]

const HAIR_COLORS := [
	Color(0.09, 0.07, 0.06),
	Color(0.35, 0.22, 0.12),
	Color(0.72, 0.55, 0.25),
	Color(0.65, 0.12, 0.10),
	Color(0.85, 0.85, 0.85),
]

const SHOE_COLORS := [
	Color(0.1, 0.1, 0.1),
	Color(0.9, 0.9, 0.9),
	Color(0.75, 0.1, 0.1),
	Color(0.15, 0.3, 0.75),
	Color(0.944, 0.489, 0.878, 1.0),
]


static func mock_from_id(player_id: String) -> Dictionary:
	return {
		"skin_tone": _mock_index(player_id, "skin_tone"),
		"hair_style": _mock_index(player_id, "hair_style"),
		"hair_color": _mock_index(player_id, "hair_color"),
		"face": _mock_index(player_id, "face"),
		"shoe_color": _mock_index(player_id, "shoe_color"),
	}


## Each slot hashes the id with its own salt rather than splitting one hash
## into 5 pieces (e.g. via division/modulo) -- independent hashes avoid any
## risk of the 5 slots correlating with each other for a given id.
static func _mock_index(player_id: String, salt: String) -> int:
	return abs((player_id + "_" + salt).hash()) % OPTION_COUNT
