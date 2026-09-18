"""Cross-account rankings, read straight off the collections rather than
a maintained leaderboard document -- see AdminFirestoreClient.query_top on
why this needs no composite index.

Both endpoints page: `page` is zero-based, LEADERBOARD_PAGE_SIZE rows each,
and every entry carries its absolute `rank` so page 3's first row says 31.
One extra row is fetched to answer `has_more` without a count query.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from config import LEADERBOARD_PAGE_SIZE, PLAYER_LEADERBOARD_STATS, USER_LEADERBOARD_STATS
from admin_firestore_client import AdminFirestoreClient
from deps import verify_id_token
from engine import PLAYER_CLASS_MAP, POSITION_CATEGORIES

router = APIRouter(tags=["leaderboard"])


async def _page(
    uid: str, collection: str, field_path: str, page: int, where=None
) -> tuple[list[dict], int, bool]:
    """(docs for the page, rank of the first one, whether a next page exists)."""
    page = max(0, page)
    offset = page * LEADERBOARD_PAGE_SIZE
    docs = await AdminFirestoreClient(uid).query_top(
        collection, field_path, LEADERBOARD_PAGE_SIZE + 1, offset=offset, where=where
    )
    has_more = len(docs) > LEADERBOARD_PAGE_SIZE
    return docs[:LEADERBOARD_PAGE_SIZE], offset + 1, has_more


def _position_filter(position: str):
    """The where clause for a position filter: an exact position ("ST"), a
    family from POSITION_CATEGORIES ("attacker" -> in [ST, LW, RW]), or
    nothing for "". Anything else is a 400 rather than an empty board."""
    if not position:
        return None
    if position in POSITION_CATEGORIES:
        return ("position", "in", list(POSITION_CATEGORIES[position].keys()))
    if position in PLAYER_CLASS_MAP:
        return ("position", "==", position)
    raise HTTPException(400, f"position must be one of {list(PLAYER_CLASS_MAP)} or {list(POSITION_CATEGORIES)}")


@router.get("/leaderboard/players")
async def leaderboard_players(
    stat: str = "goals", page: int = 0, position: str = "", uid: str = Depends(verify_id_token)
):
    field_path = PLAYER_LEADERBOARD_STATS.get(stat)
    if field_path is None:
        raise HTTPException(400, f"stat must be one of {list(PLAYER_LEADERBOARD_STATS)}")

    docs, first_rank, has_more = await _page(uid, "players", field_path, page, where=_position_filter(position))
    return {
        "stat": stat,
        "position": position,
        "page": max(0, page),
        "page_size": LEADERBOARD_PAGE_SIZE,
        "has_more": has_more,
        "entries": [
            {
                "rank": first_rank + i,
                "player_id": d["id"],
                "fname": d.get("fname"),
                "lname": d.get("lname"),
                "position": d.get("position"),
                "tier": d.get("tier"),
                # The manager who owns the card -- what a tap on the row opens.
                "owner_uid": d.get("owner_uid"),
                "value": d.get("statistics", {}).get(stat, 0),
                # So a rating board can say "7.12 over 9 matches".
                "matches_played": d.get("statistics", {}).get("matches_played", 0),
            }
            for i, d in enumerate(docs)
        ],
    }


@router.get("/leaderboard/users")
async def leaderboard_users(stat: str = "wins", page: int = 0, uid: str = Depends(verify_id_token)):
    field_path = USER_LEADERBOARD_STATS.get(stat)
    if field_path is None:
        raise HTTPException(400, f"stat must be one of {list(USER_LEADERBOARD_STATS)}")

    docs, first_rank, has_more = await _page(uid, "users", field_path, page)
    return {
        "stat": stat,
        "page": max(0, page),
        "page_size": LEADERBOARD_PAGE_SIZE,
        "has_more": has_more,
        "entries": [
            {
                "rank": first_rank + i,
                "uid": d["id"],
                "display_name": d.get("display_name"),
                "value": d.get(stat, 0),
                "wins": d.get("wins", 0),
                "draws": d.get("draws", 0),
                "losses": d.get("losses", 0),
                "is_me": d["id"] == uid,
            }
            for i, d in enumerate(docs)
        ],
    }
