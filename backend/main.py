"""Authoritative game backend: the Cloud Run service that closes the
CLIENT-TRUSTED gap called out in packedfootball/firebase_client.py,
firestore.rules, and game_state.py.

Pack opening and match results now happen here, using a server-generated
seed and the *same* gameEngine/packEngine code the client used to run
locally -- so a client can no longer just tell the server it won, or that it
opened five icon cards. It reads/writes Firestore with the Admin SDK
(AdminFirestoreClient), which is not subject to firestore.rules, instead of
the user's own ID token.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path
from typing import Optional

import firebase_admin
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import auth as firebase_auth
from firebase_admin import firestore
from pydantic import BaseModel

# Make packedfootball/'s modules (gameEngine, packEngine, player.*, game_state)
# importable as top-level names, the same way packedfootball/main.py already
# runs them. Deliberately NOT importing firebase_config here: that file is
# gitignored (it holds the client's public API key, which this server-side
# Admin SDK code doesn't need anyway) and so isn't present in Cloud Build's
# upload -- the project id comes from an env var instead, set at deploy time.
_PACKEDFOOTBALL_DIR = Path(__file__).resolve().parent.parent / "packedfootball"
sys.path.insert(0, str(_PACKEDFOOTBALL_DIR))

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")

from game_state import GameState, player_to_fields
from gameEngine import game
from packEngine import PLAYER_CLASS_MAP, PackManager
from player.classes.midfielder import Midfielder

from admin_firestore_client import AdminFirestoreClient

firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})

ELO_K = 32  # matches packedfootball/main.py's client-side formula

app = FastAPI(title="Packed Football backend")

# The pygbag web build runs in-browser from GitHub Pages, a different origin
# than this service's own *.run.app domain, so browser fetches need CORS
# explicitly enabled -- desktop builds use `requests` instead, which isn't
# subject to CORS at all. Add any other deployed frontend origins here
# (a custom domain, a future Godot web export, etc).
ALLOWED_ORIGINS = ["https://cemcoma.github.io"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class _Team:
    def __init__(self, name, players):
        self.name = name
        self.players = players


async def verify_id_token(authorization: str = Header(...)) -> str:
    """Extracts and verifies the caller's Firebase ID token, returns their uid."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception as exc:
        raise HTTPException(401, f"Invalid ID token: {exc}") from exc
    return decoded["uid"]


def _game_state_for(uid: str) -> GameState:
    return GameState(AdminFirestoreClient(uid), PLAYER_CLASS_MAP, Midfielder)


@app.get("/health")
async def health():
    return {"status": "ok"}


class OpenPackRequest(BaseModel):
    pack_id: int


@app.post("/pack/open")
async def open_pack(req: OpenPackRequest, uid: str = Depends(verify_id_token)):
    packs_client = AdminFirestoreClient(uid)
    pack_path = f"packs/{req.pack_id}"
    config = await packs_client.get_document(pack_path)
    if config is None:
        raise HTTPException(404, "Unknown pack_id")
    if not config.get("active", False):
        raise HTTPException(403, "This pack is not currently available")

    state = _game_state_for(uid)
    profile = await state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])

    price = config["price"]
    if profile["credits"] < price:
        raise HTTPException(402, "Not enough credits")

    seed = secrets.randbits(63)
    cards = PackManager({req.pack_id: config}, seed=seed).open_pack(req.pack_id)

    remaining_credits = profile["credits"] - price
    await state.set_credits(remaining_credits)
    for card in cards:
        await state.add_inventory_card(card)
    await packs_client.set_document(pack_path, {"times_opened": firestore.Increment(1)}, merge=True)

    return {
        "seed": seed,
        "credits_remaining": remaining_credits,
        "cards": [player_to_fields(c) for c in cards],
    }


PLAYER_LEADERBOARD_STATS = {
    "goals": "statistics.goals",
    "assists": "statistics.assists",
    "matches_played": "statistics.matches_played",
}


@app.get("/leaderboard/players")
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


class SimulateMatchRequest(BaseModel):
    opponent_uid: str
    seed: Optional[int] = None


@app.post("/match/simulate")
async def simulate_match(req: SimulateMatchRequest, uid: str = Depends(verify_id_token)):
    if req.opponent_uid == uid:
        raise HTTPException(400, "Cannot challenge yourself")

    caller_state = _game_state_for(uid)
    caller_profile = await caller_state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])
    if len(caller_profile["roster"]) != 11:
        raise HTTPException(400, "Your roster must have exactly 11 players")

    # The lobby entry is the "this uid has opted in to being challenged" gate
    # -- it also stops a typo'd/made-up opponent_uid from silently creating a
    # junk profile document below. Once confirmed, the actual roster/elo used
    # for the match comes fresh from their own profile (via GameState, same
    # path the caller's own data went through), not the lobby's snapshot,
    # which could be stale if they changed their team without republishing.
    lobby_doc = await AdminFirestoreClient(req.opponent_uid).get_document(f"lobby/{req.opponent_uid}")
    if lobby_doc is None:
        raise HTTPException(404, "Opponent has not published a lobby entry")

    opponent_state = GameState(AdminFirestoreClient(req.opponent_uid), PLAYER_CLASS_MAP, Midfielder)
    opponent_profile = await opponent_state.load_or_create_profile(
        default_roster=[], default_display_name=lobby_doc.get("display_name", req.opponent_uid[:8])
    )
    if len(opponent_profile["roster"]) != 11:
        raise HTTPException(400, "Opponent roster must have exactly 11 players")

    seed = req.seed if req.seed is not None else secrets.randbits(63)

    # Record the game as it starts (status "in_progress"), then flip it to
    # "finished" once the simulation actually completes below -- so a crash
    # mid-simulation would leave an honestly-stuck "in_progress" record
    # rather than no record at all.
    games_client = caller_state.client
    game_doc = {
        "status": "in_progress",
        "participants": [uid, req.opponent_uid],
        "initiator_uid": uid,
        "opponent_uid": req.opponent_uid,
        "seed": seed,
        "teams": {
            "initiator": {
                "uid": uid,
                "display_name": caller_profile["display_name"],
                "elo": caller_profile["elo"],
                "formation": "4-4-2",
                "players": [player_to_fields(p) for p in caller_profile["roster"]],
            },
            "opponent": {
                "uid": req.opponent_uid,
                "display_name": opponent_profile["display_name"],
                "elo": opponent_profile["elo"],
                "formation": "4-4-2",
                "players": [player_to_fields(p) for p in opponent_profile["roster"]],
            },
        },
        "created_at": firestore.SERVER_TIMESTAMP,
        "finished_at": None,
        "score": None,
    }
    game_id = await games_client.add_document("games", game_doc)

    match = game(
        _Team(caller_profile["display_name"], caller_profile["roster"]),
        _Team(opponent_profile["display_name"], opponent_profile["roster"]),
        seed=seed,
    )
    match.run_match(max_steps=3000, render=False)
    my_score, opp_score = match.scores

    await games_client.set_document(
        f"games/{game_id}",
        {"status": "finished", "finished_at": firestore.SERVER_TIMESTAMP, "score": [my_score, opp_score]},
        merge=True,
    )

    actual = 1.0 if my_score > opp_score else (0.5 if my_score == opp_score else 0.0)
    expected = 1.0 / (1.0 + 10 ** ((opponent_profile["elo"] - caller_profile["elo"]) / 400.0))
    new_elo = round(caller_profile["elo"] + ELO_K * (actual - expected))

    wins, losses, draws = caller_profile["wins"], caller_profile["losses"], caller_profile["draws"]
    if my_score > opp_score:
        wins += 1
    elif my_score == opp_score:
        draws += 1
    else:
        losses += 1

    await caller_state.set_elo(new_elo)
    await caller_state.record_match_result(wins, losses, draws)

    return {
        "seed": seed,
        "score": [my_score, opp_score],
        "elo": new_elo,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "game_id": game_id,
    }
