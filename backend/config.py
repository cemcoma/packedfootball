"""Every number the backend can be tuned by, in one file.

This is the file to open to change what something costs, what it pays, how
big a club can get, or which stats a leaderboard will sort on -- none of
that should mean reading an endpoint. Anything here is a decision about the
GAME; anything that is a decision about a protocol (RevenueCat's store
names, say) stays next to the code that speaks that protocol.

Several of these have a counterpart in the Godot client that has to be kept
in step by hand -- each one says which, and says which end is authoritative.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Local-dev convenience only: fills in os.environ from backend/.env (copy
# .env.example -> .env, gitignored, never touches the deployed service) so
# running `uvicorn main:app` locally doesn't need a dozen `export`s first.
# Never overrides a variable that's already set (dotenv's own default), so
# on Cloud Run -- where secrets arrive via --set-env-vars/--set-secrets and
# no .env file exists in the image at all -- this is a harmless no-op that
# changes nothing.
load_dotenv()

# -- deployment ---------------------------------------------------------------

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")
#allowed websites to call this backend
ALLOWED_ORIGINS = [
    "https://cemcoma.github.io",
    "http://localhost:8060",
    "http://127.0.0.1:8060",
]
REVENUECAT_WEBHOOK_SECRET = os.environ.get("REVENUECAT_WEBHOOK_SECRET", "")

# -- new accounts -------------------------------------------------------------

STARTER_FORMATION = "4-4-2"
STARTER_TIER = "bronze"

# -- squad size ---------------------------------------------------------------

# How many BENCHED cards a club can hold. The starting XI is separate and
# uncapped by this (it's fixed at 11 by the formation), so a full club is
# INVENTORY_CAP + 11 players.
#
# THE only copy of this number: /account/bootstrap hands it to the client on
# every login, so changing it here is the whole change -- no client edit, no
# app release. The client's own DEFAULT_INVENTORY_CAP is a pre-login
# fallback, never an authority.
INVENTORY_CAP = 100

# What releasing a card pays, by tier -- the keys are packEngine.TIER_RANGES'.
# mobile/scripts/data/PlayerCard.gd carries the same table so the Release
# button can show the amount BEFORE the request; this end is the one that
# actually pays out, so the two have to be kept in step by hand (same
# arrangement as APPEARANCE_OPTION_COUNTS and PlayerAppearance.gd).

# -- what things cost, what they pay ------------------------------------------

# What releasing a card pays, by tier -- the keys are packEngine.TIER_RANGES'.
# mobile/scripts/data/PlayerCard.gd carries the same table so the Release
# button can show the amount BEFORE the request; this end is the one that
# actually pays out, so the two have to be kept in step by hand (same
# arrangement as APPEARANCE_OPTION_COUNTS and PlayerAppearance.gd).
RELEASE_CREDITS_BY_TIER = {
    "bronze": 10,
    "silver": 20,
    "gold": 50,
    "platinum": 100,
    "diamond": 250,
    "special": 500,
    "icon": 1000,
}
# A card whose tier this build has never heard of pays the floor rather than
# nothing, so a future tier added to packEngine before it's added here is a
# bad payout, not a broken button.
RELEASE_CREDITS_DEFAULT = 10

# Charged per CHANGED appearance slot, not per save: swapping a hairstyle
# and its colour in one visit costs 200. Mirrored in the client's
# CustomizePlayer.gd purely for the running total it shows before saving.

# Charged per CHANGED appearance slot, not per save: swapping a hairstyle
# and its colour in one visit costs 200. Mirrored in the client's
# CustomizePlayer.gd purely for the running total it shows before saving.
CUSTOMIZE_CREDITS_PER_SLOT = 100

# How much a Quick Match pays out, by result.
QUICK_MATCH_REWARD_CREDITS = {"loss":10,"draw":25,"win":100}

# What a pack's "price_currency" is allowed to be -- these are exactly the
# balance fields on users/{uid}, since the check and the deduction both
# index the profile by this name.
PACK_PRICE_CURRENCIES = ("credits", "bucks", "medals")

# The Credits Exchange catalog -- fixed and code-defined rather than
# Firestore-backed like packs and deals, because these rates aren't meant to
# be admin-editable without a redeploy.
CREDIT_EXCHANGE_RATES = {
    "exchange_10": {"bucks_cost": 10, "credits_reward": 1000},
    "exchange_25": {"bucks_cost": 25, "credits_reward": 2600},
    "exchange_100": {"bucks_cost": 100, "credits_reward": 12500},
    "exchange_200": {"bucks_cost": 200, "credits_reward": 30000},
}

# The Bucks tab's real-money catalog. product_id is what the client hands to
# the platform IAP plugin; usd_reference_price_cents is a display fallback
# only, since Apple owns actual regional pricing.
BUCKS_IAP_CATALOG = {
    "bucks_10": {"bucks_amount": 10, "usd_reference_price_cents": 100},
    "bucks_55": {"bucks_amount": 55, "usd_reference_price_cents": 500},
    "bucks_125": {"bucks_amount": 125, "usd_reference_price_cents": 1000},
    "bucks_300": {"bucks_amount": 300, "usd_reference_price_cents": 2000},
}

# -- cosmetics ----------------------------------------------------------------

# The shirt every Quick Match bot wears. Format is the client's -- see
# mobile/scripts/data/KitDesign.gd; this end never parses it.
BOT_KIT = "v1;pattern=stripes;primary=c8102e;secondary=121216"

# -- leaderboards -------------------------------------------------------------

# Which stats /leaderboard/players will sort on, and the Firestore field path
# each one lives at. An allow-list, so an arbitrary field path can't be
# queried by asking for it.
PLAYER_LEADERBOARD_STATS = {
    "goals": "statistics.goals",
    "assists": "statistics.assists",
    "matches_played": "statistics.matches_played",
}

# Only "wins" for now, by design -- the mobile Leaderboard screen's Users
# tab is a deliberately minimal first pass (see mobile/README.md). Shaped
# the same way as PLAYER_LEADERBOARD_STATS/leaderboard_players above (a
# dict of allowed stats, checked the same way) so adding another one later
# (credits, bucks, ...) is just another entry, not new plumbing.
USER_LEADERBOARD_STATS = {
    "wins": "wins",
}
