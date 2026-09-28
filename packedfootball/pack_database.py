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

sprite_key names the art at mobile/sprites/packs/<type>/<sprite_key>.png;
missing art falls back to standard/StandardPack1.
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
        "description": "Two everyday players and a piece of kit. Mostly bronze, with a shot at silver.",
        "price": 100,
        "cards_per_pack": 2,
        "items_per_pack": 1,
        "item_rates": {"bronze": 0.55, "silver": 0.30, "gold": 0.15},
        "rates": {"bronze": 0.85, "silver": 0.15},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"StandardPack1"
    },
    "jumbo_standard": {
        "active": True,
        "order": 20,
        "name": "Jumbo Player Pack",
        "type": "standard",
        "description": "Six cards and two pieces of kit in one pull. Better odds than Standard Player Pack.",
        "price": 500,
        "cards_per_pack": 6,
        "items_per_pack": 2,
        "item_rates": {"bronze": 0.45, "silver": 0.35, "gold": 0.20},
        "rates": {"bronze": 0.70, "silver": 0.28, "gold": 0.02},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"StandardPack1"
    },
    "standard_gold": {
        "active": True,
        "order": 35,
        "name": "Gold Player Pack",
        "type": "standard",
        "description": "Mostly golds, a piece of kit, and a slim shot at a platinum.",
        "price": 1000,
        "cards_per_pack": 2,
        "items_per_pack": 1,
        "item_rates": {"silver": 0.35, "gold": 0.45, "platinum": 0.20},
        "rates": {"silver": 0.35, "gold": 0.63, "platinum": 0.02},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"StandardGold"
    },
    "standard_plat": {
        "active": True,
        "order": 40,
        "name": "Platinum Player Pack",
        "type": "standard",
        "description": "High rated players ready for any matchup, plus kit. Rare chance at a diamond.",
        "price": 2000,
        "cards_per_pack": 2,
        "items_per_pack": 1,
        "item_rates": {"gold": 0.45, "platinum": 0.40, "diamond": 0.15},
        "rates": {"gold": 0.45, "platinum": 0.53, "diamond": 0.02},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"StandardPlatinum"
    },
    
    # RETIRED. A guaranteed icon for credits was ~10 days of grinding, which is
    # the whole reason nothing was left to chase by week two. Icons are bucks
    # only now, and only as a CHANCE -- see the icon_chance_* packs.
    "tournament_small": {
        "active": True,
        "order": 40,
        "name": "Small Tournament Player Pack",
        "type": "tournament",
        "description": "One tournament ready player at your service.",
        "price": 2,
        "cards_per_pack": 1,
        "rates": {"silver": 0.30, "gold": 0.55, "platinum": 0.15},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"medals",
        "sprite_key":"TournamentPack1"
    },
    "tournament_medium": {
        "active": True,
        "order": 50,
        "name": "Medium Tournament Player Pack",
        "type": "tournament",
        "description": "Two players and a piece of kit. Better odds than the Small Tournament Player Pack.",
        "price": 5,
        "cards_per_pack": 2,
        "items_per_pack": 1,
        "item_rates": {"gold": 0.45, "platinum": 0.40, "diamond": 0.15},
        "rates": {"gold": 0.50, "platinum": 0.45, "diamond": 0.05},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"medals",
        "sprite_key":"TournamentPack1"
    },
    "tournament_premium": {
        "active": True,
        "order": 60,
        "name": "Premium Tournament Player Pack",
        "type": "tournament",
        "description": "One card for the real tournament grinders, plus two pieces of kit. The only pack with a shot at a SPECIAL.",
        "price": 10,
        "cards_per_pack": 1,
        "items_per_pack": 2,
        "item_rates": {"gold": 0.35, "platinum": 0.40, "diamond": 0.25},
        "rates": {"platinum": 0.85, "diamond": 0.10, "special": 0.05},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"medals",
        "sprite_key":"TournamentPack2"
    },
    # The premium storefront: bucks only. Each headline card (slot 0) is never
    # below the pack's name; premium_diamond is the only one selling specials.
    "premium_gold": {
        "active": True,
        "order": 10,
        "name": "Gold Premium Pack",
        "type": "premium",
        "description": "Two golds or better and a piece of kit, with a real shot at a platinum.",
        "price": 5,
        "cards_per_pack": 2,
        "items_per_pack": 1,
        "item_rates": {"silver": 0.20, "gold": 0.50, "platinum": 0.30},
        "rates": {"gold": 0.75, "platinum": 0.22, "diamond": 0.03},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"bucks",
        "sprite_key":"PremiumPack1"
    },
    "premium_plat": {
        "active": True,
        "order": 20,
        "name": "Platinum Premium Pack",
        "type": "premium",
        "description": "Three players and two pieces of kit. The headline card is a platinum or better, with a big shot at a diamond.",
        "price": 20,
        "cards_per_pack": 3,
        "items_per_pack": 2,
        "item_rates": {"gold": 0.30, "platinum": 0.45, "diamond": 0.25},
        "rates": {"gold": 0.30, "platinum": 0.65, "diamond": 0.05},
        "slot_rates": {"0": {"platinum": 0.60, "diamond": 0.40}},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"bucks",
        "sprite_key":"PremiumPack1"
    },
    "premium_diamond": {
        "active": True,
        "order": 30,
        "name": "Diamond Premium Pack",
        "type": "premium",
        "description": "Three players and two pieces of kit. The headline card is a diamond at worst -- and one in five is a SPECIAL.",
        "price": 30,
        "cards_per_pack": 3,
        "items_per_pack": 2,
        "item_rates": {"platinum": 0.45, "diamond": 0.45, "special": 0.10},
        "rates": {"gold": 0.20, "platinum": 0.70, "diamond": 0.10},
        "slot_rates": {"0": {"diamond": 0.80, "special": 0.20}},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"bucks",
        "sprite_key":"PremiumPack1"
    },
    "promo_champions": {
        "active": False,
        "order": 90,
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
        "order": 70,
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
    # The top of the CREDIT ladder, and where diamonds come from. It replaced a
    # guaranteed-special pack at this same price: a guarantee meant a player
    # could hold a special on day one, which is what left nothing to chase.
    # One slot carries the real chance (slot_rates), the other two are Platinum
    # pack odds -- so the pack is affordable and the diamond is still luck.
    # Per-pack diamond chance is 1 - 0.90*0.98*0.98 = 13.6%.
    "standard_diamond": {
        "active": True,
        "order": 45,
        "name": "Diamond Player Pack",
        "type": "standard",
        "description": "Three high-rated players and two pieces of kit. The headline card has a real shot at a diamond.",
        "price": 5000,
        "cards_per_pack": 3,
        "rates": {"gold": 0.45, "platinum": 0.53, "diamond": 0.02},
        "slot_rates": {"0": {"platinum": 0.80, "diamond": 0.20}},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "item_rates": {"gold": 0.40, "platinum": 0.40, "diamond": 0.20},
        "items_per_pack": 2,
        "price_currency":"credits",
        "sprite_key":"StandardDiamond"
    },
    # Items only, no cards. The recurring sink: socketing is one-way, so
    # every upgrade destroys the item it replaces and a squad is never
    # finished the way it would be with removable ones.
    "item_standard": {
        "active": True,
        "order": 15,
        "name": "Equipment Pack",
        "type": "equipment",
        "description": "Three items to socket into your cards. Permanent, and they replace whatever is already there.",
        "price": 300,
        "cards_per_pack": 0,
        "rates": {},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "item_rates": {"bronze": 0.45, "silver": 0.30, "gold": 0.20, "platinum": 0.05},
        "items_per_pack": 3,
        "price_currency":"credits",
        "sprite_key":"StandardPack1"
    },
    "item_premium": {
        "active": True,
        "order": 25,
        "name": "Premium Equipment Pack",
        "type": "equipment",
        "description": "Three high-grade items, with a shot at the slot extender -- the only way past three slots.",
        "price": 1500,
        "cards_per_pack": 0,
        "rates": {},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "item_rates": {"silver": 0.20, "gold": 0.40, "platinum": 0.25, "diamond": 0.13, "icon": 0.02},
        "items_per_pack": 3,
        "price_currency":"credits",
        "sprite_key":"StandardPack1"
    },
    "promo_testers": {
        "active": False,
        "order": 95,
        "name": "Test Pack",
        "type": "timed",
        "description": "Testing walkouts + game balance with this pack...",
        "price": 1,
        "cards_per_pack": 5,
        "rates": {"silver": 0.0, "gold": 0.0, "platinum": 0.4, "diamond": 0.4, "special": 0.05, "special_champ": 0.04,"special_cont": 0.03,"special_conf": 0.03, "icon": 0.05},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"credits",
        "sprite_key":"CHAMPPack",
        "available_at": datetime.datetime(2026, 10, 15, 15, 0, tzinfo=datetime.timezone.utc)
    },
    # THE ONLY ROUTE TO AN ICON, and it is a 1% chance on one slot rather than
    # a guarantee. Bucks-priced and windowed, so a player can save toward a
    # known date; the window itself is available_at/expires_at on the Firestore
    # doc, never here, so it opens and closes without a redeploy.
    #
    # Priced at 20 so a free player (~12 bucks a week) can reach one every
    # couple of weeks: ~30 openings a year at 1% is roughly a one-in-three
    # chance of an icon in a year, with specials and diamonds off slot 0 in the
    # meantime. Copy this entry per drop, with its own name and sprite.
    #
    # BEFORE SETTING active: True -- routers/packs._pack_unavailable_reason
    # checks `active`, max_opens and expires_at, but NOT available_at, so
    # `active: True` plus a future available_at is purchasable immediately. Set
    # active only when the window is actually open, or fix that gate first.
    "icon_chance_1": {
        "active": False,
        "order": 5,
        "name": "Icon Chance Pack",
        "type": "timed",
        "description": "Three players and a piece of kit. The headline card can be an ICON -- one in a hundred.",
        "price": 20,
        "cards_per_pack": 3,
        "items_per_pack": 1,
        "item_rates": {"silver": 0.20, "gold": 0.40, "platinum": 0.25, "diamond": 0.13, "icon": 0.02},
        "rates": {"gold": 0.45, "platinum": 0.53, "diamond": 0.02},
        "slot_rates": {"0": {"platinum": 0.44, "diamond": 0.35, "special": 0.20, "icon": 0.01}},
        "pos_rates": {"goalkeeper":0.1,"defender":0.3,"midfielder":0.3,"attacker":0.3},
        "price_currency":"bucks",
        "sprite_key":"CHAMPPack"
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
    "premium": 15,
    "tournament": 20,
    "special": 30,
    "timed": 40,
    "equipment":50
}
