from packedfootball.player.player import player, ActionProfile


class GoalkeeperActionProfile(ActionProfile):
    role_name = "goalkeeper"
    allowed_actions = {
        "stop",
        "pass",
        "clear",
        "hold_attack",
        "hold_defense",
        "recover",
        "recover_slow",
        "contain",
        "capture",
    }
    action_biases = {
        "pass": 0.2,
        "clear": 3.0,
        "hold_attack": 0.8,
        "hold_defense": 1.6,
        "recover": 3,
        "contain": 1.2,
        "capture": 1,
    }


class Goalkeeper(player):
    def __init__(self, fname, lname, position, attributes=None):
        self.action_profile = GoalkeeperActionProfile()
        super().__init__(fname, lname, position, attributes)
