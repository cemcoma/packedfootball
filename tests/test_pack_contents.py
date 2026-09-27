"""Guaranteed slots and item drops, and the seed promise underneath both.

Every pack opening is stored as a seed and replayed from it, so the ONE thing
that must never break is that an untouched pack rolls what it always rolled.
Both new features are drawn after the existing loop for exactly that reason --
`test_existing_packs_roll_identically` is what holds them there.
"""

from __future__ import annotations

import items as item_rules
from game_config import TIER_RANGES, tier_family
from packEngine import PACK_DATABASE, PackManager

# Every pack that predates guarantees and items. If one of these ever gains
# either key, its seeds are allowed to move -- but it must be a decision, not
# a surprise, which is what this list makes it.
LEGACY_PACKS = [
    slug
    for slug, cfg in PACK_DATABASE.items()
    if not cfg.get("guarantees") and not cfg.get("item_rates")
]


_POS = {"goalkeeper": 0.1, "defender": 0.3, "midfielder": 0.3, "attacker": 0.3}

# Tested against synthetic packs, not catalog slugs: the mechanics outlive any
# one pack, and the live catalog stopped selling a guarantee when specials
# moved off the credit ladder.
FIXTURE_PACKS = {
    "fx_guarantee": {
        "cards_per_pack": 5,
        "guarantees": [{"tier": "special", "count": 1}],
        "rates": {"gold": 0.5, "platinum": 0.5},
        "pos_rates": _POS,
        "item_rates": {"gold": 0.5, "platinum": 0.5},
        "items_per_pack": 2,
    },
    "fx_cards_only": {
        "cards_per_pack": 3,
        "rates": {"gold": 1.0},
        "pos_rates": _POS,
    },
}


def _fingerprint(cards):
    return [(c.tier, c.position, c.fname, c.lname, c.attributes.shooting) for c in cards]


def test_existing_packs_roll_identically():
    """The regression that would silently invalidate every stored pack seed."""
    assert LEGACY_PACKS, "no legacy packs left to check"
    for slug in LEGACY_PACKS:
        a = _fingerprint(PackManager(PACK_DATABASE, seed=12345).open_pack(slug))
        b = _fingerprint(PackManager(PACK_DATABASE, seed=12345).open_pack(slug))
        assert a == b, f"{slug} is not reproducible from its seed"


def test_rolling_items_does_not_disturb_the_cards():
    """Items are drawn after every card, so asking for them cannot change
    which cards came out."""
    pm = PackManager(FIXTURE_PACKS, seed=999)
    with_items = _fingerprint(pm.open_pack("fx_guarantee"))
    pm.open_pack_items("fx_guarantee")

    without = _fingerprint(PackManager(FIXTURE_PACKS, seed=999).open_pack("fx_guarantee"))
    assert with_items == without


def test_a_pack_with_no_item_rates_spends_no_draws():
    assert PackManager(FIXTURE_PACKS, seed=1).open_pack_items("fx_cards_only") == []


# --- guarantees -------------------------------------------------------------


def test_the_guarantee_always_lands():
    """Across many seeds, never once missing -- the whole point of paying for
    a guarantee is that it is not a rate."""
    for seed in range(60):
        cards = PackManager(FIXTURE_PACKS, seed=seed).open_pack("fx_guarantee")
        assert len(cards) == FIXTURE_PACKS["fx_guarantee"]["cards_per_pack"]
        families = [tier_family(c.tier) for c in cards]
        assert "special" in families, f"seed {seed} produced {families}"


def test_the_guarantee_comes_out_of_the_pack_size_not_on_top():
    cfg = FIXTURE_PACKS["fx_guarantee"]
    cards = PackManager(FIXTURE_PACKS, seed=3).open_pack("fx_guarantee")
    assert len(cards) == cfg["cards_per_pack"]


# --- item drops -------------------------------------------------------------


def test_item_packs_drop_the_advertised_count():
    for slug in ("item_standard", "item_premium"):
        cfg = PACK_DATABASE[slug]
        items = PackManager(PACK_DATABASE, seed=8).open_pack_items(slug)
        assert len(items) == cfg["items_per_pack"]
        assert PackManager(PACK_DATABASE, seed=8).open_pack(slug) == []


def test_dropped_items_are_well_formed_and_equippable():
    seen_kinds = set()
    for seed in range(40):
        for item in PackManager(PACK_DATABASE, seed=seed).open_pack_items("item_premium"):
            assert item["r"] in PACK_DATABASE["item_premium"]["item_rates"]
            assert item_rules.sanitize_pool([item]) == [item]
            seen_kinds.add(item["k"])
            position = "GK" if item["k"] == item_rules.KIND_KEEPER else "ST"
            assert item_rules.can_equip([], item, position) is None
    assert item_rules.KIND_KEEPER in seen_kinds, "keeper items never drop"
    assert item_rules.KIND_OUTFIELD in seen_kinds


def test_the_slot_extender_only_drops_from_packs_that_sell_it():
    """It is the only way past three slots, so it must not leak into the
    cheap pack."""
    for seed in range(120):
        for item in PackManager(PACK_DATABASE, seed=seed).open_pack_items("item_standard"):
            assert not item_rules.is_slot_extender(item)


def test_every_item_rate_table_is_a_probability_distribution():
    for slug, cfg in PACK_DATABASE.items():
        rates = cfg.get("item_rates")
        if not rates:
            continue
        assert abs(sum(rates.values()) - 1.0) < 1e-6, f"{slug} item_rates sum to {sum(rates.values())}"
        for rarity in rates:
            assert rarity in item_rules.ITEM_VALUES, f"{slug} sells unknown item rarity {rarity}"


def test_every_slot_rate_table_is_a_probability_distribution():
    """Same guard as item_rates, for the per-slot override. A slot table that
    does not sum to 1.0 silently reweights every tier in it."""
    for slug, cfg in PACK_DATABASE.items():
        for slot, rates in (cfg.get("slot_rates") or {}).items():
            assert str(slot).isdigit(), f"{slug} slot key {slot!r} is not an index"
            assert int(slot) < int(cfg["cards_per_pack"]), f"{slug} slot {slot} is past the pack size"
            assert abs(sum(rates.values()) - 1.0) < 1e-6, f"{slug} slot {slot} sums to {sum(rates.values())}"
            for tier in rates:
                assert tier in TIER_RANGES, f"{slug} slot {slot} sells unknown tier {tier}"


def test_slot_rates_survive_numeric_keys():
    """The silent-failure guard. `slot_rates` is looked up by str(slot), so a map
    written with numeric keys used to fall through to `rates` and roll the
    GENERIC odds -- a pack advertising a 20% diamond headline slot would quietly
    roll 2%. Both key shapes must roll identically."""
    as_text = {
        "cards_per_pack": 3,
        "rates": {"gold": 1.0},
        "slot_rates": {"0": {"icon": 1.0}},
        "pos_rates": _POS,
    }
    as_number = dict(as_text, slot_rates={0: {"icon": 1.0}})
    text_tiers = [c.tier for c in PackManager({"p": as_text}, seed=1).open_pack("p")]
    number_tiers = [c.tier for c in PackManager({"p": as_number}, seed=1).open_pack("p")]
    assert text_tiers[0] == "icon", text_tiers
    assert number_tiers == text_tiers, f"numeric keys rolled {number_tiers}, text keys {text_tiers}"


def test_every_guarantee_names_a_real_tier():

    for slug, cfg in PACK_DATABASE.items():
        for guarantee in cfg.get("guarantees", []) or []:
            assert guarantee["tier"] in TIER_RANGES, f"{slug} guarantees unknown tier {guarantee['tier']}"
            assert int(guarantee.get("count", 1)) <= cfg["cards_per_pack"]
