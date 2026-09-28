"""The daily penalty shootout: streak, prestige, rewards.

Split the way energy and tournaments are: everything above `-- firestore --`
is a pure function of its arguments with `now` passed in, so the rules can be
tested without a client and without freezing a clock. Only the half below
touches a transaction.

State lives on users/{uid}/minigames/shootout -- a subcollection, so the next
minigame is another doc beside it rather than four more columns on the profile.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import config
from engine import best_taker_order, penalty_score
from services import energy as energy_service
from services.ads import counters, game_date

# One doc per minigame under the player's profile.
STATE_COLLECTION = "minigames"
SHOOTOUT_DOC = "shootout"

LAST_PLAYED_FIELD = "last_played"
CYCLE_DAY_FIELD = "cycle_day"
PRESTIGE_FIELD = "prestige"
PAID_TODAY_FIELD = "paid_today"

# The ad track that buys a second attempt. Registered in services/ads.py.
RETRY_TRACK = "shootout_retry"


def state_path(uid: str) -> str:
    return f"users/{uid}/{STATE_COLLECTION}/{SHOOTOUT_DOC}"


def session_path(uid: str) -> str:
    """One live shootout per player, overwritten each day. Top-level, like
    games/ and ad_ssv_grants/, so the rules' default-deny already covers it."""
    return f"shootout_sessions/{uid}"


def encode_input(aim: int | None, dive: int | None) -> dict:
    """One kick's supplied corners, as the session doc stores them.

    A MAP per kick, not an [aim, dive] pair: Firestore refuses an array
    nested directly inside an array, and the client library encodes one
    without complaint -- so a pair is accepted locally and rejected by the
    server, which means it only ever fails in a deployed environment.
    """
    return {"aim": aim, "dive": dive}


def decode_inputs(session: dict | None) -> list:
    """The input log as (aim, dive) pairs, in kick order."""
    return [
        (played.get("aim"), played.get("dive"))
        for played in (session or {}).get("inputs") or []
        if isinstance(played, dict)
    ]


# -- the kick order -----------------------------------------------------------

def picker_squad(players: list) -> dict:
    """The XI as the pre-match picker shows it: each player's penalty score,
    and the engine's own best-first order for Auto-select. Scored by the
    engine's function, so the number on screen is the one the kick is rolled
    from."""
    return {
        "players": [
            {
                "idx": i,
                "name": getattr(p, "lname", "") or "",
                "position": getattr(p, "position", "") or "",
                "score": int(round(penalty_score(p.attributes))),
            }
            for i, p in enumerate(players)
        ],
        "suggested": best_taker_order(players),
    }


def taker_order(requested: list | None, squad_size: int) -> list[int] | None:
    """The kick order the player sent, checked. None when none was sent (an
    older client), which leaves the engine to order best-first.

    Every player exactly once: a short list, or one naming the same striker
    twice, would let the best finisher take every kick.
    """
    if requested is None:
        return None
    order = [int(i) for i in requested]
    if sorted(order) != list(range(squad_size)):
        raise ValueError(f"the kick order must name all {squad_size} players, each once")
    return order


def previous_date(today: str) -> str:
    """The game-day before `today`. String in, string out -- the callers
    compare stored dates, never datetimes."""
    return (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")


def seconds_until_reset(now: datetime | None = None) -> int:
    """How long the current game-day has left, for the client's countdown.
    Seconds, never a timestamp -- the client ticks it down locally and is
    never exposed to device-clock skew (same call as energy.describe)."""
    now = now or energy_service.now_utc()
    shifted = now - timedelta(hours=config.TOURNAMENT_DAY_OFFSET_HOURS)
    next_day = (shifted + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(0, int((next_day - shifted).total_seconds()))


# -- the ramp -----------------------------------------------------------------

def reward_credits(day: int, prestige: int, won: bool) -> int:
    """What one finished shootout pays.

    Three multipliers on one base: how far into the cycle, how many cycles
    have been completed (capped), and whether it was won. Day 1 at prestige 0
    is 100/300, which is what the flat table it replaced paid.
    """
    day_mult = 1.0 + config.PENALTY_SHOOTOUT_DAY_STEP * (max(1, day) - 1)
    prestige_mult = 1.0 + config.PENALTY_SHOOTOUT_PRESTIGE_STEP * clamp_prestige(prestige)
    outcome = config.PENALTY_SHOOTOUT_WIN_MULTIPLIER if won else 1.0
    return int(round(config.PENALTY_SHOOTOUT_BASE_CREDITS * day_mult * prestige_mult * outcome))


def clamp_prestige(prestige: int) -> int:
    """Both the reward ramp and the bot grid stop at the same level."""
    return max(0, min(int(prestige or 0), config.PENALTY_SHOOTOUT_PRESTIGE_MAX))


def is_cycle_end(day: int) -> bool:
    return day >= config.PENALTY_SHOOTOUT_CYCLE_DAYS


def cycle_bonus(day: int) -> dict:
    """The one-off for finishing a cycle. Flat: prestige does not scale it."""
    return dict(config.PENALTY_SHOOTOUT_CYCLE_BONUS) if is_cycle_end(day) else {}


def owed(reward: int, paid_today: int) -> int:
    """What is still payable after what today already paid.

    This is what makes the ad retry a top-up: a loss pays, and a winning
    retry pays only the difference, so a day can never pay more than one win.
    It also makes a replayed settle a no-op rather than a second payout.
    """
    return max(0, int(reward) - int(paid_today or 0))


# -- the bot ------------------------------------------------------------------

def bot_tier_for_day(day: int) -> str:
    """Day 1 bronze, day 15 special."""
    index = max(1, min(int(day), config.PENALTY_SHOOTOUT_CYCLE_DAYS)) - 1
    return config.PENALTY_SHOOTOUT_BOT_LADDER[index]


def bot_pool_path(day: int) -> str:
    """The named bots for one day of the cycle, one per prestige level.

    A 15 x PRESTIGE_LEVELS grid written by scripts/seed_bots.py -- the same
    bots/{id} docs the tournament pools use, so one seeding run and one
    bot_profile_from_doc cover both.
    """
    return f"bot_pools/shootout_{int(day)}"


def bot_id_from_pool(pool_doc: dict | None, prestige: int) -> str | None:
    """This cell's bot, or None when the grid has not been seeded.

    Clamped by the same rule the reward ramp uses, so prestige past the cap
    keeps meeting the top row rather than falling off the end of the list.
    """
    uids = list((pool_doc or {}).get("uids") or [])
    if not uids:
        return None
    return uids[min(clamp_prestige(prestige), len(uids) - 1)]


def bot_rates(day: int, prestige: int) -> dict:
    """Card-tier weights for the day's bot, nudged by prestige.

    The tier is the day's; prestige only leans the MIX one step up it, so a
    veteran's day-5 bot is still a silver side with more golds in it. Day 15
    sits at the top of PENALTY_SHOOTOUT_TIER_ORDER and takes no nudge -- the
    only tier above special is icon, which is not a difficulty setting.
    """
    tier = bot_tier_for_day(day)
    order = config.PENALTY_SHOOTOUT_TIER_ORDER
    step = clamp_prestige(prestige) * config.PENALTY_SHOOTOUT_PRESTIGE_NUDGE
    index = order.index(tier)
    if step <= 0.0 or index + 1 >= len(order):
        return {tier: 1.0}
    return {tier: 1.0 - step, order[index + 1]: step}


# -- reading the state --------------------------------------------------------

def state_from_doc(doc: dict | None, now: datetime | None = None) -> dict:
    """Where a player stands right now.

    A rolled day is derived, never migrated: `played_today` and `paid_today`
    read as fresh the moment the stored date stops matching, the same lazy
    reset the ad counters use.
    """
    doc = doc or {}
    now = now or energy_service.now_utc()
    today = game_date(now)
    last_played = str(doc.get(LAST_PLAYED_FIELD, "") or "")
    played_today = last_played == today

    cycle_day = max(0, int(doc.get(CYCLE_DAY_FIELD, 0) or 0))
    prestige = max(0, int(doc.get(PRESTIGE_FIELD, 0) or 0))

    # The day this attempt counts as: the one just played if today is already
    # counted, otherwise the one the next attempt would earn.
    if played_today:
        day = max(1, cycle_day) if cycle_day else config.PENALTY_SHOOTOUT_CYCLE_DAYS
    else:
        day = next_day(cycle_day, last_played, today)

    return {
        "today": today,
        "last_played": last_played,
        "cycle_day": cycle_day,
        "prestige": prestige,
        "played_today": played_today,
        "paid_today": int(doc.get(PAID_TODAY_FIELD, 0) or 0) if played_today else 0,
        "day": day,
        "cycle_days": config.PENALTY_SHOOTOUT_CYCLE_DAYS,
        "bot_tier": bot_tier_for_day(day),
        "reward": {
            "loss": reward_credits(day, prestige, won=False),
            "win": reward_credits(day, prestige, won=True),
            "cycle_bonus": cycle_bonus(day),
        },
        "seconds_until_reset": seconds_until_reset(now),
    }


def next_day(cycle_day: int, last_played: str, today: str) -> int:
    """Which day of the cycle the next attempt earns.

    Consecutive days walk up the ramp; any other gap drops back to day 1.
    Prestige is untouched either way -- a missed day costs the ramp that was
    built, never the cycles already banked.
    """
    if last_played and last_played == previous_date(today):
        return max(0, int(cycle_day or 0)) + 1
    return 1


def advance_fields(state: dict, won: bool) -> dict:
    """The state doc's fields after this attempt, and what it pays.

    Called for every finished attempt, including an ad retry -- the retry
    re-settles the SAME day, so the streak moves only on the first one and
    the payout is topped up rather than repeated.
    """
    day = state["day"]
    prestige = state["prestige"]
    reward = reward_credits(day, prestige, won)
    pay = owed(reward, state["paid_today"])
    bonus = cycle_bonus(day) if not state["played_today"] else {}

    if state["played_today"]:
        # A retry: the day is already counted, only the running total moves.
        cycle_day, new_prestige = state["cycle_day"], prestige
    elif is_cycle_end(day):
        # Cycle done: banked as a prestige, and tomorrow starts at day 1 again
        # because cycle_day counts days COMPLETED in the current cycle.
        cycle_day, new_prestige = 0, prestige + 1
    else:
        cycle_day, new_prestige = day, prestige

    return {
        "fields": {
            LAST_PLAYED_FIELD: state["today"],
            CYCLE_DAY_FIELD: cycle_day,
            PRESTIGE_FIELD: new_prestige,
            PAID_TODAY_FIELD: max(int(state["paid_today"]), reward),
        },
        "credits": pay,
        "bonus": bonus,
        "day": day,
        "prestige": new_prestige,
        "prestiged": new_prestige > prestige,
    }


# -- firestore ----------------------------------------------------------------
#
# Everything above is pure. Below is the one transaction that pays a finished
# shootout and moves the streak, and the reads the router needs around it.


class ShootoutRefused(Exception):
    """The attempt cannot be started or settled -- out of attempts, no session."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def can_buy_retry(won: bool, attempts_used: int, allowed: int) -> bool:
    """Whether an ad would buy another go today.

    Only after a LOSS that spent the last attempt, and only while the day's
    retry ads are not all watched -- `allowed` is 1 + ads watched, so past the
    cap the ad track would refuse the grant and the button would be a lie.
    """
    return (
        not won
        and attempts_used >= allowed
        and allowed < 1 + config.PENALTY_SHOOTOUT_AD_RETRIES_PER_DAY
    )


def attempts_allowed(profile: dict | None, now: datetime | None = None) -> int:
    """The free attempt, plus one per retry ad watched today.

    The ad track's daily cap is the retry allowance, so nothing here has to
    count ads -- services/ads.py already refuses the second one.
    """
    now = now or energy_service.now_utc()
    watched = counters(profile, game_date(now)).get(RETRY_TRACK, {}).get("watched", 0)
    return 1 + int(watched)


def settle_in_tx(tx, uid: str, won: bool, now: datetime | None = None) -> dict:
    """Pay a finished shootout and move the streak, in one commit.

    Three documents: the profile (credits and the cycle's bucks), the streak
    doc, and the session. Every read happens first because TransactionScope
    enforces it, and the body is a pure function of what it reads because
    Firestore may run it more than once.

    Balances move by Increment and are never read-compute-written, so a pack
    bought at the same moment cannot be clobbered by a stale read.
    """
    from firebase_admin import firestore  # local: keeps the pure half import-free

    now = now or energy_service.now_utc()
    user_path = f"users/{uid}"
    streak_path = state_path(uid)
    live_path = session_path(uid)

    docs = tx.get_all([user_path, streak_path, live_path])
    user_doc = docs.get(user_path) or {}
    live = docs.get(live_path)
    if live is None or live.get("status") == "finished":
        raise ShootoutRefused("no live shootout")

    state = state_from_doc(docs.get(streak_path), now)
    moved = advance_fields(state, won)

    payout: dict = {}
    if moved["credits"]:
        payout["credits"] = moved["credits"]
    for currency, amount in moved["bonus"].items():
        if amount:
            payout[currency] = payout.get(currency, 0) + int(amount)

    if payout:
        tx.set(user_path, {c: firestore.Increment(a) for c, a in payout.items()}, merge=True)
    tx.set(streak_path, moved["fields"], merge=True)
    tx.set(live_path, {"status": "finished", "won": bool(won)}, merge=True)

    balances = {c: int(user_doc.get(c, 0) or 0) + a for c, a in payout.items()}
    return {
        "rewards": payout,
        "balances": balances,
        "day": moved["day"],
        "prestige": moved["prestige"],
        "prestiged": moved["prestiged"],
        # Off the profile this transaction already read, so the end screen can
        # say whether an ad would buy another go without a second read.
        "attempts_allowed": attempts_allowed(user_doc, now),
    }
