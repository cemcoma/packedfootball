from game_config import (  # noqa: F401 -- the appearance/career names are re-exported from here
    APPEARANCE_OPTION_COUNTS,
    APPEARANCE_SLOTS,
    BALL_AIR_FRICTION,
    BALL_GRAVITY,
    DEFAULT_APPEARANCE,
    HEAD_CONTACT_HEIGHT,
    PITCH_HEIGHT,
    PITCH_WIDTH,
    PLAYER_BASE_SPEED,
    RATED_MATCHES_FOR_AVERAGE,
    LINE_ROLES,
    RECOVERY_BEATEN_MARGIN,
    RECOVERY_CB_LANE,
    RECOVERY_DEFENDING_BONUS,
    RECOVERY_GOAL_SIDE,
    RECOVERY_LANE_MAX_SHIFT,
    RECOVERY_LANE_PULL,
    RECOVERY_LANE_PULL_DEFAULT,
    RECOVERY_LEAD_SECONDS,
    RECOVERY_LINE_DEPTH,
    RECOVERY_MIN_DEPTH,
    RECOVERY_PRESS_RANGE,
    RECOVERY_RANGE,
    RECOVERY_ROLE_EFFORT,
    RECOVERY_SPRINT,
    STAT_CEILING,
    CROSS_LANE_WIDTH,
    cross_flight,
    pace_ability,
    stat_ability,
    pass_power,
    take_on_skill,
    BASE_KICK_POW,
    DEFAULT_TACTIC,
    TACTICS,
)
from dataclasses import dataclass, asdict
from typing import Final
from abc import ABC, abstractmethod
import numpy as np
import math

position = ["GK","CD","LB","RB","CDM","CM","CAM","LM","RM","CF","LW","RW"]
base_speed: Final = PLAYER_BASE_SPEED   # see game_config: shared with gameEngine


# Minimum spread (in pitch units at the goal line) on any shot's aim -- see
# _calculate_shot.
SHOT_VARIANCE_FLOOR = 0.25
# Aim error is units at the goal line, so it shrinks as he closes in: times
# dist / SHOT_ACCURACY_RANGE inside that range, never below SHOT_CLOSE_ACCURACY.
SHOT_ACCURACY_RANGE = 20.0
SHOT_CLOSE_ACCURACY = 0.35
# Nobody between him and the keeper and still further out than
# SHOT_PATIENCE_RANGE: carry it on for a better one (shoot weight x SHOT_PATIENCE).
SHOT_PATIENCE_RANGE = 10.0
SHOT_PATIENCE = 0.5
KEEPER_ZONE_DEPTH = 4.0     # the lane is checked up to this far off the goal line
CROSS_ERROR_FLOOR = 0.4
# Cross aim error per axis: (100 - crossing) / CROSS_ERROR_DIVISOR units. At 15 a
# 70 crosser missed his spot by ~2 units, beyond a header's reach of his runner.
CROSS_ERROR_DIVISOR = 30.0

# A rolling ball loses this much speed per unit travelled (-ln of the ground
# friction), and how far ahead of a runner a pass may be played.
PASS_DECAY_PER_UNIT = 0.6931
PASS_MAX_LEAD_SECONDS = 1.2

# The opposition box, as gameEngine's in_boxes draws it: a cross is aimed only
# at a runner inside it when the ball arrives. See _cross_candidates.
BOX_X_MIN: Final = 14.0
BOX_X_MAX: Final = 56.0
CROSS_TARGET_DEPTH: Final = 18.0

# The cross comes late: a winger in the zone carries on to CROSS_LATE_DEPTH off
# the goal line unless CROSS_READY_RUNNERS are already in the box or he is being
# closed down. A box run is timed to that: arrive at the spot (BOX_RUN_SPOT_DEPTH,
# near or far post) as the carrier gets there, never past the offside line,
# sprinting at most BOX_RUN_SPRINT.
CROSS_LATE_DEPTH: Final = 10.0
CROSS_READY_RUNNERS: Final = 2
BOX_RUN_SPOT_DEPTH: Final = 10.0
BOX_RUN_SPRINT: Final = 1.3
OFFSIDE_MARGIN: Final = 0.5

# How close to goal a wide player must be before an open lane inside is
# worth leaving the touchline for. Below ~26 it never fires: that close from
# the touchline is already the crossing zone. See _decide_wingplay.
CUT_INSIDE_RANGE: Final = 38.0

# How near the middle counts as having cut in: the drive ends here and the
# full menu (shoot, pass) takes over again.
CUT_INSIDE_DONE_X: Final = 9.0

# Clearances: how far off his facing a man can hit one, how much he angles
# it at the touchline, and how far he tries to put it.
CLEAR_MAX_TURN: Final = math.radians(90.0)
CLEAR_WIDE_BIAS: Final = 0.9
CLEAR_DISTANCE: Final = 30.0

@dataclass
class Attributes: #out of 100, can be over
    #Physical attributes
    stamina: int = 60
    speed: int = 60
    agility: int = 50
    passing: int = 50
    ballcontrol: int = 50
    defending: int = 50
    tackling: int = 70
    dribbling: int = 30
    shooting: int = 50
    power: int = 80
    accuracy: int = 80
    vision:int = 60
    heading: int = 50

    # Centimetres, not a 0-100 skill. Standing reach for headers (see
    # gameEngine._head_reach). See PHYSICAL_FIELDS below for why it is kept
    # out of the overall calculation.
    height: int = 180

    #Tendencies
    pass_tendency: int = 50
    shoot_tendency: int = 50
    drible_tendency: int = 60
    aggression: int = 40
    composure: int = 70
    clear_tendency:int = 10

    def __post_init__(self):
        # The one gate every attribute passes through: generation, Firestore,
        # the out-of-position copy, and items. Height is centimetres, not a skill.
        for field in self.__dataclass_fields__:
            if field in PHYSICAL_FIELDS:
                continue
            value = getattr(self, field)
            if value < 0 or value > STAT_CEILING:
                setattr(self, field, int(min(STAT_CEILING, max(0, value))))

TENDENCY_FIELDS = {
    "pass_tendency", "shoot_tendency", "drible_tendency",
    "aggression", "composure", "clear_tendency"
}


PHYSICAL_FIELDS = {"height"}


DEFAULT_STATISTICS = {
    "goals": 0,
    "assists": 0,
    "matches_played": 0,
    "shots": 0,
    "shots_on_target": 0,
    "passes": 0,
    "passes_completed": 0,
    "tackles": 0,
    "tackles_won": 0,
    "saves": 0,
    "clean_sheets": 0,
    "goals_conceded": 0,
    "fouls": 0,
    "interceptions": 0,
    "clearances": 0,
    "blocks": 0,
    "rating_sum": 0.0,
    "rating_count": 0,
}


# RATED_MATCHES_FOR_AVERAGE: see game_config.py (imported above).

MATCH_STAT_FIELDS = (
    "shots",
    "shots_on_target",
    "passes",
    "passes_completed",
    "tackles",
    "tackles_won",
    "saves",
    "goals_conceded",
    "clean_sheets",
    "fouls",
    "interceptions",
    "clearances",
    "blocks",
)

# APPEARANCE_SLOTS / APPEARANCE_OPTION_COUNTS / DEFAULT_APPEARANCE: see
# game_config.py (imported above).

DEFAULT_ACTIONS = {
    "stop", "shoot", "pass", "clear", "cross", "dribble",
    "forward_run", "support", "hold_attack", "hold_defense",
    "press", "contain", "recover", "recover_slow", "tackle", "capture",
}


def _norm2(v) -> float:
    """|v| for a 2-vector. np.linalg.norm spends more on call overhead than
    on the arithmetic at this size, and the decision code calls this
    hundreds of thousands of times a match."""
    return math.hypot(float(v[0]), float(v[1]))


_BALANCED = TACTICS[DEFAULT_TACTIC]

# A long ball (Tactic.long_ball) goes to the furthest man forward, if he is at
# least LONG_BALL_MIN_GAIN ahead, as far as the kicker's power reaches.
LONG_BALL_MIN_GAIN: Final = 20.0
LONG_BALL_REACH: Final = (35.0, 55.0)   # units at power 40 / 90
# Against a line at least LONG_BALL_ROOM off its goal it goes over the top instead,
# LONG_BALL_BEHIND past the line in his lane -- a race a quick striker wins.
LONG_BALL_ROOM: Final = 20.0
LONG_BALL_BEHIND: Final = 8.0

# Runs in behind: a forward holds the shoulder of the line, onside by IN_BEHIND_ONSIDE,
# when there is room behind it and he has the legs; passers look for him and play it
# IN_BEHIND_LEAD past the line in his lane (_in_behind_target).
IN_BEHIND_KEEPER_ZONE: Final = 12.0   # room behind the line counts from here -- the keeper's
IN_BEHIND_ROOM_FULL: Final = 20.0     # this much room makes the run fully worth making
IN_BEHIND_PACE_GAIN: Final = 15.0     # per point of pace_ability over the defender beside him
IN_BEHIND_WEIGHT: Final = 60.0
IN_BEHIND_ONSIDE: Final = 1.5         # the line moves between his decisions
IN_BEHIND_CHANNEL: Final = 3.0        # stood this far beside the defender, not behind him
IN_BEHIND_SHOULDER: Final = 4.0       # a teammate within this of the line, onside, is on it
IN_BEHIND_LEAD: Final = 10.0
IN_BEHIND_REACH: Final = 45.0
IN_BEHIND_PASS_BIAS: Final = 1.2      # any midfielder looks for the run, not only a CAM
TARGET_MAN_WEIGHT: Final = 150.0      # a Tactic.target_man striker's pull to stay on their line
TARGET_MAN_ROLES: Final = ("ST", "CF")
# A pass to a man stood offside: how much it costs in the passer's choice. The vision
# noise on that choice still lets a poor reader play it now and then.
OFFSIDE_PASS_PENALTY: Final = 200.0
# The wall pass: the man who just gave it to me and is running on (state["give_and_go"]).
GIVE_AND_GO_BONUS: Final = 120.0
GIVE_AND_GO_PASS_WEIGHT: Final = 60.0   # ...and how much more I lean towards passing at all
GIVE_AND_GO_FREE: Final = 3.0            # he's free if nobody is this close to him
# A full-back overlapping me (state["overlap"]): his pull in my pass choice, and once a man is
# within OVERLAP_ENGAGED of me, the lean to passing -- or, on a wing run, the chance I release him.
OVERLAP_BONUS: Final = 120.0
OVERLAP_PASS_WEIGHT: Final = 60.0
OVERLAP_ENGAGED: Final = 5.0
OVERLAP_RELEASE: Final = 0.5

# Pressing or containing the man on the ball: between him and my goal, GOAL_SIDE_PRESS (in
# tackling range) or GOAL_SIDE_CONTAIN (jockeying) off where he will be when I get there -- at
# most GOAL_SIDE_LEAD seconds on. Running at where he WAS, a quicker man was simply gone.
GOAL_SIDE_PRESS: Final = 1.0
GOAL_SIDE_CONTAIN: Final = 3.0
GOAL_SIDE_LEAD: Final = 1.0
# A midfielder's or forward's own spot is never closer than this to his centre-backs' line:
# nobody but the back line stands behind it -- unless a loose ball is coming at our goal faster
# than BALL_COMING_SPEED, when everybody gets back as before (the back line too, defender._hold_line_y).
BACK_LINE_GAP: Final = 6.0
BALL_COMING_SPEED: Final = 2.0

# Going round the man (take_on): the nearest opponent goal-side within TAKE_ON_RANGE, with nobody
# covering goal-side of him within TAKE_ON_COVER, is beaten on the clearer side -- TAKE_ON_WIDTH to
# that side and TAKE_ON_BEYOND past him, a spot at least TAKE_ON_SPACE from anyone else.
TAKE_ON_RANGE: Final = 5.0
TAKE_ON_COVER: Final = 6.0
TAKE_ON_WIDTH: Final = 3.0
TAKE_ON_BEYOND: Final = 2.0
TAKE_ON_SPACE: Final = 2.5
TAKE_ON_WEIGHT: Final = 3.0         # per point of (take_on_skill + drible_tendency) / 2
WING_RUN_WEIGHT: Final = 100.0      # a latched wing run's weight against a take-on

# Carrying it across (carry_across): with the shot shut from here, the man on the ball carries it
# ACROSS_DIST sideways at the same depth, inside the box's width, to a spot the shot is on from.
# A shot's lane is SHOT_LANE_WIDTH wide, checked up to KEEPER_ZONE_DEPTH short of goal. From the
# edge -- outside the box, within EDGE_SHOT_RANGE -- a forward shoots only with that lane open.
ACROSS_DIST: Final = 8.0
ACROSS_WEIGHT: Final = 2.0          # per point of (shoot_tendency + vision) / 2
ACROSS_PACE: Final = 0.8            # of his dribbling pace: carrying it, not running with it
SHOT_LANE_WIDTH: Final = 1.5
EDGE_SHOT_RANGE: Final = 26.0
EDGE_SHOT_PENALTY: Final = 2.0      # per unit out, against the 20 a forward takes off with the lane shut
# Any move against a set defender leaves this much of the straight run at him.
MOVE_DRIBBLE_KEEP: Final = 0.3


# Showing for the ball (Tactic.show_in_space): the most open spot SUPPORT_SPACE_RADIUS
# from the man on it, onside and clear of teammates -- not at the ball, which drags a
# marker into the lane with him.
SUPPORT_SPACE_RADIUS: Final = 9.0
SUPPORT_SPACE_ANGLES: Final = tuple(math.radians(a) for a in (-150, -110, -70, -35, 0, 35, 70, 110, 150))
SUPPORT_SPACE_CROWD: Final = 5.0      # a teammate nearer than this to the spot has it already


def _clamp(x: float, lo: float, hi: float) -> float:
    """np.clip for one float, bit for bit (lo on a tie, like numpy), minus its call overhead."""
    x = x if x > lo else lo
    return x if x < hi else hi


def _clamp_to_pitch(x: float, y: float) -> np.ndarray:
    return np.array([_clamp(float(x), 0.0, PITCH_WIDTH), _clamp(float(y), 0.0, PITCH_HEIGHT)])


def _isclose2(a, b) -> bool:
    """np.all(np.isclose(a, b)) for 2-vectors, same tolerances."""
    return (
        abs(float(a[0]) - float(b[0])) <= 1e-8 + 1e-5 * abs(float(b[0]))
        and abs(float(a[1]) - float(b[1])) <= 1e-8 + 1e-5 * abs(float(b[1]))
    )


def _equal2(a, b) -> bool:
    """np.array_equal for 2-vectors."""
    return a[0] == b[0] and a[1] == b[1]


def _count_within(points, centre, radius: float) -> int:
    """How many rows of `points` lie closer than `radius` to `centre`."""
    cx, cy = float(centre[0]), float(centre[1])
    return sum(1 for x, y in np.asarray(points, dtype=float).tolist() if math.hypot(x - cx, y - cy) < radius)


class ActionProfile:
    """Role template for tweening action sets and decision weights per position."""
    role_name = "generic"
    allowed_actions = set(DEFAULT_ACTIONS)
    action_biases = {
        "pass": 1.0, "shoot": 1.0, "dribble": 1.0, "cross": 0.5,
        "clear": 0.5, "forward_run": 1.0, "support": 1.0,
        "hold_attack": 1.0, "hold_defense": 1.0, "press": 0.8,
        "contain": 0.8, "recover": 0.9, "recover_slow": 0.5,
        "tackle": 0.8, "capture": 0.8,
    }

    def get_allowed_actions(self, phase: str | None = None):
        actions = set(self.allowed_actions)
        if phase is not None:
            return {action for action in actions if action not in {"stop"}}
        return actions

    def get_action_biases(self):
        return dict(self.action_biases)

def _clip_lead_to_pitch(origin, unit, dist, margin=0.4):
    """Cut a lead short where the ball would leave the pitch. Aiming past the
    touchline parked the chaser ON the line (positions are clamped there) while
    the ball rolled by untouched -- so cut it out at the line instead."""
    t = float(dist)
    for axis, size in ((0, PITCH_WIDTH), (1, PITCH_HEIGHT)):
        d = float(unit[axis])
        if d > 1e-9:
            t = min(t, (size - margin - float(origin[axis])) / d)
        elif d < -1e-9:
            t = min(t, (margin - float(origin[axis])) / d)
    return origin + unit * max(0.0, t)


# -ln(BALL_GROUND_FRICTION): a rolling ball's speed decays by this per second.
BALL_DECAY_PER_SECOND: Final = 0.6931
INTERCEPT_HORIZON: Final = 2.5

# Aim this much FURTHER down the ball's path than the earliest meeting point, so
# the chaser is stood in the line waiting rather than arriving at the same
# instant as the ball. At a 1.0 possession radius, meeting it exactly means any
# error at all lets the ball straight past.
INTERCEPT_LEAD_FACTOR: Final = 1.35

# A lane is fully open once every defender is this many seconds off reaching
# it; below that, openness falls off smoothly to 0.
LANE_SAFE_MARGIN_SECONDS: Final = 0.45

# What a fully blocked lane costs a pass option. Big enough to lose to an open
# one, small enough that a tight forward ball can still beat a safe square one.
LANE_BLOCKED_PENALTY: Final = 400.0

# A wide outlet -- a teammate out on the flank (WIDE_OUTLET_X off the middle)
# in the attacking half, with the passer at least WIDE_OUTLET_INSIDE more
# central -- scores as if WIDE_PROGRESS_CREDIT further forward: the ball out
# wide is progress, since that is where the cross comes from.
WIDE_OUTLET_X: Final = 15.0
WIDE_OUTLET_INSIDE: Final = 8.0
WIDE_OUTLET_DEPTH: Final = 50.0
WIDE_PROGRESS_CREDIT: Final = 4.0


def _ball_rolled(ball_speed: float, t: float) -> float:
    """How far a rolling ball has travelled by time t."""
    return (ball_speed / BALL_DECAY_PER_SECOND) * (1.0 - (0.5 ** t))


def _ball_time_to(ball_speed: float, dist: float) -> float | None:
    """Seconds for a rolling ball to cover `dist`, or None if it stops short."""
    if ball_speed <= 1e-6:
        return None
    frac = 1.0 - (dist * BALL_DECAY_PER_SECOND / ball_speed)
    if frac <= 1e-6:
        return None
    return -math.log2(frac)


def _lane_openness(start, end, opponents, opponent_vels, opponent_paces, ball_speed):
    """0..1 for how open a passing lane is: can any opponent get to it before
    the ball does?

    Replaces a binary distance gate that called an opponent 0.99m off the line
    a blocked pass and one at 1.01m perfectly safe, ignored whether he was
    moving, and could not tell a defender near the START of the lane (no time
    to react, ball is past him) from one near the END (a full second to step
    across).
    """
    sx, sy = float(start[0]), float(start[1])
    dx, dy = float(end[0]) - sx, float(end[1]) - sy
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 1e-8 or opponents is None:
        return 1.0
    opponents = np.asarray(opponents, dtype=float)
    if opponents.size == 0:
        return 1.0
    seg_len = math.sqrt(seg_len_sq)
    vels = np.asarray(opponent_vels, dtype=float).tolist() if opponent_vels is not None else None

    worst = 1.0
    for i, (ox, oy) in enumerate(opponents.tolist()):
        projection = ((ox - sx) * dx + (oy - sy) * dy) / seg_len_sq
        clamped = min(1.0, max(0.0, projection))
        mx, my = sx + clamped * dx, sy + clamped * dy

        ball_t = _ball_time_to(ball_speed, clamped * seg_len)
        if ball_t is None:
            continue                      # ball dies before this point: no threat

        pace = float(opponent_paces[i]) if opponent_paces is not None else base_speed * 0.7
        vx, vy = vels[i] if vels is not None else (0.0, 0.0)
        # Where he already is by the time the ball arrives, then how long the
        # rest of the trip takes him.
        px, py = ox + vx * ball_t, oy + vy * ball_t
        opp_t = ball_t + math.hypot(mx - px, my - py) / max(pace, 1e-3)

        margin = opp_t - ball_t
        worst = min(worst, max(0.0, margin) / LANE_SAFE_MARGIN_SECONDS)
        if worst <= 0.0:
            return 0.0
    return min(1.0, worst)


def _intercept_point(ball_pos, ball_unit, ball_speed, chaser_pos, pace):
    """Earliest point on the ball's path the chaser can actually get to, as
    (point, seconds, reachable).

    This replaces a `time_to_reach * 0.7` guess that systematically under-led,
    so chasers arrived behind the ball -- survivable at a 2.0 possession radius,
    fatal at 1.0. Decay is exponential in time so there is no closed form:
    scan, then bisect the crossing. An unreachable ball gives back the closest
    approach, so a bad pass is chased honestly rather than caught by magic.
    """
    ball_pos = np.asarray(ball_pos, dtype=float)
    chaser_pos = np.asarray(chaser_pos, dtype=float)
    pace = max(1e-3, float(pace))

    def gap(t):
        point = ball_pos + ball_unit * _ball_rolled(ball_speed, t)
        return _norm2(point - chaser_pos) / pace - t

    if gap(0.0) <= 0.0:
        return ball_pos, 0.0, True

    steps = 12
    prev_t = 0.0
    for i in range(1, steps + 1):
        t = INTERCEPT_HORIZON * i / steps
        if gap(t) <= 0.0:
            lo, hi = prev_t, t
            for _ in range(12):
                mid = 0.5 * (lo + hi)
                if gap(mid) <= 0.0:
                    hi = mid
                else:
                    lo = mid
            aim = min(hi * INTERCEPT_LEAD_FACTOR, INTERCEPT_HORIZON)
            return ball_pos + ball_unit * _ball_rolled(ball_speed, aim), hi, True
        prev_t = t

    best_t = min(
        (INTERCEPT_HORIZON * i / steps for i in range(steps + 1)),
        key=lambda t: _norm2(ball_pos + ball_unit * _ball_rolled(ball_speed, t) - chaser_pos),
    )
    return ball_pos + ball_unit * _ball_rolled(ball_speed, best_t), best_t, False


class player(ABC):
    # How much of the overall rating comes from primary_stats vs. every other
    # non-tendency attribute. A good player isn't ONLY their primary stats
    # (e.g. a fast defender should rate higher than a slow one), so the rest
    # leaks in at a reduced weight. Override per-class to retune the split.
    primary_weight: float = 0.8

    # Off-ball attacking shape, per role: how far behind the ball's line this
    # slot stands, how far it will leave its formation slot to get there, and
    # how much it slides sideways toward the play. See _attack_shape_target.
    attack_push_trail: float = 14.0
    attack_push_limit: float = 30.0
    attack_push_drift: float = 0.3

    def __init__(self, fname, lname, tier, position, attributes:Attributes = None, country: str = None, hometown: str = None, appearance: dict = None):
        #cosmetic
        self.fname = fname
        self.lname = lname
        self.country = country or "Unknown"
        self.hometown = hometown or "Unknown"
        self.appearance = appearance if appearance is not None else dict(DEFAULT_APPEARANCE)
        self.statistics = dict(DEFAULT_STATISTICS)
        self.tier = tier

        #functional
        self.position = position
        if not self.primary_stats:
            raise ValueError(f"{type(self).__name__}.primary_stats must be a non-empty tuple of Attributes field names")
        self.role_name = getattr(self, "role_name", "generic")
        self.action_profile = getattr(self, "action_profile", ActionProfile())
        self.allowed_actions = set(self.action_profile.get_allowed_actions())
        self.action_biases = dict(self.action_profile.get_action_biases())
        if attributes is None:
            self.attributes = Attributes()
        else:
            self.attributes = attributes
        # Socketed equipment (items.py). The rolled card, kept apart from
        # .attributes so a loaded-and-resaved card cannot bake a buff in
        # twice -- game_state.py is the only place that fills either.
        self.items = []
        self.base_attributes = self.attributes
        self.overall = self._calculate_overall()

    def getAttributes(self):
        return self.attributes

    def getStatistics(self):
        return self.statistics

    @property
    @abstractmethod
    def primary_stats(self) -> tuple[str, ...]:
        """Attributes field names this position's overall rating is averaged from.

        Concrete subclasses satisfy this by declaring a plain class attribute,
        e.g. `primary_stats = ("defending", "tackling")`
        """
        raise NotImplementedError

    def get_allowed_actions(self, phase: str | None = None):
        return set(self.action_profile.get_allowed_actions(phase=phase))

    def register_action(self, name: str, bias: float = 1.0):
        self.allowed_actions.add(name)
        self.action_biases[name] = bias

    def _tactic(self, state: dict):
        """This side's Tactic (game_config.TACTICS); Balanced when a state has none."""
        return state.get("tactic") or _BALANCED

    def get_action_bias(self, action_name: str, default: float = 1.0) -> float:
        return float(self.action_biases.get(action_name, default))

    def _apply_action_limits(self, weights: dict) -> dict:
        filtered = {}
        allowed = self.get_allowed_actions()
        for action_name, value in weights.items():
            if action_name in allowed:
                filtered[action_name] = value * self.get_action_bias(action_name)
        return filtered

    # --- Helper Functions ---
    def _calculate_overall(self):
        attrs = asdict(self.attributes)
        primary = set(self.primary_stats)

        primary_values = [attrs[stat] for stat in primary]
        secondary_values = [
            val
            for key, val in attrs.items()
            if key not in primary and key not in TENDENCY_FIELDS and key not in PHYSICAL_FIELDS
        ]

        primary_avg = sum(primary_values) / len(primary_values)
        secondary_avg = sum(secondary_values) / len(secondary_values) if secondary_values else primary_avg

        weight = self.primary_weight
        return round(primary_avg * weight + secondary_avg * (1.0 - weight))

    def _is_pass_safe(self, start: np.ndarray, end: np.ndarray, opponents: np.ndarray | None = None, line_width: float = 1.0) -> bool:
        if opponents is None:
            return True

        opponents = np.asarray(opponents, dtype=float)
        if opponents.size == 0:
            return True

        sx, sy = float(start[0]), float(start[1])
        dx, dy = float(end[0]) - sx, float(end[1]) - sy
        segment_length_sq = dx * dx + dy * dy
        if segment_length_sq < 1e-8:
            return True

        for ox, oy in opponents.tolist():
            projection = ((ox - sx) * dx + (oy - sy) * dy) / segment_length_sq
            clamped = _clamp(projection, 0.0, 1.0)
            if math.hypot(ox - (sx + clamped * dx), oy - (sy + clamped * dy)) <= line_width:
                return False
        return True

    def _goal_lane_is_open(self, state: dict, lane_width: float = 2.5, lookahead: float = 10.0) -> bool:
        return self._lane_open_from(state, state["my_pos"], lane_width, lookahead)

    def _shot_lane_open(self, state: dict, point) -> bool:
        """Nobody in the way of a shot from `point`, short of the keeper's own ground."""
        dist = _norm2(np.asarray(state["enemy_goal"], dtype=float) - np.asarray(point, dtype=float))
        return self._lane_open_from(state, point, SHOT_LANE_WIDTH, max(0.0, dist - KEEPER_ZONE_DEPTH))

    def _lane_open_from(self, state: dict, point, lane_width: float, lookahead: float) -> bool:
        mx, my = float(point[0]), float(point[1])
        gx, gy = float(state["enemy_goal"][0]) - mx, float(state["enemy_goal"][1]) - my
        goal_norm = math.hypot(gx, gy)
        if goal_norm < 1e-8:
            return True
        ux, uy = gx / goal_norm, gy / goal_norm

        for ox, oy in np.asarray(state["opponents"], dtype=float).tolist():
            rx, ry = ox - mx, oy - my
            forward = rx * ux + ry * uy
            if forward <= 0.0:
                continue
            lateral = math.hypot(rx - forward * ux, ry - forward * uy)
            if forward <= lookahead and lateral <= lane_width:
                return False
        return True

    def _better_shot_ahead(self, state: dict) -> bool:
        """An open run at the keeper from further out than SHOT_PATIENCE_RANGE:
        worth carrying it closer rather than shooting now."""
        dist = float(state.get("dist_to_goal", 99.0))
        return dist > SHOT_PATIENCE_RANGE and self._goal_lane_is_open(
            state, lane_width=2.5, lookahead=max(0.0, dist - KEEPER_ZONE_DEPTH)
        )

    def _is_progressive_ball_move(self, state: dict) -> bool:
        ball_vel = state.get("ball_velocity")
        if ball_vel is None:
            return False
        vx, vy = float(ball_vel[0]), float(ball_vel[1])
        if math.hypot(vx, vy) <= 1e-6:
            return False

        team_direction = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        return team_direction * vy > 0.0

    def _predict_ball_landing_target(self, state: dict) -> np.ndarray:
        bx, by = float(state["ball_pos"][0]), float(state["ball_pos"][1])
        ball_vel = state.get("ball_velocity")
        vx, vy = (float(ball_vel[0]), float(ball_vel[1])) if ball_vel is not None else (0.0, 0.0)
        ball_height = float(state.get("ball_height", 0.0))
        ball_speed = math.hypot(vx, vy)

        fall_time = self._head_ball_drop_time(state)
        if fall_time is not None and ball_speed > 1e-6:
            decay = -math.log(BALL_AIR_FRICTION)
            drop_distance = (ball_speed / decay) * (1.0 - (BALL_AIR_FRICTION ** fall_time))
            return _clamp_to_pitch(bx + (vx / ball_speed) * drop_distance, by + (vy / ball_speed) * drop_distance)

        if not self._is_progressive_ball_move(state):
            return np.array([bx, by])

        player_speed_factor = max(0.4, min(1.5, pace_ability(self.attributes.speed)))
        slow_ball_cutoff = max(1.5, base_speed * 0.2 * player_speed_factor)
        flight_cutoff = max(0.25, 0.25 * player_speed_factor)

        if ball_speed <= slow_ball_cutoff:
            return np.array([bx, by])
        if ball_height <= flight_cutoff and ball_speed < base_speed * 0.6:
            return np.array([bx, by])

        predict_time_seconds = max(1.0, min(3.0, ball_speed / max(1.0, base_speed * 0.8)))
        decay_constant = 0.6931 
        friction_adjusted_distance = (ball_speed / decay_constant) * (1.0 - (0.5 ** predict_time_seconds))
        
        unit = max(1.0, ball_speed)
        return _clamp_to_pitch(bx + (vx / unit) * friction_adjusted_distance, by + (vy / unit) * friction_adjusted_distance)

    # --- Attacking shape ------------------------------------------------
    def _attack_shape_target(self, state: dict, anchor_x: float | None = None) -> np.ndarray:
        """My formation slot pushed up to attack_push_trail behind the ball's
        line (never more than attack_push_limit from the slot), so the team
        arrives together instead of leaving the carrier alone up front."""
        forward = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        fx, fy = float(state["formation_pos"][0]), float(state["formation_pos"][1])
        bx, by = float(state["ball_pos"][0]), float(state["ball_pos"][1])
        push = _clamp((by - fy) * forward - self.attack_push_trail, 0.0, self.attack_push_limit)
        ax = bx if anchor_x is None else float(anchor_x)
        return np.array([
            _clamp(fx + (ax - fx) * self.attack_push_drift, 2.0, PITCH_WIDTH - 2.0),
            _clamp(fy + push * forward, 2.0, PITCH_HEIGHT - 2.0),
        ])

    # --- Wingplay -------------------------------------------------------
    # A wide player runs the touchline to the crossing zone and crosses.
    # Choosing "wing_run" latches state["intent"] = "wingplay" (the engine
    # keeps it until the ball is released) and _decide_wingplay then
    # narrows the menu to wing_run / cross / pass -- no dribble at goal
    # unless the marker is genuinely beaten (_beat_marker). A cross needs
    # someone to aim at: with the box empty (_box_runners) the latch drops
    # and they go at the goal themselves.
    def _touchline_x(self, state: dict) -> float:
        return 3.0 if state["formation_pos"][0] < PITCH_WIDTH / 2.0 else PITCH_WIDTH - 3.0

    def _is_wide(self, state: dict) -> bool:
        return abs(state["my_pos"][0] - PITCH_WIDTH / 2.0) >= 15.0

    def _in_crossing_zone(self, state: dict) -> bool:
        enemy_goal_y = PITCH_HEIGHT if state.get("a_direction", 1) == 1 else 0.0
        x, y = state["my_pos"]
        return abs(x - PITCH_WIDTH / 2.0) >= 18.0 and abs(enemy_goal_y - y) <= 20.0

    def _box_runners(self, state: dict) -> int:
        """Teammates a cross could actually find: bodies in the opposition
        box. state["teammates"] holds all eleven, so drop my own row."""
        return len(self._cross_candidates(state))

    def _cross_candidates(self, state: dict, lofted: bool = False) -> list:
        """(arrival_pos, velocity) for teammates a cross could actually find --
        in the box now, or arriving there by the time the ball does. A man
        running in counts: crossing only to bodies already stood there meant
        the ball went to whoever was loitering outside the area instead."""
        teammates = np.asarray(state.get("teammates", []), dtype=float)
        if teammates.size == 0:
            return []
        vels = state.get("teammate_vel")
        vels = np.asarray(vels, dtype=float).tolist() if vels is not None else None
        my_pos = state["my_pos"]
        mx, my = float(my_pos[0]), float(my_pos[1])
        enemy_goal_y = PITCH_HEIGHT if state.get("a_direction", 1) == 1 else 0.0
        out = []
        for i, tm in enumerate(teammates.tolist()):
            if _isclose2(tm, my_pos):
                continue
            tx, ty = tm
            vx, vy = vels[i] if vels is not None else (0.0, 0.0)
            # Where he is when THIS ball gets there, not a fixed second on: a
            # flat cross beat the runners in and found them still outside.
            t = cross_flight(math.hypot(tx - mx, ty - my), lofted)
            ax, ay = tx + vx * t, ty + vy * t
            t = cross_flight(math.hypot(ax - mx, ay - my), lofted)
            ax, ay = tx + vx * t, ty + vy * t
            if (
                BOX_X_MIN < ax < BOX_X_MAX
                and abs(enemy_goal_y - ay) <= CROSS_TARGET_DEPTH
            ):
                out.append((np.array([ax, ay]), np.array([vx, vy])))
        return out

    def _runners_in_box_now(self, state: dict) -> int:
        """Teammates actually in the box now, not just on their way (_box_runners)."""
        my_pos = state["my_pos"]
        enemy_goal_y = PITCH_HEIGHT if state.get("a_direction", 1) == 1 else 0.0
        return sum(
            1 for tm in np.asarray(state.get("teammates", []), dtype=float).tolist()
            if not _isclose2(tm, my_pos)
            and BOX_X_MIN < tm[0] < BOX_X_MAX
            and abs(enemy_goal_y - tm[1]) <= CROSS_TARGET_DEPTH
        )

    def _box_needs_bodies(self, state: dict) -> bool:
        """Ball in the final third, nobody in the box, and I'm near enough to
        be the one who goes in."""
        enemy_goal_y = PITCH_HEIGHT if state.get("a_direction", 1) == 1 else 0.0
        return (
            abs(enemy_goal_y - float(state["ball_pos"][1])) <= 40.0
            and float(state.get("dist_to_goal", 99.0)) <= 50.0
            and self._box_runners(state) == 0
        )

    def _beat_marker(self, state: dict) -> bool:
        """A marker (opponent within 5) is now behind me and nobody is
        goal-side within 7. Unmarked isn't beaten: nobody to go past, run the line."""
        if state.get("pressure_count", 0) > 0:
            return False
        my_pos = np.asarray(state["my_pos"], dtype=float)
        rel = np.asarray(state["opponents"], dtype=float) - my_pos
        dists = np.sqrt(np.einsum("ij,ij->i", rel, rel))
        nearest = int(np.argmin(dists))
        if dists[nearest] > 5.0:
            return False
        goal_vec = np.asarray(state["enemy_goal"], dtype=float) - my_pos
        goal_dir = goal_vec / max(_norm2(goal_vec), 1e-8)
        if float(np.dot(rel[nearest], goal_dir)) > -1.0:
            return False
        return self._goal_lane_is_open(state, lane_width=4.0, lookahead=7.0)

    def _build_wing_action(self, decision: str, state: dict) -> dict | None:
        touchline_x = self._touchline_x(state)
        forward = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        if decision == "wing_run":
            enemy_goal_y = PITCH_HEIGHT if forward > 0 else 0.0
            target = np.array([touchline_x, enemy_goal_y - 6.0 * forward])
            speed = max(1.0, stat_ability(self.attributes.dribbling) * 1.25)
            return {"type": "move", "target": target, "speed_mod": speed, "intent": "wingplay"}
        if decision == "wide_run":
            ahead_y = float(_clamp(state["ball_pos"][1] + 12.0 * forward, 0.0, PITCH_HEIGHT))
            return {"type": "move", "target": np.array([touchline_x, ahead_y]), "speed_mod": pace_ability(self.attributes.speed) * 0.9}
        if decision == "attack_box":
            return self._timed_box_run(state)
        return self._build_attack_move(decision, state)

    def _timed_box_run(self, state: dict) -> dict:
        """Get on the end of a cross: to the near or far post side of the spot
        (by which side I'm on), timed to arrive as the carrier reaches the
        crossing zone. Faster than him, I ease off; never past the offside line."""
        forward = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        enemy_goal_y = PITCH_HEIGHT if forward > 0 else 0.0
        my_pos = np.asarray(state["my_pos"], dtype=float)
        ball_pos = np.asarray(state["ball_pos"], dtype=float)
        side = float(_clamp((my_pos[0] - PITCH_WIDTH / 2.0) * 0.5, -8.0, 8.0))

        line = self._offside_line(state)
        depth = max(BOX_RUN_SPOT_DEPTH, line + OFFSIDE_MARGIN)
        target = np.array([PITCH_WIDTH / 2.0 + side, enemy_goal_y - depth * forward])

        top = pace_ability(self.attributes.speed) * BOX_RUN_SPRINT
        carrier_depth = (enemy_goal_y - float(ball_pos[1])) * forward
        carrier_speed = float(np.asarray(state.get("ball_velocity", np.zeros(2)), dtype=float)[1]) * forward
        to_zone = carrier_depth - CROSS_LATE_DEPTH
        if to_zone <= 0.0 or carrier_speed <= 1.0:
            speed = top if to_zone <= 0.0 else top * 0.6   # he is there, or holding it up
        else:
            speed = min(top, _norm2(target - my_pos) / (to_zone / carrier_speed) / base_speed)
        return {"type": "move", "target": target, "speed_mod": max(speed, pace_ability(self.attributes.speed) * 0.4)}

    def _cross_incoming(self, state: dict) -> bool:
        """The ball is wide and coming up the flank, and I'm close enough to
        get in the box for it. Deliberately early: a run that only starts
        once the ball is level with the box arrives after the cross."""
        enemy_goal_y = PITCH_HEIGHT if state.get("a_direction", 1) == 1 else 0.0
        bx, by = state["ball_pos"]
        return (
            abs(bx - PITCH_WIDTH / 2.0) >= 15.0
            and abs(enemy_goal_y - by) <= 45.0
            and float(state.get("dist_to_goal", 99.0)) <= 50.0
        )

    def _decide_wingplay(self, state: dict) -> str | None:
        """The narrowed on-ball menu while latched. None drops the latch and
        hands back the full menu: the marker is beaten, the box is empty, or
        the lane inside is open."""
        if state.get("intent") != "wingplay":
            return None
        rng = state["rng"]
        pressure = state.get("pressure_count", 0)
        progressive = self._best_progressive_pass_target(state) is not None
        if self._in_crossing_zone(state):
            if self._box_runners(state) == 0:
                return None  # nobody to cross to: go at the goal instead
            # Late, not at the edge of the area: carry it on to the byline while
            # the runners get in, unless they are in already or he is closed down.
            enemy_goal_y = PITCH_HEIGHT if state.get("a_direction", 1) == 1 else 0.0
            late = abs(enemy_goal_y - float(state["my_pos"][1])) <= CROSS_LATE_DEPTH
            if not late and pressure < 2 and self._runners_in_box_now(state) < CROSS_READY_RUNNERS and not self._tactic(state).early_cross:
                return "wing_run"
            tac = self._tactic(state)
            t_cross = (70.0 + self.attributes.passing * 0.5) * tac.cross_bias
            t_pass = (pressure * 18.0 if progressive else 0.0) * tac.pass_bias
            t_run = 10.0
            total = t_cross + t_pass + t_run
            return rng.choice(["cross", "pass", "wing_run"], p=[t_cross / total, t_pass / total, t_run / total])
        if self._overlap_release(state) and rng.random() < OVERLAP_RELEASE:
            return "pass"
        if self._beat_marker(state):
            return None
        if pressure >= 2 and progressive:
            return rng.choice(["pass", "wing_run"], p=[0.6, 0.4])
        # Unmarked with the goal in range and the lane inside open: break off
        # the line instead of running it to the byline on rails.
        if (
            pressure == 0
            and float(state.get("dist_to_goal", 99.0)) <= CUT_INSIDE_RANGE
            and self._goal_lane_is_open(state, lane_width=5.0, lookahead=14.0)
        ):
            return None
        take_on = self._take_on_weight(state)
        if take_on > 0.0 and rng.random() < take_on / (take_on + WING_RUN_WEIGHT):
            return "take_on"
        return "wing_run"

    def _head_ball_drop_time(self, state: dict) -> float | None:
        """Seconds until the ball next comes down through head height, or
        None if it is on the deck or never gets up there."""
        h = float(state.get("ball_height", 0.0))
        vz = float(state.get("ball_vz", 0.0))
        if h <= 0.0 and vz <= 0.0:
            return None
        disc = vz * vz - 2.0 * BALL_GRAVITY * (HEAD_CONTACT_HEIGHT - h)
        if disc < 0.0:
            return None
        t = (vz + math.sqrt(disc)) / BALL_GRAVITY
        return t if t > 0.0 else None

    def _high_ball_mine(self, state: dict, my_dist: float, closer_teammates: int) -> bool:
        """A lofted loose ball is attacked by the three nearest teammates,
        not only the nearest -- a header is a contest, not a collection."""
        return (
            self._head_ball_drop_time(state) is not None
            and closer_teammates <= 2
            and my_dist < 14.0
        )

    def _chase_target(self, state: dict) -> np.ndarray:
        """Where to run for a loose ball: under a high one where it drops
        to head height, otherwise ahead of it by how long it takes to get there."""
        ball_pos = state["ball_pos"]
        ball_vel = state.get("ball_velocity", np.zeros(2, dtype=float))
        ball_speed = _norm2(ball_vel)
        if self._head_ball_drop_time(state) is not None:
            return self._predict_ball_landing_target(state)
        if ball_speed < 2.0:
            return ball_pos
        my_speed = max(1.0, pace_ability(self.attributes.speed) * base_speed)
        time_to_reach = _norm2(ball_pos - state["my_pos"]) / my_speed
        predict_time = min(time_to_reach * 0.7, 1.5)
        lead_dist = _ball_rolled(ball_speed, predict_time)
        return _clip_lead_to_pitch(ball_pos, ball_vel / ball_speed, lead_dist)

    def _is_beaten(self, state: dict) -> bool:
        """The man on the ball has got goal-side of me, and he is near enough
        that chasing back is my job rather than holding shape."""
        if state.get("team_possession") != -1 or state.get("is_loose", False):
            return False
        my_pos = np.asarray(state["my_pos"], dtype=float)
        ball_pos = np.asarray(state["ball_pos"], dtype=float)
        behind = (float(my_pos[1]) - float(ball_pos[1])) * state.get("a_direction", 1)
        return behind > RECOVERY_BEATEN_MARGIN and _norm2(ball_pos - my_pos) < RECOVERY_RANGE

    def _ahead_of_back_line(self, state: dict, target) -> np.ndarray:
        """`target`, moved up if need be to BACK_LINE_GAP in front of my centre-backs' line."""
        target = np.asarray(target, dtype=float)
        if state.get("cb_line") is None or self._ball_coming(state):
            return target
        own_goal_y = float(state["own_goal"][1])
        forward = 1.0 if own_goal_y == 0.0 else -1.0
        floor = (float(state["cb_line"]) - own_goal_y) * forward + BACK_LINE_GAP
        if (float(target[1]) - own_goal_y) * forward >= floor:
            return target
        return np.array([float(target[0]), own_goal_y + forward * min(floor, PITCH_HEIGHT)])

    def _ball_coming(self, state: dict) -> bool:
        """A loose ball running at my goal faster than BALL_COMING_SPEED."""
        forward = 1.0 if float(state["own_goal"][1]) == 0.0 else -1.0
        coming = -float(np.asarray(state.get("ball_velocity", (0.0, 0.0)))[1]) * forward
        return state.get("is_loose", False) and coming > BALL_COMING_SPEED

    def _take_on_route(self, state: dict):
        """The way round the man in front of me: (spot past his shoulder, side), or None -- nobody
        there, he is covered, or no side is clear. A side already taken (my intent) is kept."""
        me = np.asarray(state["my_pos"], dtype=float)
        to_goal = np.asarray(state["enemy_goal"], dtype=float) - me
        dist_goal = _norm2(to_goal)
        if dist_goal < 1e-6:
            return None
        u = to_goal / dist_goal
        opps = np.asarray(state["opponents"], dtype=float)
        rel = opps - me
        ahead = rel @ u
        dist = np.sqrt(np.einsum("ij,ij->i", rel, rel))
        near = [k for k in range(1, len(opps)) if ahead[k] > 0.0 and dist[k] < TAKE_ON_RANGE]   # 0: their keeper
        if not near:
            return None
        man = min(near, key=lambda k: dist[k])
        if any(k != man and ahead[k] > ahead[man] and _norm2(opps[k] - opps[man]) < TAKE_ON_COVER
               for k in range(1, len(opps))):
            return None
        intent = state.get("intent") or ""
        kept = int(intent[len("take_on"):]) if intent.startswith("take_on") else 0
        perp = np.array([-u[1], u[0]])
        best = None
        for side in ((kept,) if kept else (-1, 1)):
            spot = opps[man] + perp * side * TAKE_ON_WIDTH + u * TAKE_ON_BEYOND
            if not (2.0 <= spot[0] <= PITCH_WIDTH - 2.0 and 2.0 <= spot[1] <= PITCH_HEIGHT - 2.0):
                continue
            space = min(_norm2(opps[k] - spot) for k in range(len(opps)) if k != man)
            if space >= TAKE_ON_SPACE and (best is None or space > best[0]):
                best = (space, spot, side)
        return (best[1], best[2]) if best else None

    def _take_on_weight(self, state: dict) -> float:
        if self._take_on_route(state) is None:
            return 0.0
        skill = take_on_skill(self.attributes)
        return (skill + self.attributes.drible_tendency) * 0.5 * TAKE_ON_WEIGHT * self._tactic(state).dribble_bias

    def _across_route(self, state: dict):
        """Where to carry it across to open the shot: (spot, side), or None -- the shot is on from
        here already, I am too far out for it, or no spot ACROSS_DIST either side has it."""
        me = np.asarray(state["my_pos"], dtype=float)
        goal = np.asarray(state["enemy_goal"], dtype=float)
        if _norm2(goal - me) > EDGE_SHOT_RANGE + ACROSS_DIST or self._shot_lane_open(state, me):
            return None
        intent = state.get("intent") or ""
        kept = int(intent[len("across"):]) if intent.startswith("across") else 0
        opps = np.asarray(state["opponents"], dtype=float)
        best = None
        for side in ((kept,) if kept else (-1, 1)):
            spot = np.array([_clamp(me[0] + side * ACROSS_DIST, BOX_X_MIN, BOX_X_MAX), me[1]])
            if abs(spot[0] - me[0]) < ACROSS_DIST * 0.5 or _norm2(goal - spot) > EDGE_SHOT_RANGE:
                continue
            if not self._shot_lane_open(state, spot):
                continue
            space = float(np.min(np.linalg.norm(opps - spot, axis=1)))
            if best is None or space > best[0]:
                best = (space, spot, side)
        return (best[1], best[2]) if best else None

    def _across_weight(self, state: dict) -> float:
        if self._across_route(state) is None:
            return 0.0
        return (self.attributes.shoot_tendency + self.attributes.vision) * 0.5 * ACROSS_WEIGHT

    def _carve_attack_moves(self, state: dict, t_dribble: float) -> tuple[dict, float]:
        """The moves against a set defender and their weights, and the straight dribble left over:
        with a better way, not straight at him."""
        moves = {"take_on": self._take_on_weight(state), "carry_across": self._across_weight(state)}
        if any(weight > 0.0 for weight in moves.values()):
            t_dribble *= MOVE_DRIBBLE_KEEP
        return moves, t_dribble

    def _latched_attack_move(self, state: dict) -> str | None:
        """The move I am latched onto, while it still applies."""
        intent = state.get("intent") or ""
        if intent.startswith("take_on") and self._take_on_route(state) is not None:
            return "take_on"
        if intent.startswith("across"):
            if self._across_route(state) is not None:
                return "carry_across"
            me = np.asarray(state["my_pos"], dtype=float)
            if _norm2(np.asarray(state["enemy_goal"], dtype=float) - me) <= EDGE_SHOT_RANGE and self._shot_lane_open(state, me):
                return "shoot"   # what it was for
        return None

    def _build_attack_move(self, decision: str, state: dict) -> dict | None:
        if decision == "take_on":
            speed = max(1.0, stat_ability(self.attributes.dribbling) * 1.25)
            route = self._take_on_route(state)
            if route is None:   # nobody left to go round: on at goal
                return {"type": "move", "target": np.asarray(state["enemy_goal"], dtype=float), "speed_mod": speed}
            spot, side = route
            return {"type": "move", "target": spot, "speed_mod": speed, "intent": f"take_on{side:+d}"}
        if decision == "carry_across":
            speed = max(1.0, stat_ability(self.attributes.dribbling) * 1.25) * ACROSS_PACE
            route = self._across_route(state)
            if route is None:   # the shot is on now, or gone: on at goal
                return {"type": "move", "target": np.asarray(state["enemy_goal"], dtype=float), "speed_mod": speed}
            spot, side = route
            return {"type": "move", "target": spot, "speed_mod": speed, "intent": f"across{side:+d}"}
        return None

    def _carrier_to_stop(self, state: dict) -> bool:
        """An opponent has the ball at his feet (not a pass or a loose ball, which I go for)."""
        return state.get("team_possession") == -1 and not state.get("is_loose", False)

    def _goal_side_target(self, state: dict, gap: float) -> np.ndarray:
        """`gap` goal-side of where the man on the ball will be by the time I can get there."""
        carrier = np.asarray(state["ball_pos"], dtype=float)
        my_speed = max(1.0, pace_ability(self.attributes.speed) * base_speed)
        lead = min(_norm2(carrier - np.asarray(state["my_pos"], dtype=float)) / my_speed, GOAL_SIDE_LEAD)
        ahead = carrier + np.asarray(state.get("ball_velocity", np.zeros(2)), dtype=float) * lead
        to_goal = np.asarray(state["own_goal"], dtype=float) - ahead
        dist = _norm2(to_goal)
        target = ahead + to_goal / (dist + 1e-8) * min(gap, dist)
        return _clamp_to_pitch(target[0], target[1])

    def _carrier_ahead(self, state: dict) -> np.ndarray:
        """Where the man on the ball is going, RECOVERY_LEAD_SECONDS on."""
        carrier = np.asarray(state["ball_pos"], dtype=float)
        return carrier + np.asarray(state.get("ball_velocity", np.zeros(2)), dtype=float) * RECOVERY_LEAD_SECONDS

    def _line_target(self, state: dict) -> np.ndarray:
        """My spot in the shape goal-side of the ball: my lane (_line_lane_x) on
        the defensive line, or level with the ball for a midfielder."""
        carrier = self._carrier_ahead(state)
        own_goal_y = float(state["own_goal"][1])
        forward = 1.0 if own_goal_y == 0.0 else -1.0   # out of my goal, up the pitch
        depth = RECOVERY_LINE_DEPTH if state.get("my_role") in LINE_ROLES else 0.0
        line = max(RECOVERY_MIN_DEPTH, (float(carrier[1]) - own_goal_y) * forward - depth)
        return np.array([self._line_lane_x(state, float(carrier[0])), own_goal_y + forward * line])

    def _line_lane_x(self, state: dict, ball_x: float) -> float:
        """My formation x drawn toward the ball by role: a centre-back stays in
        the middle, a full-back takes his flank."""
        role = state.get("my_role", "")
        home_x = float(state["formation_pos"][0])
        x = home_x + (ball_x - home_x) * RECOVERY_LANE_PULL.get(role, RECOVERY_LANE_PULL_DEFAULT)
        x = float(_clamp(x, home_x - RECOVERY_LANE_MAX_SHIFT, home_x + RECOVERY_LANE_MAX_SHIFT))
        if role == "CB":
            x = float(_clamp(x, PITCH_WIDTH / 2.0 - RECOVERY_CB_LANE, PITCH_WIDTH / 2.0 + RECOVERY_CB_LANE))
        return x

    def _recovery_run(self, state: dict) -> dict:
        """Flat out back into my place on the line goal-side of the ball; only
        once the carrier is within RECOVERY_PRESS_RANGE, at him -- goal-side of
        where he is going, to cut him off. Defending adds to the sprint."""
        carrier = self._carrier_ahead(state)
        if _norm2(carrier - np.asarray(state["my_pos"], dtype=float)) <= RECOVERY_PRESS_RANGE:
            to_goal = np.asarray(state["own_goal"], dtype=float) - carrier
            target = carrier + to_goal / (_norm2(to_goal) + 1e-8) * min(RECOVERY_GOAL_SIDE, _norm2(to_goal))
        else:
            target = self._line_target(state)
        target = _clamp_to_pitch(target[0], target[1])
        bonus = 1.0 + RECOVERY_DEFENDING_BONUS * stat_ability(getattr(self.attributes, "defending", 50))
        effort = RECOVERY_ROLE_EFFORT.get(state.get("my_role", ""), 1.0)
        return {"type": "move", "target": target, "speed_mod": pace_ability(self.attributes.speed) * RECOVERY_SPRINT * bonus * effort}

    def _wide_credit(self, state: dict, tm) -> float:
        """Progress credited to a pass out to a wide outlet (WIDE_OUTLET_*)."""
        my_x = float(state["my_pos"][0])
        tm_x, tm_y = float(tm[0]), float(tm[1])
        wide = abs(tm_x - PITCH_WIDTH / 2.0)
        enemy_goal_y = PITCH_HEIGHT if state.get("a_direction", 1) == 1 else 0.0
        if (
            wide >= WIDE_OUTLET_X
            and abs(my_x - PITCH_WIDTH / 2.0) <= wide - WIDE_OUTLET_INSIDE
            and abs(enemy_goal_y - tm_y) <= WIDE_OUTLET_DEPTH
        ):
            return WIDE_PROGRESS_CREDIT * self._tactic(state).wide_credit_scale
        return 0.0

    def _best_progressive_pass_target(self, state: dict) -> np.ndarray | None:
        teammates = np.asarray(state["teammates"], dtype=float)
        opponents = np.asarray(state["opponents"], dtype=float)
        my_pos = np.asarray(state["my_pos"], dtype=float)
        goal_dir = 1.0 if state.get("a_direction", 1) == 1 else -1.0

        best_target = None
        best_score = -1e9

        for tm_i, tm in enumerate(teammates):
            if _equal2(tm, my_pos): continue

            vec_to_tm = tm - my_pos
            forward_progress = (tm[1] - my_pos[1]) * goal_dir + self._wide_credit(state, tm)
            if forward_progress <= 0.0: continue
            if self._is_offside(state, tm): continue
            if not self._is_pass_safe(my_pos, tm, opponents, line_width=1.2): continue

            nearby_opp_distance = np.min(np.linalg.norm(opponents - tm, axis=1)) if opponents.size else 999.0
            if nearby_opp_distance < 1.5: continue

            score = forward_progress * 30.0 - _norm2(vec_to_tm) * 0.7 + nearby_opp_distance * 12.0
            if score > best_score:
                best_score = score
                best_target = tm

        return best_target

    def _choose_pass_target(self, state: dict) -> np.ndarray:
        teammates = state["teammates"]
        teammate_vel = state.get("teammate_vel")
        opponents = state["opponents"]
        my_pos = state["my_pos"]
        goal_dir = 1.0 if state.get("a_direction", 1) == 1 else -1.0

        pass_options = []
        tac = self._tactic(state)
        # Recycling it backwards is a build-up thing: only in my own half. Picking the free
        # man over the forward one holds until the final third, where a side attacks.
        own_depth = float(my_pos[1]) if goal_dir > 0 else PITCH_HEIGHT - float(my_pos[1])
        back_scale = tac.backward_scale if own_depth < PITCH_HEIGHT / 2.0 else 1.0
        build_up = own_depth < PITCH_HEIGHT * 2.0 / 3.0
        safety_scale = tac.safety_scale if build_up else 1.0
        progress_scale = tac.progress_scale if build_up else 1.0
        lane_scale = tac.lane_scale if build_up else 1.0
        nearby_teammates = sum(1 for tm in teammates if _norm2(tm - my_pos) < 4.5)

        for tm_i, tm in enumerate(teammates):
            if _equal2(tm, my_pos): continue

            dist_to_tm = _norm2(tm - my_pos)
            nearest_opp_dist = np.min(np.linalg.norm(opponents - tm, axis=1))

            credit = self._wide_credit(state, tm)
            forward_progress = (tm[1] - my_pos[1]) * goal_dir + credit
            # Score the lane we will ACTUALLY pass down. The ball is played
            # ahead of a moving receiver (_lead_pass), so judging the lane to
            # where he stands now rated a path the ball never takes -- and a
            # body sat in the real one went unseen.
            aim = self._lead_pass(tm, my_pos, teammate_vel, tm_i)
            ball_speed = pass_power(_norm2(aim - my_pos), self.attributes.power) * BASE_KICK_POW
            openness = _lane_openness(
                my_pos, aim, opponents, state.get("opponent_vel"),
                state.get("opponent_pace"), ball_speed,
            )

            # Safety used to outweigh progress 20:30, so the square or
            # backward ball to a free man beat the forward one. Progress now
            # leads, and going backwards is expensive.
            sideways = 0.0 if credit else abs(tm[0] - my_pos[0]) * 0.3   # out wide is the point
            raw_score = (nearest_opp_dist * (10.0 * safety_scale)) + max(0.0, forward_progress * (55.0 * progress_scale)) - max(0.0, -forward_progress * (110.0 * back_scale)) - sideways - (dist_to_tm * 0.7)
            if dist_to_tm < 4.5: raw_score -= 35.0
            if nearby_teammates > 3: raw_score -= 12.0
            raw_score -= (1.0 - openness) * (LANE_BLOCKED_PENALTY * lane_scale)

            if _norm2(state["enemy_goal"] - tm) < _norm2(state["enemy_goal"] - my_pos):
                raw_score += 18.0
            if forward_progress < 0.0:
                raw_score -= 80.0 * back_scale
            if self._is_offside(state, tm):
                raw_score -= OFFSIDE_PASS_PENALTY
            elif tm_i == state.get("give_and_go", -1):
                raw_score += GIVE_AND_GO_BONUS
            elif tm_i == state.get("overlap", -1):
                raw_score += OVERLAP_BONUS

            pressure_penalty = state["pressure_count"] * max(0.0, 100 - self.attributes.composure) / 10.0
            effective_vision = max(1.0, self.attributes.vision - pressure_penalty)
            error_variance = 220.0 / (100.0 * stat_ability(effective_vision))

            perceived_score = raw_score + state["rng"].normal(loc=0.0, scale=error_variance)
            pass_options.append((perceived_score, aim, tm_i))

        if not pass_options: return my_pos
        pass_options.sort(key=lambda x: x[0], reverse=True)
        # Already the led point -- scored that way above.
        return pass_options[0][1]

    def _offside_line(self, state: dict) -> float:
        """Their offside line as distance from their goal line: the second-deepest
        opponent, or the ball if it is deeper."""
        forward = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        enemy_goal_y = PITCH_HEIGHT if forward > 0 else 0.0
        depths = sorted((enemy_goal_y - float(y)) * forward for y in np.asarray(state["opponents"], dtype=float)[:, 1])
        return min(depths[1] if len(depths) > 1 else 0.0, (enemy_goal_y - float(state["ball_pos"][1])) * forward)

    def _wall_pass_pull(self, state: dict) -> float:
        """The lean to passing for a runner off me: GIVE_AND_GO_PASS_WEIGHT for the man who
        just gave it to me, OVERLAP_PASS_WEIGHT for an overlapping full-back once I'm closed down."""
        if self._runner_free(state, "give_and_go"):
            return GIVE_AND_GO_PASS_WEIGHT
        if self._overlap_release(state):
            return OVERLAP_PASS_WEIGHT
        return 0.0

    def _runner_free(self, state: dict, key: str) -> bool:
        """The teammate at state[key] is ahead of me, onside and free."""
        runner_i = state.get(key, -1)
        if runner_i < 0:
            return False
        runner = state["teammates"][runner_i]
        goal_dir = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        if (float(runner[1]) - float(state["my_pos"][1])) * goal_dir <= 0.0 or self._is_offside(state, runner):
            return False
        return _count_within(state["opponents"], runner, GIVE_AND_GO_FREE) == 0

    def _overlap_release(self, state: dict) -> bool:
        """The overlapping full-back is free ahead of me and a man is on me: play him in."""
        return self._runner_free(state, "overlap") and _count_within(state["opponents"], state["my_pos"], OVERLAP_ENGAGED) > 0

    def _is_offside(self, state: dict, tm) -> bool:
        """Is teammate `tm` in an offside position right now (gameEngine._offside_snapshot's rule)?"""
        forward = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        depth = ((PITCH_HEIGHT if forward > 0 else 0.0) - float(tm[1])) * forward
        return depth < min(self._offside_line(state) - 0.3, PITCH_HEIGHT / 2.0)

    def _support_target(self, state: dict, default: np.ndarray) -> np.ndarray:
        """With show_in_space and a teammate on the ball: the most open spot around him to
        offer the pass; otherwise `default`."""
        if not self._tactic(state).show_in_space or state.get("is_loose", False) or state.get("team_possession") != 1:
            return default
        forward = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        bx, by = float(state["ball_pos"][0]), float(state["ball_pos"][1])
        mx, my = float(state["my_pos"][0]), float(state["my_pos"][1])
        opponents = np.asarray(state["opponents"], dtype=float).tolist()
        mates = [tm for tm in np.asarray(state["teammates"], dtype=float).tolist() if not (tm[0] == mx and tm[1] == my)]
        best, best_score = default, -1e9
        for angle in SUPPORT_SPACE_ANGLES:
            x = _clamp(bx + SUPPORT_SPACE_RADIUS * math.sin(angle), 2.0, PITCH_WIDTH - 2.0)
            y = _clamp(by + forward * SUPPORT_SPACE_RADIUS * math.cos(angle), 2.0, PITCH_HEIGHT - 2.0)
            if self._is_offside(state, (x, y)):
                continue
            if any(math.hypot(x - tx, y - ty) < SUPPORT_SPACE_CROWD for tx, ty in mates):
                continue
            free = min(math.hypot(x - ox, y - oy) for ox, oy in opponents)
            score = free - 0.3 * math.hypot(x - mx, y - my)
            if score > best_score:
                best, best_score = np.array([x, y]), score
        return best

    def _line_man_beside_me(self, state: dict) -> int:
        """The defender in their back line (the four deepest bar the keeper) nearest me across the pitch."""
        forward = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        enemy_goal_y = PITCH_HEIGHT if forward > 0 else 0.0
        opponents = np.asarray(state["opponents"], dtype=float)
        deepest = sorted(range(len(opponents)), key=lambda i: (enemy_goal_y - float(opponents[i][1])) * forward)
        my_x = float(state["my_pos"][0])
        return min(deepest[1:5], key=lambda i: abs(float(opponents[i][0]) - my_x))

    def _in_behind_weight(self, state: dict) -> float:
        """What a run in behind is worth now: room behind their line x my pace edge on the man beside me."""
        line = self._offside_line(state)
        room = _clamp((line - IN_BEHIND_KEEPER_ZONE) / IN_BEHIND_ROOM_FULL, 0.0, 1.0)
        forward = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        ball_depth = ((PITCH_HEIGHT if forward > 0 else 0.0) - float(state["ball_pos"][1])) * forward
        reach = LONG_BALL_REACH[1] if self._tactic(state).long_ball else IN_BEHIND_REACH
        if room <= 0.0 or ball_depth - line > reach - IN_BEHIND_LEAD:
            return 0.0   # no room, or nobody on the ball who could find it
        paces = state.get("opponent_pace")
        theirs = float(paces[self._line_man_beside_me(state)]) / base_speed if paces is not None else pace_ability(50)
        edge = pace_ability(self.attributes.speed) - theirs
        return IN_BEHIND_WEIGHT * room * _clamp(1.0 + edge * IN_BEHIND_PACE_GAIN, 0.0, 2.0)

    def _in_behind_run(self, state: dict) -> dict:
        """On the shoulder: in the channel beside the nearest defender in the line, onside."""
        forward = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        enemy_goal_y = PITCH_HEIGHT if forward > 0 else 0.0
        beside_x = float(np.asarray(state["opponents"], dtype=float)[self._line_man_beside_me(state)][0])
        side = 1.0 if float(state["my_pos"][0]) >= beside_x else -1.0
        x = _clamp(beside_x + side * IN_BEHIND_CHANNEL, 8.0, PITCH_WIDTH - 8.0)
        depth = self._offside_line(state) + IN_BEHIND_ONSIDE
        return {"type": "move", "target": np.array([x, enemy_goal_y - depth * forward]),
                "speed_mod": pace_ability(self.attributes.speed) * 0.8}

    def _in_behind_target(self, state: dict, lofted: bool = False) -> np.ndarray | None:
        """For a teammate on the shoulder with room behind: IN_BEHIND_LEAD past the line in his
        lane, if it is ahead of me, in reach and (on the ground) the lane is clear -- else None."""
        forward = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        enemy_goal_y = PITCH_HEIGHT if forward > 0 else 0.0
        line = self._offside_line(state)
        if line - IN_BEHIND_KEEPER_ZONE < IN_BEHIND_LEAD * 0.5:
            return None
        my_pos = state["my_pos"]
        my_depth = (enemy_goal_y - float(my_pos[1])) * forward
        runner = None
        for tm in state["teammates"]:
            depth = (enemy_goal_y - float(tm[1])) * forward
            if _equal2(tm, my_pos) or not (line <= depth <= line + IN_BEHIND_SHOULDER) or depth >= my_depth:
                continue
            if runner is None or depth < runner[1]:
                runner = (float(tm[0]), depth)
        if runner is None:
            return None
        depth = max(IN_BEHIND_KEEPER_ZONE, line - IN_BEHIND_LEAD)
        target = _clamp_to_pitch(runner[0], enemy_goal_y - depth * forward)
        if _norm2(target - my_pos) > (LONG_BALL_REACH[1] if lofted else IN_BEHIND_REACH):
            return None
        if not lofted and not self._is_pass_safe(my_pos, target, state.get("opponents"), line_width=1.3):
            return None
        return target

    def _long_ball_target(self, state: dict) -> np.ndarray | None:
        """For the furthest man forward: over the top of a high line, else led into his run.
        Cut to the kicker's reach; None when nobody is far enough ahead."""
        on_the_shoulder = self._in_behind_target(state, lofted=True)
        if on_the_shoulder is not None:
            return on_the_shoulder
        goal_dir = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        teammates, my_pos = state["teammates"], state["my_pos"]
        best = max(range(len(teammates)), key=lambda i: float(teammates[i][1]) * goal_dir)
        if (float(teammates[best][1]) - float(my_pos[1])) * goal_dir < LONG_BALL_MIN_GAIN:
            return None
        enemy_goal_y = PITCH_HEIGHT if goal_dir > 0 else 0.0
        depths = sorted((enemy_goal_y - float(y)) * goal_dir for y in np.asarray(state["opponents"], dtype=float)[:, 1])
        line = depths[1]   # the deepest is the keeper
        if line >= LONG_BALL_ROOM:
            aim = np.array([float(teammates[best][0]), enemy_goal_y - goal_dir * (line - LONG_BALL_BEHIND)])
        else:
            aim = self._lead_pass(teammates[best], my_pos, state.get("teammate_vel"), best)
        lo, hi = LONG_BALL_REACH
        reach = lo + (hi - lo) * _clamp((float(self.attributes.power) - 40.0) / 50.0, 0.0, 1.0)
        vec = aim - my_pos
        dist = _norm2(vec)
        if dist > reach:
            aim = my_pos + vec * (reach / dist)
        return _clamp_to_pitch(aim[0], aim[1])

    def _lead_pass(self, target, my_pos, teammate_vel, tm_i):
        """Pass into the runner's path. The ball takes real time to arrive, so
        aiming at where they stand now puts it behind them."""
        if teammate_vel is None:
            return target
        vel = np.asarray(teammate_vel[tm_i], dtype=float)
        if _norm2(vel) < 0.5:
            return target
        dist = _norm2(target - my_pos)
        v0 = pass_power(dist, self.attributes.power) * BASE_KICK_POW
        k = PASS_DECAY_PER_UNIT
        travel = 1.0 - (k * dist / max(v0, 1e-6))
        if travel <= 1e-3:
            return target
        flight = min(-math.log(travel) / k, PASS_MAX_LEAD_SECONDS)
        return target + vel * flight

    def _calculate_shot(self, state: dict) -> dict:
        goal_center_x = 35.0
        goal_y = 100.0 if state["a_direction"] == 1 else 0.0 
        
        rng = state["rng"]
        # Aim inside the frame, not at the post itself. The goal's inner edges
        # are ~31.5/38.5, so aiming exactly there made even a perfectly struck
        # shot a coin flip to go wide however good the shooter was.
        target_x = 32.2 if rng.choice([True, False]) else 37.8
        intended_target = np.array([target_x, goal_y, rng.uniform(0.5, 2.0)])
        
        pressure_penalty = state["pressure_count"] * (max(0.0, 100.0 - self.attributes.composure) / 20.0)
        dist = _norm2(np.array([goal_center_x, goal_y]) - state["my_pos"])
        unit_to_goal = (np.array([goal_center_x, goal_y]) - state["my_pos"]) / (dist + 0.001)
        
        heading_penalty = max(0.0, (0.8 - np.dot(state["my_heading"], unit_to_goal)) * 5.0) 
        strike = (self.attributes.power * 0.6) + (self.attributes.shooting * 0.4)
        total_variance = ((100.0 / 15.0) * (1.0 - stat_ability(self.attributes.shooting))) + pressure_penalty + heading_penalty
        total_variance *= min(1.0, max(SHOT_CLOSE_ACCURACY, dist / SHOT_ACCURACY_RANGE))
        # A floor so even a perfect shooter isn't a laser, but low enough that
        # shooting still tells right up to 100 -- at 0.9 everything above 86 was
        # identical, so an icon shot like a gold.
        total_variance = max(total_variance, SHOT_VARIANCE_FLOOR)
        
        actual_x = intended_target[0] + rng.normal(0, total_variance)
        actual_z = max(0.0, intended_target[2] + rng.normal(0, total_variance * 0.5))
        
        return {
            "type": "shoot",
            "target_3d": [actual_x, goal_y, actual_z],
            "power": min(1.0, dist / 4.0) * (strike / 40.0)
        }

    def _clearance_target(self, state: dict) -> np.ndarray:
        """Where a defender hoofs it.

        Away from his own goal and angled at the nearer touchline, but never
        more than CLEAR_MAX_TURN off where he is already facing -- nobody
        swivels 180 degrees to hit a clearance. Putting it out for a throw-in
        is a perfectly good outcome; leaving it loose in his own box is not,
        which is what the old "aim at a random far corner" did whenever that
        corner was behind him.
        """
        my_pos = np.asarray(state["my_pos"], dtype=float)
        own_goal = np.asarray(state.get("own_goal", my_pos), dtype=float)
        away = my_pos - own_goal
        if _norm2(away) < 1e-6:
            away = np.array([0.0, 1.0 if state.get("a_direction", 1) == 1 else -1.0])
        away = away / _norm2(away)

        side = -1.0 if my_pos[0] < PITCH_WIDTH / 2.0 else 1.0
        want = away + np.array([side * CLEAR_WIDE_BIAS, 0.0])
        want = want / max(_norm2(want), 1e-6)

        heading = np.asarray(state.get("my_heading", want), dtype=float)
        if _norm2(heading) < 1e-6:
            heading = want
        else:
            heading = heading / _norm2(heading)

        angle = math.acos(float(_clamp(np.dot(heading, want), -1.0, 1.0)))
        if angle > CLEAR_MAX_TURN:
            turn = CLEAR_MAX_TURN * (1.0 if heading[0] * want[1] - heading[1] * want[0] > 0 else -1.0)
            c, sn = math.cos(turn), math.sin(turn)
            want = np.array([heading[0] * c - heading[1] * sn, heading[0] * sn + heading[1] * c])
        return my_pos + want * CLEAR_DISTANCE

    def _cross_action(self, state: dict) -> dict:
        """Flat and quick into a clear lane; lofted over anyone stood in it. With
        nobody to find in the box, no cross: lay it off instead -- except at a
        set piece (must_pass), which goes in whoever is there."""
        if not self._cross_candidates(state) and not state.get("must_pass_next", False):
            target = self._choose_pass_target(state)
            power = pass_power(_norm2(target - state["my_pos"]), self.attributes.power, 1.0, 60.0)
            return {"type": "pass", "target": target, "power": power}
        target = self._choose_cross_target(state)
        lofted = not self._is_pass_safe(state["my_pos"], target, state.get("opponents"), line_width=CROSS_LANE_WIDTH)
        # Lofted leads him further; if that ball finds nobody, drive it flat.
        lofted = lofted and bool(self._cross_candidates(state, lofted=True))
        if lofted:
            target = self._choose_cross_target(state, lofted=True)
        return {"type": "pass", "target": target, "power": 1.0, "pass_type": "cross", "loft": lofted}

    def _choose_cross_target(self, state: dict, lofted: bool = False) -> np.ndarray:
        teammates = np.asarray(state.get("teammates", []), dtype=float)
        opponents = np.asarray(state.get("opponents", []), dtype=float)
        my_pos = np.asarray(state["my_pos"], dtype=float)
        goal_dir = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        enemy_goal_y = PITCH_HEIGHT if goal_dir == 1 else 0.0

        # Only men in (or arriving into) the box. Being unmarked used to be
        # worth 8x its distance from goal, so the ball went to whoever was free
        # OUTSIDE the area rather than to the danger.
        best_target = None
        best_score = -999.0
        for arrival, _vel in self._cross_candidates(state, lofted):
            dist_to_goal = _norm2(np.array([35.0, enemy_goal_y]) - arrival)
            off_centre = abs(arrival[0] - 35.0)
            nearest_opp_dist = (
                float(np.min(np.linalg.norm(opponents - arrival, axis=1)))
                if opponents.size > 0 else 10.0
            )
            score = -(dist_to_goal * 1.5) - (off_centre * 0.8) + (nearest_opp_dist * 2.0)
            if score > best_score:
                best_score = score
                best_target = arrival

        if best_target is None:
            # Nobody to find: hang it up at the spot rather than drilling it out
            # of play. _decide_wingplay normally drops the latch before this.
            base_target = np.array([35.0, enemy_goal_y - (11.0 * goal_dir)])
        else:
            base_target = np.asarray(best_target, dtype=float)

        pressure_penalty = state.get("pressure_count", 0) * 5.0
        cross_stat = (self.attributes.passing * 0.6) + (self.attributes.vision * 0.4)
        # Floor low enough that crossing still separates up to 100 (was 1.0,
        # which made everything above 85 identical).
        error_scale = max(CROSS_ERROR_FLOOR, (100.0 - cross_stat + pressure_penalty) / CROSS_ERROR_DIVISOR)
        
        rng = state["rng"]
        fuzz_x = rng.normal(0, error_scale)
        fuzz_y = rng.normal(0, error_scale)
        
        final_target = base_target + np.array([fuzz_x, fuzz_y])
        # Drops between the penalty spot and the six-yard line, never on the keeper.
        if goal_dir == 1:
            final_target[1] = min(final_target[1], PITCH_HEIGHT - 9.0)
        else:
            final_target[1] = max(final_target[1], 9.0)
        return _clamp_to_pitch(final_target[0], final_target[1])

    #statistic updaters
    def scored(self): self.statistics["goals"] += 1
    def assisted(self): self.statistics["assists"] += 1
    def match_played(self): self.statistics["matches_played"] += 1

    def record_match(self, match_stats: dict, rating: float) -> None:
        """Folds one match's counters and rating into this card's career
        totals. Called once per player at full time.
        """

        for field in MATCH_STAT_FIELDS:
            self.statistics[field] += int(match_stats[field])
        self.statistics["rating_sum"] += float(rating)
        self.statistics["rating_count"] += 1
        if int(self.statistics["rating_count"]) >= RATED_MATCHES_FOR_AVERAGE:
            self.statistics["avg_rating"] = self.average_rating()

    def average_rating(self) -> float:
        """Career average match rating, or 0.0 for a card that's never played."""
        count = int(self.statistics["rating_count"])
        if count <= 0:
            return 0.0
        return round(float(self.statistics["rating_sum"]) / count, 2)

    # --- Engine Step & Abstract Actions ---
    def step(self, state: dict) -> dict:
        if state.get("has_ball"):
            decision = self._decide_on_ball_attack(state) if state.get("past_halfspace") else self._decide_on_ball_defense(state)
        elif state.get("team_possession") == 1:
            decision = self._decide_off_ball_attack(state)
        elif state.get("team_possession") == -1:
            decision = self._decide_off_ball_defense(state)
        else: 
            decision = self._decide_loose_ball(state)
            
        return self._build_action(decision, state)

    @abstractmethod
    def _build_action(self, decision: str, state: dict) -> dict | None:
        """Maps specific string decisions into engine dictionaries. Implemented by subclasses."""
        pass

    @abstractmethod
    def _decide_on_ball_attack(self, state: dict) -> str:
        pass

    @abstractmethod
    def _decide_on_ball_defense(self, state: dict) -> str:
        pass

    @abstractmethod
    def _decide_off_ball_attack(self, state: dict) -> str:
        pass

    @abstractmethod
    def _decide_off_ball_defense(self, state: dict) -> str:
        pass

    @abstractmethod
    def _decide_loose_ball(self, state: dict) -> str:
        pass

    def __str__(self):
        attributes_str = "".join([f"{k}: {v}\n" for k, v in asdict(self.attributes).items()])
        return f"""*** {self.fname} {self.lname} ***
        Overall = {self.overall}
        Tier = {self.tier}
        Position = {self.position}
        Country = {self.country}
        Hometown = {self.hometown}
        Matches Played = {self.statistics.get("matches_played")}
        Goals = {self.statistics.get("goals")}
        Assists = {self.statistics.get("assists")}
        """
        # *** Attributes ***
        # {attributes_str}
        # ------------------------
        # """

    def __repr__(self):
        return f"Player({self.fname} {self.lname}, {self.position})"