from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import config
from admin_firestore_client import AdminFirestoreClient
from deps import verify_id_token

router = APIRouter(tags=["ads"])

class ClaimAdRequest(BaseModel):
    # The client will send "reward" or "energy", extendable
    track: str 

@router.post("/ads/reward")
async def claim_ad_reward(req: ClaimAdRequest, uid: str = Depends(verify_id_token)):
    """
    Grants a reward for watching an ad and handles the daily lazy reset.
    """
    if req.track not in ("reward", "energy"):
        raise HTTPException(400, "Invalid ad track requested.")

    # Determine the current "Game Date" string
    # We subtract the offset so that 11:59 AM in Istanbul still counts as "yesterday",
    # matching the exact logic used for daily tournaments
    now = datetime.now(timezone.utc)
    shifted = now - timedelta(hours=config.TOURNAMENT_DAY_OFFSET_HOURS)
    current_game_date = shifted.strftime("%Y-%m-%d")

    client = AdminFirestoreClient(uid)
    user_path = f"users/{uid}"

    def _grant_ad_reward(tx):
        profile_doc = tx.get(user_path)
        if profile_doc is None:
            raise HTTPException(404, "Profile not found")

        # Read the current lazy state
        last_date = profile_doc.get("last_ad_date", "")
        reward_ads_watched = profile_doc.get("reward_ads_watched", 0)
        energy_ads_watched = profile_doc.get("energy_ads_watched", 0)

        # The Lazy Reset: Wipe counters if the day rolled over
        if last_date != current_game_date:
            reward_ads_watched = 0
            energy_ads_watched = 0
            last_date = current_game_date

        updates = {"last_ad_date": last_date}
        response_data = {}

        # Handle the specific track logic
        if req.track == "reward":
            if reward_ads_watched >= len(config.AD_REWARD_PATH):
                raise HTTPException(429, "You have reached your daily limit for reward ads.")
            
            # Fetch the specific reward for their current step
            reward = config.AD_REWARD_PATH[reward_ads_watched]
            
            new_credits = profile_doc.get("credits", 0) + reward.get("credits", 0)
            new_bucks = profile_doc.get("bucks", 0) + reward.get("bucks", 0)
            new_count = reward_ads_watched + 1
            
            updates["credits"] = new_credits
            updates["bucks"] = new_bucks
            updates["reward_ads_watched"] = new_count
            
            response_data = {
                "credits_remaining": new_credits,
                "bucks_remaining": new_bucks,
                "reward_ads_watched": new_count,
                "reward_ads_max": len(config.AD_REWARD_PATH),
                "track": req.track
            }

        elif req.track == "energy":
            if energy_ads_watched >= config.AD_ENERGY_MAX:
                raise HTTPException(429, "You have reached your daily limit for energy ads.")
            
            from services import energy as energy_service
            now = energy_service.now_utc()
            current_energy, anchor = energy_service.from_profile(profile_doc, now)
            
            if current_energy >= config.ENERGY_MAX:
                raise HTTPException(400, "Your energy is already full.")
                
            new_energy = min(config.ENERGY_MAX, current_energy + config.AD_ENERGY_REWARD)
            new_count = energy_ads_watched + 1
            
            updates[energy_service.ENERGY_FIELD] = new_energy
            updates[energy_service.ENERGY_UPDATED_AT_FIELD] = (
                now.isoformat() if new_energy >= config.ENERGY_MAX else anchor.isoformat()
            )
            updates["energy_ads_watched"] = new_count

        tx.set(user_path, updates, merge=True)
        return response_data

    return await client.run_transaction(_grant_ad_reward)