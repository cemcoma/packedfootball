from dataclasses import dataclass, asdict
from typing import Final
import numpy as np

position = ["GK","CD","LB","RB","CDM","CM","CAM","LM","RM","CF","LW","RW"]
base_speed:Final = 10.0

@dataclass
class Attributes: #out of 100, can be over

    #Physical attributes
    stamina: int = 60 ##kullanmıcam poc için 
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
    pass_tendency: int = 1
    shoot_tendency: int = 90
    drible_tendency: int = 60
    aggression: int = 40
    composure: int = 70
    clear_tendency:int = 10


DEFAULT_ACTIONS = {
    "stop",
    "shoot",
    "pass",
    "clear",
    "cross",
    "dribble",
    "forward_run",
    "support",
    "hold_attack",
    "hold_defense",
    "press",
    "contain",
    "recover",
    "recover_slow",
    "tackle",
    "capture",
}


class ActionProfile:
    """Role template for tweening action sets and decision weights per position."""

    role_name = "generic"
    allowed_actions = set(DEFAULT_ACTIONS)
    action_biases = {
        "pass": 1.0,
        "shoot": 1.0,
        "dribble": 1.0,
        "cross": 0.5,
        "clear": 0.5,
        "forward_run": 1.0,
        "support": 1.0,
        "hold_attack": 1.0,
        "hold_defense": 1.0,
        "press": 0.8,
        "contain": 0.8,
        "recover": 0.9,
        "recover_slow": 0.5,
        "tackle": 0.8,
        "capture": 0.8,
    }

    def get_allowed_actions(self, phase: str | None = None):
        actions = set(self.allowed_actions)
        if phase is not None:
            return {action for action in actions if action not in {"stop"}}
        return actions

    def get_action_biases(self):
        return dict(self.action_biases)


class player:
    def __init__(self, fname, lname, position, attributes:Attributes = None):

        #cosmetic
        self.fname = fname
        self.lname = lname
        self.statistics = {"goals": 0,"assists":0,"matches_played": 0}

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

    def getAttributes(self):
        return self.attributes

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
        if forward_component <= 0.0:
            return False

        return True

    def _predict_ball_landing_target(self, state: dict) -> np.ndarray:
        ball_pos = np.asarray(state["ball_pos"], dtype=float)
        ball_vel = np.asarray(state.get("ball_velocity", np.zeros(2, dtype=float)), dtype=float)
        ball_height = float(state.get("ball_height", 0.0))
        ball_speed = float(np.linalg.norm(ball_vel))

        if not self._is_progressive_ball_move(state):
            return ball_pos.copy()

        # The player can only read a pass when the ball is moving in the attacking direction.
        # Backward passes are treated as direct-ball chases because the defender should cut off the ball,
        # not run to a future intercept that is moving away from goal.
        player_speed_factor = max(0.4, min(1.5, self.attributes.speed / 100.0))
        slow_ball_cutoff = max(1.5, base_speed * 0.2 * player_speed_factor)
        flight_cutoff = max(0.25, 0.25 * player_speed_factor)

        if ball_speed <= slow_ball_cutoff:
            return ball_pos.copy()
        if ball_height <= flight_cutoff and ball_speed < base_speed * 0.6:
            return ball_pos.copy()

        lookahead_scale = base_speed * (0.8 + player_speed_factor * 0.8)
        predict_steps = max(1.0, min(6.0, ball_speed / max(1.0, base_speed * 0.8)))
        future = ball_pos + (ball_vel / max(1.0, ball_speed)) * (predict_steps * lookahead_scale)
        future = np.clip(future, [0.0, 0.0], [70.0, 100.0])
        return future

    #statistic updaters
    def scored(self):
        self.statistics["goals"]+=1
    def assisted(self):
        self.statistics["assists"]+=1
    def matchPlayed(self):
         self.statistics["matches_played"]+=1


    def _best_progressive_pass_target(self, state: dict) -> np.ndarray | None:
        teammates = np.asarray(state["teammates"], dtype=float)
        opponents = np.asarray(state["opponents"], dtype=float)
        my_pos = np.asarray(state["my_pos"], dtype=float)
        goal_dir = 1.0 if state.get("a_direction", 1) == 1 else -1.0

        best_target = None
        best_score = -1e9

        for tm in teammates:
            if np.array_equal(tm, my_pos):
                continue

            vec_to_tm = tm - my_pos
            forward_progress = (tm[1] - my_pos[1]) * goal_dir
            if forward_progress <= 0.0:
                continue
            if not self._is_pass_safe(my_pos, tm, opponents, line_width=1.2):
                continue

            nearby_opp_distance = np.min(np.linalg.norm(opponents - tm, axis=1)) if opponents.size else 999.0
            if nearby_opp_distance < 1.5:
                continue

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
            if np.array_equal(tm, my_pos):
                continue

            vec_to_tm = tm - my_pos
            dist_to_tm = np.linalg.norm(vec_to_tm)
            opp_dists_to_tm = np.linalg.norm(opponents - tm, axis=1)
            nearest_opp_dist = np.min(opp_dists_to_tm)

            forward_progress = (tm[1] - my_pos[1]) * goal_dir
            progressive_bonus = max(0.0, forward_progress * 30.0)
            backward_penalty = max(0.0, -forward_progress * 18.0)
            lateral_penalty = abs(tm[0] - my_pos[0]) * 0.3
            safety_bonus = nearest_opp_dist * 20.0
            distance_penalty = dist_to_tm * 0.7

            cluster_penalty = 0.0
            if dist_to_tm < 4.5:
                cluster_penalty += 35.0
            if nearby_teammates > 3:
                cluster_penalty += 12.0

            line_is_safe = self._is_pass_safe(my_pos, tm, opponents, line_width=1.0)
            if not line_is_safe:
                raw_score = -999.0
            else:
                raw_score = safety_bonus + progressive_bonus - backward_penalty - lateral_penalty - distance_penalty - cluster_penalty

            if np.linalg.norm(state["enemy_goal"] - tm) < np.linalg.norm(state["enemy_goal"] - my_pos):
                raw_score += 18.0

            if forward_progress < 0.0:
                raw_score -= 20.0

            pressure_penalty = state["pressure_count"] * (100 - self.attributes.composure) / 10.0
            effective_vision = max(1.0, self.attributes.vision - pressure_penalty)
            error_variance = 220.0 / effective_vision

            perceived_score = raw_score + np.random.normal(loc=0.0, scale=error_variance)
            pass_options.append((perceived_score, tm))

        if not pass_options:
            return my_pos

        pass_options.sort(key=lambda x: x[0], reverse=True)
        return pass_options[0][1]

    def _calculate_shot(self, state: dict) -> dict:
        goal_center_x = 35.0
        goal_y = 100.0 if state["a_direction"] == 1 else 0.0 
        
        aim_left = np.random.choice([True, False])
        target_x = 31.5 if aim_left else 38.5
        target_z = np.random.uniform(0.5, 2.0)
        
        intended_target = np.array([target_x, goal_y, target_z])
        base_error = (100.0 - self.attributes.shooting) / 15.0

        pressure_penalty = state["pressure_count"] * ((100.0 - self.attributes.composure) / 20.0)
        
        my_pos = state["my_pos"]
        vec_to_center = np.array([goal_center_x, goal_y]) - my_pos
        dist = np.linalg.norm(vec_to_center)
        unit_to_goal = vec_to_center / (dist + 0.001)
        facing_dot = np.dot(state["my_heading"], unit_to_goal)
        
        heading_penalty = max(0.0, (0.8 - facing_dot) * 5.0) 
        
        total_variance = base_error + pressure_penalty + heading_penalty
        
        actual_x = intended_target[0] + np.random.normal(0, total_variance)
        actual_z = intended_target[2] + np.random.normal(0, total_variance * 0.5) 
        actual_z = max(0.0, actual_z)
        
        final_target_3d = [actual_x, goal_y, actual_z]

        required_power = min(1.0, dist / 4.0)
        actual_power = required_power * (self.attributes.power / 40.0)
        
        return {
            "type": "shoot",
            "target_3d": final_target_3d,
            "power": actual_power
        }


    #action calculations
    def step(self, state: dict) -> dict:
        decision = "stop"
        
        if state.get("has_ball"):
            if state.get("past_halfspace"):
                decision = self._decide_on_ball_attack(state)
            else:
                decision = self._decide_on_ball_defense(state)
        elif state.get("team_possession") == 1:
            decision = self._decide_off_ball_attack(state)
        elif state.get("team_possession") == -1:
            decision = self._decide_off_ball_defense(state)
        else: 
            decision = self._decide_loose_ball(state)
            
        return self._build_action(decision, state)

    def _build_action(self, decision: str, state: dict) -> dict | None:
        """Maps specific string decisions into engine dictionaries."""
        if decision == "stop":
            return None
            
        # --- On-Ball Actions ---
        elif decision == "shoot":
            return self._calculate_shot(state)
            
        elif decision == "pass":
            best_target = self._choose_pass_target(state)
            dist = np.linalg.norm(best_target - state["my_pos"])
            required_power = min(1.0, dist / 10.0) 
            actual_power = required_power * (self.attributes.power / 60.0)
            return {"type": "pass", "target": best_target, "power": actual_power}
            
        elif decision == "clear":
            forward_y = 100.0 if state.get("a_direction", 1) == 1 else 0.0
            wide_x = np.random.choice([0.0, 70.0]) 
            target = np.array([wide_x + np.random.uniform(-15, 15), forward_y])
            return {"type": "pass", "target": target, "power": min(1.0, self.attributes.power / 50.0), "pass_type": "clearance"}

        elif decision == "cross":
            cross_target = np.array([np.random.uniform(20.0, 50.0), 100.0 if state.get("a_direction", 1) == 1 else 0.0])
            return {"type": "pass", "target": cross_target, "power": min(1.0, self.attributes.power / 52.0), "pass_type": "cross"}
            
        elif decision == "dribble":
            enemy_goal_y = 100.0 if state.get("a_direction", 1) == 1 else 0.0
            dribble_speed = max(1.0, (self.attributes.dribbiling / 100.0) * 1.25)
            return {"type": "move", "target": np.array([35.0, enemy_goal_y]), "speed_mod": dribble_speed}
            
        # --- Off-Ball Attacking Movement ---
        elif decision == "forward_run":
            enemy_goal_y = 100.0 if state.get("a_direction", 1) == 1 else 0.0
            run_target = np.array([state["my_pos"][0], enemy_goal_y])
            return {"type": "move", "target": run_target, "speed_mod": (self.attributes.speed * 0.9) / 100.0}
            
        elif decision == "support":
            target = self._predict_ball_landing_target(state)
            vec_to_target = target - state["my_pos"]
            intercept_weight = 0.55 + (self.attributes.speed / 100.0) * 0.35
            support_target = state["my_pos"] + (vec_to_target * intercept_weight)
            return {"type": "move", "target": support_target, "speed_mod": (self.attributes.speed * 0.7) / 100.0}
            
        elif decision == "hold_attack":
            forward_shift = 15.0 if state.get("a_direction", 1) == 1 else -15.0
            tactical_pos = np.array([state["formation_pos"][0], state["formation_pos"][1] + forward_shift])
            return {"type": "move", "target": tactical_pos, "speed_mod": (self.attributes.speed * 0.5) / 100.0}
            
        # --- Defensive & Loose Ball Movement ---
        elif decision == "hold_defense":
            backward_shift = -10.0 if state.get("a_direction", 1) == 1 else 10.0
            defensive_pos = np.array([state["formation_pos"][0], state["formation_pos"][1] + backward_shift])
            return {"type": "move", "target": defensive_pos, "speed_mod": (self.attributes.speed * 0.6) / 100.0}
            
        elif decision == "press":
            target = self._predict_ball_landing_target(state)
            vec_to_target = target - state["my_pos"]
            press_weight = 0.7 + (self.attributes.speed / 100.0) * 0.25
            press_target = state["my_pos"] + (vec_to_target * press_weight)
            return {"type": "move", "target": press_target, "speed_mod": (self.attributes.speed * 0.9) / 100.0}

        elif decision == "contain":
            target = self._predict_ball_landing_target(state)
            vec_to_target = target - state["my_pos"]
            contain_weight = 0.5 + (self.attributes.speed / 100.0) * 0.2
            contain_target = state["my_pos"] + (vec_to_target * contain_weight)
            return {"type": "move", "target": contain_target, "speed_mod": (self.attributes.speed * 0.5) / 100.0}
            
        elif decision == "recover":
            return {"type": "move", "target": state["formation_pos"], "speed_mod": (self.attributes.speed * 0.5) / 100.0}
            
        elif decision == "recover_slow":
            return {"type": "move", "target": state["formation_pos"], "speed_mod": (self.attributes.speed * 0.2) / 100.0}
            
        # --- Dispossession ---
        elif decision == "tackle":
            return {"type": "tackle", "stat": self.attributes.defending}
            
        elif decision == "capture":
            return {"type": "capture", "stat": self.attributes.ballcontrol}
            
        return None

    def _decide_on_ball_attack(self, state: dict) -> str:
        if state.get("must_pass_next", False):
            return "pass"

        actions = ["pass", "shoot", "dribble", "stop"]
        progressive_pass = self._best_progressive_pass_target(state) is not None
        pressure = state.get("pressure_count", 0)

        t_pass = self.attributes.pass_tendency * 0.4
        t_shoot = self.attributes.shoot_tendency
        t_dribble = self.attributes.drible_tendency
        t_stop = 10.0

        if not progressive_pass:
            t_pass *= 0.08
        elif pressure > 0:
            t_pass *= 1.35

        dist_to_goal = state["dist_to_goal"]
        unit_vec_to_goal = state["vec_to_goal"] / (dist_to_goal if dist_to_goal > 0 else 1.0)
        facing_goal = np.dot(state["my_heading"], unit_vec_to_goal)

        if state.get("in_attacking_box"):
            t_shoot *= 2.5 
        else:
            t_shoot -= (dist_to_goal * 2.0) 

        if facing_goal < 0.0: t_shoot *= 0.1 
        elif facing_goal > 0.8: t_shoot *= 1.5

        if pressure > 1:
            t_dribble -= (pressure * 25)
            t_pass += (pressure * 18)
            t_stop = 0
        elif pressure == 0:
            t_dribble += (self.attributes.speed * 1.8) + 90.0
            t_pass -= 25.0
            t_stop += 10

        if self._goal_lane_is_open(state, lane_width=2.5, lookahead=10.0):
            t_dribble += 60.0
            t_pass -= 18.0
            t_stop += 5.0

        if pressure > 0 and not self._goal_lane_is_open(state, lane_width=3.0, lookahead=12.0):
            t_pass += 40.0
            t_dribble *= 0.55

        t_pass = max(0.0, t_pass)
        t_shoot = max(0.0, t_shoot)
        t_dribble = max(1.0, t_dribble)
        t_stop = max(0.0, t_stop)

        total = t_pass + t_shoot + t_dribble + t_stop
        if total <= 0:
            return "dribble"
        probs = [t_pass/total, t_shoot/total, t_dribble/total, t_stop/total]
        return np.random.choice(actions, p=probs)

    def _decide_on_ball_defense(self, state: dict) -> str:
        actions = ["pass", "dribble", "stop", "clear"]
        progressive_pass = self._best_progressive_pass_target(state) is not None
        pressure = state.get("pressure_count", 0)

        t_pass = self.attributes.pass_tendency * 0.45
        t_dribble = self.attributes.drible_tendency
        t_stop = 15.0
        t_clear = self.attributes.clear_tendency

        if not progressive_pass:
            t_pass *= 0.1
        elif pressure > 0:
            t_pass *= 1.3

        own_goal_y = 0.0 if state.get("a_direction", 1) == 1 else 100.0
        dist_to_own_goal = np.linalg.norm(np.array([35.0, own_goal_y]) - state["my_pos"])

        if dist_to_own_goal < 25.0:
            t_clear *= 2.5
            t_dribble *= 0.3

        if pressure > 1:
            t_clear += (pressure * 40)
            t_pass += (pressure * 12)
            if not self._goal_lane_is_open(state, lane_width=3.0, lookahead=12.0):
                t_dribble *=0.1
                t_stop = 0
        elif pressure == 0:
            t_clear *= 0.1
            t_dribble += (self.attributes.speed * 2.0) + 60.0
            t_pass -= 18.0
            t_stop += 15

        t_pass = max(0.0, t_pass)
        t_dribble = max(1.0, t_dribble)
        t_clear = max(0.0, t_clear)
        t_stop = max(0.0, t_stop)

        total = t_pass + t_dribble + t_clear + t_stop
        if total <= 0:
            return "dribble"
        probs = [t_pass/total, t_dribble/total, t_stop/total, t_clear/total]
        return np.random.choice(actions, p=probs)

    def _decide_off_ball_attack(self, state: dict) -> str:
        actions = ["forward_run", "support", "hold_attack"]
        t_forward = self.attributes.shoot_tendency + (self.attributes.speed * 0.5)
        t_support = self.attributes.pass_tendency + 20.0
        t_hold = self.attributes.defending + 30.0

        dist_to_ball = np.linalg.norm(state["ball_pos"] - state["my_pos"])
        ball_pressure_count = int(np.sum(np.linalg.norm(state["opponents"] - state["ball_pos"], axis=1) < 3.0))
        own_goal_y = 0.0 if state.get("a_direction", 1) == 1 else 100.0
        dist_to_own_goal = abs(state["formation_pos"][1] - own_goal_y)

        if dist_to_ball > 12.0:
            t_support *= 0.4
            t_hold *= 2.5
        if ball_pressure_count >= 2:
            t_forward *= 0.2
            t_support *= 0.15
            t_hold *= 4.0
            
        if dist_to_ball < 20.0: t_support *= 2.0 
        if state["dist_to_goal"] < 35.0: t_forward *= 1.5 
            
        if dist_to_own_goal < 30.0:
            t_hold *= 5.0 
            t_forward *= 0.1

        t_forward = max(0.0, t_forward)
        t_support = max(0.0, t_support)
        t_hold = max(1.0, t_hold)

        total = t_forward + t_support + t_hold
        probs = [t_forward/total, t_support/total, t_hold/total]
        return np.random.choice(actions, p=probs)

    def _decide_off_ball_defense(self, state: dict) -> str:
        dist_to_ball = np.linalg.norm(state["ball_pos"] - state["my_pos"])
        ball_pressure_count = int(np.sum(np.linalg.norm(state["opponents"] - state["ball_pos"], axis=1) < 3.0))
        
        # Immediate proximity: Tackle or block
        if dist_to_ball < 2.0:
            actions = ["tackle", "contain"]
            t_tackle = max(1.0, self.attributes.aggression * 1.5)
            t_contain = max(1.0, getattr(self.attributes, "defending", 50) + (100 - self.attributes.aggression))
            probs = [t_tackle / (t_tackle + t_contain), t_contain / (t_tackle + t_contain)]
            return np.random.choice(actions, p=probs)

        # Mid-range: Get in front of the ball instead of retreating
        if dist_to_ball < 15.0:
            if ball_pressure_count >= 2:
                return "contain" 
            if np.random.randint(0, 100) < getattr(self.attributes, "aggression", 40):
                return "press"
            else:
                return "contain"
        
        # Far away: Fall back to formation shape
        return "hold_defense"
        
    def _decide_loose_ball(self, state: dict) -> str:
        dist_to_ball = np.linalg.norm(state["ball_pos"] - state["my_pos"])
        teammate_closer_count = int(np.sum(np.linalg.norm(state["teammates"] - state["my_pos"], axis=1) < 4.0))
        
        if teammate_closer_count >= 2: return "recover"
        if dist_to_ball < 1.0: return "capture"
        if dist_to_ball < 20.0: return "press"
        
        return "recover_slow"



    ##visual stuff
    def __str__(self):
        attributes_str = ""
        for aname,aval in asdict(self.attributes).items():
            attributes_str += f"{aname}: {aval}\n"  

        return f"""*** {self.fname} {self.lname} *** 
        Matches Played = {self.statistics.get("matches_played")}
        Goals = {self.statistics.get("goals")}
        Assists = {self.statistics.get("assists")}
        
        *** Attributes ***
        {attributes_str}
        ------------------------
        """

    def __repr__(self):
        return f"Player({self.fname} {self.lname}, {self.position})"