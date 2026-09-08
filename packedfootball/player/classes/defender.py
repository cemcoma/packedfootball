from packedfootball.player.player import player, ActionProfile


class DefenderActionProfile(ActionProfile):
    role_name = "defender"
    allowed_actions = {
        "stop",
        "pass",
        "clear",
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
        "pass": 0.8,
        "clear": 1.4,
        "dribble": 0.4,
        "forward_run": 0.5,
        "support": 0.7,
        "hold_attack": 0.7,
        "hold_defense": 1.5,
        "press": 1.2,
        "contain": 1.4,
        "recover": 1.3,
        "tackle": 1.4,
        "capture": 1.0,
    }


class Defender(player):
    def __init__(self, fname, lname, position, attributes=None):
        self.action_profile = DefenderActionProfile()
        super().__init__(fname, lname, position, attributes)
