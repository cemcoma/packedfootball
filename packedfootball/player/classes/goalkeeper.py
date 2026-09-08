from packedfootball.player.player import player, ActionProfile
import numpy as np

class GoalkeeperActionProfile(ActionProfile):
    role_name = "goalkeeper"
    allowed_actions = {
        "stop",
        "pass",
        "clear",
        "hold_defense",
        "recover",
        "recover_slow",
        "contain",
        "capture",
    }
    action_biases = {
        "pass": 0.2,
        "clear": 3.0,
        "hold_defense": 2.0,
        "recover": 3,
        "contain": 1.2,
        "capture": 1,
    }


class Goalkeeper(player):
    def __init__(self, fname, lname, position, attributes=None):
        self.action_profile = GoalkeeperActionProfile()
        super().__init__(fname, lname, position, attributes)
        self.attributes.ballcontrol +=20

    def _decide_on_ball_defense(self, state: dict) -> str:
        if state.get("must_pass_next", False):
            return "pass"

        # Goalkeepers never dribble. They pass, clear, or wait.
        actions = ["pass", "clear", "stop"]
        pressure = state.get("pressure_count", 0)

        t_pass = getattr(self.attributes, "pass_tendency", 50) * 0.8
        t_clear = getattr(self.attributes, "clear_tendency", 50) * 1.5
        t_stop = 40.0

        if pressure > 0:
            t_clear *= 4.0
            t_pass *= 1.2
            t_stop = 0.0  # Do not hold the ball under pressure

        total = t_pass + t_clear + t_stop
        if total <= 0:
            return "clear"
            
        probs = [t_pass / total, t_clear / total, t_stop / total]
        return np.random.choice(actions, p=probs)

    def _decide_on_ball_attack(self, state: dict) -> str:
        # If the keeper somehow ends up past the halfway line, force them to act defensively
        return self._decide_on_ball_defense(state)
