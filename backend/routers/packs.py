"""The pack catalog, and opening one.

Opening is server-authoritative for the reason the whole backend exists: a
client that rolled its own cards could simply tell us it pulled an icon.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import firestore
from pydantic import BaseModel

from config import INVENTORY_CAP, PACK_PRICE_CURRENCIES
from admin_firestore_client import AdminFirestoreClient
from deps import game_state_for, verify_id_token
from engine import PackManager, player_to_fields

router = APIRouter(tags=["packs"])


def _parse_time(value) -> Optional[datetime]:
    """A pack's expires_at / available_at as an aware datetime, or None when
    absent or malformed. Firestore hands back a datetime for a timestamp
    field and a string for one written as ISO text; both are accepted, and
    a naive value is taken as UTC. Malformed fails OPEN (None), so a typo
    in an admin-set field never blocks opening."""
    if not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _pack_unavailable_reason(config: dict) -> Optional[str]:
    """Why this pack can't be opened right now, or None if it can. Shared by
    /pack/open (to reject one) and /pack/list (to filter the catalog down
    to what's actually purchasable) so the two never disagree.

    "max_opens" and "expires_at" are optional Firestore-only fields (see
    pack_database.py's own docstring) -- absent means unlimited/never
    expires, matching every pack that predates this check.
    """
    if not config.get("active", False):
        return "This pack is not currently available"

    max_opens = config.get("max_opens")
    times_opened = config.get("times_opened", 0)
    if max_opens is not None and times_opened >= max_opens:
        return "This pack has sold out"

    pack_expiry = _parse_time(config.get("expires_at"))
    if pack_expiry is not None and datetime.now(timezone.utc) > pack_expiry:
        return "This pack has expired"

    return None


def _activation_due(config: dict) -> bool:
    """An inactive pack whose planned on-sale time has come."""
    if config.get("active", False):
        return False
    available_at = _parse_time(config.get("available_at"))
    return available_at is not None and datetime.now(timezone.utc) >= available_at


async def _activate_if_due(client: AdminFirestoreClient, pack_path: str, config: dict) -> dict:
    """Puts a pack on sale the first time anyone looks at it after its
    available_at -- there is no scheduler in this project, so the shop
    itself is the trigger, the same way tournaments settle lazily.

    Writes `active: true` and DELETES available_at in one merge. Deleting
    is what makes this fire exactly once: an admin who later pulls the
    pack (active back to false) doesn't get it re-activated by the next
    /pack/list, because the date that would have done so is gone. Two
    concurrent requests both activating is harmless -- identical writes.

    Returns the config as it now stands, so the caller sees the pack as
    purchasable in the same request rather than one refresh later.
    """
    if not _activation_due(config):
        return config
    await client.set_document(
        pack_path, {"active": True, "available_at": firestore.DELETE_FIELD}, merge=True
    )
    updated = {k: v for k, v in config.items() if k != "available_at"}
    updated["active"] = True
    return updated


def _pack_is_teased(config: dict) -> bool:
    """A pack that's currently unavailable but should still be shown
    (grayed out, tagged with why -- see PackData.tag_text() on the Godot
    side) instead of hidden outright, e.g. a Champions Promo pack previewed
    ahead of its real on-sale date. Opt-in only, via either of two
    Firestore-only fields an admin sets directly on the pack's doc (no
    redeploy): "visible": true, and/or "available_at" (which alone implies
    it -- setting a planned on-sale date is itself a decision to preview
    the pack). Every pack that predates these fields keeps today's
    default: an unavailable pack is hidden, full stop.
    """
    return bool(config.get("visible")) or config.get("available_at") is not None


@router.get("/pack/list")
async def list_packs(uid: str = Depends(verify_id_token)):
    """Every pack worth showing in the shop right now: everything actually
    purchasable, plus any currently-unavailable pack an admin opted into
    still previewing (see _pack_is_teased). This is purely "what to show",
    not the source of truth for "what's allowed" -- /pack/open enforces
    _pack_unavailable_reason independently regardless of what this
    returned, so a teased pack's Buy button being disabled client-side
    isn't the only thing stopping someone from opening it early.
    """
    client = AdminFirestoreClient(uid)
    docs = await client.list_collection("packs")
    packs = []
    for doc in docs:
        doc = await _activate_if_due(client, f"packs/{doc['id']}", doc)
        unavailable_reason = _pack_unavailable_reason(doc)
        is_available = unavailable_reason is None
        if not is_available and not _pack_is_teased(doc):
            continue  # hidden entirely -- the default for any unavailable pack

        max_opens = doc.get("max_opens")
        times_opened = doc.get("times_opened", 0)
        packs.append(
            {
                "pack_id": doc["id"],
                "order": doc.get("order", 0),
                "name": doc.get("name"),
                "type": doc.get("type", "standard"),
                "description": doc.get("description", ""),
                "price": doc.get("price"),
                "price_currency": doc.get("price_currency", "credits"),
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
                "sprite_key":doc.get("sprite_key"),
            }
        )
    # Shop order is the catalog's own `order` field (pack_database.py), not
    # the document id -- ids are slugs, and alphabetical is not a shop.
    packs.sort(key=lambda p: (p["order"], p["pack_id"]))
    return {"packs": packs}


class OpenPackRequest(BaseModel):
    pack_id: str  # the pack's slug, packs/{pack_id} -- see pack_database.py


@router.post("/pack/open")
async def open_pack(req: OpenPackRequest, uid: str = Depends(verify_id_token)):
    packs_client = AdminFirestoreClient(uid)
    pack_path = f"packs/{req.pack_id}"
    config = await packs_client.get_document(pack_path)
    if config is None:
        raise HTTPException(404, "Unknown pack_id")
    # A tap right on the on-sale minute can reach here before any /pack/list
    # did the flip -- same rule, so it opens rather than 403s.
    config = await _activate_if_due(packs_client, pack_path, config)
    unavailable_reason = _pack_unavailable_reason(config)
    if unavailable_reason is not None:
        raise HTTPException(403, unavailable_reason)

    state = game_state_for(uid)
    profile = await state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])

    inventory = await state.client.list_collection(f"users/{uid}/inventory")
    cards_per_pack = int(config.get("cards_per_pack") or 1)
    if len(inventory) + cards_per_pack > INVENTORY_CAP:
        raise HTTPException(
            409,
            f"Your inventory is full ({len(inventory)}/{INVENTORY_CAP}) -- "
            f"release players to make room for {cards_per_pack} more",
        )

    price_currency = config.get("price_currency", "credits")
    if price_currency not in PACK_PRICE_CURRENCIES:
        raise HTTPException(500, f"Pack has unsupported price_currency: {price_currency}")

    price = config["price"]
    if profile[price_currency] < price:
        raise HTTPException(402, f"Not enough {price_currency}")

    seed = secrets.randbits(63)
    cards = PackManager({req.pack_id: config}, seed=seed).open_pack(req.pack_id)

    remaining = profile[price_currency] - price
    await state.update_profile_fields({price_currency: remaining})
    for card in cards:
        await state.add_inventory_card(card)
    await packs_client.set_document(pack_path, {"times_opened": firestore.Increment(1)}, merge=True)

    # Every balance, not just the one spent: the client mirrors all three
    # and shouldn't have to guess which one moved. credits_remaining stays
    # in the response under its original name so nothing that already reads
    # it breaks.
    balances = {currency: profile[currency] for currency in PACK_PRICE_CURRENCIES}
    balances[price_currency] = remaining
    return {
        "seed": seed,
        "credits_remaining": balances["credits"],
        "bucks_remaining": balances["bucks"],
        "medals_remaining": balances["medals"],
        "inventory_count": len(inventory) + len(cards),
        "inventory_cap": INVENTORY_CAP,
        "cards": [
            {**player_to_fields(c), "player_id": c.player_id, "doc_id": getattr(c, "doc_id", None)}
            for c in cards
        ],
    }
