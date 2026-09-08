from packedfootball.gameEngine import run_match
from packedfootball.player.player import Attributes
from packedfootball.player.classes.goalkeeper import Goalkeeper
from packedfootball.player.classes.defender import Defender
from packedfootball.player.classes.midfielder import Midfielder
from packedfootball.player.classes.winger import Winger
from packedfootball.player.classes.striker import Striker


TEAM_A = [
    ("Cem", "Akbaş", "GK", {"speed": 62, "agility": 68, "passing": 54, "defending": 58, "composure": 76}),
    ("Arda", "Yılmaz", "CB", {"speed": 72, "agility": 67, "defending": 81, "tackling": 83, "composure": 74}),
    ("Mert", "Sarı", "CB", {"speed": 70, "agility": 65, "defending": 80, "tackling": 82, "composure": 72}),
    ("Tarık", "Demir", "LB", {"speed": 76, "agility": 74, "passing": 69, "defending": 76, "composure": 70}),
    ("Mustafa", "Kaya", "RB", {"speed": 75, "agility": 72, "passing": 67, "defending": 75, "composure": 71}),
    ("Emre", "Kaya", "CM", {"speed": 78, "agility": 80, "passing": 81, "ballcontrol": 82, "composure": 84}),
    ("Onur", "Aydın", "CM", {"speed": 80, "agility": 78, "passing": 75, "ballcontrol": 84, "defending": 72, "composure": 80}),
    ("Can", "Tuna", "AM", {"speed": 82, "agility": 85, "passing": 88, "ballcontrol": 86, "shooting": 78, "composure": 87}),
    ("Kerem", "Yalçın", "LW", {"speed": 88, "agility": 90, "passing": 74, "dribbiling": 88, "shooting": 70, "composure": 80}),
    ("Baran", "Şen", "RW", {"speed": 86, "agility": 88, "passing": 72, "dribbiling": 87, "shooting": 72, "composure": 79}),
    ("İsmail", "Kartal", "ST", {"speed": 83, "agility": 79, "shooting": 89, "passing": 68, "ballcontrol": 82, "composure": 86}),
]

TEAM_B = [
    ("Ali", "Çolak", "GK", {"speed": 60, "agility": 66, "passing": 52, "defending": 57, "composure": 77}),
    ("Koray", "Eren", "CB", {"speed": 71, "agility": 64, "defending": 82, "tackling": 84, "composure": 73}),
    ("Ozan", "Turan", "CB", {"speed": 69, "agility": 63, "defending": 79, "tackling": 80, "composure": 72}),
    ("Mehmet", "Ak", "LB", {"speed": 74, "agility": 73, "passing": 70, "defending": 75, "composure": 70}),
    ("Yusuf", "Kurt", "RB", {"speed": 73, "agility": 70, "passing": 66, "defending": 76, "composure": 69}),
    ("Volkan", "Demir", "CM", {"speed": 77, "agility": 79, "passing": 82, "ballcontrol": 81, "defending": 71, "composure": 83}),
    ("Deniz", "Erol", "CM", {"speed": 79, "agility": 77, "passing": 79, "ballcontrol": 83, "defending": 70, "composure": 82}),
    ("Umut", "Fidan", "AM", {"speed": 81, "agility": 84, "passing": 87, "ballcontrol": 85, "shooting": 77, "composure": 86}),
    ("Musa", "Gül", "LW", {"speed": 87, "agility": 91, "passing": 73, "dribbiling": 89, "shooting": 69, "composure": 81}),
    ("Burak", "Sak", "RW", {"speed": 85, "agility": 87, "passing": 71, "dribbiling": 86, "shooting": 73, "composure": 80}),
    ("Kaan", "Kızıl", "ST", {"speed": 82, "agility": 78, "shooting": 88, "passing": 67, "ballcontrol": 83, "composure": 85}),
]

PLAYER_CLASS_MAP = {
    "GK": Goalkeeper,
    "CB": Defender,
    "LB": Defender,
    "RB": Defender,
    "CM": Midfielder,
    "AM": Midfielder,
    "LW": Winger,
    "RW": Winger,
    "ST": Striker,
}


def build_player(first, last, position, overrides=None):
    attrs = Attributes()
    base_stats = {
        "stamina": 70,
        "speed": 70,
        "agility": 70,
        "passing": 70,
        "ballcontrol": 70,
        "defending": 70,
        "tackling": 70,
        "dribbiling": 70,
        "shooting": 70,
        "power": 75,
        "accuracy": 75,
        "vision": 70,
        "pass_tendency": 60,
        "shoot_tendency": 70,
        "drible_tendency": 60,
        "aggression": 50,
        "composure": 70,
        "clear_tendency": 30,
    }
    for key, value in base_stats.items():
        setattr(attrs, key, value)
    if overrides:
        for key, value in overrides.items():
            setattr(attrs, key, value)
    player_cls = PLAYER_CLASS_MAP.get(position, Midfielder)
    return player_cls(first, last, position, attrs)


class Team:
    def __init__(self, name, prefix, rows):
        self.name = name
        self.prefix = prefix
        self.players = [build_player(first, last, position, attrs) for first, last, position, attrs in rows]


def sim_match(team_a, team_b, render=True, max_steps=10000):
    return run_match(team_a, team_b, max_steps=max_steps, fps=60, render=render)











team_a = Team("Sönmezkent Vila Spor Kulübü", "SVSK", TEAM_A)
team_b = Team("Kamçıoğlu FC", "KFC", TEAM_B)

sim_match(team_a, team_b, render=True)


