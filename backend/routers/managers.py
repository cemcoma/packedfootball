"""Another manager, as everyone is allowed to see them: name, record, tier,
and the squad they field. What the Manager screen shows when a leaderboard
row is tapped; the same screen shows a match opponent from the match
response instead, without calling this.

Everything here is already visible in-game some other way -- an opponent's
XI is shown before every match, names and win counts sit on the
leaderboard -- so nothing is exposed that wasn't. Balances, energy and
the bench are not part of it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import config
from admin_firestore_client import AdminFirestoreClient
from deps import verify_id_token
from engine import GameState, Midfielder, PLAYER_CLASS_MAP, player_to_fields
from services import tournament as tournament_service

router = APIRouter(tags=["managers"])


@router.get("/manager/{manager_uid}")
async def manager_profile(manager_uid: str, uid: str = Depends(verify_id_token)):
    client = AdminFirestoreClient(manager_uid)
    doc = await client.get_document(f"users/{manager_uid}")
    if doc is None:
        raise HTTPException(404, "No such manager")

    # get_document first, THEN load_or_create_profile: the latter would
    # CREATE a profile for a uid that has none -- the same trap
    # pick_opponent_from_candidates guards against.
    state = GameState(client, PLAYER_CLASS_MAP, Midfielder)
    profile = await state.load_or_create_profile(
        default_roster=[], default_display_name=doc.get("display_name") or manager_uid[:8]
    )
    tier = tournament_service.tier_of(doc)
    return {
        "uid": manager_uid,
        "display_name": profile["display_name"],
        "wins": profile["wins"],
        "draws": profile["draws"],
        "losses": profile["losses"],
        "formation": profile["formation"],
        "kit": profile.get("kit", ""),
        "tier": tier,
        "tier_name": config.TOURNAMENT_TIER_NAMES.get(tier, f"Tier {tier}"),
        # In formation slot order, same as a match response's roster halves.
        "roster": [player_to_fields(p) for p in profile["roster"]],
        "is_me": manager_uid == uid,
    }
