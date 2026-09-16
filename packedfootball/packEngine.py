import os
import random
import datetime
from player.player import Attributes, APPEARANCE_SLOTS, APPEARANCE_OPTION_COUNTS, TENDENCY_FIELDS, PHYSICAL_FIELDS, player

from player.classes.goalkeeper import Goalkeeper
from player.classes.defender import CenterBack, Fullback, Wingback
from player.classes.midfielder import Midfielder, DefensiveMid, AttackingMid
from player.classes.forward import Forward, Winger

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
    "WB": Wingback,
    "CDM": DefensiveMid,
    "CM": Midfielder,
    "CAM": AttackingMid,
    "LM": Midfielder,
    "RM": Midfielder,
    "LW": Winger,
    "RW": Winger,
    "ST": Forward,
}

TIER_RANGES = {
    "bronze": (45, 54),
    "silver": (55, 60),
    "gold": (62, 70),
    "platinum": (72, 77),
    "diamond": (78, 83),
    "special_conf": (85, 88),
    "special_uel": (86, 90),
    "special_ucl": (87, 92),
    "icon": (95,99)
}


TENDENCY_RANGES = {
    "pass_tendency": (30, 70),
    "shoot_tendency": (20, 70),
    "drible_tendency": (30, 80),
    "aggression": (15, 65),
    "clear_tendency": (5, 45),
}

_TENDENCY_STAT_NAMES = tuple(sorted(TENDENCY_FIELDS - {"composure"}))
# PHYSICAL_FIELDS (height) is excluded here as well as from the tendency
# list: _roll_skill_stat scales with card TIER, and an icon is not taller
# than a bronze. Height is rolled separately by _roll_height.
_SKILL_STAT_NAMES = tuple(
    f
    for f in Attributes.__dataclass_fields__
    if f not in _TENDENCY_STAT_NAMES and f not in PHYSICAL_FIELDS
)

# Height in cm: (mean, spread) per position. Keepers and centre-backs are
# picked for being tall; wingers and full-backs tend not to be.
HEIGHT_PROFILES = {
    "GK": (180, 6),
    "CB": (183, 8),
    "ST": (180, 9),
    "CDM": (182, 8),
    "CM": (177, 7),
    "CAM": (175, 8),
    "LB": (177, 5),
    "RB": (177, 5),
    "WB": (176, 5),
    "LM": (177, 6),
    "RM": (177, 6),
    "LW": (175, 6),
    "RW": (175, 6),
}
HEIGHT_MIN, HEIGHT_MAX = 158, 205


def _roll_height(rng: random.Random, position: str) -> int:
    """Height for one card. Position-biased, tier-independent on purpose."""
    mean, spread = HEIGHT_PROFILES.get(position, (180, 6))
    return int(max(HEIGHT_MIN, min(HEIGHT_MAX, round(rng.gauss(mean, spread)))))

# Per-position stat tiers:
# "primary" (rolls in the top half of its range),
# "secondary" (full range -- the default for anything not listed here),
# "tertiary" (bottom half -- a real but secondary-to-that trait), or
# "nerfed" (this position basically never grows this stat)
# LB/RB, LM/RM, and LW/RW are mirrored sides -- nothing here distinguishes
# left from right, so each pair repeats the same profile.
POSITION_STAT_TIERS = {
    "GK": {
        "passing": "primary", "agility": "primary", "composure": "primary", "ballcontrol": "primary",
        "defending": "nerfed", "tackling": "nerfed", "shooting": "nerfed", "dribbiling": "nerfed",
        "speed": "tertiary", "power": "secondary", "accuracy": "secondary", "vision": "secondary",
        "stamina": "nerfed",
        "clear_tendency": "primary", "pass_tendency": "secondary", "aggression": "tertiary",
        "shoot_tendency": "nerfed", "drible_tendency": "nerfed",
    },
    "CB": {
        "defending": "primary", "tackling": "primary",
        "shooting": "nerfed", "dribbiling": "nerfed", "speed": "nerfed",
        "passing": "tertiary", "ballcontrol": "tertiary", "agility": "tertiary", "accuracy": "tertiary", "vision": "tertiary",
        "power": "secondary", "composure": "secondary",
        "stamina": "tertiary",
        "clear_tendency": "primary", "aggression": "secondary",
        "pass_tendency": "tertiary", "shoot_tendency": "nerfed", "drible_tendency": "nerfed",
    },
    "LB": {
        "defending": "primary", "tackling": "primary",
        "shooting": "nerfed", "accuracy": "nerfed",
        "passing": "secondary", "speed": "secondary",
        "dribbiling": "tertiary", "ballcontrol": "tertiary", "agility": "tertiary", "power": "tertiary",
        "vision": "tertiary", "composure": "tertiary",
        "stamina": "primary",
        "clear_tendency": "secondary", "pass_tendency": "secondary",
        "drible_tendency": "tertiary", "aggression": "tertiary", "shoot_tendency": "nerfed",
    },
    "WB": {
        "speed": "primary", "passing": "primary",
        "shooting": "nerfed", "accuracy": "nerfed",
        "defending": "secondary", "tackling": "secondary", "dribbiling": "secondary",
        "ballcontrol": "secondary", "agility": "secondary", "vision": "secondary",
        "power": "tertiary", "composure": "tertiary",
        "stamina": "primary",
        "pass_tendency": "secondary", "drible_tendency": "secondary",
        "clear_tendency": "tertiary", "aggression": "tertiary", "shoot_tendency": "nerfed",
    },
    "CDM": {
        "defending": "primary", "tackling": "primary", "passing": "primary",
        "shooting": "nerfed", "drible_tendency": "nerfed",
        "ballcontrol": "secondary", "power": "secondary", "vision": "secondary", "composure": "secondary",
        "dribbiling": "tertiary", "speed": "tertiary", "agility": "tertiary", "accuracy": "tertiary",
        "stamina": "primary",
        "pass_tendency": "secondary", "clear_tendency": "secondary", "aggression": "secondary",
        "shoot_tendency": "nerfed",
    },
    "CM": {
        "passing": "primary", "ballcontrol": "primary", "vision": "primary",
        "dribbiling": "secondary", "speed": "secondary", "agility": "secondary", "composure": "secondary",
        "defending": "tertiary", "tackling": "tertiary", "shooting": "tertiary", "power": "tertiary", "accuracy": "tertiary",
        "stamina": "primary",
        "pass_tendency": "primary", "drible_tendency": "secondary",
        "shoot_tendency": "tertiary", "aggression": "tertiary", "clear_tendency": "tertiary",
    },
    "CAM": {
        "passing": "primary", "ballcontrol": "primary", "vision": "primary", "shooting": "primary",
        "defending": "nerfed", "tackling": "nerfed",
        "dribbiling": "secondary", "speed": "secondary", "agility": "secondary", "accuracy": "secondary", "composure": "secondary",
        "power": "tertiary",
        "stamina": "tertiary",
        "shoot_tendency": "primary", "pass_tendency": "secondary", "drible_tendency": "secondary",
        "aggression": "nerfed", "clear_tendency": "nerfed",
    },
    "LM": {
        "passing": "primary", "ballcontrol": "primary", "speed": "primary",
        "dribbiling": "secondary", "agility": "secondary", "vision": "secondary",
        "defending": "tertiary", "tackling": "tertiary", "shooting": "tertiary", "power": "tertiary",
        "accuracy": "tertiary", "composure": "tertiary",
        "stamina": "secondary",
        "pass_tendency": "secondary", "drible_tendency": "secondary",
        "shoot_tendency": "tertiary", "aggression": "tertiary", "clear_tendency": "tertiary",
    },
    "LW": {
        "speed": "primary", "agility": "primary", "dribbiling": "primary",
        "defending": "nerfed", "tackling": "nerfed", "aggression": "nerfed", "clear_tendency": "nerfed",
        "ballcontrol": "secondary", "shooting": "secondary", "accuracy": "secondary",
        "passing": "tertiary", "power": "tertiary", "vision": "tertiary", "composure": "tertiary",
        "stamina": "tertiary",
        "drible_tendency": "primary", "shoot_tendency": "secondary", "pass_tendency": "tertiary",
    },
    "ST": {
        "shooting": "primary", "power": "primary", "accuracy": "primary",
        "defending": "nerfed", "tackling": "nerfed", "pass_tendency": "nerfed", "clear_tendency": "nerfed",
        "dribbiling": "secondary", "ballcontrol": "secondary", "speed": "secondary", "agility": "secondary", "composure": "secondary",
        "passing": "tertiary", "vision": "tertiary",
        "stamina": "tertiary",
        "shoot_tendency": "primary", "drible_tendency": "tertiary", "aggression": "tertiary",
    },
}
POSITION_STAT_TIERS["RB"] = POSITION_STAT_TIERS["LB"]
POSITION_STAT_TIERS["RM"] = POSITION_STAT_TIERS["LM"]
POSITION_STAT_TIERS["RW"] = POSITION_STAT_TIERS["LW"]


def _roll_skill_stat(rng: random.Random, stat_type: str, min_s: int, max_s: int) -> int:
    """Tier-scaling roll for anything in _SKILL_STAT_NAMES. "nerfed" is
    deliberately its own shape rather than "bottom slice of (min_s, max_s)"
    -- it's meant to stay low-ish regardless of tier (a nerfed stat barely
    grows even on an icon card), where tertiary/secondary/primary all
    scale up together with tier.
    """
    if stat_type == "primary":
        return rng.randint(min_s + (max_s - min_s) // 2, max_s)
    elif stat_type == "tertiary":
        return rng.randint(min_s, min_s + (max_s - min_s) // 2)
    elif stat_type == "nerfed":
        return rng.randint(int(25 + min_s * 0.1), int(40 + max_s * 0.1))
    return rng.randint(min_s, max_s)  # "secondary", and the fallback for anything unrecognized


def _roll_tendency_stat(rng: random.Random, stat_type: str, low: int, high: int) -> int:
    """Same primary/secondary/tertiary/nerfed shape as _roll_skill_stat, but
    against a tendency's own fixed (low, high) range instead of a
    tier-dependent one (see TENDENCY_RANGES) -- "nerfed" here is just the
    bottom quarter of that fixed range, not a separate low-and-flat band,
    since the range is already tier-independent.
    """
    span = high - low
    if stat_type == "primary":
        return rng.randint(low + span // 2, high)
    elif stat_type == "tertiary":
        return rng.randint(low, low + span // 2)
    elif stat_type == "nerfed":
        return rng.randint(low, low + max(1, span // 4))
    return rng.randint(low, high)  # "secondary", and the fallback for anything unrecognized


PACK_DATABASE = {
    1: {
        "active": True,
        "name": "Standard Player Pack",
        "type": "standard",
        "description": "A reliable pack of everyday talent. Mostly bronze and silver, with a shot at gold.",
        "price": 100,
        "cards_per_pack": 3,
        "rates": {"bronze": 0.60, "silver": 0.30, "gold": 0.075, "platinum": 0.025, "diamond": 0.0},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"StandardPack1"
    },
    2: {
        "active": True,
        "name": "Jumbo Player Pack",
        "type": "standard",
        "description": "Ten cards in one pull. Better odds than Standard Player Pack.",
        "price": 500,
        "cards_per_pack": 10,
        "rates": {"bronze": 0.40, "silver": 0.40, "gold": 0.15, "platinum": 0.05, "diamond": 0.0},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"StandardPack1"
    },
    3: {
        "active": True,
        "name": "Icon Forward Pack",
        "type": "special",
        "description": "One guaranteed icon-tier forward. Extremely limited -- once they're gone, they're gone.",
        "price": 50000,
        "cards_per_pack": 1,
        "rates": {"icon":1.0},
        "pos_rates": {"attacker":1},
        "price_currency":"credits",
        "sprite_key":"StandardPack1",
        "visible":True
    },
    4: {
        "active": True,
        "name": "Small Tournament Player Pack",
        "type": "standard",
        "description": "One tournament ready player at your service.",
        "price": 1,
        "cards_per_pack": 1,
        "rates": {"bronze": 0.0, "silver": 0.15, "gold": 0.45, "platinum": 0.35, "diamond": 0.05},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"medals",
        "sprite_key":"StandardPack2"
    },
     # 5 is missing due to it being done at firebase and it takes too long to put here.
    6: {
        "active": True,
        "name": "Medium Tournament Player Pack",
        "type": "standard",
        "description": "Medium 3 player pack. Better odds than Small Tournament Winner Player Pack.",
        "price": 3,
        "cards_per_pack": 3,
        "rates": {"bronze": 0.0, "silver": 0.12, "gold": 0.45, "platinum": 0.35, "diamond": 0.08},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"medals",
        "sprite_key":"StandardPack2"
    },
    7: {
        "active": True,
        "name": "Premium Tournament Player Pack",
        "type": "standard",
        "description": "Premium 3 player pack. Only for the real tournament grinders. Chance to get an icon card!",
        "price": 5,
        "cards_per_pack": 3,
        "rates": {"bronze": 0.0, "silver": 0.145, "gold": 0.35, "platinum": 0.4, "diamond": 0.10, "icon":0.05},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"medals",
        "sprite_key":"StandardPack3"
    },
    8: {
        "active": False,
        "name": "UCL Promo Pack",
        "type": "timed",
        "description": "Champions League season is here! Take your chances for a special UCL player now!",
        "price": 3000,
        "cards_per_pack": 5,
        "rates": {"silver": 0.15, "gold": 0.40, "platinum": 0.30, "diamond": 0.13, "special_ucl": 0.02},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"UCLPack",
        "available_at": datetime.datetime(2026, 10, 10, 15, 0, tzinfo=datetime.timezone.utc)
    },

    9: {
        "active": True,
        "name": "UEL Promo Pack",
        "type": "timed",
        "description": "Europa League  is here! Take your chances for a special UEL player now!",
        "price": 1500,
        "cards_per_pack": 5,
        "rates": {"silver": 0.2, "gold": 0.40, "platinum": 0.30, "diamond": 0.08, "special_uel": 0.02},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"UELPack",
        "expires_at":datetime.datetime(2026, 9, 18, 15, 0, tzinfo=datetime.timezone.utc)
    },
    10: {
        "active": False,
        "name": "Conference League Promo Pack",
        "type": "timed",
        "description": "Conference League is here! Take your chances for a special Conference Lague player now!",
        "price": 1000,
        "cards_per_pack": 3,
        "rates": {"silver": 0.25, "gold": 0.42, "platinum": 0.25, "diamond": 0.06, "special_conf": 0.02},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"CONFPack",
        "available_at": datetime.datetime(2026, 10, 15, 15, 0, tzinfo=datetime.timezone.utc)
    },
}

class PackManager:
    def __init__(self, db: dict, seed=None):
        self.db = db
        self.rng = random.Random(seed)

    def get_all_packs(self) -> list:
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
        pos_choice = list(config["pos_rates"].keys())
        pos_weights = list(config["pos_rates"].values())

        for _ in range(config["cards_per_pack"]):
            rolled_tier = self.rng.choices(tiers, weights=weights, k=1)[0]

            position_grand_choice = self.rng.choices(pos_choice,weights=pos_weights,k=1)[0]
            position = "ST"
            if position_grand_choice == "goalkeeper":
                position = "GK"
            elif position_grand_choice == "defender":
                position = self.rng.choices(["CB", "LB", "RB", "WB"], weights=[0.40, 0.20, 0.20, 0.20], k=1)[0]
            elif position_grand_choice == "midfielder":
                position = self.rng.choices(["CDM", "CM", "CAM", "LM", "RM"], weights=[0.20, 0.30, 0.20, 0.15, 0.15], k=1)[0]
            elif position_grand_choice == "attacker":
                position = self.rng.choices(["ST", "LW", "RW"], weights=[0.50, 0.25, 0.25], k=1)[0]

            attrs = self._generate_tier_attributes(rolled_tier, position)

            player_class = PLAYER_CLASS_MAP.get(position, Midfielder)

            country = self.rng.choice(COUNTRIES)
            fname = self.rng.choice(FIRST_NAMES[country])
            lname = self.rng.choice(LAST_NAMES[country])
            hometown = self.rng.choice(CITIES[country])

            new_player = player_class(
                fname=fname,
                lname=lname,
                tier=rolled_tier,
                position=position,
                attributes=attrs,
                country=country,
                hometown=hometown,
                appearance=self._generate_appearance(),
            )

            new_cards.append(new_player)
        return new_cards

    def _generate_tier_attributes(self, tier: str, position: str) -> Attributes:
        """Rolls a full Attributes set for one card: every skill attribute
        (tier-scaling -- see _roll_skill_stat) plus every tendency
        (role-scaling only -- see _roll_tendency_stat), using position's
        entry in POSITION_STAT_TIERS to decide primary/secondary/tertiary/
        nerfed per stat (default "secondary" for anything that position's
        entry doesn't mention, or for an unrecognized position entirely).
        """
        min_s, max_s = TIER_RANGES.get(tier, (40, 50))
        position_profile = POSITION_STAT_TIERS.get(position, {})

        generated_stats = {}
        for stat in _SKILL_STAT_NAMES:
            generated_stats[stat] = _roll_skill_stat(self.rng, position_profile.get(stat, "secondary"), min_s, max_s)
        for stat in _TENDENCY_STAT_NAMES:
            low, high = TENDENCY_RANGES[stat]
            generated_stats[stat] = _roll_tendency_stat(self.rng, position_profile.get(stat, "secondary"), low, high)

        generated_stats["height"] = _roll_height(self.rng, position)

        return Attributes(**generated_stats)

    def _generate_appearance(self) -> dict:
        """Rolls one option index per appearance slot.

        Each slot has its OWN count (see player.py's
        APPEARANCE_OPTION_COUNTS) so that adding, say, four new hairstyles
        client-side only needs that one number raised here -- the other
        slots keep rolling over their own ranges and every existing card
        keeps the look it was generated with.

        Uses self.rng like every other roll in this class, so a pack open
        stays fully reproducible from its seed, appearance included.
        """
        return {
            slot: self.rng.randint(0, APPEARANCE_OPTION_COUNTS.get(slot, 1) - 1)
            for slot in APPEARANCE_SLOTS
        }


def generate_starter_roster(formation_name: str = "4-4-2", tier: str = "bronze", seed=None) -> list:
    """Generates a full 11-card roster, one player per slot of the given
    formation, all at one tier -- used to bootstrap a brand new account with
    an actually-playable squad (see backend/main.py's /account/bootstrap).

    Reuses the same tier-attribute generation open_pack() uses (via a
    PackManager whose pack database is never actually consulted -- only
    _generate_tier_attributes() is), but unlike a pack, this has to fill
    every one of the formation's specific roles, not roll positions
    independently and risk missing one.
    """
    from formations import get_formation

    manager = PackManager({}, seed=seed)
    roster = []
    for i in range(11):
        position = get_formation(formation_name)[i]["role"]
        player_cls = PLAYER_CLASS_MAP.get(position, Midfielder)
        attrs = manager._generate_tier_attributes(tier, position)

        country = manager.rng.choice(COUNTRIES)
        fname = manager.rng.choice(FIRST_NAMES[country])
        lname = manager.rng.choice(LAST_NAMES[country])
        hometown = manager.rng.choice(CITIES[country])

        roster.append(
            player_cls(
                fname=fname,
                lname=lname,
                tier=tier,
                position=position,
                attributes=attrs,
                country=country,
                hometown=hometown,
                appearance=manager._generate_appearance(),
            )
        )
    return roster