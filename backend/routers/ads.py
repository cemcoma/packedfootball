"""Rewarded ads. The grant is driven by AdMob's server-side verification
callback, never by the client -- see services/ads.py."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from admin_firestore_client import AdminFirestoreClient
from deps import verify_id_token
from services import ads as ads_service
from services import energy as energy_service

router = APIRouter(tags=["ads"])


@router.get("/ads/ssv")
async def admob_server_side_verification(request: Request):
    """AdMob's callback for a finished rewarded ad. Unauthenticated: the
    query string is signed by Google (services/ads.verify_signature), and
    `user_id` / `custom_data` are what the client attached to the ad
    (its uid and the track), covered by that signature.

    Answers 200 for anything but a bad signature -- AdMob retries non-2xx
    callbacks, and a reward refused today (cap reached, energy full) or an
    already-paid transaction is refused again on every retry.
    ad_ssv_grants/{transaction_id} is the anti-replay guard.
    """
    params = request.query_params
    signature = params.get("signature", "")
    key_id = params.get("key_id", "")
    if not signature or not key_id:
        raise HTTPException(400, "Missing signature")
    raw_query = request.url.query.encode("utf-8")
    verified = await asyncio.to_thread(ads_service.verify_signature, raw_query, signature, key_id)
    if not verified:
        raise HTTPException(401, "Bad signature")

    uid = params.get("user_id", "")
    track = params.get("custom_data", "")
    transaction_id = params.get("transaction_id", "")
    if not uid or not transaction_id or track not in ads_service.TRACKS:
        # The console's "verify URL" test ping, or an ad shown without our
        # SSV options: nothing to pay, nothing to retry.
        return {"status": "ignored"}

    client = AdminFirestoreClient(uid)
    grant_path = f"ad_ssv_grants/{transaction_id}"
    user_path = f"users/{uid}"

    def _grant(tx):
        if tx.get(grant_path) is not None:
            return {"status": "already_processed"}
        now = energy_service.now_utc()
        record = {
            "uid": uid,
            "track": track,
            "ad_unit": params.get("ad_unit", ""),
            "reward_item": params.get("reward_item", ""),
            "reward_amount": params.get("reward_amount", ""),
            "admob_timestamp": params.get("timestamp", ""),
            "received_at": now.isoformat(),
        }
        try:
            paid = ads_service.grant_in_tx(tx, user_path, track, now)
        except ads_service.AdRewardRefused as refused:
            record["status"] = "refused"
            record["reason"] = str(refused)
            tx.set(grant_path, record, merge=False)
            return {"status": "refused", "reason": str(refused)}
        record["status"] = "granted"
        record["paid"] = {k: v for k, v in paid.items() if k != "track"}
        tx.set(grant_path, record, merge=False)
        return {"status": "granted"}

    return await client.run_transaction(_grant)


@router.get("/ads/status")
async def ad_status(uid: str = Depends(verify_id_token)):
    """Today's ad counters and the balances they feed. The client polls
    this after a rewarded ad until the track's counter moves -- the grant
    arrives from AdMob, not from the client's own request."""
    client = AdminFirestoreClient(uid)
    profile = await client.get_document(f"users/{uid}") or {}
    now = energy_service.now_utc()
    energy, anchor = energy_service.from_profile(profile, now)
    return {
        **ads_service.counters(profile, ads_service.game_date(now)),
        "credits_remaining": int(profile.get("credits", 0)),
        "bucks_remaining": int(profile.get("bucks", 0)),
        "energy": energy_service.describe(energy, anchor, now),
        "last_ad_grant_at": profile.get("last_ad_grant_at", ""),
        "server_time": datetime.now(timezone.utc).isoformat(),
    }
