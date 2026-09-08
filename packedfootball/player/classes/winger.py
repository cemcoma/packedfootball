from packedfootball.player.player import player, ActionProfile


class WingerActionProfile(ActionProfile):
    role_name = "winger"
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
        "contain",
        "recover",
        "recover_slow",
        "capture",
    }
    action_biases = {
        "cross": 1.8,
        "dribble": 1.5,
        "forward_run": 1.4,
        "shoot": 0.9,
        "pass": 1.1,
        "support": 1.2,
        "hold_attack": 0.9,
        "press": 1.1,
        "contain": 0.9,
        "recover": 0.8,
        "capture": 1.0,
    }


class Winger(player):
    def __init__(self, fname, lname, position, attributes=None):
        self.action_profile = WingerActionProfile()
        super().__init__(fname, lname, position, attributes)
