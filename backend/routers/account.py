"""Account lifecycle: the health probe, and first-login bootstrap."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends

from config import INVENTORY_CAP, STARTER_FORMATION, STARTER_TIER
from deps import game_state_for, verify_id_token
from engine import generate_starter_roster

router = APIRouter(tags=["account"])


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/account/bootstrap")
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
    state = game_state_for(uid)
    existing = await state.client.get_document(f"users/{uid}")
    if existing is not None:
        return {"created": False, "inventory_cap": INVENTORY_CAP}

    seed = secrets.randbits(63)
    roster = generate_starter_roster(STARTER_FORMATION, STARTER_TIER, seed=seed)
    profile = await state.load_or_create_profile(
        default_roster=roster, default_display_name=uid[:8], default_formation=STARTER_FORMATION
    )
    return {
        "created": True,
        "formation": profile["formation"],
        "roster_size": len(profile["roster"]),
        "inventory_cap": INVENTORY_CAP,
    }
