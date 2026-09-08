from packedfootball.player.player import player, ActionProfile


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
