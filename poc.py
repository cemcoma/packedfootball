import random
import time
import multiprocessing

from packedfootball.gameEngine import run_match
from packedfootball.player.player import Attributes
from packedfootball.player.classes.goalkeeper import Goalkeeper
from packedfootball.player.classes.defender import Defender, CenterBack, Fullback
from packedfootball.player.classes.midfielder import Midfielder
from packedfootball.player.classes.forward import Forward

TIER_RANGES = {
    "bronze": (50, 55),
    "silver": (55, 60),
    "gold": (60, 70),
    "platinum": (70, 80),
    "diamond": (80, 85),
    "special": (85, 95)
}

def generate_tier_attributes(position: str, tier: str) -> dict:
    min_s, max_s = TIER_RANGES.get(tier.lower(), (40, 50))

    def roll_stat(stat_type):
        if stat_type == "primary":
            return random.randint(min_s + (max_s - min_s) // 2, max_s)
        elif stat_type == "secondary":
            return random.randint(min_s, max_s)
        elif stat_type == "nerfed":
            return random.randint(30, 55)

    profile = {
        "speed": "secondary", "agility": "secondary", "passing": "secondary", 
        "ballcontrol": "secondary", "defending": "secondary", "tackling": "secondary", 
        "dribbiling": "secondary", "shooting": "secondary", "power": "secondary", 
        "accuracy": "secondary", "vision": "secondary", "composure": "secondary"
    }

    if position == "GK":
        profile.update(defending="nerfed", tackling="nerfed", shooting="nerfed", dribbiling="nerfed", passing="primary", agility="primary", composure="primary", ballcontrol="primary")
    elif position in ["CB", "LB", "RB"]:
        profile.update(defending="primary", tackling="primary", shooting="nerfed", dribbiling="nerfed")
    elif position in ["CM", "AM"]:
        profile.update(passing="primary", ballcontrol="primary", vision="primary")
        if position == "AM":
            profile.update(defending="nerfed", tackling="nerfed")
    elif position in ["LW", "RW"]:
        profile.update(speed="primary", agility="primary", dribbiling="primary", defending="nerfed", tackling="nerfed")
    elif position == "ST":
        profile.update(shooting="primary", power="primary", accuracy="primary", defending="nerfed", tackling="nerfed")

    return {stat: roll_stat(s_type) for stat, s_type in profile.items()}

PLAYER_CLASS_MAP = {
    "GK": Goalkeeper,
    "CB": CenterBack,
    "LB": Fullback,
    "RB": Fullback,
    "CM": Midfielder,
    "LW": Forward,
    "RW": Forward,
    "ST": Forward,
}

def build_player(first, last, position, tier):
    attrs = Attributes()
    base_stats = {
        "stamina": 70, "pass_tendency": 60, "shoot_tendency": 70,
        "drible_tendency": 60, "aggression": 50, "clear_tendency": 30,
    }
    for key, value in base_stats.items():
        setattr(attrs, key, value)
        
    overrides = generate_tier_attributes(position, tier)
    for key, value in overrides.items():
        setattr(attrs, key, value)
        
    player_cls = PLAYER_CLASS_MAP.get(position, Midfielder)
    return player_cls(first, last, position, attrs)

class Team:
    def __init__(self, name, prefix, rows):
        self.name = name
        self.prefix = prefix
        self.players = [build_player(first, last, position, tier) for first, last, position, tier in rows]

def sim_match(team_a, team_b, render=True, max_steps=10800):
    return run_match(team_a, team_b, max_steps=max_steps, fps=60, render=render)

# --- Dynamic Team Templates ---

def get_tier_roster(tier: str):
    """Generates a full 11-man roster for a given tier."""
    positions = ["GK", "LB", "CB", "CB", "RB", "LW", "CM", "CM", "RW", "ST", "ST"]
    
    # Passing the Tier + Position as the `lname` argument so it renders in the UI
    return [("Player", f"{tier.capitalize()} {pos}", pos, tier) for pos in positions]

TEAM_BRONZE = get_tier_roster("bronze")
TEAM_SILVER = get_tier_roster("silver")
TEAM_GOLD = get_tier_roster("gold")
TEAM_PLATINUM = get_tier_roster("platinum")
TEAM_DIAMOND = get_tier_roster("diamond")
TEAM_SPECIAL = get_tier_roster("special")

# --- Setup and Run POC ---

# Swap these out to test different matchups!
team_a = Team("Team_A", "a", TEAM_SPECIAL)
team_b = Team("Team_B", "b", TEAM_DIAMOND)

start_time = time.perf_counter()
game = sim_match(team_a, team_b, render=False)
end_time = time.perf_counter()
execution_time = end_time - start_time
print("--- FULL TIME ---")
print(f"{game.teamA.name}: {game.scores[0]}")
print(f"{game.teamB.name}: {game.scores[1]}")
print(f"Simulation computed in: {execution_time:.4f} seconds")

all_players = team_a.players + team_b.players
for i in range(22):
    print(all_players[i])



