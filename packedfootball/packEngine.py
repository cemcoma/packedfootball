import os
import random
from player.player import Attributes, player

from player.classes.goalkeeper import Goalkeeper
from player.classes.defender import CenterBack, Fullback
from player.classes.midfielder import Midfielder
from player.classes.forward import Forward

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _load_name_data(filename: str) -> dict:
    """Parses 'Country: item1, item2, ...' lines into {country: [items]}."""
    path = os.path.join(DATA_DIR, filename)
    data = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            country, values = line.split(":", 1)
            data[country.strip()] = [v.strip() for v in values.split(",")]
    return data


FIRST_NAMES = _load_name_data("first_names.txt")
LAST_NAMES = _load_name_data("last_names.txt")
CITIES = _load_name_data("cities.txt")
COUNTRIES = list(FIRST_NAMES.keys())

PLAYER_CLASS_MAP = {
    "GK": Goalkeeper,
    "CB": CenterBack,
    "LB": Fullback,
    "RB": Fullback,
    "CM": Midfielder,
    #"AM": Midfielder,
    "LW": Forward,
    "RW": Forward,
    "ST": Forward,
}

TIER_RANGES = {
    "bronze": (45, 53),
    "silver": (55, 60),
    "gold": (62, 70),
    "platinum": (72, 80),
    "diamond": (82, 87),
    "special": (90, 99)
}


PACK_DATABASE = {
    1: {
        "name": "Standard Player Pack",
        "price": 100,
        "cards_per_pack": 3,
        "rates": {"bronze": 0.60, "silver": 0.30, "gold": 0.10, "platinum": 0.0, "diamond": 0.0, "special": 0.0}
    },
    2: {
        "name": "Jumbo Player Pack",
        "price": 500,
        "cards_per_pack": 10,
        "rates": {"bronze": 0.40, "silver": 0.40, "gold": 0.15, "platinum": 0.05, "diamond": 0.0, "special": 0.0}
    },
    3: {
        "name": "UCL Promo Pack",
        "price": 1000,
        "cards_per_pack": 5,
        "rates": {"bronze": 0.0, "silver": 0.10, "gold": 0.40, "platinum": 0.30, "diamond": 0.15, "special": 0.05}
    }
}

class PackManager:
    def __init__(self, db: dict):
        self.db = db

    def get_all_packs(self) -> list:
        # like an api call, will be one TODO
        packs = []
        for pack_id, data in self.db.items():
            pack_row = {"pack_id": pack_id}
            pack_row.update(data)
            packs.append(pack_row)
        return packs

    def get_price(self, pack_id: int) -> int:
        return self.db.get(pack_id, {}).get("price", 0)

    def open_pack(self, pack_id: int) -> list: #TODO: add different results in packs, like contract, equipment, rn just player
        config = self.db.get(pack_id)
        if not config:
            return []

        new_cards = []
        tiers = list(config["rates"].keys())
        weights = list(config["rates"].values())

        for _ in range(config["cards_per_pack"]):
            rolled_tier = random.choices(tiers, weights=weights, k=1)[0]
            
            position = random.choice(["GK", "CB", "LB", "RB", "CM", "LW", "RW", "ST"]) # TODO: add weights to positions based on packs (ie forward pack) also add more positions for other formations

            attrs = self._generate_tier_attributes(rolled_tier, position)

            player_class = PLAYER_CLASS_MAP.get(position, Midfielder)

            country = random.choice(COUNTRIES)
            fname = random.choice(FIRST_NAMES[country])
            lname = random.choice(LAST_NAMES[country])
            hometown = random.choice(CITIES[country])

            new_player = player_class(
                fname=fname,
                lname=lname,
                tier=rolled_tier,
                position=position,
                attributes=attrs,
                country=country,
                hometown=hometown
            )
            
            new_cards.append(new_player)
        return new_cards 

    def _generate_tier_attributes(self, tier: str, position: str) -> Attributes:
        min_s, max_s = TIER_RANGES.get(tier, (40, 50))

        def roll_stat(stat_type):
            if stat_type == "primary":
                return random.randint(min_s + (max_s - min_s) // 2, max_s)
            elif stat_type == "secondary":
                return random.randint(min_s, max_s)
            elif stat_type == "nerfed":
                return random.randint(int(25 + min_s * 0.1), int(40 + max_s * 0.1))

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

        generated_stats = {stat: roll_stat(s_type) for stat, s_type in profile.items()}
        
        return Attributes(**generated_stats)