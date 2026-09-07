import packedfootball.player as player
import random
fnames = ["cem","arda","kanat","mustafa","tarık","ismail"]
lnames = ["çamdalı","terzi","tivsiz","demir","taş","kartal"]




def sim_match(teamA,teamB):
    print(f"Simulating between team A: {teamA.get("name")} and team B: {teamB.get("name")}" )
    print(teamA.get("players"))























def generate_players():
    return [player.player(fnames[random.randint(0,5)],lnames[random.randint(0,5)],"CM") for _ in range()]


teamA = {"name":"Sönmezkent Vila Spor Kulübü","players":generate_players()}
teamB = {"name":"Kamçıoğlu FC", "players":generate_players()}

sim_match(teamA,teamB)


