from gameEngine import PITCH_WIDTH, GOAL_WIDTH, PITCH_HEIGHT, possession_radius
from player.player import player, ActionProfile
import numpy as np


class GoalkeeperActionProfile(ActionProfile):
    role_name = "goalkeeper"
    allowed_actions = {
        "stop", "pass", "clear", "hold_defense",
        "recover", "recover_slow", "contain", "capture", "dive", "save"
    }
    action_biases = {
        "pass": 0.2, "clear": 3.0, "hold_defense": 2.0,
        "recover": 3.0, "contain": 1.2, "capture": 1.5, "dive": 2.0
    }

class Goalkeeper(player):
    primary_stats = ("passing", "agility", "ballcontrol")
    primary_weight: float = 1.0

    def __init__(self, fname, lname, tier, position, attributes=None, country=None, hometown=None, appearance=None):
        super().__init__(fname, lname, tier, position, attributes, country, hometown, appearance)
        self.action_profile = GoalkeeperActionProfile()
        self.allowed_actions = set(self.action_profile.get_allowed_actions())
        self.action_biases = dict(self.action_profile.get_action_biases())
        
        self.attributes.ballcontrol = min(100, self.attributes.ballcontrol + 20)
        self.attributes.agility = min(100, self.attributes.agility + 15)

    def _get_keeper_line(self, state: dict) -> float:
        return 1 if state.get("a_direction", 1) == 1 else PITCH_HEIGHT-1

    def _build_action(self, decision: str, state: dict) -> dict | None:
        if decision == "stop":
            return None
            
        elif decision == "pass":
            best_target = self._choose_pass_target(state)
            dist = np.linalg.norm(best_target - state["my_pos"])
            required_power = min(1.0, dist / 8.0) 
            actual_power = required_power * (self.attributes.power / 50.0)
            return {"type": "pass", "target": best_target, "power": actual_power}
            
        elif decision == "clear":
            forward_y = PITCH_HEIGHT if state.get("a_direction", 1) == 1 else 0.0
            wide_x = state["rng"].choice([0.0, PITCH_WIDTH])
            target = np.array([wide_x + state["rng"].uniform(-15, 15), forward_y])
            return {"type": "pass", "target": target, "power": min(1.0, self.attributes.power / 40.0), "pass_type": "clearance"}

        elif decision == "dive":
            keeper_y = self._get_keeper_line(state)
            ball_pos = state["ball_pos"]
            ball_vel = state.get("ball_velocity", np.zeros(2, dtype=float))
            
            # Predict intercept accounting for basic trajectory 
            if abs(ball_vel[1]) > 0.1:
                time_to_intercept = (keeper_y - ball_pos[1]) / ball_vel[1]
                intercept_x = ball_pos[0] + (ball_vel[0] * time_to_intercept)
            else:
                intercept_x = ball_pos[0]
                
            # Fuzziness: Lower vision creates larger positional misjudgments
            fuzz = state["rng"].normal(0, max(0.0, (100 - self.attributes.vision) / 40.0))
            intercept_x += fuzz
            
            # Clamp strictly to the goal posts (35.0 +/- ~3.75) with slight padding
            target_x = np.clip(intercept_x, 31.0, 39.0)
            burst_speed = max(1.2, (self.attributes.speed * 0.4 + self.attributes.agility * 1.6) / 100.0)
            
            return {"type": "move", "target": np.array([target_x, keeper_y]), "speed_mod": burst_speed}
            
        elif decision in {"hold_defense", "contain", "recover", "recover_slow"}:
            keeper_y = self._get_keeper_line(state)
            
            # Strictly lock Y to the goal line, only track the ball's X coordinate
            target_x = np.clip(state["ball_pos"][0], 31.0, 39.0)
            
            speed = 0.9 if decision in {"contain", "recover"} else 0.5
            return {"type": "move", "target": np.array([target_x, keeper_y]), "speed_mod": (self.attributes.speed * speed) / 100.0}
            
        elif decision == "save":
            return {"type": "save", "stat": self.attributes.agility}
            
        elif decision == "capture":
            return {"type": "capture", "stat": self.attributes.ballcontrol + 15}
            
        return None

    def _decide_on_ball_attack(self, state: dict) -> str:
        return self._decide_on_ball_defense(state)

    def _decide_on_ball_defense(self, state: dict) -> str:
        if state.get("must_pass_next", False):
            return "pass"

        actions = ["pass", "clear", "stop"]
        pressure = state.get("pressure_count", 0)

        t_pass = getattr(self.attributes, "pass_tendency", 50) * 0.8 * self.get_action_bias("pass")
        t_clear = getattr(self.attributes, "clear_tendency", 50) * 1.5 * self.get_action_bias("clear")
        t_stop = 40.0 * self.get_action_bias("stop")

        if pressure > 0:
            t_clear *= 4.0
            t_pass *= 1.2
            t_stop = 0.0

        total = t_pass + t_clear + t_stop
        if total <= 0: 
            return "clear"
            
        probs = [t_pass / total, t_clear / total, t_stop / total]
        return state["rng"].choice(actions, p=probs)

    def _decide_off_ball_attack(self, state: dict) -> str:
        # GK always stay in their box mirroring the play, even on the attack
        return "hold_defense"

    def _decide_off_ball_defense(self, state: dict) -> str:
        dist_to_ball = np.linalg.norm(state["ball_pos"] - state["my_pos"])
        ball_vel = state.get("ball_velocity", np.zeros(2, dtype=float))
        ball_speed = np.linalg.norm(ball_vel)
        own_goal_y = 0.0 if state.get("a_direction", 1) == 1 else 100.0
        
        moving_to_goal = (own_goal_y == 0.0 and ball_vel[1] < -1.0) or (own_goal_y == 100.0 and ball_vel[1] > 1.0)

        if dist_to_ball < 1.5:
            return "capture"

        if moving_to_goal and dist_to_ball < 4.0:
            return "save"

        if moving_to_goal and ball_speed > 10.0:
            time_to_impact = abs((own_goal_y - state["ball_pos"][1]) / (ball_vel[1] + 1e-8))
            if time_to_impact < 1.2:
                return "dive"

        return "contain"

    def _decide_loose_ball(self, state: dict) -> str:
        return self._decide_off_ball_defense(state)