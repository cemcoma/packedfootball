class_name PlayerAppearance
extends RefCounted

## Every option a player's look can be built from. THE place to add one.
##
## Six independent slots -- skin tone, hair style, hair colour, face, boot
## colour, goal celebration -- each stored on players/{id} as a plain INDEX
## into one of the lists below. 5x5x5x5x5x9 = 28125 combinations today.
##
## Colours are a list of Colors; SHAPES (hair, face) are a list of
## rectangles; CELEBRATIONS are recipes of named poses. All data:
## PlayerFigure.gd renders whatever is here and knows nothing about any
## individual style, so adding a hairstyle is an entry in HAIR_STYLES and
## nothing else -- no drawing code, no new file. (A celebration is the one
## that may need a new arm or leg pose in PlayerFigure if none of the
## existing parts does what you want -- see CELEBRATIONS.)
##
## APPEND ONLY.
## An index is stored on every card doc forever, so inserting an option in
## the middle, or reordering, silently restyles every card already out
## there. New options go on the END.
##
## Two ends have to agree on how many options exist, because the CLIENT
## draws them but the SERVER rolls them: raise the matching entry in
## packedfootball/game_config.py's APPEARANCE_OPTION_COUNTS and redeploy,
## or newly generated cards will never be given the new option.

# --------------------------------------------------------------- colours

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

# ---------------------------------------------------------------- shapes
#
# A shape is a list of `parts`, each [x, y, w, h] in HEAD-BOX FRACTIONS:
#
#     x  0.0 = left edge of the head,   1.0 = right edge
#     y  0.0 = bottom of the head,      1.0 = top
#
# Values OUTSIDE 0..1 are legal and useful -- that is how a mohawk sticks up
# past the skull (y + h > 1) and an afro bulges past its sides (x < 0,
# w > 1). Parts draw in order, so later ones sit on top.
#
#          1.0  +---------+
#               |  hair   |   roughly 0.66 and up
#          0.42 |  eyes   |   fixed, PlayerFigure.EYE_Y
#          0.20 |  mouth  |   FACE_STYLES live here
#          0.0  +---------+

## `covers_back` is what a style does when the player is running AWAY: most
## hair fills the whole back of the head (you'd see hair, not a bald patch),
## but a mohawk or a bald head obviously does not.
const HAIR_STYLES := [
	{
		"name": "Bald",
		"parts": [],
		"covers_back": false,
	},
	{
		"name": "Short",
		"parts": [[0.00, 0.66, 1.00, 0.34]],
	},
	{
		"name": "Long",
		"parts": [
			[-0.11, 0.66, 1.22, 0.34],   # cap, hanging past head
			[-0.11, 0.11, 0.11, 0.55],   # left side, hanging past the head
			[ 1.00, 0.11, 0.11, 0.55],   # right side
		],
	},
	{
		"name": "Mohawk",
		"parts": [[0.30, 0.66, 0.40, 0.612]],   # h > the cap, so it stands up
		"covers_back": false,
	},
	{
		"name": "Afro",
		"parts": [[-0.10, 0.66, 1.20, 0.442]],  # bulges past both sides
	},
]

## Mouths, same [x, y, w, h] parts as hair. Drawn only when the player is
## facing the viewer, below the eyes.
##
## A curve is faked from offset bars, and the one thing to watch is that
## `x` is the bar's LEFT EDGE, not its centre -- so shrinking `w` shrinks
## the bar RIGHTWARD and can open a hole before the next part. Adjacent
## bars must OVERLAP or the mouth renders in pieces:
##
##    good   [0.30 .. 0.42][0.40 .. 0.60][0.58 .. 0.70]   ends overlap
##    bad    [0.28 .. 0.38] [0.40 .. 0.60]                 gap at 0.38-0.40
##
## Keep them symmetric about x = 0.50 unless the style is lopsided on
## purpose, like Smirk.
const FACE_STYLES := [
	{
		"name": "Neutral",
		"parts": [[0.30, 0.20, 0.40, 0.06]],
	},
	{
		"name": "Smile",
		"parts": [
			[0.30, 0.24, 0.12, 0.06],
			[0.40, 0.18, 0.20, 0.06],
			[0.58, 0.24, 0.12, 0.06],
		],
	},
	{
		"name": "Extra Happy",
		"parts": [
			[0.35, 0.18, 0.08, 0.20],
			[0.40, 0.18, 0.20, 0.06],
			[0.53, 0.18, 0.08, 0.20],
		],
	},
	{
		"name": "Surprised",
		"parts": [[0.42, 0.16, 0.16, 0.18]],
	},
	{
		"name": "Smirk",
		"parts": [
			[0.30, 0.24, 0.16, 0.06],
			[0.44, 0.18, 0.26, 0.06],
		],
	},
]

const MOUTH_COLOR := Color(0.25, 0.15, 0.12)

# ---------------------------------------------------------- celebrations
#
# What the SCORER does during the goal hold (MatchPlayback freezes the
# replay and PlayerFigure draws them in POSE_CELEBRATE, fed the seconds
# since the goal). Their teammates all do TEAMMATE_CELEBRATION where they
# stand -- a full-back knee-sliding on the halfway line is not a thing.
#
# Not a shape but a RECIPE: a timeline of up to three moving stages and
# then a held pose built from named parts. PlayerFigure knows how to draw
# each named part; most new celebrations are a new combination of parts
# that already exist, and a genuinely new gesture is a new arm or leg pose
# in PlayerFigure._draw_celebrating_arms / _draw_legs plus an entry here.
#
#   run     seconds of running off (toward the corner) before anything else
#   jump    seconds of one leap with a full spin in the air, still moving
#   slide   seconds the held pose keeps moving while braking to a stop --
#           what makes a knee slide slide
#   arms    "up"      both arms raised and swaying -- the classic
#           "wide"    arms straight out to the sides, aeroplane
#           "pump"    one fist pumping the air, the other arm down
#           "shush"   one finger to the lips, the other arm down
#           "back"    arms swept down and behind, chest out
#           "cradle"  arms crossed low in front, rocking the baby
#           "swing"   arms pumping alternately, as in a run
#   legs    "stand"   (default) feet planted
#           "wide"    a wide stance
#           "kneel"   knees folded under -- the figure sits lower
#           "step"    running on the spot
#   bounce  how high the held pose hops, fraction of height (0 = none)
#   spin    true to keep turning through all eight facings in the held pose
#   rock    true to sway the upper body side to side
#
# The stages add up against PlayerFigure.CELEBRATE_DURATION (5s): leave at
# least a couple of seconds for the pose itself or it's over before it
# reads. Index 0 is what every card had before this slot existed (the
# arms-up wave), which is what a doc without the field falls back to.
const CELEBRATIONS := [
	{"name": "Arms Up", "arms": "up"},
	{"name": "Jump", "run": 0.8, "arms": "up", "bounce": 0.14},
	{"name": "Knee Slide", "run": 1.2, "slide": 1.8, "arms": "wide", "legs": "kneel"},
	{"name": "Spin", "run": 0.8, "arms": "wide", "spin": true},
	{"name": "Fist Pump", "run": 0.8, "arms": "pump"},
	{"name": "Shush", "run": 1.0, "arms": "shush"},
	{"name": "Siuu", "run": 1.5, "jump": 0.8, "arms": "back", "legs": "wide"},
	{"name": "Cradle", "run": 0.8, "arms": "cradle", "rock": true},
	{"name": "Dance", "run": 0.6, "arms": "swing", "legs": "step", "rock": true},
]

## What everyone on the scoring side other than the scorer does.
const TEAMMATE_CELEBRATION := 0

# ------------------------------------------------------------ slot index
#
# The six slots, in the order a customization screen should present them:
# top of the body down. Mirrors player.py's APPEARANCE_SLOTS (which is the
# order the SERVER rolls them in, and irrelevant to display).

const SLOTS := ["skin_tone", "hair_style", "hair_color", "face", "shoe_color", "celebration"]

const SLOT_LABELS := {
	"skin_tone": "Skin tone",
	"hair_style": "Hair",
	"hair_color": "Hair colour",
	"face": "Face",
	"shoe_color": "Boots",
	"celebration": "Celebration",
}


## The palette a colour slot picks from, or [] for a slot that picks a SHAPE
## instead. This is what lets CustomizePlayer.gd build its whole UI from this
## file -- swatches where there are colours, named buttons where there
## aren't -- so a sixth slot is an entry here and nothing else.
static func colors_for(slot: String) -> Array:
	match slot:
		"skin_tone":
			return SKIN_TONES
		"hair_color":
			return HAIR_COLORS
		"shoe_color":
			return SHOE_COLORS
	return []


## A human name for one option, for a button label or a summary line. Shape
## slots carry their own "name"; colour slots have none, so they're numbered.
static func option_name(slot: String, index: int) -> String:
	match slot:
		"hair_style":
			return hair_style(index).get("name", "Hair %d" % (index + 1))
		"face":
			return face_style(index).get("name", "Face %d" % (index + 1))
		"celebration":
			return celebration(index).get("name", "Celebration %d" % (index + 1))
	return "%s %d" % [TranslationServer.translate(SLOT_LABELS.get(slot, slot.capitalize())), index + 1]


## Every slot present and in range. A card doc can be missing a slot (it
## predates it) or carry one rolled by a newer build than this one; both
## would otherwise read as "changed" the moment a customize screen wrote the
## look back, and get charged for.
static func normalize(appearance: Dictionary) -> Dictionary:
	var result := {}
	for slot in SLOTS:
		var value = appearance.get(slot)
		var index: int = value if typeof(value) in [TYPE_INT, TYPE_FLOAT] else 0
		result[slot] = clampi(index, 0, option_count(slot) - 1)
	return result


## How many options a slot has. Derived from the lists above rather than
## written out, so it can never drift from the data -- unlike the server's
## copy, which has to be kept in step by hand.
static func option_count(slot: String) -> int:
	match slot:
		"skin_tone":
			return SKIN_TONES.size()
		"hair_color":
			return HAIR_COLORS.size()
		"shoe_color":
			return SHOE_COLORS.size()
		"hair_style":
			return HAIR_STYLES.size()
		"face":
			return FACE_STYLES.size()
		"celebration":
			return CELEBRATIONS.size()
	return 1


## One hair style by index, clamped. A card generated by a NEWER build than
## this one can carry an index this build has no option for; it falls back
## to a plain short cap rather than rendering a bald head or erroring.
static func hair_style(index: int) -> Dictionary:
	if index < 0 or index >= HAIR_STYLES.size():
		return HAIR_STYLES[1]
	return HAIR_STYLES[index]


static func face_style(index: int) -> Dictionary:
	if index < 0 or index >= FACE_STYLES.size():
		return FACE_STYLES[0]
	return FACE_STYLES[index]


## One celebration recipe by index, clamped to the arms-up wave -- the
## same fallback a card from before this slot existed gets.
static func celebration(index: int) -> Dictionary:
	if index < 0 or index >= CELEBRATIONS.size():
		return CELEBRATIONS[0]
	return CELEBRATIONS[index]


## A deterministic look derived from a player_id alone, the safety net for
## a doc with no appearance field. Real cards carry their own rolled one,
## and every live card has been backfilled, so this is a last resort.
static func mock_from_id(player_id: String) -> Dictionary:
	var appearance := {}
	for slot in SLOTS:
		appearance[slot] = _mock_index(player_id, slot)
	return appearance


## Each slot hashes the id with its own salt rather than splitting one hash
## into 6 pieces (e.g. via division/modulo) -- independent hashes avoid any
## risk of the 6 slots correlating with each other for a given id.
static func _mock_index(player_id: String, slot: String) -> int:
	return abs((player_id + "_" + slot).hash()) % option_count(slot)
