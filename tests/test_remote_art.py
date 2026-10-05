"""Remote card types and art (services/remote_art.py): which Firestore docs
count, how their ranges merge with TIER_RANGES, and that a pack rolls a
remote variant inside its range without moving any static seed."""

from __future__ import annotations

import asyncio

import pytest

from game_config import TIER_RANGES
from packEngine import PackManager
from services import remote_art

ART = {"url": "https://example/x.webp", "sha256": "ab" * 32}


def _doc(tier, **fields):
    return {"id": tier, **ART, **fields}


def test_unknown_family_and_artless_docs_are_skipped():
    docs = [_doc("special_toty", range=[87, 90]), _doc("ruby_promo", range=[80, 85]), {"id": "gold_x", "range": [70, 75]}]
    assert set(remote_art.card_types_from_docs(docs)) == {"special_toty"}


def test_variant_range_merges_and_static_tiers_keep_theirs():
    card_types = remote_art.card_types_from_docs([_doc("special_toty", range=[87, 90]), _doc("gold", range=[1, 2])])
    ranges = remote_art.merged_ranges(card_types)
    assert ranges["special_toty"] == (87, 90)
    assert ranges["gold"] == TIER_RANGES["gold"]
    assert {t: ranges[t] for t in TIER_RANGES} == TIER_RANGES


@pytest.mark.parametrize("bad", [None, [90, 87], [87], ["87", "90"], [87, 87], [True, 90]])
def test_bad_range_is_not_sellable(bad):
    card_types = remote_art.card_types_from_docs([_doc("special_toty", range=bad)])
    assert "special_toty" not in remote_art.merged_ranges(card_types)


def test_manifest_shape():
    manifest = remote_art.build_manifest(
        remote_art.card_types_from_docs([_doc("special_toty", range=[87, 90], text_color="#ffffff")]),
        remote_art.pack_art_from_docs([_doc("TOTYPack"), {"id": "NoArt"}]),
    )
    assert manifest == {
        "cards": {"special_toty": {**ART, "text_color": "#ffffff"}},
        "packs": {"TOTYPack": ART},
    }


def test_pack_tiers_reads_rates_slot_rates_and_guarantees():
    config = {
        "rates": {"gold": 0.9, "silver": 0.1, "icon": 0},
        "slot_rates": {"0": {"special_toty": 1.0}},
        "guarantees": [{"tier": "special", "count": 1}],
    }
    assert remote_art.pack_tiers(config) == {"gold", "silver", "special_toty", "special"}


def _pack(tier):
    return {"p": {"cards_per_pack": 3, "rates": {tier: 1.0}, "pos_rates": {"attacker": 1, "midfielder": 1, "defender": 1}}}


def test_remote_variant_rolls_with_its_range():
    """Same seed, same range: a variant rolls exactly what that static tier would."""
    ranges = {**TIER_RANGES, "special_toty": TIER_RANGES["icon"]}
    for seed in range(10):
        promo = PackManager(_pack("special_toty"), seed=seed, tier_ranges=ranges).open_pack("p")
        icon = PackManager(_pack("icon"), seed=seed).open_pack("p")
        assert [c.tier for c in promo] == ["special_toty"] * 3
        assert [vars(c.attributes) for c in promo] == [vars(c.attributes) for c in icon]


def test_default_ranges_are_static():
    assert PackManager({}).tier_ranges is TIER_RANGES


class _Client:
    def __init__(self, card_docs):
        self.card_docs, self.calls, self.fail = card_docs, 0, False

    async def list_collection(self, path):
        self.calls += 1
        if self.fail:
            raise RuntimeError("firestore down")
        return self.card_docs if path == "card_types" else []


def test_refresh_caches_and_keeps_the_old_copy_on_a_failed_read(monkeypatch):
    monkeypatch.setattr(remote_art, "_state", {"loaded_at": None, "card_types": {}, "pack_art": {}})
    client = _Client([_doc("special_toty", range=[87, 90])])
    asyncio.run(remote_art.refresh(client))
    asyncio.run(remote_art.refresh(client))
    assert client.calls == 2  # one read of each collection; the second refresh was cached
    client.fail = True
    asyncio.run(remote_art.refresh(client, max_age=0))
    assert remote_art.tier_ranges()["special_toty"] == (87, 90)
    assert "special_toty" in remote_art.manifest()["cards"]
