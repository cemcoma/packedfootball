"""Equipment: socketing an item into a card, and scrapping the spares.

Both move things that are worth credits, so neither can be a direct client
write -- the same reason /player/release lives here rather than in
firestore.rules.

The one rule worth stating out loud: SOCKETING IS ONE-WAY. An item that goes
onto a card never comes off; replacing one destroys it with no refund. That is
the economy, not an oversight (packedfootball/items.py says why), and it makes
every equip irreversible -- so the endpoint refuses to guess. An occupied slot
is only overwritten when the request names the item being destroyed.

Neither endpoint touches a collection: an equipped item is a field on
players/{id} and a spare is an entry on users/{uid}, so both are path reads
and both fit inside a transaction (see TransactionScope's "BY PATH ONLY").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import (
    ITEM_SCRAP_BATCH_MAX,
    ITEM_SCRAP_CREDITS_BY_RARITY,
    ITEM_SCRAP_CREDITS_DEFAULT,
)
from admin_firestore_client import AdminFirestoreClient
from deps import verify_id_token
from engine import item_rules, tier_family

router = APIRouter(tags=["items"])


def _scrap_value(item: dict) -> int:
    """By rarity FAMILY, so a future themed variant pays its family's rate
    rather than the unknown floor -- mirrors _release_cards."""
    return ITEM_SCRAP_CREDITS_BY_RARITY.get(
        tier_family(str(item.get("r", ""))), ITEM_SCRAP_CREDITS_DEFAULT
    )


def _find(pool: list[dict], item_id: str) -> dict | None:
    return next((i for i in pool if i.get("id") == item_id), None)


class EquipItemRequest(BaseModel):
    player_id: str
    item_id: str
    # The item already on the card that this one replaces. Needed only when
    # every slot is full, and it is DESTROYED -- see the module docstring.
    replaces_item_id: str | None = None


@router.post("/item/equip")
async def equip_item(req: EquipItemRequest, uid: str = Depends(verify_id_token)):
    """Moves one item out of the caller's pool and onto one of their cards.

    Transactional, and it has to be: the item leaves users/{uid} and arrives
    on players/{id}, and a crash between the two would either duplicate it or
    lose it. The card is read inside the transaction too, so two requests
    racing for the last free slot cannot both take it.

    Returns the card's whole item list rather than just the new entry: the
    client folds the SERVER's state back in (the way CustomizePlayer does)
    instead of applying its own guess.
    """
    client = AdminFirestoreClient(uid)
    user_path = f"users/{uid}"
    player_path = f"players/{req.player_id}"

    def _equip(tx):
        # Every read before every write -- TransactionScope enforces it.
        docs = tx.get_all([player_path, user_path])
        card = docs[player_path]
        profile = docs[user_path]
        if card is None or card.get("owner_uid") != uid:
            # One message for "no such card" and "not yours": a different one
            # for the second would confirm someone else's card exists.
            raise HTTPException(404, "You don't own that card")
        if profile is None:
            raise HTTPException(404, "No profile for this account")

        pool = item_rules.sanitize_pool(profile.get("item_pool"))
        item = _find(pool, req.item_id)
        if item is None:
            raise HTTPException(404, "You don't own that item")

        position = card.get("position", "")
        equipped = item_rules.sanitize(card.get("items"), position)

        destroyed = None
        if req.replaces_item_id:
            destroyed = _find(equipped, req.replaces_item_id)
            if destroyed is None:
                raise HTTPException(404, "That card has no such item")
            equipped = [i for i in equipped if i.get("id") != req.replaces_item_id]

        reason = item_rules.can_equip(equipped, item, position)
        if reason is not None:
            # 409 rather than 400: a full card is the one rejection the client
            # can act on, by re-asking with the item to destroy named.
            raise HTTPException(409, reason)

        equipped.append(item)
        remaining = [i for i in pool if i.get("id") != req.item_id]

        tx.set(player_path, {"items": equipped}, merge=True)
        tx.set(user_path, {"item_pool": remaining}, merge=True)
        return equipped, destroyed, remaining

    equipped, destroyed, remaining = await client.run_transaction(_equip)
    return {
        "player_id": req.player_id,
        "items": equipped,
        "destroyed": destroyed,
        "item_pool": remaining,
    }


class ScrapItemsRequest(BaseModel):
    item_ids: list[str]


@router.post("/item/scrap")
async def scrap_items(req: ScrapItemsRequest, uid: str = Depends(verify_id_token)):
    """Destroys unequipped items for credits -- the Items screen's quick sell.

    Only ever touches the pool. An item already on a card is gone for good and
    has no scrap value, which is the whole point of socketing being one-way.

    ALL OR NOTHING, like /player/release/batch: one bad id fails the request
    rather than scrapping the rest, so the client never has to work out which
    half of its selection went through.
    """
    if not req.item_ids:
        raise HTTPException(400, "No items given")
    if len(req.item_ids) > ITEM_SCRAP_BATCH_MAX:
        raise HTTPException(400, f"At most {ITEM_SCRAP_BATCH_MAX} items at a time")

    client = AdminFirestoreClient(uid)
    user_path = f"users/{uid}"
    wanted = list(dict.fromkeys(req.item_ids))  # de-duplicated, order kept

    def _scrap(tx):
        profile = tx.get(user_path)
        if profile is None:
            raise HTTPException(404, "No profile for this account")

        pool = item_rules.sanitize_pool(profile.get("item_pool"))
        by_id = {i["id"]: i for i in pool}
        missing = [i for i in wanted if i not in by_id]
        if missing:
            raise HTTPException(404, "You don't own all of those items")

        scrapping = [by_id[i] for i in wanted]
        awarded = sum(_scrap_value(i) for i in scrapping)
        gone = set(wanted)
        remaining = [i for i in pool if i["id"] not in gone]
        credits = int(profile.get("credits", 0)) + awarded

        tx.set(user_path, {"item_pool": remaining, "credits": credits}, merge=True)
        return wanted, awarded, credits, remaining

    scrapped, awarded, credits, remaining = await client.run_transaction(_scrap)
    return {
        "scrapped": scrapped,
        "credits_awarded": awarded,
        "credits_remaining": credits,
        "item_pool": remaining,
    }
