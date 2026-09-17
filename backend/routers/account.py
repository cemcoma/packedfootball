"""Account lifecycle: the health probe, first-login bootstrap, the manager's
display name, and deleting the account."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import INVENTORY_CAP, STARTER_FORMATION, STARTER_TIER
from deps import admin_client, game_state_for, verify_id_token
from engine import generate_starter_roster
from services import account as account_service
from services import energy as energy_service
from services import tournament as tournament_service

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

    Also carries the two numbers every screen needs but nothing else hands
    over: the inventory cap, and the energy bar. Both ride along here because
    this already runs on every login -- a separate GET for each would be two
    more round trips before the Menu can draw itself.
    """
    state = game_state_for(uid)
    existing = await state.client.get_document(f"users/{uid}")
    if existing is not None:
        current, anchor = energy_service.from_profile(existing)
        return {
            "created": False,
            "inventory_cap": INVENTORY_CAP,
            "energy": energy_service.describe(current, anchor),
        }

    seed = secrets.randbits(63)
    roster = generate_starter_roster(STARTER_FORMATION, STARTER_TIER, seed=seed)
    profile = await state.load_or_create_profile(
        default_roster=roster, default_display_name=uid[:8], default_formation=STARTER_FORMATION
    )
    # The placeholder name gets a reservation like any other, so the
    # registry stays complete. A plain set: eight characters of a Firebase
    # uid don't collide, and the client replaces it moments later anyway.
    await state.client.set_document(account_service.reservation_path(profile["display_name"]), {"uid": uid})
    current, anchor = energy_service.from_profile(None)
    return {
        "created": True,
        "formation": profile["formation"],
        "roster_size": len(profile["roster"]),
        "inventory_cap": INVENTORY_CAP,
        "energy": energy_service.describe(current, anchor),
    }


# -- display name ---------------------------------------------------------------


class DisplayNameRequest(BaseModel):
    display_name: str


@router.get("/account/name_available")
async def display_name_available(display_name: str = ""):
    """Whether a name passes the rules and is free right now. Unauthenticated
    on purpose: the registration form asks BEFORE there is an account, so
    a taken name is caught before the Auth user is created rather than
    after. Only advisory -- /account/display_name is what actually decides,
    inside a transaction."""
    try:
        name = account_service.validate_display_name(display_name)
    except account_service.DisplayNameError as exc:
        return {"available": False, "reason": exc.reason}
    # No uid to act as: the reservation collection is not per-user data.
    taken = await admin_client("").get_document(account_service.reservation_path(name)) is not None
    return {"available": not taken, "reason": "taken" if taken else "", "display_name": name}


@router.post("/account/display_name")
async def set_display_name(req: DisplayNameRequest, uid: str = Depends(verify_id_token)):
    """Renames the manager, uniquely.

    400 with a `reason` when the name breaks the rules, 409 when someone
    else has it. One transaction reads the reservation the new name would
    need, the caller's profile (for the reservation they're giving up) and
    their current tournament entry (which carries a copy of the name for
    the standings), and writes all of them together -- so there is no
    moment where a name is reserved but not worn, or worn by two.
    """
    try:
        name = account_service.validate_display_name(req.display_name)
    except account_service.DisplayNameError as exc:
        raise HTTPException(400, f"Display name refused: {exc.reason}")

    client = admin_client(uid)
    user_path = f"users/{uid}"
    new_path = account_service.reservation_path(name)

    def _rename(tx):
        docs = tx.get_all([user_path, new_path])
        profile, reservation = docs[user_path], docs[new_path]
        if profile is None:
            raise HTTPException(404, "No profile -- call /account/bootstrap first")
        if reservation is not None and reservation.get("uid") != uid:
            raise HTTPException(409, "That name is taken")

        old_name = profile.get("display_name") or ""
        old_path = account_service.reservation_path(old_name) if old_name else None
        entry_path = None
        day_id, group_id = profile.get("tournament_day_id"), profile.get("tournament_group_id")
        if day_id and group_id:
            entry_path = tournament_service.entry_path(day_id, group_id, uid)
            entry = tx.get(entry_path)
            if entry is None:
                entry_path = None

        if old_path and old_path != new_path:
            old_reservation = tx.get(old_path)
            if old_reservation is not None and old_reservation.get("uid") == uid:
                tx.delete(old_path)

        tx.set(new_path, {"uid": uid}, merge=False)
        tx.set(user_path, {"display_name": name}, merge=True)
        if entry_path:
            tx.set(entry_path, {"display_name": name}, merge=True)
        return name

    stored = await client.run_transaction(_rename)
    return {"display_name": stored}


# -- deletion -------------------------------------------------------------------


@router.delete("/account")
async def delete_account(uid: str = Depends(verify_id_token)):
    """Deletes the calling account and everything that is its own -- see
    services.account.delete_account for exactly what goes and what stays.
    App Store guideline 5.1.1(v) requires this to exist in-app; the
    confirmation lives on the client (Settings), this end just does it.
    Idempotent: a retry after a partial failure finishes the job."""
    summary = await account_service.delete_account(admin_client(uid), uid)
    return {"deleted": True, **summary}
