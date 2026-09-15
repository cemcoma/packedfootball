"""Cross-account rankings, read straight off the collections rather than
a maintained leaderboard document -- see AdminFirestoreClient.query_top on
why this needs no composite index.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from config import PLAYER_LEADERBOARD_STATS, USER_LEADERBOARD_STATS
from admin_firestore_client import AdminFirestoreClient
from deps import verify_id_token

router = APIRouter(tags=["leaderboard"])


@router.get("/leaderboard/players")
async def leaderboard_players(stat: str = "goals", limit: int = 20, uid: str = Depends(verify_id_token)):
    field_path = PLAYER_LEADERBOARD_STATS.get(stat)
    if field_path is None:
        raise HTTPException(400, f"stat must be one of {list(PLAYER_LEADERBOARD_STATS)}")
    limit = max(1, min(limit, 100))

    docs = await AdminFirestoreClient(uid).query_top("players", field_path, limit)
    return {
        "stat": stat,
        "entries": [
            {
                "player_id": d["id"],
                "fname": d.get("fname"),
                "lname": d.get("lname"),
                "position": d.get("position"),
                "tier": d.get("tier"),
                "owner_uid": d.get("owner_uid"),
                "value": d.get("statistics", {}).get(stat, 0),
            }
            for d in docs
        ],
    }


@router.get("/leaderboard/users")
async def leaderboard_users(stat: str = "wins", limit: int = 20, uid: str = Depends(verify_id_token)):
    field_path = USER_LEADERBOARD_STATS.get(stat)
    if field_path is None:
        raise HTTPException(400, f"stat must be one of {list(USER_LEADERBOARD_STATS)}")
    limit = max(1, min(limit, 100))

    docs = await AdminFirestoreClient(uid).query_top("users", field_path, limit)
    return {
        "stat": stat,
        "entries": [
            {
                "uid": d["id"],
                "display_name": d.get("display_name"),
                "value": d.get(stat, 0),
            }
            for d in docs
        ],
    }
