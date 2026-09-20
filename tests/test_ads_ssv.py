"""Rewarded ads paid on AdMob's server-side verification, not the client's
claim (services/ads.py, routers/ads.py).

Two things to pin: the signature check accepts exactly what Google signs
(the query string up to `&signature=`, ECDSA P-256 over SHA-256, base64url
DER) and nothing else; and the grant pays the right step, resets on the
day boundary, and refuses instead of over-paying.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

import config
from services import ads
from services import energy as energy_service

T0 = datetime(2026, 9, 20, 15, 0, 0, tzinfo=timezone.utc)  # 18:00 Istanbul


# --------------------------------------------------------------- signature

@pytest.fixture
def signing_key(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(ads, "_keys", {"1234": key.public_key()})
    monkeypatch.setattr(ads, "_keys_fetched_at", 10**12)  # never stale
    return key


def _sign(key, message: bytes) -> str:
    der = key.sign(message, ec.ECDSA(hashes.SHA256()))
    return base64.urlsafe_b64encode(der).decode().rstrip("=")


QUERY = b"ad_network=5450213213286189855&ad_unit=1234567890&custom_data=buck_track&reward_amount=1&reward_item=coins&timestamp=1758380000000&transaction_id=abc123&user_id=uid42"


def test_message_is_everything_before_the_signature():
    raw = QUERY + b"&signature=SIG&key_id=1234"
    assert ads.message_to_verify(raw) == QUERY


def test_google_signature_verifies(signing_key):
    sig = _sign(signing_key, QUERY)
    raw = QUERY + b"&signature=" + sig.encode() + b"&key_id=1234"
    assert ads.verify_signature(raw, sig, "1234")


def test_tampered_query_fails(signing_key):
    sig = _sign(signing_key, QUERY)
    forged = QUERY.replace(b"user_id=uid42", b"user_id=me") + b"&signature=" + sig.encode() + b"&key_id=1234"
    assert not ads.verify_signature(forged, sig, "1234")


def test_unknown_key_fails(signing_key, monkeypatch):
    monkeypatch.setattr(ads, "_fetch_keys", lambda: {})
    monkeypatch.setattr(ads, "_keys_fetched_at", 0.0)
    sig = _sign(signing_key, QUERY)
    assert not ads.verify_signature(QUERY + b"&signature=" + sig.encode() + b"&key_id=9", sig, "9")


def test_garbage_signature_fails(signing_key):
    assert not ads.verify_signature(QUERY + b"&signature=!!&key_id=1234", "!!", "1234")


# ------------------------------------------------------------------- grant

class FakeTx:
    def __init__(self, docs: dict):
        self.docs = docs
        self.writes: list[tuple[str, dict]] = []

    def get(self, path):
        return self.docs.get(path)

    def set(self, path, data, merge=True):
        self.writes.append((path, data))
        if merge and self.docs.get(path):
            self.docs[path] = {**self.docs[path], **data}
        else:
            self.docs[path] = dict(data)


def _profile(**over) -> dict:
    base = {
        "credits": 100,
        "bucks": 0,
        "last_ad_date": ads.game_date(T0),
        "ad_counters": {"buck_track": 0, "energy_track": 0},
        energy_service.ENERGY_FIELD: 3,
        energy_service.ENERGY_UPDATED_AT_FIELD: T0.isoformat(),
    }
    base.update(over)
    return base


def test_first_buck_ad_pays_step_zero():
    tx = FakeTx({"users/u": _profile()})
    paid = ads.grant_in_tx(tx, "users/u", "buck_track", T0)
    step = config.AD_REWARD_PATH[0]
    assert paid["credits_remaining"] == 100 + step["credits"]
    assert paid["ad_counters"]["buck_track"]["watched"] == 1
    assert tx.docs["users/u"]["credits"] == 100 + step["credits"]


def test_buck_track_walks_the_path_then_refuses():
    tx = FakeTx({"users/u": _profile()})
    for _ in config.AD_REWARD_PATH:
        ads.grant_in_tx(tx, "users/u", "buck_track", T0)
    with pytest.raises(ads.AdRewardRefused):
        ads.grant_in_tx(tx, "users/u", "buck_track", T0)
    total = sum(s["credits"] for s in config.AD_REWARD_PATH)
    assert tx.docs["users/u"]["credits"] == 100 + total


def test_counters_reset_on_the_next_game_day():
    tx = FakeTx({"users/u": _profile(ad_counters={"buck_track": 3, "energy_track": 3})})
    tomorrow = T0 + timedelta(days=1)
    paid = ads.grant_in_tx(tx, "users/u", "buck_track", tomorrow)
    assert paid["ad_counters"]["buck_track"]["watched"] == 1
    assert tx.docs["users/u"]["ad_counters"]["energy_track"] == 0
    assert tx.docs["users/u"]["last_ad_date"] == ads.game_date(tomorrow)


def test_energy_ad_adds_one_point_and_refuses_when_full():
    tx = FakeTx({"users/u": _profile()})
    paid = ads.grant_in_tx(tx, "users/u", "energy_track", T0)
    assert paid["energy"] == 3 + config.AD_ENERGY_REWARD
    tx = FakeTx({"users/u": _profile(**{energy_service.ENERGY_FIELD: config.ENERGY_MAX})})
    with pytest.raises(ads.AdRewardRefused):
        ads.grant_in_tx(tx, "users/u", "energy_track", T0)


def test_unknown_track_is_refused():
    tx = FakeTx({"users/u": _profile()})
    with pytest.raises(ads.AdRewardRefused):
        ads.grant_in_tx(tx, "users/u", "nope", T0)


def test_status_counters_read_zero_after_the_day_rolls():
    profile = _profile(ad_counters={"buck_track": 2})
    assert ads.counters(profile, ads.game_date(T0))["buck_track"]["watched"] == 2
    rolled = ads.counters(profile, ads.game_date(T0 + timedelta(days=1)))
    assert rolled["buck_track"]["watched"] == 0
    assert rolled["buck_track"]["max"] == len(config.AD_REWARD_PATH)


def test_no_client_claim_endpoint_remains():
    """The whole point: nothing a client can call pays an ad reward."""
    from routers import ads as ads_router

    paths = {(r.path, tuple(sorted(r.methods))) for r in ads_router.router.routes}
    assert ("/ads/reward", ("POST",)) not in paths
    assert ("/ads/ssv", ("GET",)) in paths
    assert ("/ads/status", ("GET",)) in paths
