"""Playing a match: the casual Quick Match, and reporting one that went wrong.

Quick Match is thin -- picking an opponent, running the simulation and
recording what happened live in services/match.py, so it reads as the
sequence of steps they are rather than as the engine plumbing underneath.
"""

from __future__ import annotations

import asyncio
import secrets

from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import firestore
from pydantic import BaseModel

from config import (
    MATCH_REPORT_CATEGORIES,
    MATCH_REPORT_MAX_CHARS,
    QUICK_MATCH_ENERGY_COST,
    QUICK_MATCH_REWARD_CREDITS,
)
from admin_firestore_client import AdminFirestoreClient
from deps import game_state_for, replay_format, verify_id_token
from engine import ENGINE_VERSION
from services import energy as energy_service
from services.match import (
    persist_player_stats,
    pick_opponent_profile,
    record_bot_result,
    run_match,
    teams_snapshot,
    validate_formation_positions,
)

router = APIRouter(tags=["matches"])


@router.post("/match/quick")
async def quick_match(uid: str = Depends(verify_id_token), fmt: int = Depends(replay_format)):
    """Quick Match: always-available, casual match against a randomly
    picked opponent (see pick_opponent_profile) for a small credit reward
    (see QUICK_MATCH_REWARD_CREDITS). Records wins/losses/draws.

    Setting the cost to 0 in config turns the gate off without touching this code 
    """
    caller_state = game_state_for(uid)
    caller_profile = await caller_state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])
    if len(caller_profile["roster"]) != 11:
        raise HTTPException(400, "Your roster must have exactly 11 players")
    validate_formation_positions(caller_profile)

    try:
        energy_after = await energy_service.spend(caller_state.client, uid, QUICK_MATCH_ENERGY_COST)
    except energy_service.NotEnoughEnergy as exc:
        # 402 rather than 403: the client distinguishes "you can't afford this"
        # from every other failure and shows the refill offer instead of
        # "try again", which would be advice that cannot work.
        raise HTTPException(402, str(exc)) from exc

    opponent_uid, opponent_profile = await pick_opponent_profile(uid)
    is_bot = opponent_uid.startswith("bot_")
    seed = secrets.randbits(63)

    # Written "in_progress", then flipped to "finished", so a crash mid-simulation leaves an honestly-stuck record rather than
    # none at all. Same "teams" roster/formation snapshot too (see
    # _teams_snapshot) -- lets a bug or suspected tampering get checked
    # afterwards against exactly what was actually played, bot opponents
    # included (opponent_uid is just their "bot_..." sentinel, same as
    # everywhere else that isn't a real Firebase uid).
    games_client = caller_state.client
    game_id = await games_client.add_document(
        "games",
        {
            "status": "in_progress",
            "mode": "quick",
            "participants": [uid, opponent_uid],
            "initiator_uid": uid,
            "opponent_uid": opponent_uid,
            "opponent_is_bot": is_bot,
            "seed": seed,
            "engine_version": ENGINE_VERSION,
            "replay_format_version": fmt,
            "teams": teams_snapshot(uid, caller_profile, opponent_uid, opponent_profile),
            "created_at": firestore.SERVER_TIMESTAMP,
            "finished_at": None,
            "score": None,
        },
    )

    # Off the event loop: a simulation is seconds of CPU, and every other request on this instance would wait it out.
    result = await asyncio.to_thread(run_match, caller_profile, opponent_profile, seed, fmt)
    my_score, opp_score = result["score"]

    await games_client.set_document(
        f"games/{game_id}",
        {"status": "finished", "finished_at": firestore.SERVER_TIMESTAMP, "score": result["score"]},
        merge=True,
    )

    await persist_player_stats(caller_state, caller_profile)
    await record_bot_result(opponent_uid, opponent_profile, opp_score, my_score)

    credits_earned = 0

    wins, losses, draws = caller_profile["wins"], caller_profile["losses"], caller_profile["draws"]
    if my_score > opp_score:
        wins += 1
        credits_earned = QUICK_MATCH_REWARD_CREDITS["win"]
    elif my_score == opp_score:
        draws += 1
        credits_earned = QUICK_MATCH_REWARD_CREDITS["draw"]
    else:
        losses += 1
        credits_earned = QUICK_MATCH_REWARD_CREDITS["loss"]
    await caller_state.record_match_result(wins, losses, draws)
    new_credits = caller_profile["credits"] + credits_earned
    await caller_state.set_credits(new_credits)

    return {
        "seed": seed,
        "engine_version": ENGINE_VERSION,
        "replay_format_version": fmt,
        "score": result["score"],
        "opponent_display_name": opponent_profile["display_name"],
        "opponent_is_bot": is_bot,

        # For the Manager screen's header when "View Opponent" is tapped: a
        # bot has no uid worth showing.
        "opponent_uid": "" if is_bot else opponent_uid,
        "opponent_record": {
            "wins": opponent_profile.get("wins", 0),
            "draws": opponent_profile.get("draws", 0),
            "losses": opponent_profile.get("losses", 0),
        },
        "credits_earned": credits_earned,
        "credits_remaining": new_credits,
        "energy": energy_after, #so the client knows energy without making a seperate req.uest
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
        "tactics": result["tactics"],
        "captains": result["captains"],
    }


class ReportMatchRequest(BaseModel):
    game_id: str
    category: str
    description: str = ""


@router.post("/match/report")
async def report_match(req: ReportMatchRequest, uid: str = Depends(verify_id_token)):
    """Files a bug report against a match the caller played.

    The report itself is small -- who, which game, a category, some words --
    because everything needed to reproduce the match is ALREADY on the
    games/{id} doc: the seed, the engine and replay-format versions, and the
    `teams` snapshot of both rosters exactly as played. The seed and versions
    are copied onto the report so a triage listing (scripts/
    list_match_reports.py) can show them without a second read; the rosters
    stay where they are.

    One report per player per game: the doc id is game_id + uid, so sending
    again replaces the earlier text rather than piling up duplicates.
    Anyone who wasn't in the match gets a 404, not a 403 -- no confirming
    that a guessed game id exists.
    """
    if req.category not in MATCH_REPORT_CATEGORIES:
        raise HTTPException(400, f"Unknown category: {req.category!r}")
    description = " ".join(req.description.split())[:MATCH_REPORT_MAX_CHARS]

    client = AdminFirestoreClient(uid)
    game = await client.get_document(f"games/{req.game_id}")
    if game is None or uid not in (game.get("participants") or []):
        raise HTTPException(404, "No such match")

    report_id = f"{req.game_id}_{uid}"
    await client.set_document(
        f"match_reports/{report_id}",
        {
            "uid": uid,
            "game_id": req.game_id,
            "category": req.category,
            "description": description,
            "mode": game.get("mode"),
            "score": game.get("score"),
            "seed": game.get("seed"),
            "engine_version": game.get("engine_version"),
            "replay_format_version": game.get("replay_format_version"),
            "status": "open",
            "created_at": firestore.SERVER_TIMESTAMP,
        },
        merge=False,
    )
    return {"reported": True, "report_id": report_id}
