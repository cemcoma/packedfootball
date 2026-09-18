"""Daily tournaments: day keys, standings, promotion, settlement.

Layered so the rules are testable without Firestore:

    rank_rows(entries)          pure -- ordering and positions
    apply_rules(rows, ...)      pure -- promote / stay / relegate, and rewards
    settle_group(...)           the transaction that writes what those decide

Everything above the line is a function of its arguments and nothing else,
which matters twice over: a transaction body may be RETRIED, so it has to
produce the same table every time, and the standings screen calls the same
apply_rules to show "what happens if the day ended now" -- one implementation
is what stops the projection and the payout from ever disagreeing.

Addressing is by PATH throughout. There is not one where() clause in this
feature, so it needs no composite index -- which matters, because this
project has none and no firestore.indexes.json to put one in.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config

# -- day keys -----------------------------------------------------------------


def day_id_for(now: datetime) -> str:
    """The UTC calendar date a moment belongs to, as "YYYY-MM-DD".

    A single global cutoff is the only version that needs no per-player
    timezone state. TOURNAMENT_DAY_OFFSET_HOURS shifts where the boundary
    falls without changing anything else, so "the day starts at 04:00 UTC" is
    a config edit rather than a refactor.
    """
    shifted = now.astimezone(timezone.utc) - timedelta(hours=config.TOURNAMENT_DAY_OFFSET_HOURS)
    return shifted.strftime("%Y-%m-%d")


def day_start(day_id: str) -> datetime:
    naive = datetime.strptime(day_id, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return naive + timedelta(hours=config.TOURNAMENT_DAY_OFFSET_HOURS)


def day_end(day_id: str) -> datetime:
    return day_start(day_id) + timedelta(days=1)


def seconds_remaining(day_id: str, now: datetime) -> int:
    return max(0, int((day_end(day_id) - now).total_seconds()))


def previous_day_ids(day_id: str, count: int) -> list[str]:
    """The `count` day ids before `day_id`, oldest first -- what lazy
    settlement walks. Computed, never queried."""
    start = day_start(day_id)
    return [day_id_for(start - timedelta(days=n)) for n in range(count, 0, -1)]


def joining_is_closed(day_id: str, now: datetime) -> bool:
    """No joining in the last hour.

    Joining at 23:30 could only ever end in relegation -- there is neither
    time nor energy left to play a meaningful number of matches -- so the join
    is refused rather than sold as an opportunity. Players who joined EARLIER
    are unaffected and can play to the last second.
    """
    return seconds_remaining(day_id, now) < config.TOURNAMENT_JOIN_CUTOFF_SECONDS


def group_id_for(tier: int, index: int) -> str:
    """Zero-padded so lexical order equals numeric order, which is what makes
    a plain list_collection over a day's groups come back in a sane sequence."""
    return f"t{tier}-g{index:04d}"


# -- paths --------------------------------------------------------------------


def day_path(day_id: str) -> str:
    return f"tournaments/{day_id}"


def desk_path(day_id: str, tier: int) -> str:
    return f"tournaments/{day_id}/desks/{tier}"


def groups_path(day_id: str) -> str:
    return f"tournaments/{day_id}/groups"


def group_path(day_id: str, group_id: str) -> str:
    return f"tournaments/{day_id}/groups/{group_id}"


def entries_path(day_id: str, group_id: str) -> str:
    return f"tournaments/{day_id}/groups/{group_id}/entries"


def entry_path(day_id: str, group_id: str, uid: str) -> str:
    return f"tournaments/{day_id}/groups/{group_id}/entries/{uid}"


def pool_path(day_id: str, tier: int) -> str:
    return f"tournaments/{day_id}/pools/{tier}"


def bot_pool_path(tier: int) -> str:
    """The stored bots for a tier, as one list of ids -- written by
    scripts/seed_bots.py, read when a day's pool is first created so the
    pool has opponents in it before anyone else has joined."""
    return f"bot_pools/{tier}"


# -- reading a profile --------------------------------------------------------


def tier_of(profile_doc: dict | None) -> int:
    """A player's tier, clamped into the range that actually exists.

    Absent means the bottom tier, so every account that predates this feature
    starts at the bottom with no migration script. A stored value outside the
    range (a tier that was removed, say) clamps rather than crashing.
    """
    raw = (profile_doc or {}).get("daily_tournament_tier")
    tier = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else config.TOURNAMENT_DEFAULT_TIER
    return max(config.TOURNAMENT_TOP_TIER, min(config.TOURNAMENT_BOTTOM_TIER, tier))


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
        "full_day_claimed": False,
    }


def result_fields(entry: dict, my_score: int, opp_score: int, game_id: str) -> dict:
    """The entry fields after one match. A plain merge -- no transaction,
    because the match slot was already claimed before the simulation ran."""
    if my_score > opp_score:
        outcome, points = "win", config.TOURNAMENT_POINTS["win"]
    elif my_score == opp_score:
        outcome, points = "draw", config.TOURNAMENT_POINTS["draw"]
    else:
        outcome, points = "loss", config.TOURNAMENT_POINTS["loss"]

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


def _verdict(row: dict, tier: int, group_size: int) -> str:
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
    can_promote = group_size >= config.TOURNAMENT_MIN_GROUP_FOR_PROMOTION

    if group_size >= config.TOURNAMENT_GROUP_CAPACITY:
        if position in config.TOURNAMENT_PROMOTE_POSITIONS:
            if can_promote and points >= config.TOURNAMENT_PROMOTION_FLOOR:
                return "promote"
            return "stay"
        if position in config.TOURNAMENT_RELEGATE_POSITIONS:
            return "relegate"
        return "stay"

    if can_promote and points >= config.TOURNAMENT_PROMOTION_FLOOR:
        return "promote"
    if points < config.TOURNAMENT_RELEGATION_FLOOR:
        return "relegate"
    return "stay"


def rewards_for(tier: int, row: dict, verdict: str) -> dict:
    """What a finishing position pays: the tier's table row for that
    position, whatever the verdict. Promotion is a separate question from
    prize money -- 2nd on 15 points still finished 2nd.

    The one gate: playing nothing pays nothing. Medals for tapping Join is
    an exploit, not a rule anyone wrote down. (`verdict` is kept in the
    signature so apply_rules and the tests need no change if a verdict-
    dependent reward ever comes back.)
    """
    if row.get("played", 0) < config.TOURNAMENT_REWARD_MIN_MATCHES:
        return {}
    return dict(config.TOURNAMENT_REWARDS.get(tier, {}).get(row["position"], {}))


# -- the full-day reward --------------------------------------------------------


def full_day_state(entry: dict | None) -> dict:
    """Where a player stands with the play-every-match reward, for the
    screen's progress bar and Claim button.

        played     matches played so far
        required   TOURNAMENT_MATCHES_PER_DAY
        reward     the payout table (TOURNAMENT_FULL_DAY_REWARD)
        claimable  played every match and not claimed yet
        claimed    already paid

    Pure, so the /today payload, the results payload and claim_full_day's
    transaction all agree on what "claimable" means.
    """
    played = int((entry or {}).get("played", 0))
    claimed = bool((entry or {}).get("full_day_claimed", False))
    complete = played >= config.TOURNAMENT_MATCHES_PER_DAY
    return {
        "played": played,
        "required": config.TOURNAMENT_MATCHES_PER_DAY,
        "reward": dict(config.TOURNAMENT_FULL_DAY_REWARD),
        "claimable": complete and not claimed,
        "claimed": claimed,
    }


class NotClaimable(Exception):
    """The reward can't be paid: not earned yet, already claimed, or no such
    entry. `.reason` is a short code the endpoint turns into a status."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


async def claim_full_day(client, uid: str, day_id: str, group_id: str) -> dict:
    """Pays the full-day reward for one entry, exactly once.

    One transaction reads the entry and the profile, checks full_day_state,
    then flips full_day_claimed and applies the reward with Increment --
    the same read-nothing-write-increment shape settlement uses, so a pack
    purchase committing at the same moment can't be clobbered. The flag and
    the payout land in the same commit: either both happened or neither.

    Returns {"rewards": {...}, "balances": {currency: new amount}} -- the
    balances are computed from the profile this transaction read plus the
    reward, which is exact under the transaction's own lock.
    """
    from firebase_admin import firestore  # local: keeps the pure half import-free

    e_path = entry_path(day_id, group_id, uid)
    user_path = f"users/{uid}"

    def _claim(tx):
        docs = tx.get_all([e_path, user_path])
        entry, user_doc = docs[e_path], docs[user_path]
        if entry is None or entry.get("uid", uid) != uid:
            raise NotClaimable("no_entry")
        state = full_day_state(entry)
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
        tx.set(e_path, {"full_day_claimed": True}, merge=True)
        return {"rewards": rewards, "balances": balances}

    return await client.run_transaction(_claim)


def apply_rules(rows: list[dict], tier: int, group_size: int | None = None) -> list[dict]:
    """Decorates ranked rows with verdict, destination tier and rewards.

    Stores the rule's VERDICT and the clamped EFFECT separately. The top tier
    cannot promote and the bottom cannot relegate, but recording that as a
    flat "stay" would lose the distinction between "held the crown" and
    "finished mid-table" -- and, more importantly, the reward gate keys off
    the verdict.
    """
    size = len(rows) if group_size is None else group_size
    out = []
    for row in rows:
        decorated = dict(row)
        verdict = _verdict(row, tier, size)
        delta = {"promote": -1, "relegate": 1}.get(verdict, 0)
        to_tier = max(
            config.TOURNAMENT_TOP_TIER,
            min(config.TOURNAMENT_BOTTOM_TIER, tier + delta),
        )
        decorated["outcome"] = verdict
        decorated["from_tier"] = tier
        decorated["to_tier"] = to_tier
        # True when the rule said move but the edge refused -- the results
        # screen says "you hold the top tier" rather than a confusing "stay".
        decorated["tier_clamped"] = verdict != "stay" and to_tier == tier
        decorated["rewards"] = rewards_for(tier, decorated, verdict)
        out.append(decorated)
    return out


def settlement_mode(group_size: int) -> str:
    return "positional" if group_size >= config.TOURNAMENT_GROUP_CAPACITY else "threshold"


# -- settlement (writes) ------------------------------------------------------


async def settle_group(client, day_id: str, group_id: str) -> str:
    """Settles one group in exactly ONE transaction. Returns what happened.

    Thirteen reads and thirteen writes for a full group

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

    g_path = group_path(day_id, group_id)

    def _settle(tx):
        group = tx.get(g_path)
        if group is None:
            return "missing"
        if (group.get("settlement") or {}).get("status") == "settled":
            return "already"

        member_uids = list(group.get("member_uids") or [])
        tier = int(group.get("tier", config.TOURNAMENT_DEFAULT_TIER))
        if not member_uids:
            tx.set(g_path, {"settlement": {"status": "settled", "mode": "empty", "rows": []}}, merge=True)
            return "empty"

        entry_paths = [entry_path(day_id, group_id, u) for u in member_uids]
        user_paths = [f"users/{u}" for u in member_uids]
        docs = tx.get_all(entry_paths + user_paths)

        entries = [docs[p] for p in entry_paths if docs[p] is not None]
        rows = apply_rules(rank_rows(entries), tier, group_size=len(member_uids))

        for row in rows:
            uid = row["uid"]
            user_doc = docs[f"users/{uid}"]
            if user_doc is None:
                continue
            # Belt and braces next to the group-level token: a user who has
            # already been moved for this day is never moved twice, even if
            # they somehow appear in two groups.
            if (user_doc.get("tournament_last_settled_day") or "") >= day_id:
                continue

            rewards = row.get("rewards") or {}
            fields = {
                "daily_tournament_tier": row["to_tier"],
                "tournament_last_settled_day": day_id,
                "tournament_last_group_id": group_id,
                "tournament_day_id": None,
                "tournament_group_id": None,
            }
            for currency, amount in rewards.items():
                if amount:
                    fields[currency] = firestore.Increment(amount)
            tx.set(f"users/{uid}", fields, merge=True)

            tx.set(
                entry_path(day_id, group_id, uid),
                {
                    "settled": True,
                    "final_position": row["position"],
                    "outcome": row["outcome"],
                    "to_tier": row["to_tier"],
                    "rewards": rewards,
                    "is_shown": False,
                },
                merge=True,
            )


        tx.set(
            g_path,
            {
                "settlement": {
                    "status": "settled",
                    "mode": settlement_mode(len(member_uids)),
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


async def settle_day(client, day_id: str, max_groups: int | None = None) -> dict:
    """Settles up to `max_groups` unsettled groups of a day.

    Groups settle INDEPENDENTLY and errors are caught per group, so a day left
    half-settled is the normal case rather than a failure -- the next trigger
    picks up where this one stopped. The day is only marked settled once a
    full pass finds nothing left to do.

    Capped because this runs inside a player's own request and Cloud Run is
    at --max-instances 3; an unbounded sweep is a latency bomb. Capping is
    free precisely because settlement is idempotent and incremental.
    """
    day_doc = await client.get_document(day_path(day_id))
    if day_doc is None:
        return {"day_id": day_id, "settled": 0, "status": "no-such-day"}
    if day_doc.get("status") == "settled":
        return {"day_id": day_id, "settled": 0, "status": "already"}

    limit = config.TOURNAMENT_MAX_GROUPS_PER_REQUEST if max_groups is None else max_groups
    groups = await client.list_collection(groups_path(day_id))
    pending = [g for g in groups if (g.get("settlement") or {}).get("status") != "settled"]

    settled, errors = 0, []
    for group in pending[:limit]:
        try:
            outcome = await settle_group(client, day_id, group["id"])
            if outcome in ("settled", "empty"):
                settled += 1
        except Exception as exc:  # noqa: BLE001 -- see the module note on reporting
            errors.append(f"{group['id']}: {exc}")

    remaining = len(pending) - settled - len(errors)
    complete = remaining <= 0 and not errors
    fields = {"settle_attempts": (day_doc.get("settle_attempts", 0) + 1)}
    if errors:
        # There is no error reporting in this project, so the day document is
        # the only place a stuck day becomes visible. Worth the write.
        fields["settle_error"] = " | ".join(errors)[:1000]
    if complete:
        fields["status"] = "settled"
        fields["settle_error"] = None
    await client.set_document(day_path(day_id), fields, merge=True)

    return {
        "day_id": day_id,
        "settled": settled,
        "remaining": max(0, remaining),
        "errors": errors,
        "status": "settled" if complete else "partial",
    }


async def join_today(client, uid: str, display_name: str, tier: int, day_id: str, now: datetime) -> str:
    """Puts a player into a group for today and returns its group id.

    Idempotent: an already-joined player gets their existing group back rather
    than a second entry.

    ONE transaction covers the desk, the group and the entry, which is what
    stops two players racing for the last slot in a group of six. The desk
    document answers "where does the next joiner go" as a path read, so no
    query and no index is needed to find an open group.

    The matchmaking pool is written with ArrayUnion -- a server-side transform
    in the same family as the Increment used for pack counters -- so
    concurrent joins cannot clobber each other's entries.

    The first join of a day in a tier also seeds the pool with that tier's
    stored bots (bot_pools/{tier}, see scripts/seed_bots.py): they're in
    the same ArrayUnion as the joiner, so the pool never exists without
    them and a second joiner racing the first can't create it empty. Bots
    are opponents only -- they hold no seat in any group and never appear
    in a table; the pick is as random over the whole pool as it is over
    real players, which is the point.
    """
    from firebase_admin import firestore  # local: keeps the pure half import-free

    d_path = day_path(day_id)
    dk_path = desk_path(day_id, tier)
    p_path = pool_path(day_id, tier)
    user_path = f"users/{uid}"
    bp_path = bot_pool_path(tier)

    def _join(tx):
        docs = tx.get_all([d_path, dk_path, user_path, p_path, bp_path])
        day_doc, desk, user_doc = docs[d_path], docs[dk_path], docs[user_path]
        pool_exists = docs[p_path] is not None
        bot_ids = list((docs[bp_path] or {}).get("uids") or [])

        already = (user_doc or {}).get("tournament_day_id") == day_id
        existing_group = (user_doc or {}).get("tournament_group_id")
        if already and existing_group:
            return existing_group, True

        open_group_id = (desk or {}).get("open_group_id")
        group = tx.get(group_path(day_id, open_group_id)) if open_group_id else None

        members = list((group or {}).get("member_uids") or [])
        needs_new = group is None or len(members) >= config.TOURNAMENT_GROUP_CAPACITY
        if needs_new:
            next_index = int(((day_doc or {}).get("next_group_index") or {}).get(str(tier), 0))
            open_group_id = group_id_for(tier, next_index)
            members = []
            tx.set(
                d_path,
                {
                    "day_id": day_id,
                    "status": (day_doc or {}).get("status", "open"),
                    "next_group_index": {
                        **(((day_doc or {}).get("next_group_index")) or {}),
                        str(tier): next_index + 1,
                    },
                },
                merge=True,
            )

        members.append(uid)
        tx.set(
            group_path(day_id, open_group_id),
            {
                "group_id": open_group_id,
                "tier": tier,
                "day_id": day_id,
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
                "open_group_id": None if len(members) >= config.TOURNAMENT_GROUP_CAPACITY else open_group_id,
            },
            merge=True,
        )
        tx.set(
            entry_path(day_id, open_group_id, uid),
            blank_entry(uid, display_name, tier, open_group_id, now),
            merge=True,
        )
        tx.set(
            p_path,
            {"tier": tier, "uids": firestore.ArrayUnion([uid] + ([] if pool_exists else bot_ids))},
            merge=True,
        )
        tx.set(
            user_path,
            {"tournament_day_id": day_id, "tournament_group_id": open_group_id},
            merge=True,
        )
        return open_group_id, False

    group_id, _ = await client.run_transaction(_join)
    return group_id


async def ensure_settled_through(client, today: str) -> list[dict]:
    """Settles any still-open day in the lookback window.

    This is the primary trigger: whoever shows up first pays for it. It
    settles the WHOLE day, not just the caller's group, so one returning
    bottom-tier player also resolves the tiers above them.

    Failures are swallowed on purpose -- this runs at the top of a
    player-facing screen, and yesterday's malformed entry must not 500 today's
    standings. `settle_error` on the day document is what makes that visible
    instead of silent.
    """
    results = []
    for day_id in previous_day_ids(today, config.TOURNAMENT_SETTLE_LOOKBACK_DAYS):
        try:
            outcome = await settle_day(client, day_id)
        except Exception as exc:
            results.append({"day_id": day_id, "status": "error", "errors": [str(exc)]})
            continue
        if outcome["status"] not in ("no-such-day", "already"):
            results.append(outcome)
    return results
