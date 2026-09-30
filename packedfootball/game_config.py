"""Every static rule the game is built on, on one screen.

Pitch and goal geometry, the formations, the position families, the card
tiers, the appearance slots, a new account's starting balances: anything
more than one module -- or the client -- has to agree on lives here, so it
is read and changed in one place

Pure data on purpose: it imports nothing from the package.

What stays where it is: a tunable only one module reads. The match
engine's balance constants in gameEngine.py, how a card's stats are rolled
in packEngine.py, the catalogs in pack_database.py / deal_database.py, the
replay wire format in replay.py.


### SUPER IMPORTANT ###

Mirrored on the client -- change both ends together:
  PITCH_* / GOAL_*            mobile/scripts/screens/MatchPlayback.gd
  FORMATIONS, POSITION_GROUPS mobile/scripts/data/Formations.gd
  tier_family                 mobile/scripts/data/PlayerCard.gd
  APPEARANCE_*                mobile/scripts/data/PlayerAppearance.gd
  RATED_MATCHES_FOR_AVERAGE   mobile/scripts/data/PlayerCard.gd
"""

from typing import Final

# =============================================================================
# Pitch and goal
# =============================================================================
#
# Pitch units. y runs goal to goal: team A defends y = 0 and attacks
# y = PITCH_HEIGHT. The goal mouth is centred on x = PITCH_WIDTH / 2.

### CHANGING THE WIDTH AND HEIGHT BREAKES FORMATIONS, BEWARE

PITCH_WIDTH: Final[float] = 70.0
PITCH_HEIGHT: Final[float] = 100.0
GOAL_WIDTH: Final = 7.5
GOAL_HEIGHT: Final = 2.5
GOAL_POST_RADIUS: Final = 0.25
# Units/s^2 on the ball's vertical velocity: a kicked ball rises and falls in an arc.
BALL_GRAVITY: Final = 9.8
HEAD_CONTACT_HEIGHT: Final = 1.9
# Speed kept per second: on the ground, and in the air for a lofted ball
# (cross/clearance -- gameEngine.LOFTED_EVENTS).
BALL_GROUND_FRICTION: Final = 0.5
BALL_AIR_FRICTION: Final = 0.85

# A cross arrives at head height after cross_flight(distance) seconds: the
# engine launches it on that, and the crosser leads his runner by it. Flat and
# quick into a clear lane; lofted over a body in it, and for set pieces.
CROSS_FLIGHT_REF_SPEED: Final = 30.0
CROSS_FLIGHT_MIN: Final = 0.6
CROSS_FLIGHT_MAX: Final = 1.4
LOFTED_CROSS_REF_SPEED: Final = 22.0
LOFTED_CROSS_MIN: Final = 0.8
LOFTED_CROSS_MAX: Final = 1.8
CROSS_MAX_SPEED: Final = 32.0
CROSS_LANE_WIDTH: Final = 1.5   # an opponent this near the line lofts it


def cross_flight_max(lofted: bool = False) -> float:
    return LOFTED_CROSS_MAX if lofted else CROSS_FLIGHT_MAX


def cross_flight(dist: float, lofted: bool = False) -> float:
    if lofted:
        return min(LOFTED_CROSS_MAX, max(LOFTED_CROSS_MIN, dist / LOFTED_CROSS_REF_SPEED))
    return min(CROSS_FLIGHT_MAX, max(CROSS_FLIGHT_MIN, dist / CROSS_FLIGHT_REF_SPEED))


# =============================================================================
# Match feel
# =============================================================================
#
# The dials that decide how the game moves. Here rather than in gameEngine.py
# because base speed is read by BOTH the engine and the decision layer (it was
# duplicated in the two, which is how the values drift apart), and because
# these are the first things anyone tunes.

# Units per second at speed_mod 1.0, before the speed stat and fatigue scale it.
PLAYER_BASE_SPEED: Final = 10.0

# How near the ball a player must be to take it. The ball snaps to whoever wins
# it, so this is also how far it visibly jumps on a capture -- keep it tight.
POSSESSION_RADIUS: Final = 1.0

# Minimum distance between two players' centres. Wide bodies jam the middle and
# passes hit legs.
PLAYER_RADIUS: Final = 0.6


# =============================================================================
# Corners
# =============================================================================

CORNER_DEFENDING_BASE_Y: Final = 8.0
CORNER_DEFENDING_VAR_Y: Final = 3.0

CORNER_ATTACKING_BASE_Y: Final = 12.0
CORNER_ATTACKING_VAR_Y: Final = 10.0


# =============================================================================
# Penalties
# =============================================================================
#
# Read by BOTH the match engine's _resolve_penalty and the shootout minigame, so
# they live here rather than in either -- a spot kick has to mean the same thing
# in a match and in a shootout.
#
# A penalty is a guessing game, not a shot: the taker picks a corner, the keeper
# independently picks one, and the keeper only gets a save roll if he guessed
# right. Both scales floor at 0.80, so even a poor taker mostly hits his spot
# and even a poor keeper saves the ones he reads -- which is what keeps
# conversion in the 60-70% band while still rewarding the good ones.
PENALTY_PLACEMENT_MIN: Final = 0.80
PENALTY_PLACEMENT_SPAN: Final = 0.19
PENALTY_SAVE_MIN: Final = 0.80
PENALTY_SAVE_SPAN: Final = 0.19
PENALTY_SIDES: Final = (-1, 0, 1)    # left / middle / right, from the taker
PENALTY_CERTAINTY_CAP: Final = 0.99  # nobody is ever a sure thing, items or not
# Distance from the goal line to the spot.
PENALTY_SPOT_DISTANCE: Final = 11.0
# How hard a spot kick is struck, in units/second.
PENALTY_SHOT_SPEED: Final = 26.0
# Frames the staged scene holds before he strikes it (the run-up).
PENALTY_SETUP_FRAMES: Final = 10

# A full-stretch dive in lateral units, and the share of it a keeper covers
# when he commits to a corner. Shared so a dive carries the same distance in a
# shootout as in a match -- the shootout scaled it off the goal's half-width
# instead and came up short of the corners it was diving for.
KEEPER_REACH: Final = 6.2
PENALTY_KEEPER_DIVE_FRACTION: Final = 0.7


# =============================================================================
# Direct free kicks
# =============================================================================
#
# Physics, not a roll: read by gameEngine and the free-kick minigame through
# free_kick.py. Pairs are (at ability 0, at ability 1). Tune against
# scripts/free_kick_report.py (`make fk-report`).
WALL_DISTANCE: Final = 9.15
WALL_PLAYERS: Final = 3
FREE_KICK_SHOT_SPEED: Final = (24.0, 31.0)   # units/s, from power
# Side spin turns the ball FK_MAGNUS_SIDE rad/s per unit; top spin adds
# FK_MAGNUS_TOP * speed of downward pull. Spin fades to FK_SPIN_DECAY a second.
FK_MAGNUS_SIDE: Final = 0.25
FK_MAGNUS_TOP: Final = 0.50
FK_SPIN_DECAY: Final = 0.7
FK_SIDE_SPIN: Final = (0.6, 1.0)
FK_TOP_SPIN: Final = (0.6, 1.0)
# Where the AI aims: this far inside the post, at this height.
FK_AIM_INSET: Final = 0.9
FK_AIM_HEIGHT_OVER: Final = 1.7
FK_AIM_HEIGHT_AROUND: Final = 1.1
# Execution error at technique 0, scaled down by (1 - ability).
FK_AIM_ERROR_DEG: Final = 15.0
FK_LIFT_ERROR: Final = 3.5
FK_SPIN_ERROR: Final = 0.5
# Off his line to deal with a ball into the box: further the likelier that
# is (gameEngine._fk_pass_chance, 0 -> 1). A shot can go over him from there.
FK_KEEPER_OFF_LINE: Final = (2.5, 5.0)
# The keeper reads it this long after he can see it past the wall (his eyes at
# FK_KEEPER_EYE_HEIGHT), then moves across at his dive speed.
FK_KEEPER_REACTION: Final = (0.40, 0.18)
FK_KEEPER_REACTION_JITTER: Final = 0.05
FK_KEEPER_EYE_HEIGHT: Final = 1.7
FK_KEEPER_DIVE_SPEED: Final = (4.0, 8.0)
FK_KEEPER_ARM_REACH: Final = 1.5
FK_KEEPER_CATCH_REACH: Final = 0.7
FK_CATCH_SPEED: Final = (18.0, 28.0)         # hardest ball he holds, from handling
FK_BODY_RADIUS: Final = 0.45
FK_BODY_RESTITUTION: Final = 0.3
FK_PARRY_RESTITUTION: Final = 0.35
FK_FLIGHT_MAX_FRAMES: Final = 150


# =============================================================================
# Positions
# =============================================================================

# The four position families a pack's pos_rates roll over, and which
# positions each one picks from (with the weights the roll uses). Also what
# /leaderboard/players filters by when asked for "defender" rather than one
# exact position.
POSITION_CATEGORIES = {
    "goalkeeper": {"GK": 1.0},
    "defender": {"CB": 0.40, "LB": 0.20, "RB": 0.20, "RWB": 0.10, "LWB":0.10},
    "midfielder": {"CDM": 0.20, "CM": 0.30, "CAM": 0.20, "LM": 0.15, "RM": 0.15},
    "attacker": {"ST": 0.50, "LW": 0.25, "RW": 0.25},
}

# Which positions can stand in for each other at a penalty rather than
# being blocked outright -- see formations.is_similar_position. Two
# positions are "similar" when they share at least one of these groups.
POSITION_GROUPS = [
    {"CDM", "CM"},
    {"CM", "CAM"},
    {"LB", "LWB", "LM", "LW"},
    {"RB", "RWB", "RM", "RW"},
    {"LW", "RW", "ST"},
    {"RM", "CM"},
    {"LM", "CM"},
]


# =============================================================================
# Formations
# =============================================================================
#
# Each base lists team A's eleven, in slot order (the keeper first), as pitch
# coordinates in their own half plus the slot's role. Team B is the same
# shape mirrored through the centre spot -- see _mirror_formation. The
# client's Formations.gd carries the same eleven for each name.

DEFAULT_FORMATION = "4-4-2"


def _mirror_formation(team_a_data):
    """
    Generates a full 22-player dictionary from 11 base positions.
    Returns: { index: {"pos": [x, y], "role": "ROLE_NAME"} }
    """
    formation = {}
    
    for i, data in enumerate(team_a_data):
        x, y = data["pos"]
        role = data["role"]
        
        # Team A (Indices 0-10)
        formation[i] = {
            "pos": [float(x), float(y)],
            "role": role
        }
        
        # Team B (Indices 11-21) - Mirrored across both axes
        formation[i + 11] = {
            "pos": [float(PITCH_WIDTH - x), float(PITCH_HEIGHT - y)],
            "role": role
        }
        
    return formation


_442_base = [
    {"pos": [35.0, 5.0],  "role": "GK"},
    {"pos": [12.0, 20.0], "role": "LB"},
    {"pos": [27.0, 15.0], "role": "CB"},
    {"pos": [43.0, 15.0], "role": "CB"},
    {"pos": [58.0, 20.0], "role": "RB"},
    {"pos": [12.0, 40.0], "role": "LM"},
    {"pos": [27.0, 35.0], "role": "CM"},
    {"pos": [43.0, 35.0], "role": "CM"},
    {"pos": [58.0, 40.0], "role": "RM"},
    {"pos": [27.0, 47.0], "role": "ST"},
    {"pos": [43.0, 47.0], "role": "ST"},
]

_433_base = [
    {"pos": [35.0, 5.0],  "role": "GK"},
    {"pos": [12.0, 20.0], "role": "LB"},
    {"pos": [27.0, 15.0], "role": "CB"},
    {"pos": [43.0, 15.0], "role": "CB"},
    {"pos": [58.0, 20.0], "role": "RB"},
    {"pos": [35.0, 23.0], "role": "CDM"}, 
    {"pos": [25.0, 30.0], "role": "CM"},
    {"pos": [45.0, 30.0], "role": "CM"},
    {"pos": [15.0, 44.0], "role": "LW"},
    {"pos": [55.0, 44.0], "role": "RW"},
    {"pos": [35.0, 47.0], "role": "ST"},
]

_352_base = [
    {"pos": [35.0, 5.0],  "role": "GK"},
    {"pos": [18.0, 15.0], "role": "CB"},
    {"pos": [35.0, 12.0], "role": "CB"},
    {"pos": [52.0, 15.0], "role": "CB"},
    {"pos": [35.0, 22.0], "role": "CDM"},
    {"pos": [10.0, 32.0], "role": "LWB"},
    {"pos": [25.0, 32.0], "role": "CM"},
    {"pos": [45.0, 32.0], "role": "CM"},
    {"pos": [60.0, 32.0], "role": "RWB"},
    {"pos": [27.0, 47.0], "role": "ST"},
    {"pos": [43.0, 47.0], "role": "ST"},
]

_4231_base = [
    {"pos": [35.0, 5.0],  "role": "GK"},
    {"pos": [12.0, 20.0], "role": "LB"},
    {"pos": [27.0, 15.0], "role": "CB"},
    {"pos": [43.0, 15.0], "role": "CB"},
    {"pos": [58.0, 20.0], "role": "RB"},
    {"pos": [27.0, 28.0], "role": "CDM"},
    {"pos": [43.0, 28.0], "role": "CDM"},
    {"pos": [15.0, 38.0], "role": "LW"},
    {"pos": [35.0, 38.0], "role": "CAM"},
    {"pos": [55.0, 38.0], "role": "RW"},
    {"pos": [35.0, 47.0], "role": "ST"},
]

FORMATIONS = {
    "4-4-2": _mirror_formation(_442_base),
    "4-3-3": _mirror_formation(_433_base),
    "3-5-2": _mirror_formation(_352_base),
    "4-2-3-1": _mirror_formation(_4231_base),
}


# =============================================================================
# Card tiers
# =============================================================================

# =============================================================================
# Stat scale
# =============================================================================
#
# The top of the attribute axis. Cards roll to 96 (TIER_RANGES); the space
# above is what items and boosters buy. The client needs this too once
# items land -- it has no copy yet.
STAT_CEILING: Final = 130

# Raw stat -> 0..1 ability. Linear made a 50 exactly half a 100, and those
# deficits compound until a bronze card cannot function as a footballer.
# A gamma below 1 lifts the weak end without touching the strong end.
# 1.0 reproduces the old straight line exactly.
#
# Not the lever for a sterile bottom tier -- 0.75 was tried and cost silver and
# gold ~0.4 goals each while leaving bronze where it was (4.0.0 History).
STAT_CURVE_GAMMA: Final = 0.8

# Slope. Below 1 it squeezes the spread toward STAT_CURVE_PIVOT, so a weak card
# closes on a strong one WITHOUT the whole game speeding up (which is what
# gamma alone does). The pivot sits near a gold card, so gold is the fixed point.
STAT_CURVE_COMPRESS: Final = 0.70
STAT_CURVE_PIVOT: Final = 0.72


# Ball speed one kick-power unit buys (gameEngine.base_kick_pow).
BASE_KICK_POW: Final = 20.0

# A rolling ball covers speed / -ln(BALL_GROUND_FRICTION) units before it stops.
# Passes used to saturate at 10 units of distance and then get MULTIPLIED by the
# power stat, so anything past 10 units flew ~3x too far: sideways balls ran out
# of play and arrived far too fast to be controlled. Size the kick from the
# distance instead and let power CAP it, the way crosses already work.
# How fast the ball should still be going when it reaches the target. This is
# the whole trade-off: it sets how much pace a pass carries (beating a
# pressing defender) AND how far past the receiver it runs if nobody collects
# it -- overshoot is arrive * 1.44 units, whatever the distance.
PASS_ARRIVE_SPEED: Final = 22.0


def pass_power(dist: float, power_stat: float, urgency: float = 1.0,
               max_div: float = 60.0, arrive: float | None = None) -> float:
    import math
    per_unit = -math.log(BALL_GROUND_FRICTION)
    av = PASS_ARRIVE_SPEED if arrive is None else arrive
    needed = (av + dist * per_unit * urgency) / BASE_KICK_POW
    return max(0.05, min(needed, power_stat / max_div))


# How much of `defending` becomes a player's press-vs-contain rate. Pressing is
# defending's job; aggression only sets how often they commit to a tackle. The
# scale is what holds the rate where it was -- defending's mean is about double
# aggression's, so a raw swap tripled it. Gives bronze 28% up to icon 42%.
PRESS_FROM_DEFENDING: Final = 0.55

# Recovery run: a defender or midfielder the carrier has got past sprints back
# goal-side of him (player._recovery_run). Pace x RECOVERY_SPRINT, plus up to
# RECOVERY_DEFENDING_BONUS more from the defending stat.
RECOVERY_SPRINT: Final = 1.2
RECOVERY_DEFENDING_BONUS: Final = 0.15
RECOVERY_RANGE: Final = 25.0          # only this near the ball; further is shape
RECOVERY_BEATEN_MARGIN: Final = 1.0   # the ball this far goal-side of him
RECOVERY_LEAD_SECONDS: Final = 0.35   # run to where the carrier is going
RECOVERY_GOAL_SIDE: Final = 2.0       # ...and this far inside him, toward goal
# Until the carrier is within RECOVERY_PRESS_RANGE, a recovering player runs to
# his LANE on a line goal-side of the ball, not at the ball: formation x pulled
# toward the ball by RECOVERY_LANE_PULL (never more than RECOVERY_LANE_MAX_SHIFT),
# centre-backs kept within RECOVERY_CB_LANE of the middle. Defenders hold the
# line RECOVERY_LINE_DEPTH goal-side of the ball; midfielders level with it.
RECOVERY_PRESS_RANGE: Final = 8.0
RECOVERY_LINE_DEPTH: Final = 4.0
RECOVERY_MIN_DEPTH: Final = 6.0       # the line never drops inside this
RECOVERY_CB_LANE: Final = 10.0
RECOVERY_LANE_MAX_SHIFT: Final = 15.0
RECOVERY_LANE_PULL: Final = {"CB": 0.25, "LB": 0.65, "RB": 0.65, "LWB": 0.65, "RWB": 0.65}
RECOVERY_LANE_PULL_DEFAULT: Final = 0.45
LINE_ROLES: Final = frozenset({"CB", "LB", "RB", "LWB", "RWB"})
# How hard a role tracks back, times the sprint. 0 = no recovery run: beaten,
# he holds his position. Anyone unlisted (defenders, CDM) runs flat out.
RECOVERY_ROLE_EFFORT: Final = {"CAM": 0.0, "LM": 0.0, "RM": 0.0, "CM": 0.9}


# Pace only. Even a poor footballer is quick -- what they lack is technique --
# so the speed spread is narrowed while shooting/passing/control keep theirs.
# This is what stops a better card simply outrunning you to every ball.
SPEED_COMPRESS: Final = 0.60
SPEED_PIVOT: Final = 0.72


def pace_ability(stat: float, compress: float | None = None) -> float:
    a = stat_ability(stat)
    c = SPEED_COMPRESS if compress is None else compress
    if c != 1.0:
        a = SPEED_PIVOT + (a - SPEED_PIVOT) * c
    return max(0.0, a)


# What one point above 100 is worth, as a fraction of a point below it. Cards
# roll to 96; everything past that is items and boosters, and it has to be
# worth owning without letting a kitted bronze outrun an icon.
# A full +30 to STAT_CEILING buys 10.5% -- real, but a third of what the same
# 30 points buy on the base axis.
STAT_OVERDRIVE: Final = 0.35


def stat_ability(stat: float, gamma: float | None = None, compress: float | None = None) -> float:
    """Raw stat -> ability. 1.0 at 100, and it KEEPS RISING above that.

    Everything past 100 comes from items, so the tail is what makes them
    worth owning; clipping here is what made them do nothing at all.
    Callers that need a probability clamp their own result -- see
    _resolve_penalty -- because a fraction of an ability is not a chance.
    """
    raw = max(0.0, float(stat))
    a = min(1.0, raw / 100.0)
    g = STAT_CURVE_GAMMA if gamma is None else gamma
    if g != 1.0:
        a = a ** g
    c = STAT_CURVE_COMPRESS if compress is None else compress
    if c != 1.0:
        a = STAT_CURVE_PIVOT + (a - STAT_CURVE_PIVOT) * c
    return max(0.0, min(1.0, a) + max(0.0, raw - 100.0) / 100.0 * STAT_OVERDRIVE)


### SUPER IMPORTANT ###
# Every tier a card can be rolled at, with its overall range.
#
# A key is "<family>" or "<family>_<variant>". The family is the RARITY --
# what release value, card colour, ordering and the pack-odds disclosure go
# by (tier_family() is that collapse) -- and a variant is a themed edition
# of it with its own range and its own card art
# (mobile/sprites/player_cards/<tier>.png). So special_champ is a special,
# and a future diamond_turkish would be a diamond. A new variant is one
# entry here plus a sprite, and nothing else needs to know it exists; a new
# FAMILY also needs a row in the family tables (backend/config.RELEASE_CREDITS_BY_TIER,
# PlayerCard.TIER_COLORS / RELEASE_CREDITS).
#
# Plain "special" is the family's own baseline
#
# NON-OVERLAPPING, and they must stay that way -- diamond (75,82) against
# special (80,85) meant half of each tier rolled inside the other.
TIER_RANGES = {
    "bronze": (52, 60),
    "silver": (60, 67),
    "gold": (67, 74),
    "platinum": (74, 80),
    "diamond": (79, 83),
    "special": (83, 86),
    "special_conf": (84, 87),
    "special_cont": (85, 88),
    "special_champ": (86, 89),
    "icon": (89, 92)
}


def tier_family(tier: str) -> str:
    """The rarity a tier string counts as: everything before the first "_",
    so "special_champ" -> "special", "diamond_turkish" -> "diamond", and a
    plain tier is itself. Mirrored by PlayerCard.tier_family() on the client."""
    return str(tier).split("_", 1)[0]


# =============================================================================
# Appearance
# =============================================================================

# Layered character appearance: 6 independent slots, each an INDEX into an
# option list that lives client-side in mobile/scripts/data/
# PlayerAppearance.gd. This end only rolls the indices -- it has no idea what
# a hairstyle looks like, and doesn't need to. "celebration" is the goal
# celebration the client plays for this player after they score -- rolled
# and stored like any other look, just animated rather than drawn once.
#
# The counts below must not exceed what the client actually has options for,
# or a card gets an index that renders as a fallback. They are per-slot (not
# one shared number) precisely so a slot can grow on its own: ship N new
# hairstyles in PlayerAppearance.HAIR_STYLES, raise "hair_style" here, deploy.
#
# APPEND ONLY. An index is stored on every players/{id} doc forever, so
# inserting or reordering options silently restyles every card already out
# there. New options go on the end of the client's array, and the count here
# goes up to match.
#
# Real players always get one rolled by packEngine.PackManager;
# DEFAULT_APPEARANCE only backstops a player object built without going
# through that (e.g. reconstructing a doc saved before this field existed).
APPEARANCE_SLOTS = ("skin_tone", "hair_style", "hair_color", "face", "shoe_color", "celebration")
APPEARANCE_OPTION_COUNTS = {
    "skin_tone": 5,   # PlayerAppearance.SKIN_TONES
    "hair_style": 5,  # PlayerAppearance.HAIR_STYLES
    "hair_color": 5,  # PlayerAppearance.HAIR_COLORS
    "face": 5,        # PlayerAppearance.FACE_STYLES
    "shoe_color": 5,  # PlayerAppearance.SHOE_COLORS
    "celebration": 9, # PlayerAppearance.CELEBRATIONS
}
DEFAULT_APPEARANCE = {slot: 0 for slot in APPEARANCE_SLOTS}


# =============================================================================
# Careers
# =============================================================================

# A card's career average rating is rating_sum / rating_count, and Firestore
# can't order on a quotient -- so once a card has been rated this many
# times, record_match also writes the average out as statistics.avg_rating,
# which /leaderboard/players can sort on. Below the threshold the key is
# absent (not zero): a 9.5 from a single match must not top the board, and
# a doc without the field is simply left out of an ordered query.
RATED_MATCHES_FOR_AVERAGE = 5


# =============================================================================
# A new account
# =============================================================================

DEFAULT_STARTING_CREDITS = 1000
DEFAULT_STARTING_BUCKS = 10
DEFAULT_STARTING_MEDALS = 0
# "" means "no kit chosen, renderer picks" -- see game_state.GameState.
# load_or_create_profile's docstring for why this end deliberately doesn't
# spell out a default shirt.
DEFAULT_KIT = ""
