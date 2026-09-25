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
    STAT_CEILING,
    pace_ability,
    stat_ability,
    pass_power,
    BASE_KICK_POW,
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
CROSS_ERROR_FLOOR = 0.4

# A rolling ball loses this much speed per unit travelled (-ln of the ground
# friction), and how far ahead of a runner a pass may be played.
PASS_DECAY_PER_UNIT = 0.6931
PASS_MAX_LEAD_SECONDS = 1.2

# The opposition box, as gameEngine's in_boxes draws it, plus the depth a
# cross is aimed into: a runner at the edge of the area counts, one further
# out does not. See _box_runners.
BOX_X_MIN: Final = 14.0
BOX_X_MAX: Final = 56.0
CROSS_TARGET_DEPTH: Final = 20.0

# Roughly how long a cross hangs, used to work out where a runner will be.
CROSS_FLIGHT_SECONDS: Final = 1.0

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
    start = np.asarray(start, dtype=float)
    end = np.asarray(end, dtype=float)
    segment = end - start
    seg_len_sq = float(np.dot(segment, segment))
    if seg_len_sq < 1e-8 or opponents is None:
        return 1.0
    opponents = np.asarray(opponents, dtype=float)
    if opponents.size == 0:
        return 1.0
    seg_len = math.sqrt(seg_len_sq)

    worst = 1.0
    for i, opp in enumerate(opponents):
        opp = np.asarray(opp, dtype=float)
        projection = float(np.dot(opp - start, segment)) / seg_len_sq
        clamped = min(1.0, max(0.0, projection))
        meet = start + clamped * segment

        ball_t = _ball_time_to(ball_speed, clamped * seg_len)
        if ball_t is None:
            continue                      # ball dies before this point: no threat

        pace = float(opponent_paces[i]) if opponent_paces is not None else base_speed * 0.7
        vel = np.asarray(opponent_vels[i], dtype=float) if opponent_vels is not None else np.zeros(2)
        # Where he already is by the time the ball arrives, then how long the
        # rest of the trip takes him.
        projected = opp + vel * ball_t
        opp_t = ball_t + _norm2(meet - projected) / max(pace, 1e-3)

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
        start = np.asarray(start, dtype=float)
        end = np.asarray(end, dtype=float)

        if opponents is None:
            return True

        opponents = np.asarray(opponents, dtype=float)
        if opponents.size == 0:
            return True

        segment = end - start
        segment_length_sq = float(np.dot(segment, segment))
        if segment_length_sq < 1e-8:
            return True

        for opp in opponents:
            opp_vec = np.asarray(opp, dtype=float) - start
            projection = float(np.dot(opp_vec, segment)) / segment_length_sq
            clamped = np.clip(projection, 0.0, 1.0)
            closest_point = start + clamped * segment
            distance_to_line = _norm2(opp - closest_point)
            if distance_to_line <= line_width:
                return False
        return True

    def _goal_lane_is_open(self, state: dict, lane_width: float = 2.5, lookahead: float = 10.0) -> bool:
        my_pos = np.asarray(state["my_pos"], dtype=float)
        goal_vec = np.asarray(state["enemy_goal"], dtype=float) - my_pos
        goal_norm = _norm2(goal_vec)
        if goal_norm < 1e-8:
            return True
        goal_dir = goal_vec / goal_norm

        for opp in np.asarray(state["opponents"], dtype=float):
            rel = opp - my_pos
            forward = float(np.dot(rel, goal_dir))
            if forward <= 0.0:
                continue
            lateral = _norm2(rel - forward * goal_dir)
            if forward <= lookahead and lateral <= lane_width:
                return False
        return True

    def _is_progressive_ball_move(self, state: dict) -> bool:
        ball_vel = np.asarray(state.get("ball_velocity", np.zeros(2, dtype=float)), dtype=float)
        ball_speed = float(_norm2(ball_vel))
        if ball_speed <= 1e-6:
            return False

        team_direction = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        forward_component = team_direction * ball_vel[1]
        return forward_component > 0.0

    def _predict_ball_landing_target(self, state: dict) -> np.ndarray:
        ball_pos = np.asarray(state["ball_pos"], dtype=float)
        ball_vel = np.asarray(state.get("ball_velocity", np.zeros(2, dtype=float)), dtype=float)
        ball_height = float(state.get("ball_height", 0.0))
        ball_speed = float(_norm2(ball_vel))

        fall_time = self._head_ball_drop_time(state)
        if fall_time is not None and ball_speed > 1e-6:
            decay = -math.log(BALL_AIR_FRICTION)
            drop_distance = (ball_speed / decay) * (1.0 - (BALL_AIR_FRICTION ** fall_time))
            future = ball_pos + (ball_vel / ball_speed) * drop_distance
            return np.clip(future, [0.0, 0.0], [PITCH_WIDTH, PITCH_HEIGHT])

        if not self._is_progressive_ball_move(state):
            return ball_pos.copy()

        player_speed_factor = max(0.4, min(1.5, pace_ability(self.attributes.speed)))
        slow_ball_cutoff = max(1.5, base_speed * 0.2 * player_speed_factor)
        flight_cutoff = max(0.25, 0.25 * player_speed_factor)

        if ball_speed <= slow_ball_cutoff:
            return ball_pos.copy()
        if ball_height <= flight_cutoff and ball_speed < base_speed * 0.6:
            return ball_pos.copy()

        predict_time_seconds = max(1.0, min(3.0, ball_speed / max(1.0, base_speed * 0.8)))
        decay_constant = 0.6931 
        friction_adjusted_distance = (ball_speed / decay_constant) * (1.0 - (0.5 ** predict_time_seconds))
        
        unit_vel = ball_vel / max(1.0, ball_speed)
        future = ball_pos + (unit_vel * friction_adjusted_distance)
        
        return np.clip(future, [0.0, 0.0], [PITCH_WIDTH, PITCH_HEIGHT])

    # --- Attacking shape ------------------------------------------------
    def _attack_shape_target(self, state: dict, anchor_x: float | None = None) -> np.ndarray:
        """My formation slot pushed up to attack_push_trail behind the ball's
        line (never more than attack_push_limit from the slot), so the team
        arrives together instead of leaving the carrier alone up front."""
        forward = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        fx, fy = float(state["formation_pos"][0]), float(state["formation_pos"][1])
        bx, by = float(state["ball_pos"][0]), float(state["ball_pos"][1])
        push = float(np.clip((by - fy) * forward - self.attack_push_trail, 0.0, self.attack_push_limit))
        ax = bx if anchor_x is None else float(anchor_x)
        return np.array([
            float(np.clip(fx + (ax - fx) * self.attack_push_drift, 2.0, PITCH_WIDTH - 2.0)),
            float(np.clip(fy + push * forward, 2.0, PITCH_HEIGHT - 2.0)),
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
        teammates = np.asarray(state.get("teammates", []), dtype=float)
        if teammates.size == 0:
            return 0
        my_pos = np.asarray(state["my_pos"], dtype=float)
        enemy_goal_y = PITCH_HEIGHT if state.get("a_direction", 1) == 1 else 0.0
        return len(self._cross_candidates(state))

    def _cross_candidates(self, state: dict) -> list:
        """(arrival_pos, velocity) for teammates a cross could actually find --
        in the box now, or arriving there by the time the ball does. A man
        running in counts: crossing only to bodies already stood there meant
        the ball went to whoever was loitering outside the area instead."""
        teammates = np.asarray(state.get("teammates", []), dtype=float)
        if teammates.size == 0:
            return []
        vels = state.get("teammate_vel")
        my_pos = np.asarray(state["my_pos"], dtype=float)
        enemy_goal_y = PITCH_HEIGHT if state.get("a_direction", 1) == 1 else 0.0
        out = []
        for i, tm in enumerate(teammates):
            if np.all(np.isclose(tm, my_pos)):
                continue
            vel = np.asarray(vels[i], dtype=float) if vels is not None else np.zeros(2)
            arrival = tm + vel * CROSS_FLIGHT_SECONDS
            if (
                BOX_X_MIN < arrival[0] < BOX_X_MAX
                and abs(enemy_goal_y - arrival[1]) <= CROSS_TARGET_DEPTH
            ):
                out.append((arrival, vel))
        return out

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
            ahead_y = float(np.clip(state["ball_pos"][1] + 12.0 * forward, 0.0, PITCH_HEIGHT))
            return {"type": "move", "target": np.array([touchline_x, ahead_y]), "speed_mod": pace_ability(self.attributes.speed) * 0.9}
        if decision == "attack_box":
            # Get on the end of a cross: near or far post side of the spot,
            # by which side of the pitch I'm on.
            enemy_goal_y = PITCH_HEIGHT if forward > 0 else 0.0
            side = float(np.clip((state["my_pos"][0] - PITCH_WIDTH / 2.0) * 0.5, -8.0, 8.0))
            target = np.array([PITCH_WIDTH / 2.0 + side, enemy_goal_y - 10.0 * forward])
            # Faster than dribbling: an unburdened run has to beat the cross
            # to the box, and a dribbler carries at ~1.0.
            return {"type": "move", "target": target, "speed_mod": pace_ability(self.attributes.speed) * 1.3}
        return None

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
            t_cross = 70.0 + self.attributes.passing * 0.5
            t_pass = pressure * 18.0 if progressive else 0.0
            t_run = 10.0
            total = t_cross + t_pass + t_run
            return rng.choice(["cross", "pass", "wing_run"], p=[t_cross / total, t_pass / total, t_run / total])
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

    def _best_progressive_pass_target(self, state: dict) -> np.ndarray | None:
        teammates = np.asarray(state["teammates"], dtype=float)
        opponents = np.asarray(state["opponents"], dtype=float)
        my_pos = np.asarray(state["my_pos"], dtype=float)
        goal_dir = 1.0 if state.get("a_direction", 1) == 1 else -1.0

        best_target = None
        best_score = -1e9

        for tm_i, tm in enumerate(teammates):
            if np.array_equal(tm, my_pos): continue

            vec_to_tm = tm - my_pos
            forward_progress = (tm[1] - my_pos[1]) * goal_dir
            if forward_progress <= 0.0: continue
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
        nearby_teammates = sum(1 for tm in teammates if _norm2(tm - my_pos) < 4.5)

        for tm_i, tm in enumerate(teammates):
            if np.array_equal(tm, my_pos): continue

            dist_to_tm = _norm2(tm - my_pos)
            nearest_opp_dist = np.min(np.linalg.norm(opponents - tm, axis=1))

            forward_progress = (tm[1] - my_pos[1]) * goal_dir
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
            raw_score = (nearest_opp_dist * 10.0) + max(0.0, forward_progress * 55.0) - max(0.0, -forward_progress * 110.0) - (abs(tm[0] - my_pos[0]) * 0.3) - (dist_to_tm * 0.7)
            if dist_to_tm < 4.5: raw_score -= 35.0
            if nearby_teammates > 3: raw_score -= 12.0
            raw_score -= (1.0 - openness) * LANE_BLOCKED_PENALTY

            if _norm2(state["enemy_goal"] - tm) < _norm2(state["enemy_goal"] - my_pos):
                raw_score += 18.0
            if forward_progress < 0.0:
                raw_score -= 80.0

            pressure_penalty = state["pressure_count"] * max(0.0, 100 - self.attributes.composure) / 10.0
            effective_vision = max(1.0, self.attributes.vision - pressure_penalty)
            error_variance = 220.0 / (100.0 * stat_ability(effective_vision))

            perceived_score = raw_score + state["rng"].normal(loc=0.0, scale=error_variance)
            pass_options.append((perceived_score, aim, tm_i))

        if not pass_options: return my_pos
        pass_options.sort(key=lambda x: x[0], reverse=True)
        # Already the led point -- scored that way above.
        return pass_options[0][1]

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

        angle = math.acos(float(np.clip(np.dot(heading, want), -1.0, 1.0)))
        if angle > CLEAR_MAX_TURN:
            turn = CLEAR_MAX_TURN * (1.0 if heading[0] * want[1] - heading[1] * want[0] > 0 else -1.0)
            c, sn = math.cos(turn), math.sin(turn)
            want = np.array([heading[0] * c - heading[1] * sn, heading[0] * sn + heading[1] * c])
        return my_pos + want * CLEAR_DISTANCE

    def _choose_cross_target(self, state: dict) -> np.ndarray:
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
        for arrival, _vel in self._cross_candidates(state):
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
        error_scale = max(CROSS_ERROR_FLOOR, (100.0 - cross_stat + pressure_penalty) / 15.0)
        
        rng = state["rng"]
        fuzz_x = rng.normal(0, error_scale)
        fuzz_y = rng.normal(0, error_scale)
        
        final_target = base_target + np.array([fuzz_x, fuzz_y])
        # Drops between the penalty spot and the six-yard line, never on the keeper.
        if goal_dir == 1:
            final_target[1] = min(final_target[1], PITCH_HEIGHT - 9.0)
        else:
            final_target[1] = max(final_target[1], 9.0)
        return np.clip(final_target, [0.0, 0.0], [PITCH_WIDTH, PITCH_HEIGHT])

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