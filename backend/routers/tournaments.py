"""Daily tournaments: joining, playing, standings, settlement.

Thin on purpose. The day arithmetic, the ranking and the promotion rules live
in services/tournament.py, where they are pure and unit-tested; the match
itself reuses services/match.py unchanged. What's left here is the HTTP shape
and the order things happen in.
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


async def _today_payload(client, uid: str, profile_doc: dict | None) -> dict:
    """Everything the tournament screen needs, in one response.

    One call rather than four, because the screen is useless until it has all
    of it and four round trips on a phone is four chances to show a half-built
    page.
    """
    now = energy_service.now_utc()
    day_id = tournament_service.day_id_for(now)
    tier = tournament_service.tier_of(profile_doc)

    joined = (profile_doc or {}).get("tournament_day_id") == day_id
    group_id = (profile_doc or {}).get("tournament_group_id") if joined else None

    standings, played, group_size = [], 0, 0
    my_entry = None
    if group_id:
        entries = await client.list_collection(tournament_service.entries_path(day_id, group_id))
        group_doc = await client.get_document(tournament_service.group_path(day_id, group_id))
        group_size = len((group_doc or {}).get("member_uids") or entries)
        my_entry = next((e for e in entries if e.get("uid") == uid), None)
        # "What happens if the day ended now", from the SAME apply_rules
        # settlement calls -- one implementation is what stops the projection
        # and the payout from ever disagreeing.
        rows = tournament_service.apply_rules(
            tournament_service.rank_rows(entries), tier, group_size=group_size
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

    current_energy, anchor = energy_service.from_profile(profile_doc, now)
    return {
        "day_id": day_id,
        "seconds_remaining": tournament_service.seconds_remaining(day_id, now),
        "tier": tier,
        "tier_name": config.TOURNAMENT_TIER_NAMES.get(tier, f"Tier {tier}"),
        "joined": joined,
        "join_closed": tournament_service.joining_is_closed(day_id, now),
        "join_cutoff_seconds": config.TOURNAMENT_JOIN_CUTOFF_SECONDS,
        "group_id": group_id,
        "group_size": group_size,
        "group_capacity": config.TOURNAMENT_GROUP_CAPACITY,
        "settlement_mode": tournament_service.settlement_mode(group_size),
        "matches_played": played,
        "matches_max": config.TOURNAMENT_MATCHES_PER_DAY,
        "energy": energy_service.describe(current_energy, anchor, now),
        "standings": standings,
        # The play-every-match reward: progress for the bar, and whether
        # the Claim button is live. Claiming goes through POST /claim with
        # type "tournament_full_day" (routers/claims.py).
        "full_day": tournament_service.full_day_state(my_entry) if joined else None,
        "rules": {
            "points_win": config.TOURNAMENT_POINTS["win"],
            "points_draw": config.TOURNAMENT_POINTS["draw"],
            "promotion_floor": config.TOURNAMENT_PROMOTION_FLOOR,
            "relegation_floor": config.TOURNAMENT_RELEGATION_FLOOR,
            "promote_positions": list(config.TOURNAMENT_PROMOTE_POSITIONS),
            "relegate_positions": list(config.TOURNAMENT_RELEGATE_POSITIONS),
            "min_group_for_promotion": config.TOURNAMENT_MIN_GROUP_FOR_PROMOTION,
        },
        "rewards": [
            {"position": pos, **payout}
            for pos, payout in sorted(config.TOURNAMENT_REWARDS.get(tier, {}).items())
        ],
    }


@router.get("/tournament/today")
async def tournament_today(uid: str = Depends(verify_id_token)):
    """Today's tournament, settling anything overdue first.

    Settling here is what makes the whole feature work without a scheduler:
    the day a player comes back, their group is resolved before the screen is
    built, so the same response can carry yesterday's result.
    """
    client = admin_client(uid)
    now = energy_service.now_utc()
    await tournament_service.ensure_settled_through(client, tournament_service.day_id_for(now))

    profile_doc = await client.get_document(f"users/{uid}")
    payload = await _today_payload(client, uid, profile_doc)
    payload["pending_results"] = await _pending_results(client, uid, profile_doc, payload["day_id"])
    return payload


async def _pending_results(client, uid: str, profile_doc: dict | None, today: str) -> dict | None:
    """Yesterday's row, if the player has one they haven't been shown.

    There is no notification system, and lazy settlement turns that into an
    advantage: by the time this runs, ensure_settled_through has just settled
    the group, so the result is available in the same breath as the request
    that triggered it.
    """
    last_day = (profile_doc or {}).get("tournament_last_settled_day")
    if not last_day or last_day >= today:
        return None
    group_id = (profile_doc or {}).get("tournament_last_group_id")
    if not group_id:
        return None

    e_path = tournament_service.entry_path(last_day, group_id, uid)
    entry = await client.get_document(e_path)
    if (entry or {}).get("is_shown"):
        return None

    group = await client.get_document(tournament_service.group_path(last_day, group_id))
    rows = ((group or {}).get("settlement") or {}).get("rows") or []
    mine = next((r for r in rows if r.get("uid") == uid), None)
    if mine is None:
        return None

    await client.set_document(e_path, {"is_shown": True}, merge=True)

    return {
        "day_id": last_day,
        "group_id": group_id,
        "me": mine,
        "rows": rows,
        "full_day": tournament_service.full_day_state(entry),
    }

@router.post("/tournament/join")
async def join_tournament(uid: str = Depends(verify_id_token)):
    """Joins today's tournament in the caller's own tier.

    Refuses a roster that couldn't legally play, up front -- being told at
    match time that your lineup is invalid, after joining, is a worse place to
    find out.
    """
    client = admin_client(uid)
    now = energy_service.now_utc()
    day_id = tournament_service.day_id_for(now)
    await tournament_service.ensure_settled_through(client, day_id)

    state = game_state_for(uid)
    profile = await state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])
    if len(profile["roster"]) != 11:
        raise HTTPException(400, "Your roster must have exactly 11 players")
    validate_formation_positions(profile)

    profile_doc = await client.get_document(f"users/{uid}")
    already = (profile_doc or {}).get("tournament_day_id") == day_id
    if not already and tournament_service.joining_is_closed(day_id, now):
        raise HTTPException(
            409,
            "Today's tournament is closed to new entries -- it restarts in "
            f"{tournament_service.seconds_remaining(day_id, now) // 60} minutes",
        )

    tier = tournament_service.tier_of(profile_doc)
    await tournament_service.join_today(
        client, uid, profile["display_name"], tier, day_id, now
    )

    profile_doc = await client.get_document(f"users/{uid}")
    payload = await _today_payload(client, uid, profile_doc)
    payload["pending_results"] = None
    return payload


@router.post("/tournament/match")
async def tournament_match(uid: str = Depends(verify_id_token)):
    """Plays one tournament match.

    The energy AND the match slot are claimed in one transaction BEFORE the
    simulation runs. Enforcing the 10-match cap only on write-back would mean
    the player has already spent a point and sat through a match that then
    gets rejected -- and two parallel requests could both pass a check that
    only looked at the stored count.
    """
    client = admin_client(uid)
    now = energy_service.now_utc()
    day_id = tournament_service.day_id_for(now)
    await tournament_service.ensure_settled_through(client, day_id)

    caller_state = game_state_for(uid)
    caller_profile = await caller_state.load_or_create_profile(
        default_roster=[], default_display_name=uid[:8]
    )
    if len(caller_profile["roster"]) != 11:
        raise HTTPException(400, "Your roster must have exactly 11 players")
    validate_formation_positions(caller_profile)

    profile_doc = await client.get_document(f"users/{uid}")
    if (profile_doc or {}).get("tournament_day_id") != day_id:
        raise HTTPException(409, "Join today's tournament first")
    group_id = (profile_doc or {}).get("tournament_group_id")
    tier = tournament_service.tier_of(profile_doc)

    claimed = await _claim_slot(client, uid, day_id, group_id, now)
    energy_after = claimed["energy"]

    pool = await client.get_document(tournament_service.pool_path(day_id, tier))
    opponent_uid, opponent_profile = await pick_opponent_from_candidates(
        uid,
        list((pool or {}).get("uids") or []),
        max_attempts=config.TOURNAMENT_OPPONENT_MAX_ATTEMPTS,
        card_tier_rates=config.TOURNAMENT_BOT_CARD_RATES.get(tier),
    )
    is_bot = opponent_uid.startswith("bot_")
    seed = secrets.randbits(63)

    games_client = caller_state.client
    game_id = await games_client.add_document(
        "games",
        {
            "status": "in_progress",
            "mode": "tournament",
            "tournament": {"day_id": day_id, "group_id": group_id, "tier": tier},
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
    entry = await client.get_document(tournament_service.entry_path(day_id, group_id, uid))
    fields, points_earned, outcome = tournament_service.result_fields(
        entry or {}, my_score, opp_score, game_id
    )
    await client.set_document(
        tournament_service.entry_path(day_id, group_id, uid), fields, merge=True
    )

    credits_earned = config.TOURNAMENT_MATCH_REWARD_CREDITS[outcome]
    wins, losses, draws = caller_profile["wins"], caller_profile["losses"], caller_profile["draws"]
    wins += outcome == "win"
    draws += outcome == "draw"
    losses += outcome == "loss"
    await caller_state.record_match_result(wins, losses, draws)
    new_credits = caller_profile["credits"] + credits_earned
    await caller_state.set_credits(new_credits)

    profile_doc = await client.get_document(f"users/{uid}")
    payload = await _today_payload(client, uid, profile_doc)
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
            "day_id": day_id,
            "group_id": group_id,
            "tier": tier,
            "points_earned": points_earned,
            "points_total": fields["points"],
            "played": claimed["played"],
            "matches_max": config.TOURNAMENT_MATCHES_PER_DAY,
            "position": position,
        },
    }


async def _claim_slot(client, uid: str, day_id: str, group_id: str, now) -> dict:
    """Takes one energy and one of the day's ten match slots, atomically.

    Both live on documents this transaction reads anyway, so claiming them
    together costs nothing extra and closes the race that claiming them
    separately would open.
    """
    user_path = f"users/{uid}"
    e_path = tournament_service.entry_path(day_id, group_id, uid)

    def _claim(tx):
        docs = tx.get_all([user_path, e_path])
        user_doc, entry = docs[user_path], docs[e_path]
        if entry is None:
            raise HTTPException(409, "You have no entry in today's tournament")

        played = entry.get("played", 0)
        if played >= config.TOURNAMENT_MATCHES_PER_DAY:
            raise HTTPException(
                409, f"You have already played all {config.TOURNAMENT_MATCHES_PER_DAY} matches today"
            )

        current, anchor = energy_service.from_profile(user_doc, now)
        cost = config.ENERGY_COST_PER_MATCH
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


@router.get("/tournament/results")
async def tournament_results(day_id: str = "", uid: str = Depends(verify_id_token)):
    """A settled day's final table for the caller's group."""
    client = admin_client(uid)
    profile_doc = await client.get_document(f"users/{uid}")
    now = energy_service.now_utc()
    target_day = day_id or tournament_service.previous_day_ids(
        tournament_service.day_id_for(now), 1
    )[0]

    group_id = (profile_doc or {}).get("tournament_last_group_id")
    if (profile_doc or {}).get("tournament_day_id") == target_day:
        group_id = (profile_doc or {}).get("tournament_group_id")
    if not group_id:
        raise HTTPException(404, "You didn't play that day")

    group = await client.get_document(tournament_service.group_path(target_day, group_id))
    settlement = (group or {}).get("settlement") or {}
    if settlement.get("status") != "settled":
        raise HTTPException(409, "That day hasn't been settled yet")

    rows = settlement.get("rows") or []
    entry = await client.get_document(tournament_service.entry_path(target_day, group_id, uid))
    return {
        "day_id": target_day,
        "group_id": group_id,
        "mode": settlement.get("mode"),
        "rows": rows,
        "me": next((r for r in rows if r.get("uid") == uid), None),
        "full_day": tournament_service.full_day_state(entry) if entry is not None else None,
    }


class SettleRequest(BaseModel):
    day_id: str = ""


@router.post("/tournament/settle", dependencies=[Depends(verify_tournament_admin)])
async def settle_tournaments(req: SettleRequest | None = None):
    """Settles a day. Called by Cloud Scheduler, and by hand when a day is
    stuck.

    Unbounded on purpose, unlike the lazy path: this one is not inside a
    player's request, so it should finish the job rather than leave a
    remainder for the next visitor.

    The body is optional because Cloud Scheduler sends none unless told to,
    and a 422 from a missing `{}` is a miserable thing to debug through
    scheduler logs. No body means "settle the lookback window", which is what
    a nightly run wants anyway.
    """
    client = admin_client("tournament-admin")
    now = energy_service.now_utc()
    today = tournament_service.day_id_for(now)
    requested_day = req.day_id if req is not None else ""
    days = [requested_day] if requested_day else tournament_service.previous_day_ids(
        today, config.TOURNAMENT_SETTLE_LOOKBACK_DAYS
    )

    results = []
    for day in days:
        results.append(await tournament_service.settle_day(client, day, max_groups=10_000))
    return {"today": today, "days": results}
