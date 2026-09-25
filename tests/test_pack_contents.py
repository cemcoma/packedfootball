"""Guaranteed slots and item drops, and the seed promise underneath both.

Every pack opening is stored as a seed and replayed from it, so the ONE thing
that must never break is that an untouched pack rolls what it always rolled.
Both new features are drawn after the existing loop for exactly that reason --
`test_existing_packs_roll_identically` is what holds them there.
"""

from __future__ import annotations

import items as item_rules
from game_config import tier_family
from packEngine import PACK_DATABASE, PackManager

# Every pack that predates guarantees and items. If one of these ever gains
# either key, its seeds are allowed to move -- but it must be a decision, not
# a surprise, which is what this list makes it.
LEGACY_PACKS = [
    slug
    for slug, cfg in PACK_DATABASE.items()
    if not cfg.get("guarantees") and not cfg.get("item_rates")
]


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
    pm = PackManager(PACK_DATABASE, seed=999)
    with_items = _fingerprint(pm.open_pack("guaranteed_special"))
    pm.open_pack_items("guaranteed_special")

    without = _fingerprint(PackManager(PACK_DATABASE, seed=999).open_pack("guaranteed_special"))
    assert with_items == without


def test_a_pack_with_no_item_rates_spends_no_draws():
    assert PackManager(PACK_DATABASE, seed=1).open_pack_items("standard_pp") == []


# --- guarantees -------------------------------------------------------------


def test_the_guarantee_always_lands():
    """Across many seeds, never once missing -- the whole point of paying for
    a guarantee is that it is not a rate."""
    for seed in range(60):
        cards = PackManager(PACK_DATABASE, seed=seed).open_pack("guaranteed_special")
        assert len(cards) == PACK_DATABASE["guaranteed_special"]["cards_per_pack"]
        families = [tier_family(c.tier) for c in cards]
        assert "special" in families, f"seed {seed} produced {families}"


def test_the_guarantee_comes_out_of_the_pack_size_not_on_top():
    cfg = PACK_DATABASE["guaranteed_special"]
    cards = PackManager(PACK_DATABASE, seed=3).open_pack("guaranteed_special")
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


def test_every_guarantee_names_a_real_tier():
    from game_config import TIER_RANGES

    for slug, cfg in PACK_DATABASE.items():
        for guarantee in cfg.get("guarantees", []) or []:
            assert guarantee["tier"] in TIER_RANGES, f"{slug} guarantees unknown tier {guarantee['tier']}"
            assert int(guarantee.get("count", 1)) <= cfg["cards_per_pack"]
