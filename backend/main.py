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

import base64
import os
import secrets
import sys
from datetime import datetime, timezone
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
from formations import get_formation, is_similar_position
from packEngine import PLAYER_CLASS_MAP, PackManager, generate_starter_roster
from player.classes.midfielder import Midfielder

from admin_firestore_client import AdminFirestoreClient

firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})

ELO_K = 32  # matches packedfootball/main.py's client-side formula
STARTER_FORMATION = "4-4-2"
STARTER_TIER = "bronze"

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


@app.post("/account/bootstrap")
async def bootstrap_account(uid: str = Depends(verify_id_token)):
    """Ensures uid has a profile document, creating one with a full bronze
    starter roster if this is the account's first time here. Idempotent --
    safe to call on every sign-in (mirrors game_state.py's
    load_or_create_profile, which already does exactly this for the Python
    client, just with an empty default_roster since packedfootball/main.py
    builds its own local starter squad instead of asking the backend for
    one). The Godot client calls this once right after sign-in succeeds
    (see mobile/scripts/GameProfile.gd's load_all()), which never had an
    equivalent local-squad fallback -- without this, a brand new account
    created straight through Godot had no cards and no roster at all.
    """
    state = _game_state_for(uid)
    existing = await state.client.get_document(f"users/{uid}")
    if existing is not None:
        return {"created": False}

    seed = secrets.randbits(63)
    roster = generate_starter_roster(STARTER_FORMATION, STARTER_TIER, seed=seed)
    profile = await state.load_or_create_profile(
        default_roster=roster, default_display_name=uid[:8], default_formation=STARTER_FORMATION
    )
    return {"created": True, "formation": profile["formation"], "roster_size": len(profile["roster"])}


def _pack_unavailable_reason(config: dict) -> Optional[str]:
    """Why this pack can't be opened right now, or None if it can. Shared by
    /pack/open (to reject one) and /pack/list (to filter the catalog down
    to what's actually purchasable) so the two never disagree.

    "max_opens" and "expires_at" are optional Firestore-only fields (see
    packEngine.PACK_DATABASE's own comment) -- absent means unlimited/never
    expires, matching every pack that predates this check.
    """
    if not config.get("active", False):
        return "This pack is not currently available"

    max_opens = config.get("max_opens")
    times_opened = config.get("times_opened", 0)
    if max_opens is not None and times_opened >= max_opens:
        return "This pack has sold out"

    expires_at = config.get("expires_at")
    if expires_at:
        try:
            if datetime.now(timezone.utc) > datetime.fromisoformat(expires_at):
                return "This pack has expired"
        except ValueError:
            pass  # malformed expires_at shouldn't block opening -- fail open, not closed

    return None


def _pack_is_teased(config: dict) -> bool:
    """A pack that's currently unavailable but should still be shown
    (grayed out, tagged with why -- see PackData.tag_text() on the Godot
    side) instead of hidden outright, e.g. a UCL Promo pack previewed
    ahead of its real on-sale date. Opt-in only, via either of two
    Firestore-only fields an admin sets directly on the pack's doc (no
    redeploy): "visible": true, and/or "available_at" (which alone implies
    it -- setting a planned on-sale date is itself a decision to preview
    the pack). Every pack that predates these fields keeps today's
    default: an unavailable pack is hidden, full stop.
    """
    return bool(config.get("visible")) or config.get("available_at") is not None


@app.get("/pack/list")
async def list_packs(uid: str = Depends(verify_id_token)):
    """Every pack worth showing in the shop right now: everything actually
    purchasable, plus any currently-unavailable pack an admin opted into
    still previewing (see _pack_is_teased). This is purely "what to show",
    not the source of truth for "what's allowed" -- /pack/open enforces
    _pack_unavailable_reason independently regardless of what this
    returned, so a teased pack's Buy button being disabled client-side
    isn't the only thing stopping someone from opening it early.
    """
    docs = await AdminFirestoreClient(uid).list_collection("packs")
    packs = []
    for doc in docs:
        unavailable_reason = _pack_unavailable_reason(doc)
        is_available = unavailable_reason is None
        if not is_available and not _pack_is_teased(doc):
            continue  # hidden entirely -- the default for any unavailable pack

        max_opens = doc.get("max_opens")
        times_opened = doc.get("times_opened", 0)
        packs.append(
            {
                "pack_id": int(doc["id"]),
                "name": doc.get("name"),
                "type": doc.get("type", "standard"),
                "description": doc.get("description", ""),
                "price": doc.get("price"),
                "cards_per_pack": doc.get("cards_per_pack"),
                "rates": doc.get("rates", {}),
                "pos_rates": doc.get("pos_rates", {}),
                "max_opens": max_opens,
                "times_opened": times_opened,
                "remaining_opens": (max_opens - times_opened) if max_opens is not None else None,
                "expires_at": doc.get("expires_at"),
                "available": is_available,
                "unavailable_reason": unavailable_reason,
                "available_at": doc.get("available_at"),
            }
        )
    packs.sort(key=lambda p: p["pack_id"])
    return {"packs": packs}


class OpenPackRequest(BaseModel):
    pack_id: int


@app.post("/pack/open")
async def open_pack(req: OpenPackRequest, uid: str = Depends(verify_id_token)):
    packs_client = AdminFirestoreClient(uid)
    pack_path = f"packs/{req.pack_id}"
    config = await packs_client.get_document(pack_path)
    if config is None:
        raise HTTPException(404, "Unknown pack_id")
    unavailable_reason = _pack_unavailable_reason(config)
    if unavailable_reason is not None:
        raise HTTPException(403, unavailable_reason)

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
        "cards": [
            {**player_to_fields(c), "player_id": c.player_id, "doc_id": getattr(c, "doc_id", None)}
            for c in cards
        ],
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


def _validate_formation_positions(profile: dict) -> None:
    """Raises 400 if any roster player's card position can't legally fill
    their assigned formation slot -- an exact match, or is_similar_position()
    (see formations.py) at a penalty. The Team scene's own bench picker
    already only ever allows these two cases, so reaching this only means a
    client lied about its roster/formation pairing.

    Called for both sides BEFORE anything about this match gets written to
    Firestore (see /match/simulate) -- a rejected request leaves no trace at
    all: no games/{id} doc created, and this never touches either user's
    own saved roster/formation (nothing about /match/simulate writes those
    regardless -- it only ever reads them).
    """
    slots = get_formation(profile["formation"])
    for i, p in enumerate(profile["roster"]):
        role = slots[i]["role"]
        if p.position != role and not is_similar_position(p.position, role):
            raise HTTPException(400, f"Player {i + 1} ({p.position}) cannot play {role} in {profile['formation']}")


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
    _validate_formation_positions(caller_profile)

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
    _validate_formation_positions(opponent_profile)

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
                "formation": caller_profile["formation"],
                "players": [player_to_fields(p) for p in caller_profile["roster"]],
            },
            "opponent": {
                "uid": req.opponent_uid,
                "display_name": opponent_profile["display_name"],
                "elo": opponent_profile["elo"],
                "formation": opponent_profile["formation"],
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
        record_replay=True,
        formation_home=caller_profile["formation"],
        formation_away=opponent_profile["formation"],
    )
    match.run_match(max_steps=10800, render=False)  # 90 real-minute match, matching packedfootball/main.py's own loop
    my_score, opp_score = match.scores
    replay_b64 = base64.b64encode(match.replay.encode()).decode()

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
        "replay": replay_b64,
    }
