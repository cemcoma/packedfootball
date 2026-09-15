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

    The delete and the payout COMMIT TOGETHER, in one transaction, and this
    is the endpoint that most needs it: the naive version reads the card,
    reads the balance, then writes both, and two requests racing each other
    can each read the card before either deletes it and each pay out for it.
    Inside a transaction the second is aborted and retried, re-reads a card
    that is now gone, and 404s. One card, one payout, always -- and a crash
    can no longer leave a deleted card unpaid either, since nothing is
    applied until the commit.

    The inventory pointer ids are looked up BEFORE the transaction on
    purpose: finding them means reading the whole inventory collection, and
    doing that transactionally would lock every card the account owns just to
    delete one pointer. Nothing else can add a pointer for a card that
    already exists (only pack opening creates them, always for a brand new
    card), so the pre-read cannot go stale in a way that matters -- and
    deleting a path that isn't there is a no-op regardless.
    """
    client = AdminFirestoreClient(uid)

    inventory = await client.list_collection(f"users/{uid}/inventory")
    pointer_ids = [doc["id"] for doc in inventory if doc.get("player_id") == req.player_id]

    card_path = f"players/{req.player_id}"
    user_path = f"users/{uid}"

    def _release(tx):
        # Every read first -- Firestore rejects a read after a write, and
        # TransactionScope.get raises locally if this is ever reordered.
        docs = tx.get_all([card_path, user_path])
        card, profile_doc = docs[card_path], docs[user_path]

        if card is None or card.get("owner_uid") != uid:
            # Same 404 for "no such card" and "not yours" -- a different
            # message for the second would confirm someone else's card exists.
            raise HTTPException(404, "You don't own that player")
        if profile_doc is None:
            raise HTTPException(404, "No profile for this account")
        if req.player_id in (profile_doc.get("roster_player_ids") or []):
            raise HTTPException(409, "That player is in your starting XI -- replace them first")

        reward = RELEASE_CREDITS_BY_TIER.get(card.get("tier", ""), RELEASE_CREDITS_DEFAULT)
        remaining = profile_doc.get("credits", 0) + reward

        for pointer_id in pointer_ids:
            tx.delete(f"users/{uid}/inventory/{pointer_id}")
        tx.delete(card_path)
        tx.set(user_path, {"credits": remaining}, merge=True)

        return reward, remaining

    reward, remaining = await client.run_transaction(_release)

    return {
        "player_id": req.player_id,
        "credits_awarded": reward,
        "credits_remaining": remaining,
        "inventory_count": len(inventory) - len(pointer_ids),
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

    The look and the charge COMMIT TOGETHER, for the same reason release
    does: reading the balance and then writing it back is a lost update
    waiting to happen, and two restyles racing each other would otherwise
    both read the same starting balance, with only one charge surviving.
    """
    client = AdminFirestoreClient(uid)

    # Validation needs no reads, so it happens outside: a rejected request
    # should never open a transaction, and a retried body should never redo
    # work that cannot change between attempts.
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

    card_path = f"players/{req.player_id}"
    user_path = f"users/{uid}"

    def _customize(tx):
        docs = tx.get_all([card_path, user_path])
        card, profile_doc = docs[card_path], docs[user_path]

        if card is None or card.get("owner_uid") != uid:
            raise HTTPException(404, "You don't own that player")
        if profile_doc is None:
            raise HTTPException(404, "No profile for this account")
        credits = profile_doc.get("credits", 0)

        # A card written before a slot existed simply has no entry for it, so
        # the comparison below has to run against a fully-populated look or
        # every such slot would read as "changed" and be charged for.
        current = {**DEFAULT_APPEARANCE, **(card.get("appearance") or {})}
        changed = sorted(slot for slot, value in requested.items() if current.get(slot) != value)
        if not changed:
            return current, [], 0, credits  # commits with no writes

        cost = len(changed) * CUSTOMIZE_CREDITS_PER_SLOT
        if credits < cost:
            raise HTTPException(402, f"Not enough credits -- {cost} needed, you have {credits}")

        updated = {**current, **requested}
        tx.set(card_path, {"appearance": updated}, merge=True)
        tx.set(user_path, {"credits": credits - cost}, merge=True)
        return updated, changed, cost, credits - cost

    appearance, changed, cost, remaining = await client.run_transaction(_customize)

    return {
        "player_id": req.player_id,
        "appearance": appearance,
        "slots_changed": changed,
        "credits_spent": cost,
        "credits_remaining": remaining,
    }
