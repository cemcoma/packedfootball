"""Owning a card: releasing it for credits, or paying to restyle it.

Both move credits and mutate a players/{id} document, which is exactly the
pair firestore.rules denies the client outright -- so neither can be a
direct client write the way saving a lineup or a kit is.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import (
    CUSTOMIZE_CREDITS_PER_SLOT,
    INVENTORY_CAP,
    RELEASE_BATCH_MAX,
    RELEASE_CREDITS_BY_TIER,
    RELEASE_CREDITS_DEFAULT,
)
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
    result = await _release_cards(uid, [req.player_id])
    per_card = result["released"][0]

    return {
        "player_id": per_card["player_id"],
        "credits_awarded": per_card["credits_awarded"],
        "credits_remaining": result["credits_remaining"],
        "inventory_count": result["inventory_count"],
        "inventory_cap": INVENTORY_CAP,
    }


class ReleasePlayersRequest(BaseModel):
    player_ids: list[str]


@router.post("/player/release/batch")
async def release_players(req: ReleasePlayersRequest, uid: str = Depends(verify_id_token)):
    """Releases several benched cards at once -- the Inventory screen's
    multi-select "quick sell".

    ALL OR NOTHING, in a single transaction. Selling 30 cards through 30
    calls to /player/release would be 30 chances to half-succeed: a dropped
    connection or a mid-run 409 leaves the player looking at a bench that is
    partly gone and a balance they can't reconcile, with nothing to retry
    safely (the succeeded half would be charged twice). One transaction
    means the answer is always "all of them, for this much" or "none of
    them, because of this" -- and the client's confirm dialog quoted a total
    that is still the total when it lands.

    A player in the XI aborts the WHOLE batch rather than being skipped.
    Silently dropping one card from a 30-card sale, after showing a total
    that included it, is worse than refusing and saying which one -- and the
    client filters XI cards out of selection anyway, so reaching this means
    the two disagree and proceeding would be guessing.
    """
    # Order-preserving dedupe: the same id twice must not pay twice, and a
    # set() would make the error messages below non-deterministic.
    player_ids = list(dict.fromkeys(req.player_ids))

    if not player_ids:
        raise HTTPException(400, "No players selected")
    if len(player_ids) > RELEASE_BATCH_MAX:
        raise HTTPException(
            400, f"Too many players at once -- {RELEASE_BATCH_MAX} is the limit"
        )

    return {**await _release_cards(uid, player_ids), "inventory_cap": INVENTORY_CAP}


async def _release_cards(uid: str, player_ids: list[str]) -> dict:
    """The one implementation of releasing cards, shared by both endpoints
    above so the rules can never drift apart between them.

    `player_ids` must already be deduped and non-empty.
    """
    client = AdminFirestoreClient(uid)

    # One read of the inventory collection for the whole batch, mapping every
    # card to its pointer docs -- see the single-release docstring for why
    # this sits outside the transaction.
    inventory = await client.list_collection(f"users/{uid}/inventory")
    wanted = set(player_ids)
    pointers_by_player: dict[str, list[str]] = {pid: [] for pid in player_ids}
    for doc in inventory:
        pid = doc.get("player_id")
        if pid in wanted:
            pointers_by_player[pid].append(doc["id"])

    card_paths = [f"players/{pid}" for pid in player_ids]
    user_path = f"users/{uid}"

    def _release(tx):
        # Every read first -- Firestore rejects a read after a write, and
        # TransactionScope.get raises locally if this is ever reordered.
        docs = tx.get_all([*card_paths, user_path])
        profile_doc = docs[user_path]
        if profile_doc is None:
            raise HTTPException(404, "No profile for this account")
        roster = set(profile_doc.get("roster_player_ids") or [])

        # Validate the entire batch BEFORE writing anything, so a bad id in
        # the middle of the list can't leave earlier deletes staged.
        released = []
        for pid in player_ids:
            card = docs[f"players/{pid}"]
            if card is None or card.get("owner_uid") != uid:
                # Same 404 for "no such card" and "not yours" -- a different
                # message for the second would confirm someone else's card
                # exists.
                raise HTTPException(404, f"You don't own player {pid}")
            if pid in roster:
                raise HTTPException(
                    409, f"Player {pid} is in your starting XI -- replace them first"
                )
            released.append(
                {
                    "player_id": pid,
                    "credits_awarded": RELEASE_CREDITS_BY_TIER.get(
                        card.get("tier", ""), RELEASE_CREDITS_DEFAULT
                    ),
                }
            )

        total = sum(entry["credits_awarded"] for entry in released)
        remaining = profile_doc.get("credits", 0) + total

        deleted_pointers = 0
        for pid in player_ids:
            for pointer_id in pointers_by_player[pid]:
                tx.delete(f"users/{uid}/inventory/{pointer_id}")
                deleted_pointers += 1
            tx.delete(f"players/{pid}")
        tx.set(user_path, {"credits": remaining}, merge=True)

        return released, total, remaining, deleted_pointers

    released, total, remaining, deleted_pointers = await client.run_transaction(_release)

    return {
        "released": released,
        "credits_awarded": total,
        "credits_remaining": remaining,
        "inventory_count": len(inventory) - deleted_pointers,
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
