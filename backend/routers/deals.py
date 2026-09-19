"""Time-limited and capped offers. Structurally the pack catalog again,
with one addition packs never needed: a per-account redemption cap.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import firestore
from pydantic import BaseModel

from admin_firestore_client import AdminFirestoreClient
from deps import game_state_for, verify_id_token
from services import storefront

router = APIRouter(tags=["deals"])


async def _deal_unavailable_reason(
    config: dict, deals_client: AdminFirestoreClient, deal_id: str, uid: str
) -> Optional[str]:
    """Why this deal can't be redeemed by THIS uid right now, or None if it
    can. Structural copy of _pack_unavailable_reason, but async -- the
    per-account cap (max_redemptions_per_account) genuinely needs a
    Firestore read that packs' global-only cap never needed. Shared by
    /deals/list (so a deal you've personally exhausted shows its tag
    instead of a live Buy button, even while still globally available to
    everyone else) and /deals/redeem (which re-checks server-side
    regardless of what the client showed).
    """
    if not config.get("active", False):
        return "This deal is not currently available"

    max_redemptions = config.get("max_redemptions")
    times_redeemed = config.get("times_redeemed", 0)
    if max_redemptions is not None and times_redeemed >= max_redemptions:
        return "This deal is no longer available"

    expires_at = storefront.parse_time(config.get("expires_at"))
    if expires_at is not None and datetime.now(timezone.utc) > expires_at:
        return "This deal has expired"

    max_per_account = config.get("max_redemptions_per_account")
    if max_per_account is not None:
        account_doc = await deals_client.get_document(f"deals/{deal_id}/redemptions/{uid}")
        account_times = account_doc.get("times_redeemed", 0) if account_doc is not None else 0
        if account_times >= max_per_account:
            return "You've already redeemed this deal"

    return None


def _deal_is_teased(config: dict) -> bool:
    """Same opt-in "show it anyway, grayed out" rule packs use -- see
    _pack_is_teased."""
    return bool(config.get("visible")) or config.get("available_at") is not None


@router.get("/deals/list")
async def list_deals(uid: str = Depends(verify_id_token)):
    deals_client = AdminFirestoreClient(uid)
    docs = await deals_client.list_collection("deals")
    deals = []
    for doc in docs:
        unavailable_reason = await _deal_unavailable_reason(doc, deals_client, doc["id"], uid)
        is_available = unavailable_reason is None
        if not is_available and not _deal_is_teased(doc):
            continue  # hidden entirely -- the default for any unavailable deal

        max_redemptions = doc.get("max_redemptions")
        times_redeemed = doc.get("times_redeemed", 0)
        deals.append(
            {
                "deal_id": doc["id"],
                "name": doc.get("name"),
                "description": doc.get("description", ""),
                "cost_currency": doc.get("cost_currency"),
                "cost_amount": doc.get("cost_amount"),
                "reward_credits": doc.get("reward_credits", 0),
                "reward_bucks": doc.get("reward_bucks", 0),
                "max_redemptions": max_redemptions,
                "times_redeemed": times_redeemed,
                "remaining_redemptions": (max_redemptions - times_redeemed) if max_redemptions is not None else None,
                "expires_at": doc.get("expires_at"),
                "available": is_available,
                "unavailable_reason": unavailable_reason,
                "available_at": doc.get("available_at"),
            }
        )
    return {"deals": deals}


class RedeemDealRequest(BaseModel):
    deal_id: str


@router.post("/deals/redeem")
async def redeem_deal(req: RedeemDealRequest, uid: str = Depends(verify_id_token)):
    deals_client = AdminFirestoreClient(uid)
    deal_path = f"deals/{req.deal_id}"
    config = await deals_client.get_document(deal_path)
    if config is None:
        raise HTTPException(404, "Unknown deal_id")
    unavailable_reason = await _deal_unavailable_reason(config, deals_client, req.deal_id, uid)
    if unavailable_reason is not None:
        raise HTTPException(403, unavailable_reason)

    cost_currency = config.get("cost_currency", "credits")
    if cost_currency not in ("credits", "bucks"):
        raise HTTPException(500, f"Deal has unsupported cost_currency: {cost_currency}")

    state = game_state_for(uid)
    profile = await state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])
    cost_amount = config.get("cost_amount", 0)
    if profile[cost_currency] < cost_amount:
        raise HTTPException(402, f"Not enough {cost_currency}")

    new_credits = profile["credits"] + config.get("reward_credits", 0)
    new_bucks = profile["bucks"] + config.get("reward_bucks", 0)
    if cost_currency == "credits":
        new_credits -= cost_amount
    else:
        new_bucks -= cost_amount

    await state.update_profile_fields({"credits": new_credits, "bucks": new_bucks})
    await deals_client.set_document(deal_path, {"times_redeemed": firestore.Increment(1)}, merge=True)
    await deals_client.set_document(
        f"{deal_path}/redemptions/{uid}", {"times_redeemed": firestore.Increment(1)}, merge=True
    )
    return {"credits_remaining": new_credits, "bucks_remaining": new_bucks}
