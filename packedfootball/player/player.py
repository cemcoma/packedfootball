from game_config import (  # noqa: F401 -- the appearance/career names are re-exported from here
    APPEARANCE_OPTION_COUNTS,
    APPEARANCE_SLOTS,
    BALL_AIR_FRICTION,
    BALL_GRAVITY,
    DEFAULT_APPEARANCE,
    HEAD_CONTACT_HEIGHT,
    PITCH_HEIGHT,
    PITCH_WIDTH,
    RATED_MATCHES_FOR_AVERAGE,
)
from dataclasses import dataclass, asdict
from typing import Final
from abc import ABC, abstractmethod
import numpy as np
import math

position = ["GK","CD","LB","RB","CDM","CM","CAM","LM","RM","CF","LW","RW"]
base_speed:Final = 10.0


# Minimum spread (in pitch units at the goal line) on any shot's aim -- see
# _calculate_shot.
SHOT_VARIANCE_FLOOR = 0.9

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

class player(ABC):
    # How much of the overall rating comes from primary_stats vs. every other
    # non-tendency attribute. A good player isn't ONLY their primary stats
    # (e.g. a fast defender should rate higher than a slow one), so the rest
    # leaks in at a reduced weight. Override per-class to retune the split.
    primary_weight: float = 0.8

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

        player_speed_factor = max(0.4, min(1.5, self.attributes.speed / 100.0))
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

    # --- Wingplay -------------------------------------------------------
    # A wide player runs the touchline to the crossing zone and crosses.
    # Choosing "wing_run" latches state["intent"] = "wingplay" (the engine
    # keeps it until the ball is released) and _decide_wingplay then
    # narrows the menu to wing_run / cross / pass -- no dribble at goal
    # unless the marker is genuinely beaten (_beat_marker).
    def _touchline_x(self, state: dict) -> float:
        return 3.0 if state["formation_pos"][0] < PITCH_WIDTH / 2.0 else PITCH_WIDTH - 3.0

    def _is_wide(self, state: dict) -> bool:
        return abs(state["my_pos"][0] - PITCH_WIDTH / 2.0) >= 15.0

    def _in_crossing_zone(self, state: dict) -> bool:
        enemy_goal_y = PITCH_HEIGHT if state.get("a_direction", 1) == 1 else 0.0
        x, y = state["my_pos"]
        return abs(x - PITCH_WIDTH / 2.0) >= 18.0 and abs(enemy_goal_y - y) <= 20.0

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
            speed = max(1.0, (self.attributes.dribbling / 100.0) * 1.25)
            return {"type": "move", "target": target, "speed_mod": speed, "intent": "wingplay"}
        if decision == "wide_run":
            ahead_y = float(np.clip(state["ball_pos"][1] + 12.0 * forward, 0.0, PITCH_HEIGHT))
            return {"type": "move", "target": np.array([touchline_x, ahead_y]), "speed_mod": (self.attributes.speed * 0.9) / 100.0}
        if decision == "attack_box":
            # Get on the end of a cross: near or far post side of the spot,
            # by which side of the pitch I'm on.
            enemy_goal_y = PITCH_HEIGHT if forward > 0 else 0.0
            side = float(np.clip((state["my_pos"][0] - PITCH_WIDTH / 2.0) * 0.5, -8.0, 8.0))
            target = np.array([PITCH_WIDTH / 2.0 + side, enemy_goal_y - 10.0 * forward])
            return {"type": "move", "target": target, "speed_mod": (self.attributes.speed * 0.9) / 100.0}
        return None

    def _cross_incoming(self, state: dict) -> bool:
        """The ball is wide in the attacking third and I'm close enough to
        get in the box for it."""
        enemy_goal_y = PITCH_HEIGHT if state.get("a_direction", 1) == 1 else 0.0
        bx, by = state["ball_pos"]
        return (
            abs(bx - PITCH_WIDTH / 2.0) >= 15.0
            and abs(enemy_goal_y - by) <= 35.0
            and float(state.get("dist_to_goal", 99.0)) <= 40.0
        )

    def _decide_wingplay(self, state: dict) -> str | None:
        """The narrowed on-ball menu while latched; None when not latched or
        the marker is beaten (back to the full menu, latch drops)."""
        if state.get("intent") != "wingplay":
            return None
        rng = state["rng"]
        pressure = state.get("pressure_count", 0)
        progressive = self._best_progressive_pass_target(state) is not None
        if self._in_crossing_zone(state):
            t_cross = 70.0 + self.attributes.passing * 0.5
            t_pass = pressure * 18.0 if progressive else 0.0
            t_run = 10.0
            total = t_cross + t_pass + t_run
            return rng.choice(["cross", "pass", "wing_run"], p=[t_cross / total, t_pass / total, t_run / total])
        if self._beat_marker(state):
            return None
        if pressure >= 2 and progressive:
            return rng.choice(["pass", "wing_run"], p=[0.6, 0.4])
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
        my_speed = max(1.0, (self.attributes.speed / 100.0) * 10.0)
        time_to_reach = _norm2(ball_pos - state["my_pos"]) / my_speed
        predict_time = min(time_to_reach * 0.7, 1.5)
        lead_dist = (ball_speed / 0.6931) * (1.0 - (0.5 ** predict_time))
        return ball_pos + (ball_vel / ball_speed) * lead_dist

    def _best_progressive_pass_target(self, state: dict) -> np.ndarray | None:
        teammates = np.asarray(state["teammates"], dtype=float)
        opponents = np.asarray(state["opponents"], dtype=float)
        my_pos = np.asarray(state["my_pos"], dtype=float)
        goal_dir = 1.0 if state.get("a_direction", 1) == 1 else -1.0

        best_target = None
        best_score = -1e9

        for tm in teammates:
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
        opponents = state["opponents"]
        my_pos = state["my_pos"]
        goal_dir = 1.0 if state.get("a_direction", 1) == 1 else -1.0

        pass_options = []
        nearby_teammates = sum(1 for tm in teammates if _norm2(tm - my_pos) < 4.5)

        for tm in teammates:
            if np.array_equal(tm, my_pos): continue

            dist_to_tm = _norm2(tm - my_pos)
            nearest_opp_dist = np.min(np.linalg.norm(opponents - tm, axis=1))

            forward_progress = (tm[1] - my_pos[1]) * goal_dir
            raw_score = -999.0

            if self._is_pass_safe(my_pos, tm, opponents, line_width=1.0):
                raw_score = (nearest_opp_dist * 20.0) + max(0.0, forward_progress * 30.0) - max(0.0, -forward_progress * 60.0) - (abs(tm[0] - my_pos[0]) * 0.3) - (dist_to_tm * 0.7)
                if dist_to_tm < 4.5: raw_score -= 35.0
                if nearby_teammates > 3: raw_score -= 12.0

            if _norm2(state["enemy_goal"] - tm) < _norm2(state["enemy_goal"] - my_pos):
                raw_score += 18.0
            if forward_progress < 0.0:
                raw_score -= 50.0

            pressure_penalty = state["pressure_count"] * (100 - self.attributes.composure) / 10.0
            effective_vision = max(1.0, self.attributes.vision - pressure_penalty)
            error_variance = 220.0 / effective_vision

            perceived_score = raw_score + state["rng"].normal(loc=0.0, scale=error_variance)
            pass_options.append((perceived_score, tm))

        if not pass_options: return my_pos
        pass_options.sort(key=lambda x: x[0], reverse=True)
        return pass_options[0][1]

    def _calculate_shot(self, state: dict) -> dict:
        goal_center_x = 35.0
        goal_y = 100.0 if state["a_direction"] == 1 else 0.0 
        
        rng = state["rng"]
        # Aim inside the frame, not at the post itself. The goal's inner edges
        # are ~31.5/38.5, so aiming exactly there made even a perfectly struck
        # shot a coin flip to go wide however good the shooter was.
        target_x = 32.2 if rng.choice([True, False]) else 37.8
        intended_target = np.array([target_x, goal_y, rng.uniform(0.5, 2.0)])
        
        pressure_penalty = state["pressure_count"] * ((100.0 - self.attributes.composure) / 20.0)
        dist = _norm2(np.array([goal_center_x, goal_y]) - state["my_pos"])
        unit_to_goal = (np.array([goal_center_x, goal_y]) - state["my_pos"]) / (dist + 0.001)
        
        heading_penalty = max(0.0, (0.8 - np.dot(state["my_heading"], unit_to_goal)) * 5.0) 
        total_variance = ((100.0 - self.attributes.shooting) / 15.0) + pressure_penalty + heading_penalty
        # A floor so even a perfect shooter isn't a laser -- but a low one.
        # This was 2.1, which is what a 68-shooting player computes to
        # unpenalised, so everyone from gold up shot with identical spread
        # and a 96 was no more accurate than a 70. Now 96 -> ~0.9, 80 -> 1.3,
        # 50 -> 3.3, and a calm icon in space is meant to hit the target.
        total_variance = max(total_variance, SHOT_VARIANCE_FLOOR)
        
        actual_x = intended_target[0] + rng.normal(0, total_variance)
        actual_z = max(0.0, intended_target[2] + rng.normal(0, total_variance * 0.5))
        
        return {
            "type": "shoot",
            "target_3d": [actual_x, goal_y, actual_z],
            "power": min(1.0, dist / 4.0) * (self.attributes.power / 40.0)
        }

    def _choose_cross_target(self, state: dict) -> np.ndarray:
        teammates = np.asarray(state.get("teammates", []), dtype=float)
        opponents = np.asarray(state.get("opponents", []), dtype=float)
        my_pos = np.asarray(state["my_pos"], dtype=float)
        goal_dir = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        enemy_goal_y = PITCH_HEIGHT if goal_dir == 1 else 0.0

        best_target = None
        best_score = -999.0

        for tm in teammates:
            if np.array_equal(tm, my_pos): continue

            dist_to_goal = _norm2(np.array([35.0, enemy_goal_y]) - tm)
        
            if dist_to_goal > 35.0:
                continue

            nearest_opp_dist = np.min(np.linalg.norm(opponents - tm, axis=1)) if opponents.size > 0 else 10.0
            
            score = -dist_to_goal + (nearest_opp_dist * 8.0)
            
            if score > best_score:
                best_score = score
                best_target = tm

        if best_target is None:
            base_target = np.array([35.0, enemy_goal_y - (12.0 * goal_dir)])
        else:
            vec_to_goal = np.array([35.0, enemy_goal_y]) - best_target
            dist = _norm2(vec_to_goal)
            lead_dist = min(2.5, dist * 0.25)
            lead = (vec_to_goal / (dist + 1e-5)) * lead_dist
            base_target = best_target + lead

        pressure_penalty = state.get("pressure_count", 0) * 5.0
        cross_stat = (self.attributes.passing * 0.6) + (self.attributes.vision * 0.4)
        error_scale = max(1.0, (100.0 - cross_stat + pressure_penalty) / 15.0)
        
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