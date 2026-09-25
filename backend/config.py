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

# -- display names ------------------------------------------------------------

# A manager name is 3-16 characters of letters
DISPLAY_NAME_MIN_LENGTH = 3
DISPLAY_NAME_MAX_LENGTH = 16

# -- what things cost, what they pay ------------------------------------------

# What releasing a card pays, by tier FAMILY -- game_config.TIER_RANGES'
# keys after tier_family(), so the three special_* variants share the one
# "special" row. mobile/scripts/data/PlayerCard.gd carries the same table so
# the Release button can show the amount BEFORE the request; this end is
# the one that actually pays out, so the two have to be kept in step by
# hand (same arrangement as APPEARANCE_OPTION_COUNTS and PlayerAppearance.gd).
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

# What scrapping a spare ITEM pays, by rarity family -- packedfootball/
# items.py's ITEM_VALUES keys. Deliberately a fraction of what a card of the
# same rarity releases for: an item is a buff, not a footballer, and scrapping
# has to stay worse than socketing or nobody would ever equip anything.
# Only an UNEQUIPPED item can be scrapped; socketing is one-way.
ITEM_SCRAP_CREDITS_BY_RARITY = {
    "bronze": 5,
    "silver": 10,
    "gold": 25,
    "platinum": 60,
    "diamond": 150,
    "special": 300,
    "icon": 600,
}
ITEM_SCRAP_CREDITS_DEFAULT = 5

# Same reasoning as RELEASE_BATCH_MAX: one transaction, so it has to stay a
# size that commits comfortably.
ITEM_SCRAP_BATCH_MAX = 30

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
ENERGY_REGEN_SECONDS = 15 * 60
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
#
# avg_rating is a denormalised field player.py's record_match writes once
# a card has RATED_MATCHES_FOR_AVERAGE rated matches (Firestore can't order
# on rating_sum / rating_count); a card below that threshold has no such
# field and so isn't on that board at all. clean_sheets only ever move for
# keepers, so that board is a keeper board whatever the position filter.
PLAYER_LEADERBOARD_STATS = {
    "goals": "statistics.goals",
    "assists": "statistics.assists",
    "avg_rating": "statistics.avg_rating",
    "clean_sheets": "statistics.clean_sheets",
    "matches_played": "statistics.matches_played",
}

# The player board can be narrowed to one position ("ST") or one of
# packEngine.POSITION_CATEGORIES' families ("attacker"). Either way the
# query is an equality/in on `position` plus the order_by above, which
# Firestore needs a COMPOSITE index for -- one per stat, declared in the
# repo-root firestore.indexes.json and deployed with
# `firebase deploy --only firestore:indexes`. A stat added here needs its
# index added there, or the filtered query fails with a link to create it.

# Only "wins" for now, by design -- the mobile Leaderboard screen's Users
# tab is a deliberately minimal first pass (see mobile/README.md). Shaped
# the same way as PLAYER_LEADERBOARD_STATS/leaderboard_players above (a
# dict of allowed stats, checked the same way) so adding another one later
# (credits, bucks, ...) is just another entry, not new plumbing.
USER_LEADERBOARD_STATS = {
    "wins": "wins",
}

# Both leaderboards page by this many rows; the client's Leaderboard screen
# lays out exactly this many with Prev/Next, podium colours on the top three.
LEADERBOARD_PAGE_SIZE = 10

# -- daily tournaments --------------------------------------------------------

# ONE ENTRY PER TIER, holding everything that tier decides: what it's called,
# what its bots are made of, and what each finishing position pays. Reading a
# league is reading one block top to bottom rather than cross-referencing
# three tables by number, and adding or removing a tier is one entry rather
# than an edit in each of them -- the same shape AD_REWARD_PATH uses.
#
#   name             what the client shows. Not translated (see mobile's
#                    README: anything the backend composes stays as sent).
#   bot_card_rates   what a bot's eleven are made of in this tier -- each
#                    card rolls its own tier from these weights (a pack's
#                    "rates" shape), so a bronze-league bot is mostly silver
#                    with a few golds and the odd platinum rather than eleven
#                    identical cards. Used both for the stored bots
#                    scripts/seed_bots.py creates and for the throwaway one
#                    _generate_bot_opponent rolls when a pool is empty. Quick
#                    Match bots keep rolling a single random tier from the
#                    whole spread.
#   rewards          placement payouts, by finishing POSITION -- not by
#                    whether the player promoted. The podium carries the
#                    scarce currencies (medals, and bucks on the tier 1
#                    podium only -- packs 6 and 7 cost 1 and 3 medals, see
#                    packedfootball/packEngine.py, so two medals is a real
#                    prize) and every row down to last carries credits, so a
#                    bad day still pays something and there is a reason to
#                    keep playing from 5th. A position missing from the table
#                    pays nothing.
#
# Sized against the per-match credits below: ten wins is 3000, so a bronze
# win is worth about half a perfect day on top.
TOURNAMENT_TIERS = {
    1: {
        "name": "Gold League",
        "bot_card_rates": {"gold": 0.2, "platinum": 0.45, "diamond": 0.35},
        "rewards": {
            1: {"medals": 5, "bucks": 5, "credits": 3000},
            2: {"medals": 3, "bucks": 3, "credits": 2000},
            3: {"medals": 3, "credits": 1500},
            4: {"medals": 1, "credits": 1000},
            5: {"credits": 750},
            6: {"credits": 500},
        },
    },
    2: {
        "name": "Silver League",
        "bot_card_rates": {"silver": 0.15, "gold": 0.5, "platinum": 0.3, "diamond": 0.05},
        "rewards": {
            1: {"medals": 3, "credits": 2000},
            2: {"medals": 2, "credits": 1500},
            3: {"medals": 1, "credits": 1000},
            4: {"credits": 750},
            5: {"credits": 500},
            6: {"credits": 300},
        },
    },
    3: {
        "name": "Bronze League",
        "bot_card_rates": {"bronze": 0.1, "silver": 0.45, "gold": 0.4, "platinum": 0.05},
        "rewards": {
            1: {"medals": 2, "credits": 1500},
            2: {"medals": 1, "credits": 1000},
            3: {"credits": 500},
            4: {"credits": 400},
            5: {"credits": 300},
            6: {"credits": 200},
        },
    },
}

# 1 is the top. Derived from the table's own keys, so a fourth tier is one
# more entry above and nothing else. A player's tier lives on users/{uid} and
# only moves at settlement; new accounts start at the bottom.
TOURNAMENT_TOP_TIER = min(TOURNAMENT_TIERS)
TOURNAMENT_BOTTOM_TIER = max(TOURNAMENT_TIERS)
TOURNAMENT_DEFAULT_TIER = TOURNAMENT_BOTTOM_TIER

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
# 16 is five wins and a draw out of ten; 20 needed seven wins, which in a
# real group of six meant the top two rarely both cleared it.
TOURNAMENT_PROMOTION_FLOOR = 16
TOURNAMENT_RELEGATION_FLOOR = 8

# A group this small has no competition in it -- a solo player who wins 7 of
# 10 clears the floor and promotes against nobody, and at launch (everyone in
# tier 3, groups of one) that would be the NORMAL case, inflating the whole
# population into tier 1 within a week. Promotion out of a group smaller than
# this is refused.
TOURNAMENT_MIN_GROUP_FOR_PROMOTION = 3

TOURNAMENT_REWARD_MIN_MATCHES = 1

# Playing every one of the day's matches pays this, on top of placement --
# but only when CLAIMED (POST /claim, type "tournament_full_day"), so the
# player presses the button and watches the number move rather than
# finding the credits already there. Same table shape as a placement
# reward, so any currency works.
TOURNAMENT_FULL_DAY_REWARD = {"credits": 500}

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

# -- weekly tournaments -------------------------------------------------------
#
# The same machine as the daily league, run over seven days instead of one:
# services/tournament.py is written against a Mode record and builds one from
# each of these blocks, so there is a single implementation of ranking,
# promotion and settlement.
#
# Deliberately a SEPARATE set of constants rather than a multiplier on the
# daily ones. The two formats will drift -- a week is a different kind of
# commitment from a day -- and when they do, the edit is a number here rather
# than a new branch in the rules.
#
# What weekly does NOT get its own copy of: the bots. Both formats draw
# opponents from the same bot_pools/{tier} written by scripts/seed_bots.py,
# so a weekly pool needs no second seeding run.

# Its own tier ladder, stored on users/{uid}.weekly_tournament_tier. Separate
# from the daily tier on purpose: a player who is gold in the daily grind and
# bronze over a full week is telling you something true, and sharing one field
# would let a good week undo a bad month of days.
#
# Same per-tier shape as TOURNAMENT_TIERS above. Ten rows instead of six, so
# a full group pays everyone down to last, and bigger numbers than the daily
# equivalent throughout, because fifty matches over seven days has to be
# worth more than ten in one.
#
# THE INVARIANT a test holds this to: no position ever pays less here than
# the same position pays in the daily league.
#
# The bot rates are the daily tier's OBJECT, not a copy -- "the same bots as
# the daily tournament" is then something the file states rather than
# something two tables happen to agree on.
WEEKLY_TOURNAMENT_TIERS = {
    1: {
        "name": "Gold League",
        "bot_card_rates": TOURNAMENT_TIERS[1]["bot_card_rates"],
        "rewards": {
            1: {"medals": 30, "bucks": 10, "credits": 5000},
            2: {"medals": 15, "bucks": 5, "credits": 3000},
            3: {"medals": 10, "bucks": 3, "credits": 2000},
            4: {"medals": 5, "credits": 2000},
            5: {"medals": 3, "credits": 1000},
            6: {"credits": 750},
            7: {"credits": 500},
            8: {"credits": 400},
            9: {"credits": 350},
            10: {"credits": 300},
        },
    },
    2: {
        "name": "Silver League",
        "bot_card_rates": TOURNAMENT_TIERS[2]["bot_card_rates"],
        "rewards": {
            1: {"medals": 20, "credits": 4000},
            2: {"medals": 10, "credits": 2000},
            3: {"medals": 5, "credits": 1500},
            4: {"credits": 750},
            5: {"credits": 500},
            6: {"credits": 300},
            7: {"credits": 275},
            8: {"credits": 250},
            9: {"credits": 225},
            10: {"credits": 200},
        },
    },
    3: {
        "name": "Bronze League",
        "bot_card_rates": TOURNAMENT_TIERS[3]["bot_card_rates"],
        "rewards": {
            1: {"medals": 10, "credits": 3000},
            2: {"medals": 5, "credits": 1500},
            3: {"medals": 3, "credits": 1000},
            4: {"credits": 750},
            5: {"credits": 500},
            6: {"credits": 300},
            7: {"credits": 250},
            8: {"credits": 150},
            9: {"credits": 125},
            10: {"credits": 100},
        },
    },
}

WEEKLY_TOURNAMENT_TOP_TIER = min(WEEKLY_TOURNAMENT_TIERS)
WEEKLY_TOURNAMENT_BOTTOM_TIER = max(WEEKLY_TOURNAMENT_TIERS)
WEEKLY_TOURNAMENT_DEFAULT_TIER = WEEKLY_TOURNAMENT_BOTTOM_TIER

# Ten players, fifty matches. Bigger than the daily six because a week gives
# enough matches for a ten-row table to actually separate people.
WEEKLY_TOURNAMENT_GROUP_CAPACITY = 10
WEEKLY_TOURNAMENT_MATCHES_PER_WEEK = 50

WEEKLY_TOURNAMENT_POINTS = {"win": 3, "draw": 1, "loss": 0}

# Seven days, rolling over at the same hour as the daily reset so a player
# only ever has one reset time to learn (TOURNAMENT_DAY_OFFSET_HOURS == 12:00
# in Istanbul).
WEEKLY_TOURNAMENT_PERIOD_DAYS = 7
WEEKLY_TOURNAMENT_DAY_OFFSET_HOURS = TOURNAMENT_DAY_OFFSET_HOURS

# Which calendar date the seven-day grid counts from -- it fixes WHICH day of
# the week a week starts on, and nothing else. 2026-01-05 is a Sunday, so a
# week runs Monday 12:00 Istanbul to the next Monday 12:00. Weeks before this
# date are still computed correctly; it is an origin, not a start date.
WEEKLY_TOURNAMENT_PERIOD_ANCHOR = "2026-01-05"

# No joining in the last 12 hours. The daily league's reasoning at weekly
# scale: fifty matches costs fifty energy, so a join is only worth selling
# while the remaining time can still regenerate a real share of that.
# Twelve hours is half a day of regen -- 48 energy at ENERGY_REGEN_SECONDS
# of 15 minutes -- which is nearly the whole schedule, and a late joiner who
# wants the rest can buy it. This number and ENERGY_REGEN_SECONDS are paired:
# slow the bar down and this has to grow.
WEEKLY_TOURNAMENT_JOIN_CUTOFF_SECONDS = 12 * 60 * 60

# Promotion and relegation, same two-path rule as the daily league (positional
# in a full group, thresholds in a short one). Scaled to ten rows: three up,
# three down, four safe -- the daily 2/2/2 shape at this size.
WEEKLY_TOURNAMENT_PROMOTE_POSITIONS = (1, 2, 3)
WEEKLY_TOURNAMENT_RELEGATE_POSITIONS = (8, 9, 10)

# The daily floors multiplied by the five-times-longer schedule: 80 is
# twenty-five wins and five draws out of fifty, 40 is the same share of the
# week the daily 8 is of the day.
WEEKLY_TOURNAMENT_PROMOTION_FLOOR = 80
WEEKLY_TOURNAMENT_RELEGATION_FLOOR = 40

# Same guard as the daily league, for the same reason: promotion out of a
# group with nobody in it to beat is not promotion.
WEEKLY_TOURNAMENT_MIN_GROUP_FOR_PROMOTION = 3

WEEKLY_TOURNAMENT_REWARD_MIN_MATCHES = 1

# Playing all fifty pays this, on CLAIM (POST /claim, type
# "tournament_full_week"), the same way the daily league's full-day reward works.
WEEKLY_TOURNAMENT_FULL_WEEK_REWARD = {"bucks": 5}

# What one weekly match pays regardless of placement. Same numbers as the
# daily league for now, separate so the two can be priced apart.
WEEKLY_TOURNAMENT_MATCH_REWARD_CREDITS = {"loss": 10, "draw": 50, "win": 300}

# What one weekly match costs. Fifty matches is fifty energy across seven
# days, against a bar that refills about 32 a day -- comfortably affordable
# alongside a full daily run, and the dial to turn if that stops being true.
WEEKLY_TOURNAMENT_ENERGY_COST_PER_MATCH = ENERGY_COST_PER_MATCH

# Two weeks of lookback, so a player returning after missing a week still
# triggers settlement of the week they actually played.
WEEKLY_TOURNAMENT_SETTLE_LOOKBACK_WEEKS = 2

WEEKLY_TOURNAMENT_MAX_GROUPS_PER_REQUEST = 5
WEEKLY_TOURNAMENT_OPPONENT_MAX_ATTEMPTS = 5

# -- match bug reports --------------------------------------------------------

# What a player can tag a report with (POST /match/report). Keys are what
# the client sends and what match_reports/{id}.category stores; the client
# carries its own labels for them. Free text goes alongside, capped.
MATCH_REPORT_CATEGORIES = (
    "stuck_players",   # players standing still / running in place / stuck on a line
    "ball_physics",    # ball through a player, teleporting, stuck in the net
    "goalkeeper",      # keeper did something absurd
    "wrong_score",     # the scoreboard doesn't match what was shown
    "replay_glitch",   # playback itself: freezes, camera, skipped events
    "other",
)
MATCH_REPORT_MAX_CHARS = 1000

# -- ads ----------------------------------------------------------------------

# The progressive reward path for standard ads. 
# Step 0 (1st ad): 200 credits
# Step 1 (2nd ad): 300 credits
# Step 2 (3rd ad): 500 credits + 1 buck
AD_REWARD_PATH = [
    {"credits": 200, "bucks": 0},
    {"credits": 300, "bucks": 0},
    {"credits": 500, "bucks": 1},
]

# The separate track for energy ads
AD_ENERGY_MAX = 3
AD_ENERGY_REWARD = 1