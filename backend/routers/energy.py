"""Energy: reading the bar, and buying it back.

Its own router rather than living in currency.py or tournaments.py, because
it belongs to neither: `/match/quick` spends it too, so it is not
tournament-owned, and it is not currency-catalog work either.

The arithmetic is all in services/energy.py, which has no Firestore and no
FastAPI in it and is unit-tested directly. This file is only the HTTP shape.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import ENERGY_MAX, ENERGY_REFILL_PRODUCTS
from deps import admin_client, verify_id_token
from services import energy as energy_service

router = APIRouter(tags=["energy"])


@router.get("/energy")
async def get_energy(uid: str = Depends(verify_id_token)):
    """The current bar.

    A plain READ -- regen is derived, never persisted here. That keeps GETs
    side-effect-free and saves a Firestore write on every screen open; the
    stored pair is "state as of the last spend" and every reader works it out
    from there.
    """
    client = admin_client(uid)
    doc = await client.get_document(f"users/{uid}")
    current, anchor = energy_service.from_profile(doc)
    return energy_service.describe(current, anchor)


@router.get("/energy/refill/list")
async def list_refill_products(uid: str = Depends(verify_id_token)):
    """The refill catalog, shaped like the credits exchange so the client can
    render it with the existing CurrencyTileView and needs no new component.
    `energy_amount: null` means "fill the bar".
    """
    return {
        "products": [{"product_id": k, **v} for k, v in ENERGY_REFILL_PRODUCTS.items()],
        "energy_max": ENERGY_MAX,
    }


class RefillEnergyRequest(BaseModel):
    product_id: str


@router.post("/energy/refill")
async def refill_energy(req: RefillEnergyRequest, uid: str = Depends(verify_id_token)):
    """Buys energy with bucks.

    Refuses a purchase that would be wasted: buying at a full bar, or buying a
    3-point top-up at 9/10 where two of the three would evaporate, both return
    409 rather than taking the money. Nobody should be able to spend hard
    currency on nothing.
    """
    product = ENERGY_REFILL_PRODUCTS.get(req.product_id)
    if product is None:
        raise HTTPException(404, "Unknown product_id")

    client = admin_client(uid)
    now = energy_service.now_utc()
    user_path = f"users/{uid}"
    cost = product["bucks_cost"]
    amount = product["energy_amount"]

    def _refill(tx):
        doc = tx.get(user_path)
        if doc is None:
            raise HTTPException(404, "No profile for this account")

        current, anchor = energy_service.from_profile(doc, now)
        if current >= ENERGY_MAX:
            raise HTTPException(409, "Your energy is already full")

        target = ENERGY_MAX if amount is None else current + amount
        if target > ENERGY_MAX:
            raise HTTPException(
                409,
                f"That refill would waste {target - ENERGY_MAX} energy -- "
                f"you have room for {ENERGY_MAX - current}",
            )

        bucks = doc.get("bucks", 0)
        if bucks < cost:
            raise HTTPException(402, f"Not enough bucks -- {cost} needed, you have {bucks}")

        # Topping up resets the anchor only when it reaches the cap; a partial
        # refill leaves the carried-forward regen progress alone, so a player
        # doesn't lose 44 banked minutes by buying three points.
        tx.set(
            user_path,
            {
                "bucks": bucks - cost,
                energy_service.ENERGY_FIELD: target,
                energy_service.ENERGY_UPDATED_AT_FIELD: (
                    now.isoformat() if target >= ENERGY_MAX else anchor.isoformat()
                ),
            },
            merge=True,
        )
        return target, anchor, bucks - cost

    target, anchor, bucks_remaining = await client.run_transaction(_refill)
    return {
        **energy_service.describe(target, anchor, now),
        "bucks_remaining": bucks_remaining,
    }
