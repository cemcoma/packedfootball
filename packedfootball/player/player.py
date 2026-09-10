from gameEngine import PITCH_HEIGHT, PITCH_WIDTH
from dataclasses import dataclass, asdict
from typing import Final
from abc import ABC, abstractmethod
import numpy as np

position = ["GK","CD","LB","RB","CDM","CM","CAM","LM","RM","CF","LW","RW"]
base_speed:Final = 10.0

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
    dribbiling: int = 30
    shooting: int = 50
    power: int = 80
    accuracy: int = 80
    vision:int = 60

    #Tendencies
    pass_tendency: int = 50
    shoot_tendency: int = 50
    drible_tendency: int = 60
    aggression: int = 40
    composure: int = 70
    clear_tendency:int = 10

DEFAULT_ACTIONS = {
    "stop", "shoot", "pass", "clear", "cross", "dribble",
    "forward_run", "support", "hold_attack", "hold_defense",
    "press", "contain", "recover", "recover_slow", "tackle", "capture",
}

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
    def __init__(self, fname, lname, tier, position, attributes:Attributes = None):
        #cosmetic
        self.fname = fname
        self.lname = lname
        self.statistics = {"goals": 0,"assists":0,"matches_played": 0}
        self.tier = tier

        #functional
        self.position = position
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
    def _calculate_overall(self): #TODO: make it more robust it might need more stuff when we add like heading
        attrs = asdict(self.attributes)
        exclusions = {
            "pass_tendency", "shoot_tendency", "drible_tendency", 
            "aggression", "composure", "clear_tendency"
        }
    
        core_stats = [val for key, val in attrs.items() if key not in exclusions]   
        return sum(core_stats) // len(core_stats)

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
            distance_to_line = np.linalg.norm(opp - closest_point)
            if distance_to_line <= line_width:
                return False
        return True

    def _goal_lane_is_open(self, state: dict, lane_width: float = 2.5, lookahead: float = 10.0) -> bool:
        my_pos = np.asarray(state["my_pos"], dtype=float)
        goal_vec = np.asarray(state["enemy_goal"], dtype=float) - my_pos
        goal_norm = np.linalg.norm(goal_vec)
        if goal_norm < 1e-8:
            return True
        goal_dir = goal_vec / goal_norm

        for opp in np.asarray(state["opponents"], dtype=float):
            rel = opp - my_pos
            forward = float(np.dot(rel, goal_dir))
            if forward <= 0.0:
                continue
            lateral = np.linalg.norm(rel - forward * goal_dir)
            if forward <= lookahead and lateral <= lane_width:
                return False
        return True

    def _is_progressive_ball_move(self, state: dict) -> bool:
        ball_vel = np.asarray(state.get("ball_velocity", np.zeros(2, dtype=float)), dtype=float)
        ball_speed = float(np.linalg.norm(ball_vel))
        if ball_speed <= 1e-6:
            return False

        team_direction = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        forward_component = team_direction * ball_vel[1]
        return forward_component > 0.0

    def _predict_ball_landing_target(self, state: dict) -> np.ndarray:
        ball_pos = np.asarray(state["ball_pos"], dtype=float)
        ball_vel = np.asarray(state.get("ball_velocity", np.zeros(2, dtype=float)), dtype=float)
        ball_height = float(state.get("ball_height", 0.0))
        ball_speed = float(np.linalg.norm(ball_vel))

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

            score = forward_progress * 30.0 - np.linalg.norm(vec_to_tm) * 0.7 + nearby_opp_distance * 12.0
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
        nearby_teammates = sum(1 for tm in teammates if np.linalg.norm(tm - my_pos) < 4.5)

        for tm in teammates:
            if np.array_equal(tm, my_pos): continue

            dist_to_tm = np.linalg.norm(tm - my_pos)
            nearest_opp_dist = np.min(np.linalg.norm(opponents - tm, axis=1))

            forward_progress = (tm[1] - my_pos[1]) * goal_dir
            raw_score = -999.0

            if self._is_pass_safe(my_pos, tm, opponents, line_width=1.0):
                raw_score = (nearest_opp_dist * 20.0) + max(0.0, forward_progress * 30.0) - max(0.0, -forward_progress * 60.0) - (abs(tm[0] - my_pos[0]) * 0.3) - (dist_to_tm * 0.7)
                if dist_to_tm < 4.5: raw_score -= 35.0
                if nearby_teammates > 3: raw_score -= 12.0

            if np.linalg.norm(state["enemy_goal"] - tm) < np.linalg.norm(state["enemy_goal"] - my_pos):
                raw_score += 18.0
            if forward_progress < 0.0:
                raw_score -= 50.0

            pressure_penalty = state["pressure_count"] * (100 - self.attributes.composure) / 10.0
            effective_vision = max(1.0, self.attributes.vision - pressure_penalty)
            error_variance = 220.0 / effective_vision

            perceived_score = raw_score + np.random.normal(loc=0.0, scale=error_variance)
            pass_options.append((perceived_score, tm))

        if not pass_options: return my_pos
        pass_options.sort(key=lambda x: x[0], reverse=True)
        return pass_options[0][1]

    def _calculate_shot(self, state: dict) -> dict:
        goal_center_x = 35.0
        goal_y = 100.0 if state["a_direction"] == 1 else 0.0 
        
        target_x = 31.5 if np.random.choice([True, False]) else 38.5
        intended_target = np.array([target_x, goal_y, np.random.uniform(0.5, 2.0)])
        
        pressure_penalty = state["pressure_count"] * ((100.0 - self.attributes.composure) / 20.0)
        dist = np.linalg.norm(np.array([goal_center_x, goal_y]) - state["my_pos"])
        unit_to_goal = (np.array([goal_center_x, goal_y]) - state["my_pos"]) / (dist + 0.001)
        
        heading_penalty = max(0.0, (0.8 - np.dot(state["my_heading"], unit_to_goal)) * 5.0) 
        total_variance = ((100.0 - self.attributes.shooting) / 15.0) + pressure_penalty + heading_penalty
        
        actual_x = intended_target[0] + np.random.normal(0, total_variance)
        actual_z = max(0.0, intended_target[2] + np.random.normal(0, total_variance * 0.5))
        
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

            dist_to_goal = np.linalg.norm(np.array([35.0, enemy_goal_y]) - tm)
        
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
            dist = np.linalg.norm(vec_to_goal)
            lead_dist = min(4.0, dist * 0.4)
            lead = (vec_to_goal / (dist + 1e-5)) * lead_dist
            base_target = best_target + lead

        pressure_penalty = state.get("pressure_count", 0) * 5.0
        cross_stat = (self.attributes.passing * 0.6) + (self.attributes.vision * 0.4)
        error_scale = max(1.0, (100.0 - cross_stat + pressure_penalty) / 15.0)
        
        fuzz_x = np.random.normal(0, error_scale)
        fuzz_y = np.random.normal(0, error_scale)
        
        final_target = base_target + np.array([fuzz_x, fuzz_y])
        return np.clip(final_target, [0.0, 0.0], [PITCH_WIDTH, PITCH_HEIGHT])

    #statistic updaters
    def scored(self): self.statistics["goals"] += 1
    def assisted(self): self.statistics["assists"] += 1
    def match_played(self): self.statistics["matches_played"] += 1

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