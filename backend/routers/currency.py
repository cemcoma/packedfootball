"""Soft/hard currency: the credits exchange, the bucks catalog, and the
RevenueCat webhook that actually grants a real-money purchase.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from config import BUCKS_IAP_CATALOG, CREDIT_EXCHANGE_RATES, REVENUECAT_WEBHOOK_SECRET
from admin_firestore_client import AdminFirestoreClient
from deps import game_state_for, verify_id_token

router = APIRouter(tags=["currency"])


@router.get("/currency/exchange/list")
async def list_exchange_rates(uid: str = Depends(verify_id_token)):
    """The Credits Exchange tab's catalog -- fixed, code-defined rates (not
    Firestore-backed like packs/deals, since these aren't meant to be
    admin-editable without a redeploy). Returned rather than hardcoded
    client-side so the client never has to duplicate these numbers.
    """
    return {"rates": [{"tier_id": k, **v} for k, v in CREDIT_EXCHANGE_RATES.items()]}


class RedeemExchangeRequest(BaseModel):
    tier_id: str


@router.post("/currency/exchange/redeem")
async def redeem_exchange(req: RedeemExchangeRequest, uid: str = Depends(verify_id_token)):
    tier = CREDIT_EXCHANGE_RATES.get(req.tier_id)
    if tier is None:
        raise HTTPException(404, "Unknown tier_id")

    state = game_state_for(uid)
    profile = await state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])
    if profile["bucks"] < tier["bucks_cost"]:
        raise HTTPException(402, "Not enough bucks")

    new_bucks = profile["bucks"] - tier["bucks_cost"]
    new_credits = profile["credits"] + tier["credits_reward"]
    # One combined write (rather than two separate set_bucks/set_credits
    # calls) so a crash mid-redeem can't leave bucks deducted with the
    # credits reward never actually landing.
    await state.update_profile_fields({"bucks": new_bucks, "credits": new_credits})
    return {"bucks_remaining": new_bucks, "credits_remaining": new_credits}


@router.get("/currency/bucks/list")
async def list_bucks_catalog(uid: str = Depends(verify_id_token)):
    """The Bucks tab's real-money catalog. product_id is what the client
    passes to the platform IAP plugin (App Store today -- see
    mobile/scripts/autoload/IapClient.gd) to start a real purchase.
    usd_reference_price_cents is a display fallback only; once a real IAP
    plugin is wired client-side, prefer StoreKit's own localized price per
    product over this field -- Apple owns actual regional pricing.
    """
    return {"products": [{"product_id": k, **v} for k, v in BUCKS_IAP_CATALOG.items()]}


# RevenueCat's own "store" values -> this project's existing platform naming
# (iap_transactions records have always used "appstore"/"playstore"/"web";
# keep that convention rather than storing RevenueCat's raw enum values).
REVENUECAT_STORE_TO_PLATFORM = {
    "APP_STORE": "appstore",
    "PLAY_STORE": "playstore",
    "STRIPE": "web",
    "RC_BILLING": "web",
}


async def verify_revenuecat_webhook(authorization: str = Header(default="")) -> None:
    """RevenueCat signs webhook requests with whatever literal string you
    configure as the "Authorization header value" in their dashboard --
    not HMAC-signed, just an exact shared-secret match, so this compares
    the raw header against REVENUECAT_WEBHOOK_SECRET directly (constant-
    time, to not leak the secret's length/contents through timing). Fails
    closed if the env var isn't set at all -- an empty configured secret
    must never make every request "match" by both sides being empty.
    """
    if not REVENUECAT_WEBHOOK_SECRET or not hmac.compare_digest(authorization, REVENUECAT_WEBHOOK_SECRET):
        raise HTTPException(401, "Invalid webhook authorization")


@router.post("/webhooks/revenuecat", dependencies=[Depends(verify_revenuecat_webhook)])
async def revenuecat_webhook(payload: dict):
    """Grants bucks for a real-money purchase RevenueCat has already
    verified with Apple/Google itself -- this is the one endpoint in the
    whole Bucks feature that must never trust the CLIENT, but it fully
    trusts RevenueCat (gated by verify_revenuecat_webhook above) the same
    way /pack/open trusts this server's own RNG. Replaces the earlier
    design where the client sent a raw platform receipt directly here for
    this server to verify against Apple itself -- RevenueCat now owns that
    verification, and calls this independently of whether the client that
    made the purchase is even still running by the time this lands.

    Only handles NON_RENEWING_PURCHASE (RevenueCat's event type for a
    consumable, one-time purchase -- exactly what a bucks top-up is, not a
    subscription). Any other event type is acknowledged with 200 and
    ignored, not rejected -- RevenueCat retries non-2xx responses
    indefinitely, and an event type this endpoint will never care about
    should never end up in an infinite retry loop.

    iap_transactions/{event_id} is the anti-replay guard, same mechanism
    the pre-RevenueCat design already used -- just keyed by RevenueCat's
    own event id instead of a raw Apple transaction id now.
    """
    event = payload.get("event", {})
    if event.get("type") != "NON_RENEWING_PURCHASE":
        return {"status": "ignored", "reason": f"event type {event.get('type')!r} not handled"}

    event_id = event.get("id")
    uid = event.get("app_user_id")
    product_id = event.get("product_id")
    if not event_id or not uid or not product_id:
        raise HTTPException(400, "Missing required event fields")

    product = BUCKS_IAP_CATALOG.get(product_id)
    if product is None:
        # Not one of our bucks products -- ack without granting, don't retry-loop forever.
        return {"status": "ignored", "reason": f"unknown product_id {product_id!r}"}

    txn_client = AdminFirestoreClient(uid)
    txn_path = f"iap_transactions/{event_id}"
    if await txn_client.get_document(txn_path) is not None:
        return {"status": "already_processed"}

    state = game_state_for(uid)
    profile = await state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])
    new_bucks = profile["bucks"] + product["bucks_amount"]
    await state.set_bucks(new_bucks)
    await txn_client.set_document(
        txn_path,
        {
            "uid": uid,
            "product_id": product_id,
            "platform": REVENUECAT_STORE_TO_PLATFORM.get(event.get("store", ""), event.get("store", "").lower()),
            "bucks_granted": product["bucks_amount"],
            "redeemed_at": datetime.now(timezone.utc).isoformat(),
        },
        merge=False,
    )
    return {"status": "granted", "bucks_remaining": new_bucks}
