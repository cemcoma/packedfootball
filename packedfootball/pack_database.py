"""The pack catalog: what each pack IS, keyed by a slug.

The slug is the Firestore document id (packs/{slug}) and what the client
sends to /pack/open. It names what the pack is, not what it is called:
display names have been renamed before (the promo packs), and a document
id can only be "renamed" by writing a new doc, carrying the operational
fields across and deleting the old one (how these replaced the original
numeric ids). The shop sorts by the pack TYPE's order first
(pack_types/{type}.order in Firestore, seeded from PACK_TYPES below), then
by each pack's own "order", then by slug -- so the console can list docs
alphabetically without that deciding what a player sees first.

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
    # The playtesters' thank-you: one day only, around the release. Sits at
    # the top of the shop while it is on sale (order 5); the dates below are
    # the plan, the live doc's available_at/expires_at are what actually
    # gate it. No art of its own yet -- the client falls back to
    # StandardPack1 for a "special" with no sprite_key.
    "early_access": {
        "active": False,
        "order": 5,
        "name": "Ship-a-ton Early Access Pack",
        "type": "special",
        "description": "Special rewards to the playtesters and early access users! Only available for a day!",
        "price": 5000,
        "cards_per_pack": 5,
        "rates": {"silver": 0.30, "gold": 0.30, "platinum": 0.20, "diamond": 0.15, "special": 0.04, "icon": 0.01},
        "pos_rates": {"goalkeeper": 0.1, "defender": 0.25, "midfielder": 0.25, "attacker": 0.4},
        "price_currency": "credits",
        "available_at": datetime.datetime(2026, 9, 30, 22, 0, tzinfo=datetime.timezone.utc),
        "expires_at": datetime.datetime(2026, 10, 1, 22, 0, tzinfo=datetime.timezone.utc),
        "sprite_key":"EarlyAccessPack"
    },
    "standard_pp": {
        "active": True,
        "order": 10,
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
    "jumbo_standard": {
        "active": True,
        "order": 20,
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
    "standard_gold": {
        "active": True,
        "order": 35,
        "name": "Gold Player Pack",
        "type": "standard",
        "description": "Standard gold pack. Mostly golds with chance to get diamonds",
        "price": 1000,
        "cards_per_pack": 3,
        "rates": {"bronze": 0.00, "silver": 0.40, "gold": 0.50, "platinum": 0.09, "diamond": 0.01},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"StandardPack1"
    },
    "standard_plat": {
        "active": True,
        "order": 40,
        "name": "Platinum Player Pack",
        "type": "standard",
        "description": "Standard platinum pack. High rated players ready for any matchup. Rare chance to get special and icons!",
        "price": 2000,
        "cards_per_pack": 3,
        "rates": {"bronze": 0.0, "silver": 0.15, "gold": 0.35, "platinum": 0.40, "diamond": 0.095, "special": 0.004, "icon":0.001},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"StandardPack1"
    },
    
    "icon_forward": {
        "active": True,
        "order": 30,
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
    "tournament_small": {
        "active": True,
        "order": 40,
        "name": "Small Tournament Player Pack",
        "type": "tournament",
        "description": "One tournament ready player at your service.",
        "price": 1,
        "cards_per_pack": 1,
        "rates": {"bronze": 0.0, "silver": 0.15, "gold": 0.45, "platinum": 0.35, "diamond": 0.05},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"medals",
        "sprite_key":"TorunamentPack1"
    },
    "tournament_medium": {
        "active": True,
        "order": 50,
        "name": "Medium Tournament Player Pack",
        "type": "tournament",
        "description": "Medium 3 player pack. Better odds than Small Tournament Winner Player Pack.",
        "price": 3,
        "cards_per_pack": 3,
        "rates": {"bronze": 0.0, "silver": 0.12, "gold": 0.45, "platinum": 0.35, "diamond": 0.08},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"medals",
        "sprite_key":"TournamentPack1"
    },
    "tournament_premium": {
        "active": True,
        "order": 60,
        "name": "Premium Tournament Player Pack",
        "type": "tournament",
        "description": "Premium 3 player pack. Only for the real tournament grinders. Chance to get an icon card!",
        "price": 5,
        "cards_per_pack": 3,
        "rates": {"bronze": 0.0, "silver": 0.145, "gold": 0.35, "platinum": 0.4, "diamond": 0.10, "icon":0.005},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"medals",
        "sprite_key":"TournamentPack2"
    },
    "promo_champions": {
        "active": False,
        "order": 70,
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

    "promo_continental": {
        "active": True,
        "order": 80,
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
    "promo_conference": {
        "active": False,
        "order": 90,
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


# The storefront's categories -- every value a pack's "type" takes -- and the
# order the shop lists them in, as seeding DEFAULTS only. backend/scripts/
# seed_packs.py creates pack_types/{type} {"order": n} for any type missing
# from Firestore and never touches one that exists, so after seeding the
# live doc's order is the truth and reordering is a console edit, not a
# deploy. A type used by a pack but absent from both places still shows in
# the shop, sorted after every ordered one (services/storefront.py).
#
# Per-player visibility rules, when they come (VIP, a minimum win count, a
# tournament tier), belong on these same docs; the backend applies them and
# the client never learns the rules.
PACK_TYPES = {
    "standard": 10,
    "tournament": 20,
    "special": 30,
    "timed": 40,
}
