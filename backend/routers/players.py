"""Owning a card: releasing it for credits, or paying to restyle it.

Both move credits and mutate a players/{id} document, which is exactly the
pair firestore.rules denies the client outright -- so neither can be a
direct client write the way saving a lineup or a kit is.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import CUSTOMIZE_CREDITS_PER_SLOT, INVENTORY_CAP, RELEASE_CREDITS_BY_TIER, RELEASE_CREDITS_DEFAULT
from admin_firestore_client import AdminFirestoreClient
from deps import verify_id_token
from engine import APPEARANCE_OPTION_COUNTS, APPEARANCE_SLOTS, DEFAULT_APPEARANCE

router = APIRouter(tags=["players"])


# -- owning a card: releasing it, restyling it --------------------------------

class ReleasePlayerRequest(BaseModel):
    player_id: str


@router.post("/player/release")
async def release_player(req: ReleasePlayerRequest, uid: str = Depends(verify_id_token)):
    """Permanently deletes one of the caller's benched cards and pays out
    RELEASE_CREDITS_BY_TIER for its tier.

    Refuses a card in the starting XI: roster_player_ids would be left
    pointing at a players/{id} doc that no longer exists, and the client
    would show an empty slot it never asked for. Take them out of the XI
    first -- that's a save away on the Squad screen.

    The card doc goes BEFORE the payout on purpose. Neither order is atomic
    (AdminFirestoreClient has no transaction support and this is a
    two-collection write), so one of the two has to be the one that can be
    lost to a crash in between, and "released but not yet paid" is the
    failure that can't be farmed: a retry finds no players/{id} doc and
    404s. The remaining exposure is two genuinely CONCURRENT releases of the
    same card both reading the doc before either deletes it, which pays
    twice for one card. The client disables the button for the duration of
    the request, so that needs a hand-made request to hit at all; closing it
    properly means a real Firestore transaction, which is the thing to do if
    this ever turns into an actual economy leak.
    """
    client = AdminFirestoreClient(uid)

    card = await client.get_document(f"players/{req.player_id}")
    if card is None or card.get("owner_uid") != uid:
        # Same 404 for "no such card" and "not yours" -- a different message
        # for the second would confirm the existence of someone else's card.
        raise HTTPException(404, "You don't own that player")

    profile_doc = await client.get_document(f"users/{uid}")
    if profile_doc is None:
        raise HTTPException(404, "No profile for this account")
    if req.player_id in (profile_doc.get("roster_player_ids") or []):
        raise HTTPException(409, "That player is in your starting XI -- replace them first")

    reward = RELEASE_CREDITS_BY_TIER.get(card.get("tier", ""), RELEASE_CREDITS_DEFAULT)

    inventory = await client.list_collection(f"users/{uid}/inventory")
    pointers = [doc for doc in inventory if doc.get("player_id") == req.player_id]
    for pointer in pointers:
        await client.delete_document(f"users/{uid}/inventory/{pointer['id']}")
    await client.delete_document(f"players/{req.player_id}")

    remaining = profile_doc.get("credits", 0) + reward
    await client.set_document(f"users/{uid}", {"credits": remaining}, merge=True)

    return {
        "player_id": req.player_id,
        "credits_awarded": reward,
        "credits_remaining": remaining,
        "inventory_count": len(inventory) - len(pointers),
        "inventory_cap": INVENTORY_CAP,
    }


class CustomizePlayerRequest(BaseModel):
    player_id: str
    # slot name -> option index, for any subset of APPEARANCE_SLOTS. Slots
    # left out simply keep what the card already has.
    appearance: dict


@router.post("/player/customize")
async def customize_player(req: CustomizePlayerRequest, uid: str = Depends(verify_id_token)):
    """Restyles one of the caller's cards, charging
    CUSTOMIZE_CREDITS_PER_SLOT for each slot whose value actually changes.

    Unlike release, this works on ANY owned card, XI included -- a haircut
    doesn't invalidate a lineup.

    Indices are validated against APPEARANCE_OPTION_COUNTS rather than
    trusted, for the same reason the counts exist at all: the client is what
    knows how many hairstyles have been drawn, and a card stamped with an
    index past the end of that list renders as a fallback look forever. A
    client that's newer than this deploy will be refused options it can
    genuinely draw -- that's the intended direction of the mismatch (raise
    the counts, deploy, then ship the client), and the alternative is
    storing indices nothing can render.

    Charging nothing for a no-op save is deliberate: the screen's Save
    button is reachable with zero changes, and billing 100 credits for
    pressing it would be a trap.
    """
    client = AdminFirestoreClient(uid)

    card = await client.get_document(f"players/{req.player_id}")
    if card is None or card.get("owner_uid") != uid:
        raise HTTPException(404, "You don't own that player")

    requested: dict[str, int] = {}
    for slot, value in (req.appearance or {}).items():
        if slot not in APPEARANCE_SLOTS:
            raise HTTPException(400, f"Unknown appearance slot: {slot}")
        # bool is an int subclass in Python, and True would sail through the
        # range check below as index 1.
        if isinstance(value, bool) or not isinstance(value, int):
            raise HTTPException(400, f"Appearance slot {slot} must be an integer index")
        if not 0 <= value < APPEARANCE_OPTION_COUNTS[slot]:
            raise HTTPException(400, f"Appearance slot {slot} has no option {value}")
        requested[slot] = value

    # A card written before a slot existed simply has no entry for it, so
    # the comparison below has to run against a fully-populated look or
    # every such slot would read as "changed" and be charged for.
    current = {**DEFAULT_APPEARANCE, **(card.get("appearance") or {})}
    changed = sorted(slot for slot, value in requested.items() if current.get(slot) != value)
    cost = len(changed) * CUSTOMIZE_CREDITS_PER_SLOT

    profile_doc = await client.get_document(f"users/{uid}")
    if profile_doc is None:
        raise HTTPException(404, "No profile for this account")
    credits = profile_doc.get("credits", 0)

    if not changed:
        return {
            "player_id": req.player_id,
            "appearance": current,
            "slots_changed": [],
            "credits_spent": 0,
            "credits_remaining": credits,
        }

    if credits < cost:
        raise HTTPException(402, f"Not enough credits -- {cost} needed, you have {credits}")

    updated = {**current, **requested}
    await client.set_document(f"players/{req.player_id}", {"appearance": updated}, merge=True)
    credits -= cost
    await client.set_document(f"users/{uid}", {"credits": credits}, merge=True)

    return {
        "player_id": req.player_id,
        "appearance": updated,
        "slots_changed": changed,
        "credits_spent": cost,
        "credits_remaining": credits,
    }
