"""One door for everything a player collects by pressing a button.

POST /claim with a `type` and whatever that type needs to find the thing
being claimed. Every reward that is EARNED silently but PAID on a tap goes
through here, so the client has one call to make and one response shape to
read, whatever it is claiming -- today the full-day tournament reward,
later a season pass tier, a daily login streak, an achievement.

Each type is a handler in CLAIM_HANDLERS: it validates its own fields,
runs its own transaction (the pay-once guarantee lives in the service that
owns the reward, not here), and returns the rewards paid plus the balances
after. Adding a claimable is one handler and one dict entry.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import PACK_PRICE_CURRENCIES
from deps import admin_client, verify_id_token
from services import energy as energy_service
from services import tournament as tournament_service

router = APIRouter(tags=["claims"])


class ClaimRequest(BaseModel):
    type: str
    # Type-specific. Optional so a client can send only what its type needs.
    day_id: str = ""
    group_id: str = ""


async def _claim_tournament_full_day(client, uid: str, req: ClaimRequest) -> dict:
    """The play-every-match reward for one tournament entry -- today's by
    default, or any day's given day_id + group_id (the results screen
    knows both), so a reward earned late last night is still collectable
    from the results popup the next morning."""
    day_id, group_id = req.day_id, req.group_id
    if not day_id or not group_id:
        profile = await client.get_document(f"users/{uid}")
        today = tournament_service.day_id_for(energy_service.now_utc())
        if (profile or {}).get("tournament_day_id") != today:
            raise HTTPException(409, "You are not in today's tournament")
        day_id, group_id = today, (profile or {}).get("tournament_group_id") or ""
        if not group_id:
            raise HTTPException(409, "You are not in today's tournament")

    try:
        return await tournament_service.claim_full_day(client, uid, day_id, group_id)
    except tournament_service.NotClaimable as exc:
        raise HTTPException(
            {"no_entry": 404, "already_claimed": 409, "not_earned": 409}[exc.reason],
            {
                "no_entry": "No tournament entry to claim for",
                "already_claimed": "Already claimed",
                "not_earned": "Play every match first",
            }[exc.reason],
        ) from exc


CLAIM_HANDLERS: dict[str, Callable[..., Awaitable[dict]]] = {
    "tournament_full_day": _claim_tournament_full_day,
}


@router.post("/claim")
async def claim(req: ClaimRequest, uid: str = Depends(verify_id_token)):
    """Pays one claimable reward. 400 for a type this build doesn't know,
    404/409 from the handler when there is nothing to pay.

    The response carries every balance the reward could have touched, in
    the same *_remaining names /pack/open and the currency endpoints use,
    so GameProfile.apply_currency_balances takes it as-is.
    """
    handler = CLAIM_HANDLERS.get(req.type)
    if handler is None:
        raise HTTPException(400, f"Unknown claim type: {req.type!r}")

    client = admin_client(uid)
    paid = await handler(client, uid, req)

    # Anything the reward didn't touch is filled from the profile as it
    # stands, so the client can overwrite all three without a second read.
    balances = dict(paid.get("balances") or {})
    missing = [c for c in PACK_PRICE_CURRENCIES if c not in balances]
    if missing:
        profile = await client.get_document(f"users/{uid}") or {}
        for currency in missing:
            balances[currency] = int(profile.get(currency, 0))

    return {
        "type": req.type,
        "rewards": paid.get("rewards") or {},
        **{f"{currency}_remaining": balances[currency] for currency in PACK_PRICE_CURRENCIES},
    }
