from packedfootball.player.player import player, ActionProfile


class MidfielderActionProfile(ActionProfile):
    role_name = "midfielder"
    allowed_actions = {
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
    action_biases = {
        "pass": 1.5,
        "shoot": 0.8,
        "cross": 1.1,
        "dribble": 1.1,
        "forward_run": 1.2,
        "support": 1.4,
        "hold_attack": 1.0,
        "hold_defense": 1.0,
        "press": 1.1,
        "contain": 1.0,
        "recover": 1.0,
        "tackle": 0.9,
        "capture": 0.8,
    }


class Midfielder(player):
    def __init__(self, fname, lname, position, attributes=None):
        self.action_profile = MidfielderActionProfile()
        super().__init__(fname, lname, position, attributes)
