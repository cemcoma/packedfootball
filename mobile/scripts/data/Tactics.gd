class_name Tactics
extends RefCounted

## The play styles on the Tactics screen. The ids mirror
## packedfootball/game_config.py's TACTICS -- what each style actually does
## lives there; this is only the name and the one-line pitch. The backend
## reads users/{uid}.tactics through its own sanitize_tactics, so an id it
## doesn't know plays Balanced rather than breaking anything.
##
## users/{uid}.tactics is a map so later settings (crossing) are new keys,
## not new fields: sanitize() keeps keys it doesn't know, so an older client
## never strips what a newer one wrote.
##
## The captain and set-piece takers (ROLE_KEYS) are player ids; a missing key
## is Auto. Who Auto picks mirrors gameEngine._set_piece_taker and game.captains:
## never the keeper, though he can be picked as captain.

const DEFAULT_STYLE := "balanced"
const STYLE_IDS: Array[String] = ["balanced", "possession", "long_ball", "wing_play"]

const _NAMES := {
	"balanced": "Balanced",
	"possession": "Possession",
	"long_ball": "Long Ball",
	"wing_play": "Wing Play",
}

const _DESCRIPTIONS := {
	"balanced": "No instructions beyond the formation: the side reads the game as it comes.",
	"possession": "Keep the ball and starve them of it. Suits the better side -- but the high line leaves room behind it for a quick striker.",
	"long_ball": "Defenders stay deep and go long; the side pushes up to win the second ball and the free kicks. Punishes a high line.",
	"wing_play": "Get it wide and get it in: wide men are the pass to find, full-backs overlap, runners attack every cross.",
}

const CAPTAIN := "captain"
const PENALTY_TAKER := "penalty_taker"
const CORNER_TAKER := "corner_taker"
const FREE_KICK_TAKER := "free_kick_taker"
const DUTIES: Array[String] = [PENALTY_TAKER, CORNER_TAKER, FREE_KICK_TAKER]
const ROLE_KEYS: Array[String] = [CAPTAIN, PENALTY_TAKER, CORNER_TAKER, FREE_KICK_TAKER]

## tactics.py's SET_PIECE_DUTIES: the stats the engine resolves each duty with.
const _DUTY_BLENDS := {
	PENALTY_TAKER: {"shooting": 0.8, "accuracy": 0.2},
	CORNER_TAKER: {"passing": 0.6, "vision": 0.4},
	FREE_KICK_TAKER: {"shooting": 0.7, "accuracy": 0.3},
}

## The formation's usual man when nobody is picked: gameEngine._pick_role_slot's
## preference order, then its fallback slot. The free kick has none -- Auto is
## the best striker of a ball.
const _AUTO_ROLES := {
	PENALTY_TAKER: [["ST", "CF", "CAM", "LW", "RW"], 9],
	CORNER_TAKER: [["RW", "LW", "RM", "LM", "LWB", "RWB"], 8],
}

const _ROLE_NAMES := {
	CAPTAIN: "Captain",
	PENALTY_TAKER: "Penalties",
	CORNER_TAKER: "Corners",
	FREE_KICK_TAKER: "Free kicks",
}

const _ROLE_DESCRIPTIONS := {
	CAPTAIN: "Wears the armband.",
	PENALTY_TAKER: "Steps up from the spot. Shooting, then accuracy.",
	CORNER_TAKER: "Delivers corners and wide free kicks. Passing and vision.",
	FREE_KICK_TAKER: "Has a go from shooting range. Shooting and accuracy.",
}

## The rating's three-letter tag, next to the number.
const _RATING_TAGS := {
	CAPTAIN: "OVR",
	PENALTY_TAKER: "PEN",
	CORNER_TAKER: "CRN",
	FREE_KICK_TAKER: "FK",
}

const OUT_OF_POSITION_PENALTY := 0.9


static func sanitize(raw) -> Dictionary:
	var clean: Dictionary = raw.duplicate() if raw is Dictionary else {}
	# Type first: `in` on a typed Array logs an engine error for a non-String.
	var style = clean.get("style")
	if not (style is String and style in STYLE_IDS):
		clean["style"] = DEFAULT_STYLE
	for key in ROLE_KEYS:
		if clean.has(key) and not (clean[key] is String and clean[key] != ""):
			clean.erase(key)
	return clean


## TranslationServer rather than tr(): everything here is static.
static func display_name(style: String) -> String:
	return TranslationServer.translate(_NAMES.get(style, _NAMES[DEFAULT_STYLE]))


static func description(style: String) -> String:
	return TranslationServer.translate(_DESCRIPTIONS.get(style, _DESCRIPTIONS[DEFAULT_STYLE]))


static func role_name(role: String) -> String:
	return TranslationServer.translate(_ROLE_NAMES.get(role, role))


static func role_description(role: String) -> String:
	return TranslationServer.translate(_ROLE_DESCRIPTIONS.get(role, ""))


static func rating_tag(role: String) -> String:
	return TranslationServer.translate(_RATING_TAGS.get(role, ""))


# ------------------------------------------------------------- the XI's picks

## The card as the engine plays it in a slot of `slot_role`: items on, and every
## skill scaled down when it's out of position (gameEngine._apply_out_of_position_penalty).
static func slot_attributes(card: PlayerCard, slot_role: String) -> Dictionary:
	var attrs := card.effective_attributes()
	if card.position == slot_role:
		return attrs
	var scaled := attrs.duplicate()
	for key in attrs:
		if not (key in PlayerCard.TENDENCY_FIELDS or key in PlayerCard.PHYSICAL_FIELDS):
			scaled[key] = _round_half_even(float(attrs[key]) * OUT_OF_POSITION_PENALTY)
	return scaled


## How good a player is at `role` in that slot: the duty's blend, or overall for the captain.
static func rating(card: PlayerCard, slot_role: String, role: String) -> float:
	var attrs := slot_attributes(card, slot_role)
	if role == CAPTAIN:
		var scaled := PlayerCard.new()
		scaled.position = card.position
		scaled.attributes = attrs
		return float(scaled.overall())
	var total := 0.0
	var blend: Dictionary = _DUTY_BLENDS.get(role, {})
	for stat in blend:
		total += float(attrs.get(stat, 50)) * float(blend[stat])
	return total


## Can this slot do `role`? Anyone can captain; set pieces are outfield only.
static func eligible(role: String, slot_role: String) -> bool:
	return role == CAPTAIN or slot_role != "GK"


## The slot of whoever does `role` for this XI (`xi` is a PlayerCard or null per
## slot): the pick when he's in it and eligible, else whoever the engine takes.
static func assigned_slot(tactics: Dictionary, role: String, formation: String, xi: Array) -> int:
	var picked := picked_slot(tactics, role, formation, xi)
	return picked if picked >= 0 else auto_slot(role, formation, xi)


## The pick's slot, or -1 when it's Auto (nobody picked, or the pick isn't in this XI).
static func picked_slot(tactics: Dictionary, role: String, formation: String, xi: Array) -> int:
	var player_id = tactics.get(role)
	if not (player_id is String and player_id != ""):
		return -1
	var slots := Formations.get_formation(formation)
	for i in range(mini(xi.size(), slots.size())):
		var card: PlayerCard = xi[i]
		if card != null and card.player_id == player_id:
			return i if eligible(role, slots[i]["role"]) else -1
	return -1


static func auto_slot(role: String, formation: String, xi: Array) -> int:
	var slots := Formations.get_formation(formation)
	if _AUTO_ROLES.has(role):
		var preferred: Array = _AUTO_ROLES[role][0]
		for wanted in preferred:
			for i in range(slots.size()):
				if slots[i]["role"] == wanted:
					return i
		return int(_AUTO_ROLES[role][1])
	# The best outfielder at it, first slot on a tie -- Python's max().
	var best := -1
	var best_rating := -INF
	for i in range(mini(xi.size(), slots.size())):
		var card: PlayerCard = xi[i]
		if card == null or slots[i]["role"] == "GK":
			continue
		var value := rating(card, slots[i]["role"], role)
		if value > best_rating:
			best = i
			best_rating = value
	return best


## Python's round(): halves go to the even neighbour, so a scaled stat matches the engine's.
static func _round_half_even(value: float) -> int:
	var lower := floorf(value)
	var diff := value - lower
	if diff > 0.5:
		return int(lower) + 1
	if diff < 0.5:
		return int(lower)
	return int(lower) + (int(lower) % 2)
