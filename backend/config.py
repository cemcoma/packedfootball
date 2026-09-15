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

# How many cards one /player/release/batch call may release at once.
#
# The whole batch is ONE Firestore transaction, so this is really a cap on
# that transaction's size: each card costs a read plus two writes (the card
# and its inventory pointer), against Firestore's 500-write ceiling. 50 is
# comfortably inside it and still clears a full bench in two taps, and it
# bounds what a single request can cost if the id list is ever hostile.
RELEASE_BATCH_MAX = 50

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

# -- energy -------------------------------------------------------------------
#
# The first ceiling this backend has on simulations per player per day, and
# the thing that makes a match cost something. Regenerates lazily from a
# stored anchor -- nothing ticks it, because nothing here runs on a timer.
#
# NOTE ON THE SIZE OF THE BAR: a full tournament run is
# TOURNAMENT_MATCHES_PER_DAY matches, and ENERGY_MAX is the same number, so a
# player who spends a point on Quick Match cannot finish that day's tournament
# without waiting. That is deliberate pressure, but it is the dial to turn
# first if it reads as punishing.
ENERGY_MAX = 10
ENERGY_REGEN_SECONDS = 45 * 60
ENERGY_COST_PER_MATCH = 1

# Quick Match's own cost, separate from the tournament's so the two can be
# priced differently -- and so it can be set to 0 to turn energy off for the
# already-shipped endpoint without touching any code.
QUICK_MATCH_ENERGY_COST = 1

# Catalog-shaped like CREDIT_EXCHANGE_RATES on purpose: the client renders it
# with the existing CurrencyTileView ("pay 5 Cash, get 10 Energy") and needs
# no new component. energy_amount None means "fill the bar".
ENERGY_REFILL_PRODUCTS = {
    "refill_full": {"bucks_cost": 5, "energy_amount": None},
    "refill_3": {"bucks_cost": 2, "energy_amount": 3},
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

# -- daily tournaments --------------------------------------------------------

# Three tiers, 1 = top. A player's tier lives on users/{uid} and only moves at
# settlement. New accounts start at the bottom.
TOURNAMENT_TOP_TIER = 1
TOURNAMENT_BOTTOM_TIER = 3
TOURNAMENT_DEFAULT_TIER = TOURNAMENT_BOTTOM_TIER
TOURNAMENT_TIER_NAMES = {1: "Gold League", 2: "Silver League", 3: "Bronze League"}

TOURNAMENT_GROUP_CAPACITY = 6
TOURNAMENT_MATCHES_PER_DAY = 10

TOURNAMENT_POINTS = {"win": 3, "draw": 1, "loss": 0}

# When the tournament day rolls over, as hours AFTER midnight UTC.
#
# 9 == 09:00 UTC == 12:00 in Istanbul. Turkey is UTC+3 all year, so this single number holds indefinitely 
# but it IS a fixed offset, not a timezone. If Turkey ever reintroduces summer time, the reset
# drifts to 13:00 local until this is changed to 8 for the summer months.
#
# The day KEY is the Turkish calendar date the day starts on: "2026-09-15"
# runs from 15 Sept 12:00 to 16 Sept 12:00, Istanbul time.
#
# One global cutoff is the only version that needs no per-player timezone
# state. Players outside Turkey get a reset at whatever 12:00 Istanbul is for
# them, which is the trade for not storing a zone per account.
TOURNAMENT_DAY_OFFSET_HOURS = 9

# No joining in the last hour. Not enough time or energy to play a meaningful number of
# matches, so the join is refused rather than sold as an opportunity.
# Players who joined EARLIER are unaffected and can play to the last second.
TOURNAMENT_JOIN_CUTOFF_SECONDS = 60 * 60

# Promotion and relegation.
#
# FULL group: positional. Positions 1-2 promote, but ONLY if they also clear
# PROMOTION_FLOOR; 5-6 relegate regardless of points; 3-4 stay. Position beats
# points both ways -- 3rd on 22 does not go up, 4th on 9 does not go down.
#
# SHORT group: thresholds instead, because there are not enough players for a
# position to mean anything.
TOURNAMENT_PROMOTE_POSITIONS = (1, 2)
TOURNAMENT_RELEGATE_POSITIONS = (5, 6)
TOURNAMENT_PROMOTION_FLOOR = 20
TOURNAMENT_RELEGATION_FLOOR = 10

# A group this small has no competition in it -- a solo player who wins 7 of
# 10 clears the floor and promotes against nobody, and at launch (everyone in
# tier 3, groups of one) that would be the NORMAL case, inflating the whole
# population into tier 1 within a week. Promotion out of a group smaller than
# this is refused.
TOURNAMENT_MIN_GROUP_FOR_PROMOTION = 3

# Placement pays medals and bucks ONLY -- per-match credits are the separate,
# smaller table below. Scarcity is the point: packs 6 and 7 cost 1 and 3
# medals (see packedfootball/packEngine.py), so two medals is a real prize
# rather than a consolation. Bucks exist on the tier 1 podium and nowhere
# else in the game outside the store.
#
# A position missing from a tier's table pays nothing.
#
# A PROMOTION-SLOT reward only pays if the player actually cleared
# PROMOTION_FLOOR -- finishing 2nd on 15 points in a weak group is not worth a
# medal. That keys off the rule's VERDICT rather than its clamped effect, so a
# tier 1 winner (who cannot promote and is recorded as staying) still collects
# the top prize.
TOURNAMENT_REWARDS = {
    1: {1: {"medals": 5, "bucks": 5}, 2: {"medals": 3, "bucks": 3}, 3: {"medals": 3}},
    2: {1: {"medals": 3}, 2: {"medals": 2}, 3: {"medals": 1}},
    3: {1: {"medals": 2}, 2: {"medals": 1}},
}

TOURNAMENT_REWARD_MIN_MATCHES = 1

# What a single tournament match pays, regardless of placement. Higher than 
# quickplay as an incentive to play tournaments more and more
TOURNAMENT_MATCH_REWARD_CREDITS = {"loss": 10, "draw":50 , "win": 300}

# Settlement.
#
# Lazy settlement walks back this many days on any tournament request, so a
# day nobody returned to still settles eventually. Cloud Scheduler calling
# /tournament/settle is what makes it punctual.
TOURNAMENT_SETTLE_LOOKBACK_DAYS = 3

# Settling happens inside a player's own request, and Cloud Run runs at
# --max-instances 3, so an unbounded sweep is a latency bomb. Settlement is
# idempotent and incremental, which makes capping it free -- later requests
# finish the job.
TOURNAMENT_MAX_GROUPS_PER_REQUEST = 5

# Shared secret for POST /tournament/settle. A scheduled invoker has no
# Firebase ID token, so it cannot use verify_id_token. Fails CLOSED when
# unset -- an empty configured secret must never make every request match.
TOURNAMENT_ADMIN_SECRET = os.environ.get("TOURNAMENT_ADMIN_SECRET", "")

# Matchmaking. Each candidate that survives the cheap check costs 11 more
# reads to hydrate its roster, so this bounds the worst case.
TOURNAMENT_OPPONENT_MAX_ATTEMPTS = 5

# _generate_bot_opponent rolls a random CARD tier from the full spread by
# default, which puts icon bots in bronze tournaments. Tournaments pick from
# a tier-appropriate pool instead.
TOURNAMENT_BOT_CARD_TIERS = {
    1: ("platinum", "diamond"),
    2: ("gold", "platinum"),
    3: ("silver", "gold"),
}
