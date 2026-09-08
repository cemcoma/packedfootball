from packedfootball.player.player import player, ActionProfile


class StrikerActionProfile(ActionProfile):
    role_name = "striker"
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
        "shoot": 2.0,
        "dribble": 1.6,
        "forward_run": 1.5,
        "pass": 0.9,
        "cross": 0.7,
        "support": 0.9,
        "hold_attack": 0.7,
        "press": 0.8,
        "recover": 0.7,
        "capture": 1.1,
    }


class Striker(player):
    def __init__(self, fname, lname, position, attributes=None):
        self.action_profile = StrikerActionProfile()
        super().__init__(fname, lname, position, attributes)
