from packedfootball.player.player import player, ActionProfile
from packedfootball.gameEngine import PITCH_HEIGHT,PITCH_WIDTH
import numpy as np


class ForwardActionProfile(ActionProfile):
    role_name = "forward"
    allowed_actions = {
        "stop",
        "shoot",
        "pass",
        "cross",
        "dribble",
        "forward_run",
        "support",
        "hold_attack",
        "hold_defense",
        "press",
        "recover",
        "recover_slow",
        "capture",
    }
    action_biases = {
        "shoot": 1.6,
        "pass": 0.9,
        "cross": 1.1,
        "dribble": 1.4,
        "forward_run": 1.5,
        "support": 1.0,
        "hold_attack": 0.8,
        "press": 0.9,
        "recover": 0.7,
        "capture": 1.1,
    }


class Forward(player):
    def __init__(self, fname, lname, position, attributes=None):
        self.action_profile = ForwardActionProfile()
        super().__init__(fname, lname, position, attributes)

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
            
        elif decision == "press":
            target = self._predict_ball_landing_target(state)
            vec_to_target = target - state["my_pos"]
            press_weight = 0.9 + (self.attributes.speed / 100.0) * 0.25
            press_target = state["my_pos"] + (vec_to_target * press_weight)
            return {"type": "move", "target": press_target, "speed_mod": (self.attributes.speed * 0.9) / 100.0}

        elif decision == "contain":
            target = self._predict_ball_landing_target(state)
            vec_to_target = target - state["my_pos"]
            contain_weight = 0.5 + (self.attributes.speed / 100.0) * 0.2
            contain_target = state["my_pos"] + (vec_to_target * contain_weight)
            return {"type": "move", "target": contain_target, "speed_mod": (self.attributes.speed * 0.5) / 100.0}
            
        elif decision in {"recover", "recover_slow"}:
            ball_pos = state["ball_pos"]
            
            shift_x = (ball_pos[0] - 35.0) * 0.35  
            shift_y = (ball_pos[1] - 50.0) 
            
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
            t_shoot -= (dist_to_goal * 20.0)

        if facing_goal < 0.0:
            t_shoot *= 0.1
        elif facing_goal > 0.8:
            t_shoot *= 1.5

        if pressure > 1:
            t_dribble -= (pressure * 25)
            t_pass += (pressure * 18)
            t_stop = 0
            t_shoot -= (pressure * 30.0)
        elif pressure == 0:
            t_dribble += (self.attributes.speed * 1.8) + 90.0
            t_pass -= 25.0
            t_stop += 10

        if self._goal_lane_is_open(state, lane_width=2.5, lookahead=10.0):
            t_dribble += 60.0
            t_pass -= 18.0
            t_stop += 5.0

        if pressure > 0 and not self._goal_lane_is_open(state, lane_width=3.0, lookahead=12.0):
            t_pass *= 3.0
            t_dribble *= 0.55

        t_pass = max(0.0, t_pass)
        t_shoot = max(0.0, t_shoot)
        t_dribble = max(1.0, t_dribble)
        t_stop = max(0.0, t_stop)

        total = t_pass + t_shoot + t_dribble + t_stop
        if total <= 0:
            return "dribble"
        probs = [t_pass / total, t_shoot / total, t_dribble / total, t_stop / total]
        return np.random.choice(actions, p=probs)

    def _decide_on_ball_defense(self, state: dict) -> str:
        actions = ["pass", "dribble", "stop",]
        progressive_pass = self._best_progressive_pass_target(state) is not None
        pressure = state.get("pressure_count", 0)

        t_pass = self.attributes.pass_tendency * 0.45
        t_dribble = self.attributes.drible_tendency
        t_stop = 15.0

        if not progressive_pass:
            t_pass *= 0.1
        elif pressure > 0:
            t_pass *= 1.3

        own_goal_y = 0.0 if state.get("a_direction", 1) == 1 else 100.0
        dist_to_own_goal = np.linalg.norm(np.array([35.0, own_goal_y]) - state["my_pos"])

        if dist_to_own_goal < 25.0:
            t_dribble *= 0.3

        if pressure > 1:
            t_pass += (pressure * 12)
            if not self._goal_lane_is_open(state, lane_width=3.0, lookahead=12.0):
                t_dribble *= 0.1
                t_stop = 0
        elif pressure == 0:
            t_dribble += (self.attributes.speed * 2.0) + 60.0
            t_pass -= 18.0
            t_stop += 15

        t_pass = max(0.0, t_pass)
        t_dribble = max(10.0, t_dribble)
        t_stop = max(0.0, t_stop)

        total = t_pass + t_dribble + t_stop
        if total <= 0:
            return "dribble"
        probs = [t_pass / total, t_dribble / total, t_stop / total]
        return np.random.choice(actions, p=probs)

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
        return np.random.choice(actions, p=probs)

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
            return np.random.choice(actions, p=probs)

        if dist_to_ball < 15.0:
            if ball_pressure_count >= 2:
                return "contain"
            if np.random.randint(0, 100) < getattr(self.attributes, "aggression", 40):
                return "press"
            else:
                return "contain"

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