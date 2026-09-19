"""The pack catalog: what each pack IS, keyed by pack id.

The code-side source of truth for a pack's definitional fields -- name,
type, description, price and currency, cards per pack, tier and position
odds, sprite -- pushed onto the existing Firestore packs/{id} docs by
backend/scripts/sync_pack_definitions.py. Operational state (active,
expires_at, visible, available_at, max_opens, times_opened) only ever
lives in Firestore, never here: an admin flipping a pack off, or a real
opening count, must never be clobbered back to a code default by the next
sync. The backend's /pack/list and /pack/open read the live Firestore doc,
so "what's on sale right now" is answerable without a redeploy.

The deals catalog (deal_database.py) has the same relationship with its
own Firestore collection. Tier keys are game_config.TIER_RANGES'; position
keys are game_config.POSITION_CATEGORIES'.
"""

import datetime

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
        "name": "Champions Promo Pack",
        "type": "timed",
        "description": "The champions season is here! Take your chances for a special Champions player now!",
        "price": 3000,
        "cards_per_pack": 5,
        "rates": {"silver": 0.15, "gold": 0.40, "platinum": 0.30, "diamond": 0.13, "special_champ": 0.02},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"CHAMPPack",
        "available_at": datetime.datetime(2026, 10, 10, 15, 0, tzinfo=datetime.timezone.utc)
    },

    9: {
        "active": True,
        "name": "Continental Promo Pack",
        "type": "timed",
        "description": "The continental cup is here! Take your chances for a special Continental player now!",
        "price": 1500,
        "cards_per_pack": 5,
        "rates": {"silver": 0.2, "gold": 0.40, "platinum": 0.30, "diamond": 0.08, "special_cont": 0.02},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"CONTPack",
        "expires_at":datetime.datetime(2026, 9, 18, 15, 0, tzinfo=datetime.timezone.utc)
    },
    10: {
        "active": False,
        "name": "Conference Promo Pack",
        "type": "timed",
        "description": "Conference challenge is here! Take your chances for a special Conference player now!",
        "price": 1000,
        "cards_per_pack": 3,
        "rates": {"silver": 0.25, "gold": 0.42, "platinum": 0.25, "diamond": 0.06, "special_conf": 0.02},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"CONFPack",
        "available_at": datetime.datetime(2026, 10, 15, 15, 0, tzinfo=datetime.timezone.utc)
    },
}
