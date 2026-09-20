"""Rewarded ads, paid only on AdMob's word.

The client never claims an ad reward itself. When a viewer finishes a
rewarded ad, AdMob calls GET /ads/ssv (server-side verification) with the
user id and track the client attached to the ad, signed with one of
Google's rotating ECDSA keys; `verify_signature` checks that, and
`grant_in_tx` pays the next step of the track. AdMob retries a non-2xx
callback, so a reward that is REFUSED (daily cap, energy full) is still
answered 200 -- refusing again on retry gains nothing.

The daily counters reset lazily on the tournament day boundary
(`game_date`), the same clock the rest of the economy keeps.
"""

from __future__ import annotations

import base64
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_public_key

import config
from services import energy as energy_service

TRACKS = ("reward", "energy")

# Google publishes the public keys AdMob signs SSV callbacks with here; they
# rotate, so an unknown key_id triggers one refetch before it is refused.
VERIFIER_KEYS_URL = "https://www.gstatic.com/admob/reward/verifier-keys.json"
VERIFIER_KEYS_TTL_SECONDS = 24 * 3600

# AdMob's test callback (the "Verify URL" button in the console) is signed
# and comes with a placeholder user; it must be answered 200 too.
_keys_lock = threading.Lock()
_keys: dict[str, object] = {}
_keys_fetched_at = 0.0


class AdRewardRefused(Exception):
    """The reward is not payable right now -- cap reached, energy full."""


def game_date(now: datetime | None = None) -> str:
    """The reward day, on the tournament clock: shifted so the day rolls at
    noon Istanbul, not midnight UTC."""
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(hours=config.TOURNAMENT_DAY_OFFSET_HOURS)).strftime("%Y-%m-%d")


def counters(profile: dict | None, today: str | None = None) -> dict:
    """The profile's ad counters as they stand today -- zero once the day
    has rolled, whatever the doc still says."""
    profile = profile or {}
    today = today or game_date()
    rolled = profile.get("last_ad_date", "") != today
    return {
        "reward_ads_watched": 0 if rolled else int(profile.get("reward_ads_watched", 0)),
        "reward_ads_max": len(config.AD_REWARD_PATH),
        "energy_ads_watched": 0 if rolled else int(profile.get("energy_ads_watched", 0)),
        "energy_ads_max": config.AD_ENERGY_MAX,
    }


def grant_in_tx(tx, user_path: str, track: str, now: datetime | None = None) -> dict:
    """Pays the next step of `track` for the profile at `user_path`, inside
    the caller's transaction. Returns the fields the client shows."""
    if track not in TRACKS:
        raise AdRewardRefused(f"unknown track {track!r}")
    profile = tx.get(user_path)
    if profile is None:
        raise AdRewardRefused("profile not found")

    now = now or energy_service.now_utc()
    today = game_date(now)
    state = counters(profile, today)
    updates: dict = {"last_ad_date": today, "last_ad_grant_at": now.isoformat()}
    result: dict = {"track": track}

    if track == "reward":
        watched = state["reward_ads_watched"]
        if watched >= len(config.AD_REWARD_PATH):
            raise AdRewardRefused("daily reward ads used up")
        step = config.AD_REWARD_PATH[watched]
        updates["credits"] = int(profile.get("credits", 0)) + int(step.get("credits", 0))
        updates["bucks"] = int(profile.get("bucks", 0)) + int(step.get("bucks", 0))
        updates["reward_ads_watched"] = watched + 1
        # A rolled day starts the other track from zero too.
        updates["energy_ads_watched"] = state["energy_ads_watched"]
        result.update(
            credits_remaining=updates["credits"],
            bucks_remaining=updates["bucks"],
            reward_ads_watched=watched + 1,
            reward_ads_max=len(config.AD_REWARD_PATH),
        )
    else:
        watched = state["energy_ads_watched"]
        if watched >= config.AD_ENERGY_MAX:
            raise AdRewardRefused("daily energy ads used up")
        current, anchor = energy_service.from_profile(profile, now)
        if current >= config.ENERGY_MAX:
            raise AdRewardRefused("energy already full")
        new_energy = min(config.ENERGY_MAX, current + config.AD_ENERGY_REWARD)
        updates[energy_service.ENERGY_FIELD] = new_energy
        updates[energy_service.ENERGY_UPDATED_AT_FIELD] = (
            now.isoformat() if new_energy >= config.ENERGY_MAX else anchor.isoformat()
        )
        updates["energy_ads_watched"] = watched + 1
        updates["reward_ads_watched"] = state["reward_ads_watched"]
        result.update(
            energy=new_energy,
            energy_ads_watched=watched + 1,
            energy_ads_max=config.AD_ENERGY_MAX,
        )

    tx.set(user_path, updates, merge=True)
    return result


# --- signature -----------------------------------------------------------------

def _fetch_keys() -> dict[str, object]:
    response = requests.get(VERIFIER_KEYS_URL, timeout=5)
    response.raise_for_status()
    keys = {}
    for entry in response.json().get("keys", []):
        keys[str(entry["keyId"])] = load_pem_public_key(entry["pem"].encode("utf-8"))
    return keys


def _public_key(key_id: str):
    global _keys, _keys_fetched_at
    with _keys_lock:
        stale = time.time() - _keys_fetched_at > VERIFIER_KEYS_TTL_SECONDS
        if key_id not in _keys or stale:
            _keys = _fetch_keys()
            _keys_fetched_at = time.time()
        return _keys.get(key_id)


def message_to_verify(raw_query: bytes) -> bytes:
    """What AdMob signed: the query string up to, not including, the
    signature parameter (key_id follows it)."""
    marker = b"&signature="
    cut = raw_query.find(marker)
    return raw_query if cut < 0 else raw_query[:cut]


def verify_signature(raw_query: bytes, signature: str, key_id: str) -> bool:
    """True if `signature` (base64url, DER-encoded ECDSA over SHA-256) is
    Google's signature of the callback's query string. Blocking: it may
    fetch the key set."""
    key = _public_key(key_id)
    if key is None:
        return False
    padded = signature + "=" * (-len(signature) % 4)
    try:
        der = base64.urlsafe_b64decode(padded)
        key.verify(der, message_to_verify(raw_query), ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        return False
    return True
