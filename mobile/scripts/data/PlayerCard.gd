class_name PlayerCard
extends RefCounted

## Client-side player card: mirrors packedfootball/game_state.py's
## player_to_fields()/fields_to_player() round trip, plus enough of
## player.py's overall calculation to show a rating -- but none of the
## gameplay decision-making logic. Godot never simulates a match locally
## (the backend does, from a seed), so a card here only ever needs to be
## held and displayed, never acted on.

## Mirrors packEngine.py's PLAYER_CLASS_MAP keys and each class's
## primary_stats tuple. Keep in lockstep if either changes server-side.
const PRIMARY_STATS_BY_POSITION := {
	"GK": ["passing", "agility", "ballcontrol"],
	"CB": ["defending", "tackling"],
	"LB": ["defending", "tackling", "speed", "passing"],
	"RB": ["defending", "tackling", "speed", "passing"],
	"WB": ["speed", "passing", "defending"],
	"CDM": ["defending", "tackling", "passing"],
	"CM": ["passing", "ballcontrol", "vision"],
	"CAM": ["passing", "vision", "shooting"],
	"LM": ["passing", "ballcontrol", "vision"],
	"RM": ["passing", "ballcontrol", "vision"],
	"LW": ["dribbiling", "speed", "passing"],
	"RW": ["dribbiling", "speed", "passing"],
	"ST": ["shooting", "dribbiling", "speed", "power"],
}

## Mirrors player.py's TENDENCY_FIELDS -- excluded from the "secondary" stat
## average the same way the Python overall calculation excludes them.
## "composure" is deliberately in both this list and a real Attributes field;
## that's not a typo, it matches player.py exactly.
const TENDENCY_FIELDS := [
	"pass_tendency", "shoot_tendency", "drible_tendency", "aggression", "composure", "clear_tendency"
]

## Card-back color by tier -- used for pitch slot fill and bench row accents
## so tier reads at a glance without opening the stats panel.
const TIER_COLORS := {
	"bronze": Color(0.72, 0.45, 0.2),
	"silver": Color(0.75, 0.75, 0.78),
	"gold": Color(0.85, 0.65, 0.13),
	"platinum": Color(0.3, 0.75, 0.7),
	"diamond": Color(0.4, 0.75, 0.95),
	"special": Color(0.65, 0.3, 0.85),
	"icon": Color(0.95, 0.85, 0.55),
}

static func tier_color(tier: String) -> Color:
	return TIER_COLORS.get(tier, Color(0.5, 0.5, 0.5))


## Dictionary.get(key, default) only falls back to `default` when the key
## is entirely absent -- a present key holding JSON null comes back as null
## regardless, and assigning null into a statically-typed String var is a
## hard runtime error (see PackData.gd's own version of this helper, hit in
## practice there first). None of these fields are optional in today's
## schema, but every one of them still goes through this rather than a bare
## fields.get(key, default), so a malformed/partial doc degrades to an
## empty string instead of crashing the whole card.
static func _str(fields: Dictionary, key: String, default: String = "") -> String:
	var value = fields.get(key)
	return value if value is String else default


static func _dict(fields: Dictionary, key: String, default: Dictionary) -> Dictionary:
	var value = fields.get(key)
	return value if value is Dictionary else default


var player_id: String = ""
var doc_id: String = ""  # non-empty only for benched cards (inventory pointer doc id)
var fname: String = ""
var lname: String = ""
var tier: String = ""
var position: String = ""
var country: String = ""
var hometown: String = ""
var attributes: Dictionary = {}
var statistics: Dictionary = {"goals": 0, "assists": 0, "matches_played": 0}
## Layered placeholder-portrait indices (skin_tone/hair_style/hair_color/
## face/shoe_color -> 0..4) -- see PlayerAppearance.gd. {} means "not set"
## (a card whose players/{id} doc predates this field and hasn't been
## backfilled by backend/scripts/sync_player_appearance.py yet);
## PlayerModelView.gd falls back to a mock look derived from player_id in
## that case rather than rendering nothing.
var appearance: Dictionary = {}


static func from_fields(fields: Dictionary, id: String) -> PlayerCard:
	var card := PlayerCard.new()
	card.player_id = id
	card.fname = _str(fields, "fname")
	card.lname = _str(fields, "lname")
	card.tier = _str(fields, "tier")
	card.position = _str(fields, "position")
	card.country = _str(fields, "country", "Unknown")
	card.hometown = _str(fields, "hometown", "Unknown")
	card.attributes = _dict(fields, "attributes", {})
	card.statistics = _dict(fields, "statistics", {"goals": 0, "assists": 0, "matches_played": 0})
	card.appearance = _dict(fields, "appearance", {})
	return card


## Mirrors packedfootball/game_state.py's player_to_fields() -- the reverse
## of from_fields(), used when publishing a lobby entry (see
## GameProfile.publish_lobby_entry()).
func to_fields() -> Dictionary:
	return {
		"fname": fname,
		"lname": lname,
		"tier": tier,
		"position": position,
		"country": country,
		"hometown": hometown,
		"attributes": attributes,
		"statistics": statistics,
		"appearance": appearance,
	}


func display_name() -> String:
	return lname if lname != "" else fname


## Reproduces player.py's player._calculate_overall(): primary stats (by
## position) averaged with weight `primary_weight` (1.0 for GK, 0.8 for
## everyone else -- the only class-level override that exists server-side
## today), blended with the average of every other non-tendency attribute.
func overall() -> int:
	var primary: Array = PRIMARY_STATS_BY_POSITION.get(position, ["passing", "ballcontrol", "vision"])
	var primary_weight: float = 1.0 if position == "GK" else 0.8

	var primary_sum := 0.0
	for stat_name in primary:
		var stat_value: float = attributes.get(stat_name, 50)
		primary_sum += stat_value
	var primary_avg: float = primary_sum / maxf(1.0, float(primary.size()))

	var secondary_sum := 0.0
	var secondary_count := 0
	for key in attributes.keys():
		if primary.has(key) or TENDENCY_FIELDS.has(key):
			continue
		var value: float = attributes[key]
		secondary_sum += value
		secondary_count += 1
	var secondary_avg: float = (secondary_sum / secondary_count) if secondary_count > 0 else primary_avg

	return int(round(primary_avg * primary_weight + secondary_avg * (1.0 - primary_weight)))
