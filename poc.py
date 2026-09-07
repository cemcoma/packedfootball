from packedfootball.gameEngine import run_match
from packedfootball import player
import random
fnames = ["cem","arda","kanat","mustafa","tarık","ismail"]
lnames = ["çamdalı","terzi","tivsiz","demir","taş","kartal"]

class Team:
    def __init__(self, prefix):
        self.players = [player.player(prefix, str(i), "CM") for i in range(11)]


def sim_match(teamA,teamB):
    teamA = Team("A")
    teamB = Team("B")

    match = run_match(teamA, teamB, max_steps=20000, fps=60, render=True)





















def generate_players():
    return [player.player(fnames[random.randint(0,5)],lnames[random.randint(0,5)],"CM",) for _ in range(11)]


teamA = {"name":"Sönmezkent Vila Spor Kulübü","players":generate_players()}
teamB = {"name":"Kamçıoğlu FC", "players":generate_players()}

sim_match(teamA,teamB)


