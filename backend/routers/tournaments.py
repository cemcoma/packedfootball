"""Tournaments: joining, playing, standings, settlement.

Two formats, one set of handlers. The daily league lives at /tournament/*
and the weekly league at /tournament/weekly/*; each route is a two-line
wrapper that names its Mode and calls the shared implementation below, so
the only thing that differs between a day and a week is the record in
services/tournament.py that the handler was handed.

Thin on purpose. The period arithmetic, the ranking and the promotion rules
live in services/tournament.py, where they are pure and unit-tested; the
match itself reuses services/match.py unchanged. What's left here is the
HTTP shape and the order things happen in.

WIRE NAMES: the payload carries period-neutral keys (`period_id`,
`full_period`) AND the daily league's original `day_id` / `full_day`, with
the same values, for BOTH formats. That is what lets the already-shipped
Godot tournament screen render the weekly league without an edit; the
`day_id` alias on a weekly payload is a compatibility shim, not a claim
about what a week is.
"""

from __future__ import annotations

import hmac
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from firebase_admin import firestore
from pydantic import BaseModel

import config
from deps import admin_client, game_state_for, verify_id_token
from engine import ENGINE_VERSION, REPLAY_FORMAT_VERSION
from services import energy as energy_service
from services import tournament as tournament_service
from services.tournament import DAILY, WEEKLY, Mode
from services.match import (
    persist_player_stats,
    pick_opponent_from_candidates,
    run_match,
    teams_snapshot,
    validate_formation_positions,
)

router = APIRouter(tags=["tournaments"])


async def verify_tournament_admin(authorization: str = Header(default="")) -> None:
    """Shared-secret auth for the settle endpoint.

    A scheduled invoker has no Firebase ID token, so verify_id_token cannot be
    used. This is the same arrangement the RevenueCat webhook already uses:
    a constant-time compare against a configured secret, and FAILING CLOSED
    when the secret is unset -- an empty configured value must never make
    every request match by both sides being empty.
    """
    if not config.TOURNAMENT_ADMIN_SECRET or not hmac.compare_digest(
        authorization, config.TOURNAMENT_ADMIN_SECRET
    ):
        raise HTTPException(401, "Invalid tournament admin authorization")


async def _period_payload(client, uid: str, profile_doc: dict | None, mode: Mode) -> dict:
    """Everything a tournament screen needs, in one response.

    One call rather than four, because the screen is useless until it has all
    of it and four round trips on a phone is four chances to show a half-built
    page.
    """
    now = energy_service.now_utc()
    period_id = tournament_service.period_id_for(now, mode)
    tier = tournament_service.tier_of(profile_doc, mode)

    joined = tournament_service.is_entered(profile_doc, period_id, mode)
    group_id = tournament_service.entered_group(profile_doc, mode) if joined else None

    standings, played, group_size = [], 0, 0
    my_entry = None
    if group_id:
        entries = await client.list_collection(
            tournament_service.entries_path(period_id, group_id, mode)
        )
        group_doc = await client.get_document(
            tournament_service.group_path(period_id, group_id, mode)
        )
        group_size = len((group_doc or {}).get("member_uids") or entries)
        my_entry = next((e for e in entries if e.get("uid") == uid), None)
        # "What happens if the period ended now", from the SAME apply_rules
        # settlement calls -- one implementation is what stops the projection
        # and the payout from ever disagreeing.
        rows = tournament_service.apply_rules(
            tournament_service.rank_rows(entries), tier, group_size=group_size, mode=mode
        )
        for row in rows:
            if row["uid"] == uid:
                played = row.get("played", 0)
            standings.append(
                {
                    "uid": row["uid"],
                    "display_name": row.get("display_name", ""),
                    "position": row["position"],
                    "points": row.get("points", 0),
                    "played": row.get("played", 0),
                    "wins": row.get("wins", 0),
                    "draws": row.get("draws", 0),
                    "losses": row.get("losses", 0),
                    "goals_for": row.get("goals_for", 0),
                    "goals_against": row.get("goals_against", 0),
                    "goal_diff": row.get("goal_diff", 0),
                    "is_me": row["uid"] == uid,
                    "projected_outcome": row["outcome"],
                }
            )

    full_period = tournament_service.full_period_state(my_entry, mode) if joined else None
    current_energy, anchor = energy_service.from_profile(profile_doc, now)
    return {
        "mode": mode.key,
        "period_id": period_id,
        "period_days": mode.period_days,
        # Compatibility alias -- see the module docstring.
        "day_id": period_id,
        "seconds_remaining": tournament_service.seconds_remaining(period_id, now, mode),
        "tier": tier,
        "tier_name": tournament_service.tier_name(tier, mode),
        # The standings' projected_outcome is the rule's verdict BEFORE the
        # tier edges clamp it (see services.tournament._verdict); these let
        # the client word the top tier's "promote" and the bottom tier's
        # "relegate" the way the result banner already does.
        "is_top_tier": tier == mode.top_tier,
        "is_bottom_tier": tier == mode.bottom_tier,
        "joined": joined,
        "join_closed": tournament_service.joining_is_closed(period_id, now, mode),
        "join_cutoff_seconds": mode.join_cutoff_seconds,
        "group_id": group_id,
        "group_size": group_size,
        "group_capacity": mode.group_capacity,
        "settlement_mode": tournament_service.settlement_mode(group_size, mode),
        "matches_played": played,
        "matches_max": mode.matches_per_period,
        "energy": energy_service.describe(current_energy, anchor, now),
        "standings": standings,
        # The play-every-match reward: progress for the bar, and whether
        # the Claim button is live. Claiming goes through POST /claim with
        # type "tournament_full_day" / "tournament_full_week"
        # (routers/claims.py).
        "full_period": full_period,
        "full_day": full_period,
        "claim_type": _CLAIM_TYPES[mode.key],
        "rules": {
            "points_win": mode.points["win"],
            "points_draw": mode.points["draw"],
            "promotion_floor": mode.promotion_floor,
            "relegation_floor": mode.relegation_floor,
            "promote_positions": list(mode.promote_positions),
            "relegate_positions": list(mode.relegate_positions),
            "min_group_for_promotion": mode.min_group_for_promotion,
        },
        "rewards": [
            {"position": pos, **payout}
            for pos, payout in sorted(tournament_service.rewards_table(tier, mode).items())
        ],
    }


# Which POST /claim type pays this format's play-everything reward. Kept
# beside the payload that advertises it so the two can't drift.
_CLAIM_TYPES = {DAILY.key: "tournament_full_day", WEEKLY.key: "tournament_full_week"}


async def _today(uid: str, mode: Mode) -> dict:
    """This period's tournament, settling anything overdue first.

    Settling here is what makes the whole feature work without a scheduler:
    the day a player comes back, their group is resolved before the screen is
    built, so the same response can carry the last period's result.
    """
    client = admin_client(uid)
    now = energy_service.now_utc()
    await tournament_service.ensure_settled_through(
        client, tournament_service.period_id_for(now, mode), mode
    )

    profile_doc = await client.get_document(f"users/{uid}")
    payload = await _period_payload(client, uid, profile_doc, mode)
    payload["pending_results"] = await _pending_results(
        client, uid, profile_doc, payload["period_id"], mode
    )
    return payload


async def _pending_results(
    client, uid: str, profile_doc: dict | None, current_period: str, mode: Mode
) -> dict | None:
    """The last period's row, if the player has one they haven't been shown.

    There is no notification system, and lazy settlement turns that into an
    advantage: by the time this runs, ensure_settled_through has just settled
    the group, so the result is available in the same breath as the request
    that triggered it.
    """
    last_period = tournament_service.last_period(profile_doc, mode)
    if not last_period or last_period >= current_period:
        return None
    group_id = tournament_service.last_group(profile_doc, mode)
    if not group_id:
        return None

    e_path = tournament_service.entry_path(last_period, group_id, uid, mode)
    entry = await client.get_document(e_path)
    if (entry or {}).get("is_shown"):
        return None

    group = await client.get_document(
        tournament_service.group_path(last_period, group_id, mode)
    )
    rows = ((group or {}).get("settlement") or {}).get("rows") or []
    mine = next((r for r in rows if r.get("uid") == uid), None)
    if mine is None:
        return None

    await client.set_document(e_path, {"is_shown": True}, merge=True)

    full_period = tournament_service.full_period_state(entry, mode)
    return {
        "mode": mode.key,
        "period_id": last_period,
        "day_id": last_period,
        "group_id": group_id,
        "me": mine,
        "rows": rows,
        "full_period": full_period,
        "full_day": full_period,
    }


async def _join(uid: str, mode: Mode) -> dict:
    """Joins this period's tournament in the caller's own tier.

    Refuses a roster that couldn't legally play, up front -- being told at
    match time that your lineup is invalid, after joining, is a worse place to
    find out.
    """
    client = admin_client(uid)
    now = energy_service.now_utc()
    period_id = tournament_service.period_id_for(now, mode)
    await tournament_service.ensure_settled_through(client, period_id, mode)

    state = game_state_for(uid)
    profile = await state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])
    if len(profile["roster"]) != 11:
        raise HTTPException(400, "Your roster must have exactly 11 players")
    validate_formation_positions(profile)

    profile_doc = await client.get_document(f"users/{uid}")
    already = tournament_service.is_entered(profile_doc, period_id, mode)
    if not already and tournament_service.joining_is_closed(period_id, now, mode):
        raise HTTPException(
            409,
            f"This {mode.label}'s tournament is closed to new entries -- it restarts in "
            f"{tournament_service.seconds_remaining(period_id, now, mode) // 60} minutes",
        )

    tier = tournament_service.tier_of(profile_doc, mode)
    await tournament_service.join_period(
        client, uid, profile["display_name"], tier, period_id, now, mode
    )

    profile_doc = await client.get_document(f"users/{uid}")
    payload = await _period_payload(client, uid, profile_doc, mode)
    payload["pending_results"] = None
    return payload


async def _match(uid: str, mode: Mode) -> dict:
    """Plays one tournament match.

    The energy AND the match slot are claimed in one transaction BEFORE the
    simulation runs. Enforcing the per-period cap only on write-back would
    mean the player has already spent a point and sat through a match that
    then gets rejected -- and two parallel requests could both pass a check
    that only looked at the stored count.
    """
    client = admin_client(uid)
    now = energy_service.now_utc()
    period_id = tournament_service.period_id_for(now, mode)
    await tournament_service.ensure_settled_through(client, period_id, mode)

    caller_state = game_state_for(uid)
    caller_profile = await caller_state.load_or_create_profile(
        default_roster=[], default_display_name=uid[:8]
    )
    if len(caller_profile["roster"]) != 11:
        raise HTTPException(400, "Your roster must have exactly 11 players")
    validate_formation_positions(caller_profile)

    profile_doc = await client.get_document(f"users/{uid}")
    if not tournament_service.is_entered(profile_doc, period_id, mode):
        raise HTTPException(409, f"Join this {mode.label}'s tournament first")
    group_id = tournament_service.entered_group(profile_doc, mode)
    tier = tournament_service.tier_of(profile_doc, mode)

    claimed = await _claim_slot(client, uid, period_id, group_id, now, mode)
    energy_after = claimed["energy"]

    pool = await client.get_document(tournament_service.pool_path(period_id, tier, mode))
    opponent_uid, opponent_profile = await pick_opponent_from_candidates(
        uid,
        list((pool or {}).get("uids") or []),
        max_attempts=mode.opponent_max_attempts,
        card_tier_rates=tournament_service.bot_card_rates(tier, mode),
    )
    is_bot = opponent_uid.startswith("bot_")
    seed = secrets.randbits(63)

    games_client = caller_state.client
    game_id = await games_client.add_document(
        "games",
        {
            "status": "in_progress",
            "mode": "tournament" if mode is DAILY else f"{mode.key}_tournament",
            "tournament": {
                "mode": mode.key,
                "period_id": period_id,
                "day_id": period_id,
                "group_id": group_id,
                "tier": tier,
            },
            "participants": [uid, opponent_uid],
            "initiator_uid": uid,
            "opponent_uid": opponent_uid,
            "opponent_is_bot": is_bot,
            "seed": seed,
            "engine_version": ENGINE_VERSION,
            "replay_format_version": REPLAY_FORMAT_VERSION,
            "teams": teams_snapshot(uid, caller_profile, opponent_uid, opponent_profile),
            "created_at": firestore.SERVER_TIMESTAMP,
            "finished_at": None,
            "score": None,
        },
    )

    result = run_match(caller_profile, opponent_profile, seed)
    my_score, opp_score = result["score"]

    await games_client.set_document(
        f"games/{game_id}",
        {"status": "finished", "finished_at": firestore.SERVER_TIMESTAMP, "score": result["score"]},
        merge=True,
    )
    await persist_player_stats(caller_state, caller_profile)

    # The slot was already claimed, so folding the result in is a plain merge.
    entry = await client.get_document(
        tournament_service.entry_path(period_id, group_id, uid, mode)
    )
    fields, points_earned, outcome = tournament_service.result_fields(
        entry or {}, my_score, opp_score, game_id, mode
    )
    await client.set_document(
        tournament_service.entry_path(period_id, group_id, uid, mode), fields, merge=True
    )

    credits_earned = mode.match_reward_credits[outcome]
    wins, losses, draws = caller_profile["wins"], caller_profile["losses"], caller_profile["draws"]
    wins += outcome == "win"
    draws += outcome == "draw"
    losses += outcome == "loss"
    await caller_state.record_match_result(wins, losses, draws)
    new_credits = caller_profile["credits"] + credits_earned
    await caller_state.set_credits(new_credits)

    profile_doc = await client.get_document(f"users/{uid}")
    payload = await _period_payload(client, uid, profile_doc, mode)
    position = next((s["position"] for s in payload["standings"] if s["is_me"]), None)

    return {
        "seed": seed,
        "engine_version": ENGINE_VERSION,
        "replay_format_version": REPLAY_FORMAT_VERSION,
        "score": result["score"],
        "opponent_display_name": opponent_profile["display_name"],
        "opponent_is_bot": is_bot,
        "opponent_uid": "" if is_bot else opponent_uid,
        "opponent_record": {
            "wins": opponent_profile.get("wins", 0),
            "draws": opponent_profile.get("draws", 0),
            "losses": opponent_profile.get("losses", 0),
        },
        "credits_earned": credits_earned,
        "credits_remaining": new_credits,
        "energy": energy_after,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "game_id": game_id,
        "replay": result["replay"],
        "roster": result["roster"],
        "added_time": result["added_time"],
        "player_match_stats": result["player_match_stats"],
        "kits": result["kits"],
        "formations": result["formations"],
        # Extra block on top of the /match/quick shape. MatchSession reads
        # only the keys it knows and ignores the rest, so playback and the
        # result screen work with no autoload change.
        "tournament": {
            "mode": mode.key,
            "period_id": period_id,
            "day_id": period_id,
            "group_id": group_id,
            "tier": tier,
            "points_earned": points_earned,
            "points_total": fields["points"],
            "played": claimed["played"],
            "matches_max": mode.matches_per_period,
            "position": position,
        },
    }


async def _claim_slot(client, uid: str, period_id: str, group_id: str, now, mode: Mode) -> dict:
    """Takes one energy and one of the period's match slots, atomically.

    Both live on documents this transaction reads anyway, so claiming them
    together costs nothing extra and closes the race that claiming them
    separately would open.
    """
    user_path = f"users/{uid}"
    e_path = tournament_service.entry_path(period_id, group_id, uid, mode)

    def _claim(tx):
        docs = tx.get_all([user_path, e_path])
        user_doc, entry = docs[user_path], docs[e_path]
        if entry is None:
            raise HTTPException(409, f"You have no entry in this {mode.label}'s tournament")

        played = entry.get("played", 0)
        if played >= mode.matches_per_period:
            raise HTTPException(
                409,
                f"You have already played all {mode.matches_per_period} matches this {mode.label}",
            )

        current, anchor = energy_service.from_profile(user_doc, now)
        cost = mode.energy_cost_per_match
        if cost > 0 and current < cost:
            raise energy_service.NotEnoughEnergy(
                current, cost, energy_service.describe(current, anchor, now)["seconds_to_next"]
            )

        if cost > 0:
            spent = energy_service.spend_fields(current, anchor, cost, now)
            tx.set(user_path, spent, merge=True)
            remaining, new_anchor = spent[energy_service.ENERGY_FIELD], energy_service.parse_timestamp(
                spent[energy_service.ENERGY_UPDATED_AT_FIELD], now
            )
        else:
            remaining, new_anchor = current, anchor

        tx.set(e_path, {"played": played + 1, "last_match_at": now.isoformat()}, merge=True)
        return played + 1, remaining, new_anchor

    try:
        played, remaining, anchor = await client.run_transaction(_claim)
    except energy_service.NotEnoughEnergy as exc:
        raise HTTPException(402, str(exc)) from exc
    return {"played": played, "energy": energy_service.describe(remaining, anchor, now)}


async def _results(uid: str, period_id: str, mode: Mode) -> dict:
    """A settled period's final table for the caller's group."""
    client = admin_client(uid)
    profile_doc = await client.get_document(f"users/{uid}")
    now = energy_service.now_utc()
    target = period_id or tournament_service.previous_period_ids(
        tournament_service.period_id_for(now, mode), 1, mode
    )[0]

    group_id = tournament_service.last_group(profile_doc, mode)
    if tournament_service.is_entered(profile_doc, target, mode):
        group_id = tournament_service.entered_group(profile_doc, mode)
    if not group_id:
        raise HTTPException(404, f"You didn't play that {mode.label}")

    group = await client.get_document(tournament_service.group_path(target, group_id, mode))
    settlement = (group or {}).get("settlement") or {}
    if settlement.get("status") != "settled":
        raise HTTPException(409, f"That {mode.label} hasn't been settled yet")

    rows = settlement.get("rows") or []
    entry = await client.get_document(
        tournament_service.entry_path(target, group_id, uid, mode)
    )
    full_period = tournament_service.full_period_state(entry, mode) if entry is not None else None
    return {
        "mode": mode.key,
        "period_id": target,
        "day_id": target,
        "group_id": group_id,
        "settlement_mode": settlement.get("mode"),
        "rows": rows,
        "me": next((r for r in rows if r.get("uid") == uid), None),
        "full_period": full_period,
        "full_day": full_period,
    }


# -- routes: the daily league -------------------------------------------------


@router.get("/tournament/today")
async def tournament_today(uid: str = Depends(verify_id_token)):
    return await _today(uid, DAILY)


@router.post("/tournament/join")
async def join_tournament(uid: str = Depends(verify_id_token)):
    return await _join(uid, DAILY)


@router.post("/tournament/match")
async def tournament_match(uid: str = Depends(verify_id_token)):
    return await _match(uid, DAILY)


@router.get("/tournament/results")
async def tournament_results(day_id: str = "", uid: str = Depends(verify_id_token)):
    return await _results(uid, day_id, DAILY)


# -- routes: the weekly league ------------------------------------------------


@router.get("/tournament/weekly/today")
async def weekly_tournament_today(uid: str = Depends(verify_id_token)):
    return await _today(uid, WEEKLY)


@router.post("/tournament/weekly/join")
async def join_weekly_tournament(uid: str = Depends(verify_id_token)):
    return await _join(uid, WEEKLY)


@router.post("/tournament/weekly/match")
async def weekly_tournament_match(uid: str = Depends(verify_id_token)):
    return await _match(uid, WEEKLY)


@router.get("/tournament/weekly/results")
async def weekly_tournament_results(
    period_id: str = "", day_id: str = "", uid: str = Depends(verify_id_token)
):
    return await _results(uid, period_id or day_id, WEEKLY)


# -- settlement ---------------------------------------------------------------


class SettleRequest(BaseModel):
    # Empty day_id means "the lookback window"; empty mode means "every
    # format", so one scheduler job with no body settles the lot.
    day_id: str = ""
    period_id: str = ""
    mode: str = ""


@router.post("/tournament/settle", dependencies=[Depends(verify_tournament_admin)])
async def settle_tournaments(req: SettleRequest | None = None):
    """Settles a period. Called by Cloud Scheduler, and by hand when a period
    is stuck.

    Unbounded on purpose, unlike the lazy path: this one is not inside a
    player's request, so it should finish the job rather than leave a
    remainder for the next visitor.

    The body is optional because Cloud Scheduler sends none unless told to,
    and a 422 from a missing `{}` is a miserable thing to debug through
    scheduler logs. No body means "settle every format's lookback window",
    which is what a nightly run wants anyway.
    """
    client = admin_client("tournament-admin")
    now = energy_service.now_utc()

    requested_mode = (req.mode if req is not None else "") or ""
    try:
        modes = [tournament_service.mode_for(requested_mode)] if requested_mode else list(
            tournament_service.MODES.values()
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    requested_period = (req.period_id or req.day_id) if req is not None else ""
    # A named period only makes sense against a named format -- the same
    # string is a day to one and a week to the other.
    if requested_period and not requested_mode:
        modes = [DAILY]

    out = {}
    for mode in modes:
        current = tournament_service.period_id_for(now, mode)
        periods = [requested_period] if requested_period else tournament_service.previous_period_ids(
            current, mode.settle_lookback_periods, mode
        )
        out[mode.key] = {
            "current_period": current,
            "periods": [
                await tournament_service.settle_period(client, p, max_groups=10_000, mode=mode)
                for p in periods
            ],
        }
    return {"modes": out}
