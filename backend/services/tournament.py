"""Tournaments: period keys, standings, promotion, settlement.

ONE implementation, two formats. Everything below is written against a
`Mode` record -- the daily league is `DAILY`, the weekly league is `WEEKLY`,
and a Mode is nothing but the config block that format was built from. A
third format is a new block in config.py and a new Mode, not a new module.

Layered so the rules are testable without Firestore:

    rank_rows(entries)          pure -- ordering and positions
    apply_rules(rows, ...)      pure -- promote / stay / relegate, and rewards
    settle_group(...)           the transaction that writes what those decide

Everything above the line is a function of its arguments and nothing else,
which matters twice over: a transaction body may be RETRIED, so it has to
produce the same table every time, and the standings screen calls the same
apply_rules to show "what happens if the period ended now" -- one
implementation is what stops the projection and the payout from ever
disagreeing.

Addressing is by PATH throughout. There is not one where() clause in this
feature, so it needs no composite index -- which matters, because this
project has none and no firestore.indexes.json to put one in.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import config


# -- modes --------------------------------------------------------------------


@dataclass(frozen=True)
class Mode:
    """One tournament format, assembled from its config block.

    Carries the Firestore root it lives under; on users/{uid} its state is
    keyed by `key` inside the shared maps below, so two formats run side by
    side without sharing a document, a tier or a seat. The one thing they DO
    share is the bot pool -- see bot_pool_path.
    """

    key: str
    label: str
    collection: str
    period_days: int
    period_anchor: str
    offset_hours: int

    top_tier: int
    bottom_tier: int
    default_tier: int
    # {tier: {"name", "bot_card_rates", "rewards"}} -- see config's
    # TOURNAMENT_TIERS. One table, so a tier's name, its bots and its payouts
    # can't drift apart.
    tiers: dict

    group_capacity: int
    matches_per_period: int
    points: dict
    join_cutoff_seconds: int

    promote_positions: tuple
    relegate_positions: tuple
    promotion_floor: int
    relegation_floor: int
    min_group_for_promotion: int

    reward_min_matches: int
    full_period_reward: dict
    match_reward_credits: dict
    energy_cost_per_match: int

    settle_lookback_periods: int
    max_groups_per_request: int
    opponent_max_attempts: int

    # What the trophy cabinet calls this format. Composed here, so not translated.
    name: str = ""
    # Play is only allowed in the last `open_seconds` of a period; None = always.
    open_seconds: int | None = None
    # One table for everyone: paged standings snapshot, member-by-member settlement.
    global_table: bool = False


DAILY = Mode(
    key="daily",
    label="day",
    collection="tournaments",
    period_days=1,
    # Unused at period_days=1 -- every date is its own period -- but the
    # formula is the same one the weekly grid uses, so it needs an origin.
    period_anchor="2026-01-05",
    offset_hours=config.TOURNAMENT_DAY_OFFSET_HOURS,
    top_tier=config.TOURNAMENT_TOP_TIER,
    bottom_tier=config.TOURNAMENT_BOTTOM_TIER,
    default_tier=config.TOURNAMENT_DEFAULT_TIER,
    tiers=config.TOURNAMENT_TIERS,
    group_capacity=config.TOURNAMENT_GROUP_CAPACITY,
    matches_per_period=config.TOURNAMENT_MATCHES_PER_DAY,
    points=config.TOURNAMENT_POINTS,
    join_cutoff_seconds=config.TOURNAMENT_JOIN_CUTOFF_SECONDS,
    promote_positions=config.TOURNAMENT_PROMOTE_POSITIONS,
    relegate_positions=config.TOURNAMENT_RELEGATE_POSITIONS,
    promotion_floor=config.TOURNAMENT_PROMOTION_FLOOR,
    relegation_floor=config.TOURNAMENT_RELEGATION_FLOOR,
    min_group_for_promotion=config.TOURNAMENT_MIN_GROUP_FOR_PROMOTION,
    reward_min_matches=config.TOURNAMENT_REWARD_MIN_MATCHES,
    full_period_reward=config.TOURNAMENT_FULL_DAY_REWARD,
    match_reward_credits=config.TOURNAMENT_MATCH_REWARD_CREDITS,
    energy_cost_per_match=config.ENERGY_COST_PER_MATCH,
    settle_lookback_periods=config.TOURNAMENT_SETTLE_LOOKBACK_DAYS,
    max_groups_per_request=config.TOURNAMENT_MAX_GROUPS_PER_REQUEST,
    opponent_max_attempts=config.TOURNAMENT_OPPONENT_MAX_ATTEMPTS,
    name="Daily League",
)

WEEKLY = Mode(
    key="weekly",
    label="week",
    collection="weekly_tournaments",
    period_days=config.WEEKLY_TOURNAMENT_PERIOD_DAYS,
    period_anchor=config.WEEKLY_TOURNAMENT_PERIOD_ANCHOR,
    offset_hours=config.WEEKLY_TOURNAMENT_DAY_OFFSET_HOURS,
    top_tier=config.WEEKLY_TOURNAMENT_TOP_TIER,
    bottom_tier=config.WEEKLY_TOURNAMENT_BOTTOM_TIER,
    default_tier=config.WEEKLY_TOURNAMENT_DEFAULT_TIER,
    tiers=config.WEEKLY_TOURNAMENT_TIERS,
    group_capacity=config.WEEKLY_TOURNAMENT_GROUP_CAPACITY,
    matches_per_period=config.WEEKLY_TOURNAMENT_MATCHES_PER_WEEK,
    points=config.WEEKLY_TOURNAMENT_POINTS,
    join_cutoff_seconds=config.WEEKLY_TOURNAMENT_JOIN_CUTOFF_SECONDS,
    promote_positions=config.WEEKLY_TOURNAMENT_PROMOTE_POSITIONS,
    relegate_positions=config.WEEKLY_TOURNAMENT_RELEGATE_POSITIONS,
    promotion_floor=config.WEEKLY_TOURNAMENT_PROMOTION_FLOOR,
    relegation_floor=config.WEEKLY_TOURNAMENT_RELEGATION_FLOOR,
    min_group_for_promotion=config.WEEKLY_TOURNAMENT_MIN_GROUP_FOR_PROMOTION,
    reward_min_matches=config.WEEKLY_TOURNAMENT_REWARD_MIN_MATCHES,
    full_period_reward=config.WEEKLY_TOURNAMENT_FULL_WEEK_REWARD,
    match_reward_credits=config.WEEKLY_TOURNAMENT_MATCH_REWARD_CREDITS,
    energy_cost_per_match=config.WEEKLY_TOURNAMENT_ENERGY_COST_PER_MATCH,
    settle_lookback_periods=config.WEEKLY_TOURNAMENT_SETTLE_LOOKBACK_WEEKS,
    max_groups_per_request=config.WEEKLY_TOURNAMENT_MAX_GROUPS_PER_REQUEST,
    opponent_max_attempts=config.WEEKLY_TOURNAMENT_OPPONENT_MAX_ATTEMPTS,
    name="Weekly League",
)

WEEKEND = Mode(
    key="weekend",
    label="weekend",
    collection="weekend_leagues",
    period_days=config.WEEKEND_LEAGUE_PERIOD_DAYS,
    period_anchor=config.WEEKEND_LEAGUE_PERIOD_ANCHOR,
    offset_hours=config.WEEKEND_LEAGUE_OFFSET_HOURS,
    top_tier=min(config.WEEKEND_LEAGUE_TIERS),
    bottom_tier=max(config.WEEKEND_LEAGUE_TIERS),
    default_tier=min(config.WEEKEND_LEAGUE_TIERS),
    tiers=config.WEEKEND_LEAGUE_TIERS,
    group_capacity=config.WEEKEND_LEAGUE_GROUP_CAPACITY,
    matches_per_period=config.WEEKEND_LEAGUE_MATCHES,
    points=config.WEEKEND_LEAGUE_POINTS,
    join_cutoff_seconds=config.WEEKEND_LEAGUE_JOIN_CUTOFF_SECONDS,
    promote_positions=config.WEEKEND_LEAGUE_PROMOTE_POSITIONS,
    relegate_positions=config.WEEKEND_LEAGUE_RELEGATE_POSITIONS,
    promotion_floor=config.WEEKEND_LEAGUE_PROMOTION_FLOOR,
    relegation_floor=config.WEEKEND_LEAGUE_RELEGATION_FLOOR,
    min_group_for_promotion=config.WEEKEND_LEAGUE_MIN_GROUP_FOR_PROMOTION,
    reward_min_matches=config.WEEKEND_LEAGUE_REWARD_MIN_MATCHES,
    full_period_reward=config.WEEKEND_LEAGUE_FULL_REWARD,
    match_reward_credits=config.WEEKEND_LEAGUE_MATCH_REWARD_CREDITS,
    energy_cost_per_match=config.WEEKEND_LEAGUE_ENERGY_COST_PER_MATCH,
    settle_lookback_periods=config.WEEKEND_LEAGUE_SETTLE_LOOKBACK,
    max_groups_per_request=config.WEEKEND_LEAGUE_MAX_SETTLES_PER_REQUEST,
    opponent_max_attempts=config.WEEKEND_LEAGUE_OPPONENT_MAX_ATTEMPTS,
    name="Weekend League",
    open_seconds=config.WEEKEND_LEAGUE_OPEN_SECONDS,
    global_table=True,
)

MODES = {DAILY.key: DAILY, WEEKLY.key: WEEKLY, WEEKEND.key: WEEKEND}


def mode_for(key: str) -> Mode:
    """The Mode a request asked for. Unknown keys raise rather than falling
    back to daily -- a typo must not silently settle the wrong collection."""
    try:
        return MODES[key]
    except KeyError:
        raise ValueError(f"Unknown tournament mode: {key!r}") from None


# -- period keys --------------------------------------------------------------


def period_id_for(now: datetime, mode: Mode = DAILY) -> str:
    """The period a moment belongs to, named by its first calendar date.

    A single global cutoff is the only version that needs no per-player
    timezone state. `offset_hours` shifts where the boundary falls, and
    `period_days` + `period_anchor` snap it to a grid -- so a day is "the
    date" and a week is "the Monday it started on", from one formula.
    """
    shifted = now.astimezone(timezone.utc) - timedelta(hours=mode.offset_hours)
    if mode.period_days == 1:
        return shifted.strftime("%Y-%m-%d")
    anchor = date.fromisoformat(mode.period_anchor)
    # Floor division, so dates BEFORE the anchor land on the right period too.
    elapsed = (shifted.date() - anchor).days // mode.period_days
    return (anchor + timedelta(days=elapsed * mode.period_days)).isoformat()


def period_start(period_id: str, mode: Mode = DAILY) -> datetime:
    naive = datetime.strptime(period_id, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return naive + timedelta(hours=mode.offset_hours)


def period_end(period_id: str, mode: Mode = DAILY) -> datetime:
    return period_start(period_id, mode) + timedelta(days=mode.period_days)


def seconds_remaining(period_id: str, now: datetime, mode: Mode = DAILY) -> int:
    return max(0, int((period_end(period_id, mode) - now).total_seconds()))


def previous_period_ids(period_id: str, count: int, mode: Mode = DAILY) -> list[str]:
    """The `count` periods before `period_id`, oldest first -- what lazy
    settlement walks. Computed, never queried."""
    start = period_start(period_id, mode)
    return [
        period_id_for(start - timedelta(days=n * mode.period_days), mode)
        for n in range(count, 0, -1)
    ]


def joining_is_closed(period_id: str, now: datetime, mode: Mode = DAILY) -> bool:
    """No joining in the final stretch.

    Joining with an hour of the day (or a day of the week) left could only
    ever end in relegation -- there is neither time nor energy left to play a
    meaningful number of matches -- so the join is refused rather than sold as
    an opportunity. Players who joined EARLIER are unaffected and can play to
    the last second.
    """
    return seconds_remaining(period_id, now, mode) < mode.join_cutoff_seconds


def opens_in(period_id: str, now: datetime, mode: Mode = DAILY) -> int:
    """Seconds until play opens in this period; 0 once it is open."""
    if mode.open_seconds is None:
        return 0
    return max(0, seconds_remaining(period_id, now, mode) - mode.open_seconds)


def is_open(period_id: str, now: datetime, mode: Mode = DAILY) -> bool:
    return opens_in(period_id, now, mode) == 0


def group_id_for(tier: int, index: int) -> str:
    """Zero-padded so lexical order equals numeric order, which is what makes
    a plain list_collection over a period's groups come back in a sane
    sequence."""
    return f"t{tier}-g{index:04d}"


# A global-table format has exactly one group; every per-group path keeps working.
GLOBAL_GROUP = group_id_for(1, 0)


# -- paths --------------------------------------------------------------------


def period_path(period_id: str, mode: Mode = DAILY) -> str:
    return f"{mode.collection}/{period_id}"


def desk_path(period_id: str, tier: int, mode: Mode = DAILY) -> str:
    return f"{mode.collection}/{period_id}/desks/{tier}"


def groups_path(period_id: str, mode: Mode = DAILY) -> str:
    return f"{mode.collection}/{period_id}/groups"


def group_path(period_id: str, group_id: str, mode: Mode = DAILY) -> str:
    return f"{mode.collection}/{period_id}/groups/{group_id}"


def entries_path(period_id: str, group_id: str, mode: Mode = DAILY) -> str:
    return f"{mode.collection}/{period_id}/groups/{group_id}/entries"


def entry_path(period_id: str, group_id: str, uid: str, mode: Mode = DAILY) -> str:
    return f"{mode.collection}/{period_id}/groups/{group_id}/entries/{uid}"


def pool_path(period_id: str, tier: int, mode: Mode = DAILY) -> str:
    return f"{mode.collection}/{period_id}/pools/{tier}"


def standings_meta_path(period_id: str, mode: Mode) -> str:
    return f"{mode.collection}/{period_id}/standings/meta"


def standings_chunk_path(period_id: str, chunk: int, mode: Mode) -> str:
    return f"{mode.collection}/{period_id}/standings/c{chunk:05d}"


def bot_pool_path(tier: int) -> str:
    """The stored bots for a tier, as one list of ids -- written by
    scripts/seed_bots.py, read when a period's pool is first created so the
    pool has opponents in it before anyone else has joined.

    NOT mode-scoped: every format draws from the same bots, so adding a
    format needs no second seeding run.
    """
    return f"bot_pools/{tier}"


# -- reading a profile --------------------------------------------------------
#
# A player's tournament state lives in three MAPS on users/{uid}, each keyed
# by format -- the shape ad_counters already uses:
#
#     tournament_tiers    {"daily": 2, "weekly": 3}
#     tournament_entries  {"daily": {"period_id": ..., "group_id": ...}, ...}
#     tournament_last     {"daily": {"period_id": ..., "group_id": ...}, ...}
#
# One map per QUESTION rather than one field per format-and-question: adding
# a third format adds keys, never columns, and "what is this player's
# tournament state" is three fields to read in the console instead of
# fifteen scattered ones.
#
# Every write goes through the *_fields builders below and lands with
# merge=True, which merges nested maps rather than replacing them -- so
# settling the weekly league cannot blank the daily league's seat.

TIERS_FIELD = "tournament_tiers"
ENTRIES_FIELD = "tournament_entries"
LAST_FIELD = "tournament_last"


def _slot(profile_doc: dict | None, field: str, mode: Mode) -> dict:
    """One format's sub-map, or {} -- an account that has never played this
    format, or a doc written before the format existed."""
    stored = (profile_doc or {}).get(field)
    if not isinstance(stored, dict):
        return {}
    slot = stored.get(mode.key)
    return slot if isinstance(slot, dict) else {}


def tier_of(profile_doc: dict | None, mode: Mode = DAILY) -> int:
    """A player's tier in this format, clamped into the range that exists.

    Absent means the bottom tier, so every account that predates a format
    starts at its bottom with no migration. A stored value outside the range
    (a tier that was removed, say) clamps rather than crashing.
    """
    stored = (profile_doc or {}).get(TIERS_FIELD)
    raw = stored.get(mode.key) if isinstance(stored, dict) else None
    tier = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else mode.default_tier
    return max(mode.top_tier, min(mode.bottom_tier, tier))


def entered_period(profile_doc: dict | None, mode: Mode = DAILY) -> str:
    """The period this player is currently entered in, "" if none. Cleared at
    settlement, which is what makes "are you in?" a single comparison."""
    return str(_slot(profile_doc, ENTRIES_FIELD, mode).get("period_id") or "")


def entered_group(profile_doc: dict | None, mode: Mode = DAILY) -> str:
    return str(_slot(profile_doc, ENTRIES_FIELD, mode).get("group_id") or "")


def last_period(profile_doc: dict | None, mode: Mode = DAILY) -> str:
    """The last period settled for this player, "" if none."""
    return str(_slot(profile_doc, LAST_FIELD, mode).get("period_id") or "")


def last_group(profile_doc: dict | None, mode: Mode = DAILY) -> str:
    return str(_slot(profile_doc, LAST_FIELD, mode).get("group_id") or "")


def is_entered(profile_doc: dict | None, period_id: str, mode: Mode = DAILY) -> bool:
    return entered_period(profile_doc, mode) == period_id


def enter_fields(period_id: str, group_id: str, mode: Mode = DAILY) -> dict:
    """What to merge onto users/{uid} when a player takes a seat."""
    return {ENTRIES_FIELD: {mode.key: {"period_id": period_id, "group_id": group_id}}}


def settle_fields(to_tier: int, period_id: str, group_id: str, mode: Mode = DAILY) -> dict:
    """What to merge onto users/{uid} when a period is settled: the new tier,
    a pointer to the result, and the seat released.

    The seat is set to None rather than deleted -- a null reads the same as
    absent everywhere above, and it keeps the write a plain merge.
    """
    return {
        TIERS_FIELD: {mode.key: to_tier},
        LAST_FIELD: {mode.key: {"period_id": period_id, "group_id": group_id}},
        ENTRIES_FIELD: {mode.key: None},
    }


def tier_config(tier: int, mode: Mode = DAILY) -> dict:
    """One tier's block, or {} for a tier this format doesn't have -- callers
    get an empty name and no rewards rather than a KeyError."""
    return mode.tiers.get(tier) or {}


def tier_name(tier: int, mode: Mode = DAILY) -> str:
    return tier_config(tier, mode).get("name") or f"Tier {tier}"


def rewards_table(tier: int, mode: Mode = DAILY) -> dict:
    return tier_config(tier, mode).get("rewards") or {}


def bot_card_rates(tier: int, mode: Mode = DAILY) -> dict | None:
    return tier_config(tier, mode).get("bot_card_rates")


def blank_entry(uid: str, display_name: str, tier: int, group_id: str, now: datetime) -> dict:
    return {
        "uid": uid,
        "display_name": display_name,
        "tier": tier,
        "group_id": group_id,
        "played": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "points": 0,
        "goals_for": 0,
        "goals_against": 0,
        "game_ids": [],
        "joined_at_iso": now.isoformat(),
        "settled": False,
        "is_shown": False,
        "full_period_claimed": False,
    }


def result_fields(entry: dict, my_score: int, opp_score: int, game_id: str, mode: Mode = DAILY) -> dict:
    """The entry fields after one match. A plain merge -- no transaction,
    because the match slot was already claimed before the simulation ran."""
    if my_score > opp_score:
        outcome, points = "win", mode.points["win"]
    elif my_score == opp_score:
        outcome, points = "draw", mode.points["draw"]
    else:
        outcome, points = "loss", mode.points["loss"]

    return {
        "points": entry.get("points", 0) + points,
        "wins": entry.get("wins", 0) + (outcome == "win"),
        "draws": entry.get("draws", 0) + (outcome == "draw"),
        "losses": entry.get("losses", 0) + (outcome == "loss"),
        "goals_for": entry.get("goals_for", 0) + my_score,
        "goals_against": entry.get("goals_against", 0) + opp_score,
        "game_ids": (entry.get("game_ids") or []) + [game_id],
    }, points, outcome


# -- ranking (pure) -----------------------------------------------------------


def rank_rows(entries: list[dict]) -> list[dict]:
    """Standings, best first, with `position` assigned 1..N.

    The tiebreak chain has to be TOTAL, not merely fair: a transaction body
    can be retried, and two runs that ordered equal records differently would
    promote different people. Points, then goal difference, then goals for,
    then wins -- and finally joined_at and uid, which exist purely to make the
    order deterministic when everything else is level.

    `played` is deliberately NOT a tiebreaker. Points already reward playing;
    ranking an 8-match 12-pointer above a 4-match 12-pointer would be double-
    counting, and a player who went unbeaten in fewer matches has not done
    worse.
    """
    rows = [dict(e) for e in entries]
    for row in rows:
        row["goal_diff"] = row.get("goals_for", 0) - row.get("goals_against", 0)

    rows.sort(
        key=lambda r: (
            -r.get("points", 0),
            -r.get("goal_diff", 0),
            -r.get("goals_for", 0),
            -r.get("wins", 0),
            r.get("joined_at_iso", ""),
            r.get("uid", ""),
        )
    )
    for i, row in enumerate(rows, start=1):
        row["position"] = i
    return rows


# -- the rules (pure) ---------------------------------------------------------


def _verdict(row: dict, tier: int, group_size: int, mode: Mode) -> str:
    """"promote" / "stay" / "relegate", BEFORE clamping at a tier edge.

    FULL group -- positional, and position beats points in both directions:
    a 3rd place on 22 does not go up, a 4th place on 9 does not go down. The
    promotion slots additionally have to clear the floor, so a weak group
    cannot promote someone on 12 points.

    SHORT group -- thresholds, because a position means nothing when there is
    nobody to be ahead of.

    Either way, promotion needs a group big enough to have competition in it.
    A solo player who wins 7 of 10 clears the floor against nobody, and at
    launch -- everyone in the bottom tier, groups of one -- that would be the
    NORMAL case, inflating the whole population to the top within a week.
    """
    points = row.get("points", 0)
    position = row["position"]
    can_promote = group_size >= mode.min_group_for_promotion

    if group_size >= mode.group_capacity:
        if position in mode.promote_positions:
            if can_promote and points >= mode.promotion_floor:
                return "promote"
            return "stay"
        if position in mode.relegate_positions:
            return "relegate"
        return "stay"

    if can_promote and points >= mode.promotion_floor:
        return "promote"
    if points < mode.relegation_floor:
        return "relegate"
    return "stay"


def rewards_for(tier: int, row: dict, verdict: str, mode: Mode = DAILY, field: int = 0) -> dict:
    """What a finishing position pays: the tier's table row for that
    position, whatever the verdict, else its percentile bracket of `field`
    (how many played). Promotion is a separate question from prize money --
    2nd on 15 points still finished 2nd.

    The one gate: playing nothing pays nothing. Medals for tapping Join is
    an exploit, not a rule anyone wrote down. (`verdict` is kept in the
    signature so apply_rules and the tests need no change if a verdict-
    dependent reward ever comes back.)
    """
    if row.get("played", 0) < mode.reward_min_matches:
        return {}
    table = rewards_table(tier, mode)
    if row["position"] in table:
        return dict(table[row["position"]])
    brackets = tier_config(tier, mode).get("percentile_rewards") or []
    for cut, payout in brackets:
        if row["position"] <= cut * field:
            return dict(payout)
    # Non-players can rank above a pointless player, pushing them past the field.
    return dict(brackets[-1][1]) if brackets else {}


# -- the play-everything reward -----------------------------------------------


def full_period_state(entry: dict | None, mode: Mode = DAILY) -> dict:
    """Where a player stands with the play-every-match reward, for the
    screen's progress bar and Claim button.

        played     matches played so far
        required   the format's matches_per_period
        reward     the payout table
        claimable  played every match and not claimed yet
        claimed    already paid

    Pure, so the /today payload, the results payload and claim_full_period's
    transaction all agree on what "claimable" means.
    """
    played = int((entry or {}).get("played", 0))
    # full_day_claimed is what daily entries written before the weekly league
    # existed carry; read both so a mid-period deploy can't re-pay anyone.
    claimed = bool(
        (entry or {}).get("full_period_claimed", False)
        or (entry or {}).get("full_day_claimed", False)
    )
    complete = played >= mode.matches_per_period
    return {
        "played": played,
        "required": mode.matches_per_period,
        "reward": dict(mode.full_period_reward),
        "claimable": complete and not claimed,
        "claimed": claimed,
    }


class NotClaimable(Exception):
    """The reward can't be paid: not earned yet, already claimed, or no such
    entry. `.reason` is a short code the endpoint turns into a status."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


async def claim_full_period(client, uid: str, period_id: str, group_id: str, mode: Mode = DAILY) -> dict:
    """Pays the play-everything reward for one entry, exactly once.

    One transaction reads the entry and the profile, checks
    full_period_state, then flips the claimed flag and applies the reward
    with Increment -- the same read-nothing-write-increment shape settlement
    uses, so a pack purchase committing at the same moment can't be
    clobbered. The flag and the payout land in the same commit: either both
    happened or neither.

    Returns {"rewards": {...}, "balances": {currency: new amount}} -- the
    balances are computed from the profile this transaction read plus the
    reward, which is exact under the transaction's own lock.
    """
    from firebase_admin import firestore  # local: keeps the pure half import-free

    e_path = entry_path(period_id, group_id, uid, mode)
    user_path = f"users/{uid}"

    def _claim(tx):
        docs = tx.get_all([e_path, user_path])
        entry, user_doc = docs[e_path], docs[user_path]
        if entry is None or entry.get("uid", uid) != uid:
            raise NotClaimable("no_entry")
        state = full_period_state(entry, mode)
        if state["claimed"]:
            raise NotClaimable("already_claimed")
        if not state["claimable"]:
            raise NotClaimable("not_earned")

        rewards = state["reward"]
        fields = {}
        balances = {}
        for currency, amount in rewards.items():
            if amount:
                fields[currency] = firestore.Increment(amount)
                balances[currency] = int((user_doc or {}).get(currency, 0)) + amount
        if fields:
            tx.set(user_path, fields, merge=True)
        # Both names, so an entry written by either build reads as claimed.
        tx.set(e_path, {"full_period_claimed": True, "full_day_claimed": True}, merge=True)
        return {"rewards": rewards, "balances": balances}

    return await client.run_transaction(_claim)


def apply_rules(rows: list[dict], tier: int, group_size: int | None = None, mode: Mode = DAILY) -> list[dict]:
    """Decorates ranked rows with verdict, destination tier and rewards.

    Stores the rule's VERDICT and the clamped EFFECT separately. The top tier
    cannot promote and the bottom cannot relegate, but recording that as a
    flat "stay" would lose the distinction between "held the crown" and
    "finished mid-table" -- and, more importantly, the reward gate keys off
    the verdict.
    """
    size = len(rows) if group_size is None else group_size
    # Joining without playing must not stretch everyone else's percentile.
    field = sum(1 for r in rows if r.get("played", 0) >= mode.reward_min_matches)
    out = []
    for row in rows:
        decorated = dict(row)
        verdict = _verdict(row, tier, size, mode)
        delta = {"promote": -1, "relegate": 1}.get(verdict, 0)
        to_tier = max(mode.top_tier, min(mode.bottom_tier, tier + delta))
        decorated["outcome"] = verdict
        decorated["from_tier"] = tier
        decorated["to_tier"] = to_tier
        # True when the rule said move but the edge refused -- the results
        # screen says "you hold the top tier" rather than a confusing "stay".
        decorated["tier_clamped"] = verdict != "stay" and to_tier == tier
        decorated["rewards"] = rewards_for(tier, decorated, verdict, mode, field)
        out.append(decorated)
    return out


def settlement_mode(group_size: int, mode: Mode = DAILY) -> str:
    if mode.global_table:
        return "global"
    return "positional" if group_size >= mode.group_capacity else "threshold"


# -- trophies -----------------------------------------------------------------
#
# users/{uid}.trophies = {mode: {tier: {"count": n, "last": iso}}}. Server-only
# (firestore.rules lets the client write four other fields), written in the
# same settlement write as the payout, so it is paid exactly once too.

TROPHIES_FIELD = "trophies"


def wins_trophy(row: dict) -> bool:
    """1st AND the rule said promote -- below the top tier that is a
    promotion, at the top (or in a one-tier format) it is the title."""
    return row.get("position") == 1 and row.get("outcome") == "promote"


def trophy_fields(row: dict, period_id: str, mode: Mode, increment) -> dict:
    """The users/{uid} merge for a trophy, {} for none. `increment` is
    firestore.Increment, passed in so this stays importable without the SDK."""
    if not wins_trophy(row):
        return {}
    won_at = period_end(period_id, mode).isoformat()
    return {TROPHIES_FIELD: {mode.key: {str(row["from_tier"]): {"count": increment(1), "last": won_at}}}}


def trophy_list(profile_doc: dict | None) -> list[dict]:
    """The cabinet, best first: weekend, then weekly, then daily; top tier
    first inside each. Formats or tiers that no longer exist are skipped."""
    stored = (profile_doc or {}).get(TROPHIES_FIELD)
    if not isinstance(stored, dict):
        return []
    out = []
    for mode in (WEEKEND, WEEKLY, DAILY):
        by_tier = stored.get(mode.key)
        if not isinstance(by_tier, dict):
            continue
        for tier in sorted(mode.tiers):
            slot = by_tier.get(str(tier))
            count = slot.get("count") if isinstance(slot, dict) else None
            if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                continue
            out.append({
                "mode": mode.key,
                "mode_name": mode.name,
                "tier": tier,
                "tier_name": tier_name(tier, mode),
                "kind": "champion" if tier == mode.top_tier else "promotion",
                "count": count,
                "last": str(slot.get("last") or ""),
            })
    return out


def member_settlement(row: dict, period_id: str, group_id: str, mode: Mode, increment) -> tuple[dict, dict]:
    """What settling one decorated row writes: (users/{uid} merge, entry merge).
    The one implementation behind both group and global settlement."""
    rewards = row.get("rewards") or {}
    user_fields = settle_fields(row["to_tier"], period_id, group_id, mode)
    for currency, amount in rewards.items():
        if amount:
            user_fields[currency] = increment(amount)
    user_fields.update(trophy_fields(row, period_id, mode, increment))
    entry_fields = {
        "settled": True,
        "final_position": row["position"],
        "outcome": row["outcome"],
        "to_tier": row["to_tier"],
        "rewards": rewards,
        "is_shown": False,
    }
    return user_fields, entry_fields


# -- settlement (writes) ------------------------------------------------------


async def settle_group(client, period_id: str, group_id: str, mode: Mode = DAILY) -> str:
    """Settles one group in exactly ONE transaction. Returns what happened.

    Two reads and two writes per member, plus the group document.

    Three things make it correct:

      - `settlement.status` is the idempotency token, and it is checked INSIDE
        the transaction and written in the same atomic commit as the payouts.
        Either everyone was paid and the group is marked, or neither happened.
        A concurrent scheduler run and lazy run cannot both pay out.
      - Rewards are applied with firestore.Increment, never read-compute-
        write. Settlement therefore never needs anyone's BALANCE at all, so a
        pack purchase committing at the same moment cannot be clobbered by a
        stale read -- and contention drops, because the balance field is not
        part of the read set.
      - Entry and user documents are addressed by path from `member_uids`.
        Listing the entries collection inside the transaction would lock it;
        the membership list is already on the group document, so it doesn't
        have to.
    """
    from firebase_admin import firestore  # local: keeps the pure half import-free

    g_path = group_path(period_id, group_id, mode)

    def _settle(tx):
        group = tx.get(g_path)
        if group is None:
            return "missing"
        if (group.get("settlement") or {}).get("status") == "settled":
            return "already"

        member_uids = list(group.get("member_uids") or [])
        tier = int(group.get("tier", mode.default_tier))
        if not member_uids:
            tx.set(g_path, {"settlement": {"status": "settled", "mode": "empty", "rows": []}}, merge=True)
            return "empty"

        entry_paths = [entry_path(period_id, group_id, u, mode) for u in member_uids]
        user_paths = [f"users/{u}" for u in member_uids]
        docs = tx.get_all(entry_paths + user_paths)

        entries = [docs[p] for p in entry_paths if docs[p] is not None]
        rows = apply_rules(rank_rows(entries), tier, group_size=len(member_uids), mode=mode)

        for row in rows:
            uid = row["uid"]
            user_doc = docs[f"users/{uid}"]
            if user_doc is None:
                continue
            # Belt and braces next to the group-level token: a user who has
            # already been moved for this period is never moved twice, even if
            # they somehow appear in two groups.
            if last_period(user_doc, mode) >= period_id:
                continue

            user_fields, entry_fields = member_settlement(row, period_id, group_id, mode, firestore.Increment)
            tx.set(f"users/{uid}", user_fields, merge=True)
            tx.set(entry_path(period_id, group_id, uid, mode), entry_fields, merge=True)

        tx.set(
            g_path,
            {
                "settlement": {
                    "status": "settled",
                    "mode": settlement_mode(len(member_uids), mode),
                    "rows": [_row_summary(r) for r in rows],
                }
            },
            merge=True,
        )
        return "settled"

    return await client.run_transaction(_settle)


def _row_summary(row: dict) -> dict:
    """The slice of a settled row worth keeping on the group document -- what
    a results screen renders, without the bookkeeping."""
    return {
        key: row.get(key)
        for key in (
            "uid", "display_name", "position", "points", "played",
            "wins", "draws", "losses", "goals_for", "goals_against", "goal_diff",
            "outcome", "from_tier", "to_tier", "tier_clamped", "rewards",
        )
    }


async def settle_period(client, period_id: str, max_groups: int | None = None, mode: Mode = DAILY) -> dict:
    """Settles up to `max_groups` unsettled groups of a period.

    Groups settle INDEPENDENTLY and errors are caught per group, so a period
    left half-settled is the normal case rather than a failure -- the next
    trigger picks up where this one stopped. The period is only marked settled
    once a full pass finds nothing left to do.

    Capped because this runs inside a player's own request and Cloud Run is
    at --max-instances 3; an unbounded sweep is a latency bomb. Capping is
    free precisely because settlement is idempotent and incremental.
    """
    period_doc = await client.get_document(period_path(period_id, mode))
    if period_doc is None:
        return {"period_id": period_id, "settled": 0, "status": "no-such-period"}
    if period_doc.get("status") == "settled":
        return {"period_id": period_id, "settled": 0, "status": "already"}

    limit = mode.max_groups_per_request if max_groups is None else max_groups
    if mode.global_table:
        return await settle_global_period(client, period_id, limit, mode)
    groups = await client.list_collection(groups_path(period_id, mode))
    pending = [g for g in groups if (g.get("settlement") or {}).get("status") != "settled"]

    settled, errors = 0, []
    for group in pending[:limit]:
        try:
            outcome = await settle_group(client, period_id, group["id"], mode)
            if outcome in ("settled", "empty"):
                settled += 1
        except Exception as exc:  # noqa: BLE001 -- see the module note on reporting
            errors.append(f"{group['id']}: {exc}")

    remaining = len(pending) - settled - len(errors)
    complete = remaining <= 0 and not errors
    fields = {"settle_attempts": (period_doc.get("settle_attempts", 0) + 1)}
    if errors:
        # There is no error reporting in this project, so the period document
        # is the only place a stuck period becomes visible. Worth the write.
        fields["settle_error"] = " | ".join(errors)[:1000]
    if complete:
        fields["status"] = "settled"
        fields["settle_error"] = None
    await client.set_document(period_path(period_id, mode), fields, merge=True)

    return {
        "period_id": period_id,
        "settled": settled,
        "remaining": max(0, remaining),
        "errors": errors,
        "status": "settled" if complete else "partial",
    }


async def join_period(
    client, uid: str, display_name: str, tier: int, period_id: str, now: datetime, mode: Mode = DAILY
) -> str:
    """Puts a player into a group for this period and returns its group id.

    Idempotent: an already-joined player gets their existing group back rather
    than a second entry.

    ONE transaction covers the desk, the group and the entry, which is what
    stops two players racing for the last slot in a group. The desk document
    answers "where does the next joiner go" as a path read, so no query and no
    index is needed to find an open group.

    The matchmaking pool is written with ArrayUnion -- a server-side transform
    in the same family as the Increment used for pack counters -- so
    concurrent joins cannot clobber each other's entries.

    The first join of a period in a tier also seeds the pool with that tier's
    stored bots (bot_pools/{tier}, see scripts/seed_bots.py): they're in
    the same ArrayUnion as the joiner, so the pool never exists without
    them and a second joiner racing the first can't create it empty. Bots
    are opponents only -- they hold no seat in any group and never appear
    in a table; the pick is as random over the whole pool as it is over
    real players, which is the point. Every format draws from the same bots.
    """
    from firebase_admin import firestore  # local: keeps the pure half import-free

    pd_path = period_path(period_id, mode)
    dk_path = desk_path(period_id, tier, mode)
    p_path = pool_path(period_id, tier, mode)
    user_path = f"users/{uid}"
    bp_path = bot_pool_path(tier)

    def _join(tx):
        docs = tx.get_all([pd_path, dk_path, user_path, p_path, bp_path])
        period_doc, desk, user_doc = docs[pd_path], docs[dk_path], docs[user_path]
        pool_exists = docs[p_path] is not None
        bot_ids = list((docs[bp_path] or {}).get("uids") or [])

        existing_group = entered_group(user_doc, mode)
        if is_entered(user_doc, period_id, mode) and existing_group:
            return existing_group, True

        open_group_id = (desk or {}).get("open_group_id")
        group = tx.get(group_path(period_id, open_group_id, mode)) if open_group_id else None

        members = list((group or {}).get("member_uids") or [])
        needs_new = group is None or len(members) >= mode.group_capacity
        if needs_new:
            next_index = int(((period_doc or {}).get("next_group_index") or {}).get(str(tier), 0))
            open_group_id = group_id_for(tier, next_index)
            members = []
            tx.set(
                pd_path,
                {
                    "period_id": period_id,
                    "mode": mode.key,
                    "status": (period_doc or {}).get("status", "open"),
                    "next_group_index": {
                        **(((period_doc or {}).get("next_group_index")) or {}),
                        str(tier): next_index + 1,
                    },
                },
                merge=True,
            )

        members.append(uid)
        tx.set(
            group_path(period_id, open_group_id, mode),
            {
                "group_id": open_group_id,
                "tier": tier,
                "period_id": period_id,
                "mode": mode.key,
                "member_uids": members,
                "member_count": len(members),
            },
            merge=True,
        )
        # Once a group is full the desk has to point somewhere else, or the
        # next joiner reads a full group and creates a new one anyway -- this
        # just saves them the wasted read.
        tx.set(
            dk_path,
            {
                "tier": tier,
                "open_group_id": None if len(members) >= mode.group_capacity else open_group_id,
            },
            merge=True,
        )
        tx.set(
            entry_path(period_id, open_group_id, uid, mode),
            blank_entry(uid, display_name, tier, open_group_id, now),
            merge=True,
        )
        tx.set(
            p_path,
            {"tier": tier, "uids": firestore.ArrayUnion([uid] + ([] if pool_exists else bot_ids))},
            merge=True,
        )
        tx.set(user_path, enter_fields(period_id, open_group_id, mode), merge=True)
        return open_group_id, False

    group_id, _ = await client.run_transaction(_join)
    return group_id


async def ensure_settled_through(client, current_period: str, mode: Mode = DAILY) -> list[dict]:
    """Settles any still-open period in this format's lookback window.

    This is the primary trigger: whoever shows up first pays for it. It
    settles the WHOLE period, not just the caller's group, so one returning
    bottom-tier player also resolves the tiers above them.

    Failures are swallowed on purpose -- this runs at the top of a
    player-facing screen, and yesterday's malformed entry must not 500 today's
    standings. `settle_error` on the period document is what makes that
    visible instead of silent.
    """
    results = []
    for period_id in previous_period_ids(current_period, mode.settle_lookback_periods, mode):
        try:
            outcome = await settle_period(client, period_id, mode=mode)
        except Exception as exc:
            results.append({"period_id": period_id, "status": "error", "errors": [str(exc)]})
            continue
        if outcome["status"] not in ("no-such-period", "already"):
            results.append(outcome)
    return results


# -- global table -------------------------------------------------------------
#
# One table for everyone (WEEKEND). Reading every entry on every screen load
# would cost N reads per view, so the ranked table is stored as a snapshot --
# chunk docs of STANDINGS_CHUNK rows plus a meta doc with each uid's position --
# rebuilt from the entries at most every STANDINGS_REFRESH_SECONDS. Settlement
# walks the final snapshot one member per transaction, podium first.


SETTLE_GRACE_SECONDS = 120


def _iso(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def snapshot_rows(entries: list[dict], mode: Mode) -> list[dict]:
    """The whole table, ranked and decorated by the same rules settlement uses."""
    rows = apply_rules(rank_rows(entries), mode.top_tier, group_size=len(entries), mode=mode)
    return [_row_summary(r) for r in rows]


def page_slice(chunk_rows: list[dict], page: int, page_size: int, chunk_size: int) -> list[dict]:
    """Page `page` (0-based) out of the chunk that holds it."""
    start = (page * page_size) % chunk_size
    return chunk_rows[start:start + page_size]


def page_of(position: int, page_size: int) -> int:
    return max(0, (position - 1) // page_size)


async def join_global(client, uid: str, display_name: str, period_id: str, now: datetime, mode: Mode) -> str:
    """join_period for a global table. Touches no shared doc it READS, so a
    Friday-18:00 rush doesn't serialise on one group document: the pool is an
    idempotent ArrayUnion (bots included every time, no read needed) and the
    period doc is a blind merge. A global table is everyone's, so every
    tier's stored bots go in -- each bot carries its own squad."""
    from firebase_admin import firestore  # local: keeps the pure half import-free

    user_path = f"users/{uid}"
    bot_paths = [bot_pool_path(tier) for tier in sorted(config.TOURNAMENT_TIERS)]

    def _join(tx):
        docs = tx.get_all([user_path] + bot_paths)
        if is_entered(docs[user_path], period_id, mode):
            return
        bot_ids = [b for p in bot_paths for b in ((docs[p] or {}).get("uids") or [])]
        tx.set(
            entry_path(period_id, GLOBAL_GROUP, uid, mode),
            blank_entry(uid, display_name, mode.top_tier, GLOBAL_GROUP, now),
            merge=True,
        )
        tx.set(
            pool_path(period_id, mode.top_tier, mode),
            {"tier": mode.top_tier, "uids": firestore.ArrayUnion([uid] + bot_ids)},
            merge=True,
        )
        tx.set(period_path(period_id, mode), {"period_id": period_id, "mode": mode.key}, merge=True)
        tx.set(user_path, enter_fields(period_id, GLOBAL_GROUP, mode), merge=True)

    await client.run_transaction(_join)
    return GLOBAL_GROUP


async def rebuild_standings(client, period_id: str, now: datetime, mode: Mode, final: bool = False) -> dict:
    """Reads every entry once and rewrites the snapshot. Returns the meta doc.
    shortcut: `positions` is one map in one doc (~20k entrants before the 1 MiB
    limit); shard it by uid hash if the league outgrows that."""
    entries = await client.list_collection(entries_path(period_id, GLOBAL_GROUP, mode))
    rows = snapshot_rows(entries, mode)
    size = config.WEEKEND_LEAGUE_STANDINGS_CHUNK
    for chunk in range(0, max(1, -(-len(rows) // size))):
        await client.set_document(
            standings_chunk_path(period_id, chunk, mode),
            {"rows": rows[chunk * size:(chunk + 1) * size]},
            merge=False,
        )
    meta = {
        "built_at": now.isoformat(),
        "total": len(rows),
        "positions": {r["uid"]: r["position"] for r in rows},
        "final": final,
        "claimed_at": None,
    }
    await client.set_document(standings_meta_path(period_id, mode), meta, merge=False)
    return meta


async def ensure_fresh_standings(client, period_id: str, now: datetime, mode: Mode) -> dict:
    """The meta doc, rebuilt first if it is older than the refresh interval.
    A transaction claims the rebuild so one request does it and the rest serve
    the slightly stale snapshot."""
    refresh = timedelta(seconds=config.WEEKEND_LEAGUE_STANDINGS_REFRESH_SECONDS)
    m_path = standings_meta_path(period_id, mode)

    def _fresh(meta) -> bool:
        built = _iso((meta or {}).get("built_at"))
        claimed = _iso((meta or {}).get("claimed_at"))
        return bool(
            (meta or {}).get("final")
            or (built and now - built < refresh)
            or (claimed and now - claimed < timedelta(seconds=60))
        )

    meta = await client.get_document(m_path)
    if _fresh(meta):
        return meta

    def _claim(tx):
        current = tx.get(m_path)
        if _fresh(current):
            return current, False
        tx.set(m_path, {"claimed_at": now.isoformat()}, merge=True)
        return current, True

    meta, mine = await client.run_transaction(_claim)
    if mine:
        return await rebuild_standings(client, period_id, now, mode)
    return meta or {"built_at": None, "total": 0, "positions": {}, "final": False}


async def standings_page(client, period_id: str, page: int, mode: Mode, page_size: int) -> list[dict]:
    chunk_size = config.WEEKEND_LEAGUE_STANDINGS_CHUNK
    chunk = (page * page_size) // chunk_size
    doc = await client.get_document(standings_chunk_path(period_id, chunk, mode))
    return page_slice(list((doc or {}).get("rows") or []), page, page_size, chunk_size)


async def settle_member(client, period_id: str, row: dict, mode: Mode) -> bool:
    """Settles one row in its own transaction; False if it was already done.
    The entry's `settled` flag is the pay-once token."""
    from firebase_admin import firestore  # local: keeps the pure half import-free

    uid = row["uid"]
    e_path = entry_path(period_id, GLOBAL_GROUP, uid, mode)
    user_path = f"users/{uid}"

    def _settle(tx):
        docs = tx.get_all([e_path, user_path])
        entry, user_doc = docs[e_path], docs[user_path]
        if entry is None or entry.get("settled") or user_doc is None:
            return False
        if last_period(user_doc, mode) >= period_id:
            return False
        user_fields, entry_fields = member_settlement(row, period_id, GLOBAL_GROUP, mode, firestore.Increment)
        tx.set(user_path, user_fields, merge=True)
        tx.set(e_path, entry_fields, merge=True)
        return True

    return await client.run_transaction(_settle)


async def settle_global_period(client, period_id: str, max_members: int, mode: Mode) -> dict:
    """Settles up to `max_members` rows of a finished global table, podium first.

    A period-doc claim (60 s) means one request works at a time while the rest
    return at once -- this runs inside /account/bootstrap, so a crowd opening
    the app at 18:00 must not all settle the same rows. The cursor only moves
    over a contiguous run of successes, so a failed member is retried.
    """
    now = datetime.now(timezone.utc)
    # A match claimed at 17:59:59 lands its result a few seconds later.
    if now < period_end(period_id, mode) + timedelta(seconds=SETTLE_GRACE_SECONDS):
        return {"period_id": period_id, "settled": 0, "status": "grace"}
    p_path = period_path(period_id, mode)

    def _claim(tx):
        doc = tx.get(p_path) or {}
        if doc.get("status") == "settled":
            return None
        until = _iso(doc.get("settling_until"))
        if until and until > now:
            return None
        tx.set(p_path, {"settling_until": (now + timedelta(seconds=60)).isoformat()}, merge=True)
        return doc

    period_doc = await client.run_transaction(_claim)
    if period_doc is None:
        return {"period_id": period_id, "settled": 0, "status": "busy"}

    meta = await client.get_document(standings_meta_path(period_id, mode))
    if not (meta or {}).get("final"):
        meta = await rebuild_standings(client, period_id, now, mode, final=True)
    total = int(meta.get("total", 0))
    cursor = int(period_doc.get("settle_cursor", 0))
    end = min(total, cursor + max_members)

    size = config.WEEKEND_LEAGUE_STANDINGS_CHUNK
    rows = []
    for chunk in range(cursor // size, -(-end // size)):
        doc = await client.get_document(standings_chunk_path(period_id, chunk, mode))
        rows.extend((doc or {}).get("rows") or [])
    rows = rows[cursor - (cursor // size) * size:][:end - cursor]

    settled, errors, advanced = 0, [], cursor
    for i in range(0, len(rows), 20):
        batch = rows[i:i + 20]
        results = await asyncio.gather(*(settle_member(client, period_id, r, mode) for r in batch), return_exceptions=True)
        for row, result in zip(batch, results):
            if isinstance(result, Exception):
                errors.append(f"{row['uid']}: {result}")
            else:
                settled += bool(result)
                if not errors:
                    advanced += 1

    complete = advanced >= total and not errors
    fields = {
        "settle_cursor": advanced,
        "settling_until": None,
        "settle_attempts": int(period_doc.get("settle_attempts", 0)) + 1,
        "settle_error": " | ".join(errors)[:1000] if errors else None,
    }
    if complete:
        fields["status"] = "settled"
    await client.set_document(p_path, fields, merge=True)
    return {
        "period_id": period_id,
        "settled": settled,
        "remaining": max(0, total - advanced),
        "errors": errors,
        "status": "settled" if complete else "partial",
    }
