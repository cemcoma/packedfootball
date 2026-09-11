from player.player import player, ActionProfile
from gameEngine import PITCH_HEIGHT,PITCH_WIDTH
import numpy as np

class MidfielderActionProfile(ActionProfile):
    role_name = "midfielder"
    allowed_actions = {
        "stop", "shoot", "pass", "clear", "cross", "dribble",
        "forward_run", "support", "hold_attack", "hold_defense",
        "press", "contain", "recover", "recover_slow", "tackle", "capture",
    }
    action_biases = {
        "pass": 1.5, "shoot": 0.8, "cross": 1.1, "dribble": 1.1,
        "forward_run": 1.2, "support": 1.4, "hold_attack": 1.0,
        "hold_defense": 1.0, "press": 1.1, "contain": 1.0,
        "recover": 1.0, "tackle": 0.9, "capture": 0.8,
    }


class DefensiveMidActionProfile(ActionProfile):
    role_name = "defensive_mid"
    allowed_actions = {
        "stop", "shoot", "pass", "clear", "cross", "dribble",
        "forward_run", "support", "hold_attack", "hold_defense",
        "press", "contain", "recover", "recover_slow", "tackle", "capture",
        "screen",
    }
    action_biases = {
        "pass": 1.6, "shoot": 0.3, "cross": 0.3, "dribble": 0.6,
        "forward_run": 0.5, "support": 1.3, "hold_attack": 0.6,
        "hold_defense": 1.8, "press": 1.3, "contain": 1.4,
        "recover": 1.4, "tackle": 1.6, "capture": 1.3,
        "screen": 1.7,
    }


class AttackingMidActionProfile(ActionProfile):
    role_name = "attacking_mid"
    allowed_actions = {
        "stop", "shoot", "pass", "clear", "cross", "dribble",
        "forward_run", "support", "hold_attack", "hold_defense",
        "press", "contain", "recover", "recover_slow", "tackle", "capture",
        "through_ball",
    }
    action_biases = {
        "pass": 1.3, "shoot": 1.5, "cross": 1.0, "dribble": 1.3,
        "forward_run": 1.4, "support": 1.2, "hold_attack": 0.6,
        "hold_defense": 0.5, "press": 0.7, "contain": 0.7,
        "recover": 0.6, "tackle": 0.5, "capture": 0.9,
        "through_ball": 1.6,
    }


class Midfielder(player):
    primary_stats = ("passing", "ballcontrol", "vision")

    def __init__(self, fname, lname, tier, position, attributes=None, country=None, hometown=None):
        self.action_profile = MidfielderActionProfile()
        super().__init__(fname, lname, tier, position, attributes, country, hometown)

    def _choose_through_ball_target(self, state: dict):
        teammates = np.asarray(state.get("teammates", []), dtype=float)
        opponents = np.asarray(state.get("opponents", []), dtype=float)
        my_pos = np.asarray(state["my_pos"], dtype=float)
        goal_dir = 1.0 if state.get("a_direction", 1) == 1 else -1.0

        best_runner = None
        best_progress = 2.0  # minimum forward progress to even consider a runner
        for tm in teammates:
            if np.array_equal(tm, my_pos):
                continue
            forward_progress = (tm[1] - my_pos[1]) * goal_dir
            if forward_progress > best_progress:
                best_progress = forward_progress
                best_runner = tm

        if best_runner is None:
            return None

        lead_distance = 4.0 + (self.attributes.vision / 100.0) * 8.0
        led_target = best_runner.copy()
        led_target[1] += lead_distance * goal_dir
        led_target = np.clip(led_target, [0.0, 0.0], [PITCH_WIDTH, PITCH_HEIGHT])

        if not self._is_pass_safe(my_pos, led_target, opponents, line_width=1.3):
            return None
        return led_target

    def _build_action(self, decision: str, state: dict) -> dict | None:
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

        elif decision == "through_ball":
            through_target = self._choose_through_ball_target(state)
            if through_target is None:
                through_target = self._choose_pass_target(state)
            dist = np.linalg.norm(through_target - state["my_pos"])
            required_power = min(1.0, dist / 9.0)
            actual_power = required_power * (self.attributes.power / 55.0)
            return {"type": "pass", "target": through_target, "power": actual_power, "pass_type": "through_ball"}

        elif decision == "clear":
            forward_y = 100.0 if state.get("a_direction", 1) == 1 else 0.0
            wide_x = state["rng"].choice([0.0, 70.0])
            target = np.array([wide_x + state["rng"].uniform(-15, 15), forward_y])
            return {"type": "pass", "target": target, "power": min(1.0, self.attributes.power / 50.0), "pass_type": "clearance"}

        elif decision == "cross":
            cross_target = self._choose_cross_target(state)
            dist = np.linalg.norm(cross_target - state["my_pos"])
            required_power = min(1.0, dist / 12.0) 
            actual_power = required_power * (self.attributes.power / 60.0)
            return {"type": "pass", "target": cross_target, "power": actual_power, "pass_type": "cross"}
            
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

        elif decision == "screen":
            # CDM signature move: sits on the line between the ball and its
            # own goal to cut the passing lane into the back line, unlike
            # hold_defense's fixed formation offset or contain's ball-chase.
            own_goal_y = 0.0 if state.get("a_direction", 1) == 1 else 100.0
            own_goal = np.array([35.0, own_goal_y])
            ball_pos = np.asarray(state["ball_pos"], dtype=float)
            vec_to_goal = own_goal - ball_pos
            dist = np.linalg.norm(vec_to_goal)
            shield_distance = min(14.0, dist * 0.4)
            screen_target = ball_pos + (vec_to_goal / (dist + 1e-5)) * shield_distance
            return {"type": "move", "target": screen_target, "speed_mod": (self.attributes.speed * 0.7) / 100.0}

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
            return {"type": "move", "target": contain_target, "speed_mod": (self.attributes.speed) / 100.0}
            
        elif decision in {"recover", "recover_slow"}:
            ball_pos = state["ball_pos"]
            
            shift_x = (ball_pos[0] - 35.0) * 0.35  
            shift_y = (ball_pos[1] - 50.0) * 0.4
            
            base_pos = np.asarray(state["formation_pos"], dtype=float)
            shifted_target = base_pos + np.array([shift_x, shift_y])
            shifted_target[0] = np.clip(shifted_target[0], 0.0, 70.0) #TODO: hardcoded bunlar dğeiştir
            shifted_target[1] = np.clip(shifted_target[1], 0.0, 100.0)
            
            speed_mult = 0.7 if decision == "recover" else 0.4
            return {"type": "move", "target": shifted_target, "speed_mod": (self.attributes.speed * speed_mult) / 100.0}
            
        # --- Dispossession ---
        elif decision == "tackle":
            return {"type": "tackle", "stat": self.attributes.defending}
            
        elif decision == "capture":
            return {"type": "capture", "stat": self.attributes.ballcontrol}

        elif decision == "chase":
            ball_pos = state["ball_pos"]
            ball_vel = state.get("ball_velocity", np.zeros(2, dtype=float))
            ball_speed = np.linalg.norm(ball_vel)
            dist_to_ball = np.linalg.norm(ball_pos - state["my_pos"])
            
            if ball_speed < 2.0:
                target = ball_pos
            else:
                # Scale prediction by how long it takes the player to arrive
                my_speed = max(1.0, (self.attributes.speed / 100.0) * 10.0) 
                time_to_reach = dist_to_ball / my_speed
                predict_time = min(time_to_reach * 0.7, 1.5)
                
                decay_constant = 0.6931 
                lead_dist = (ball_speed / decay_constant) * (1.0 - (0.5 ** predict_time))
                unit_vel = ball_vel / ball_speed
                target = ball_pos + (unit_vel * lead_dist)
                
            return {"type": "move", "target": target, "speed_mod": (self.attributes.speed * 1.0) / 100.0}
            
        return None

    def _decide_on_ball_attack(self, state: dict) -> str:
        if state.get("must_pass_next", False):
            px, py = state["my_pos"]
            if (px <= 5.0 or px >=PITCH_WIDTH ) and (py <= 5.0 or py >=PITCH_HEIGHT):
                return "cross"
            return "pass"

        actions = ["pass", "shoot", "dribble", "stop", "through_ball"]
        progressive_pass = self._best_progressive_pass_target(state) is not None
        pressure = state.get("pressure_count", 0)

        t_pass = self.attributes.pass_tendency * 0.4
        t_shoot = self.attributes.shoot_tendency
        t_dribble = self.attributes.drible_tendency
        t_stop = 10.0
        through_ball_target = self._choose_through_ball_target(state)
        t_through = (self.attributes.vision + self.attributes.passing) * 0.5 * self.get_action_bias("through_ball", 0.0) if through_ball_target is not None else 0.0

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

        if facing_goal < 0.0:
            t_shoot *= 0.1
        elif facing_goal > 0.8:
            t_shoot *= 1.5

        if pressure > 1:
            t_dribble -= (pressure * 25)
            t_pass += (pressure * 18)
            t_stop = 0
            t_through *= 1.2
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
        t_through = max(0.0, t_through)

        total = t_pass + t_shoot + t_dribble + t_stop + t_through
        if total <= 0:
            return "dribble"
        probs = [t_pass / total, t_shoot / total, t_dribble / total, t_stop / total, t_through / total]
        return state["rng"].choice(actions, p=probs)

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
                t_dribble *= 0.1
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
        probs = [t_pass / total, t_dribble / total, t_stop / total, t_clear / total]
        return state["rng"].choice(actions, p=probs)

    def _decide_off_ball_attack(self, state: dict) -> str:
        if state.get("is_loose", False):
            landing_target = self._predict_ball_landing_target(state)
            my_dist = np.linalg.norm(landing_target - state["my_pos"])
            
            teammates = np.asarray(state.get("teammates", []))
            closer_teammates = 0
            if teammates.size > 0:
                closer_teammates = int(np.sum(np.linalg.norm(teammates - landing_target, axis=1) < my_dist - 0.1))
                
            if closer_teammates == 0:
                return "chase"
        
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

        if dist_to_ball < 20.0:
            t_support *= 2.0
        if state["dist_to_goal"] < 35.0:
            t_forward *= 1.5

        if dist_to_own_goal < 30.0:
            t_hold *= 5.0
            t_forward *= 0.1

        t_forward = max(0.0, t_forward)
        t_support = max(0.0, t_support)
        t_hold = max(1.0, t_hold)

        total = t_forward + t_support + t_hold
        probs = [t_forward / total, t_support / total, t_hold / total]
        return state["rng"].choice(actions, p=probs)

    def _decide_off_ball_defense(self, state: dict) -> str:
        if state.get("is_loose", False):
            landing_target = self._predict_ball_landing_target(state)
            my_dist = np.linalg.norm(landing_target - state["my_pos"])
            
            teammates = np.asarray(state.get("teammates", []))
            closer_teammates = 0
            if teammates.size > 0:
                closer_teammates = int(np.sum(np.linalg.norm(teammates - landing_target, axis=1) < my_dist - 0.1))
                
            if closer_teammates == 0:
                return "chase"
            
        dist_to_ball = np.linalg.norm(state["ball_pos"] - state["my_pos"])
        ball_pressure_count = int(np.sum(np.linalg.norm(state["opponents"] - state["ball_pos"], axis=1) < 3.0))

        if dist_to_ball < 2.0:
            actions = ["tackle", "contain"]
            t_tackle = max(1.0, self.attributes.aggression * 1.5)
            t_contain = max(1.0, getattr(self.attributes, "defending", 50) + (100 - self.attributes.aggression))
            probs = [t_tackle / (t_tackle + t_contain), t_contain / (t_tackle + t_contain)]
            return state["rng"].choice(actions, p=probs)

        if dist_to_ball < 15.0:
            if ball_pressure_count >= 2:
                return "contain"
            if state["rng"].integers(0, 100) < getattr(self.attributes, "aggression", 40):
                return "press"
            else:
                return "contain"

        t_screen = self.get_action_bias("screen", 0.0)
        if t_screen > 0.0:
            actions = ["hold_defense", "screen"]
            t_hold = 1.0
            probs = [t_hold / (t_hold + t_screen), t_screen / (t_hold + t_screen)]
            return state["rng"].choice(actions, p=probs)

        return "hold_defense"

    def _decide_loose_ball(self, state: dict) -> str:
            dist_to_ball = np.linalg.norm(state["ball_pos"] - state["my_pos"])
            
            # Calculate distances of all teammates to the ball
            teammates = np.asarray(state.get("teammates", []))
            if teammates.size > 0:
                teammate_dists = np.linalg.norm(teammates - state["ball_pos"], axis=1)
                # Count exactly how many teammates are closer to the ball than I am
                # We subtract 0.1 to avoid tie-breaking bugs with our own distance
                closer_teammates = int(np.sum(teammate_dists < dist_to_ball - 0.1))
            else:
                closer_teammates = 0

            # Absolute priority: grab the ball if it is at our feet
            if dist_to_ball < 2.5: 
                return "capture"

            # 1. The single closest player to the ball goes directly to the landing spot
            if closer_teammates == 0:
                return "chase"
                
            # 2. The second closest player provides secondary support if nearby
            if closer_teammates == 1 and dist_to_ball < 15.0:
                return "contain"

            # 3. Everyone else actively runs away from the ball back to their tactical zone
            return "recover"


class DefensiveMid(Midfielder):
    """CDM: shields the back line. Signature move is "screen" 
    """
    primary_stats = ("defending", "tackling", "passing")

    def __init__(self, fname, lname, tier, position, attributes=None, country=None, hometown=None):
        super().__init__(fname, lname, tier, position, attributes, country, hometown)
        self.action_profile = DefensiveMidActionProfile()
        self.allowed_actions = set(self.action_profile.get_allowed_actions())
        self.action_biases = dict(self.action_profile.get_action_biases())

        self.attributes.defending = min(100, self.attributes.defending + 12)
        self.attributes.tackling = min(100, self.attributes.tackling + 8)


class AttackingMid(Midfielder):
    """CAM: the creative outlet in the pocket behind the striker. Signature
    move is "through_ball" 
    """
    primary_stats = ("passing", "vision", "shooting")

    def __init__(self, fname, lname, tier, position, attributes=None, country=None, hometown=None):
        super().__init__(fname, lname, tier, position, attributes, country, hometown)
        self.action_profile = AttackingMidActionProfile()
        self.allowed_actions = set(self.action_profile.get_allowed_actions())
        self.action_biases = dict(self.action_profile.get_action_biases())

        self.attributes.vision = min(100, self.attributes.vision + 12)
        self.attributes.shoot_tendency = min(100, self.attributes.shoot_tendency + 10)