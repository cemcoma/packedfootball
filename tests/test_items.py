"""Equipment: the rules, the storage round trip, and that a buff is REAL.

The last of those is the one that matters. Items only do anything because
game_config.stat_ability keeps rising past 100 (STAT_OVERDRIVE); before that
tail existed every formula clipped at 1.0, so a +12 on a 96 card was worth
exactly nothing. `test_overdrive_*` are the regression tests for that, and
`test_kitted_xi_beats_an_unkitted_one` is the end-to-end proof.

The other thing being guarded here is the double-apply trap: loading a kitted
card and saving it again must not write the buffed numbers back as though
they were rolled. See game_state.player_to_fields.
"""

from __future__ import annotations

import copy

import pytest

import items as item_rules
from conftest import Team
from game_config import STAT_CEILING, STAT_OVERDRIVE, pace_ability, stat_ability
from game_state import fields_to_player, player_to_fields
from gameEngine import game
from packEngine import PLAYER_CLASS_MAP, generate_starter_roster
from player.classes.midfielder import Midfielder
from player.player import Attributes


def _card(**overrides):
    attrs = Attributes(**overrides) if overrides else Attributes()
    return Midfielder("Test", "Card", "gold", "CM", attrs)


# --- the overdrive tail -----------------------------------------------------


def test_overdrive_is_continuous_and_rising_through_100():
    """The bug this replaces: everything above 100 returned exactly 1.0."""
    ladder = [stat_ability(s) for s in (90, 96, 100, 104, 112, 130)]
    assert ladder == sorted(ladder)
    assert ladder[2] == pytest.approx(1.0)
    # Strictly rising past the old clip, not flat.
    assert ladder[3] > ladder[2] > 0.99
    assert ladder[-1] == pytest.approx(1.0 + 0.30 * STAT_OVERDRIVE)


def test_overdrive_is_worth_less_than_the_base_axis():
    """A kitted bronze must not outrun an icon. Twelve points of pure
    overdrive buy materially less than the twelve below the anchor -- measured
    either side of 100 so neither span straddles it."""
    below = stat_ability(100) - stat_ability(88)
    above = stat_ability(112) - stat_ability(100)
    assert above < below * 0.5


def test_pace_carries_the_tail_too():
    assert pace_ability(112) > pace_ability(100) > pace_ability(90)


# --- slots and legality -----------------------------------------------------


def test_three_slots_then_full():
    kit = [item_rules.make_item("gold", s) for s in ("speed", "shooting", "power")]
    assert item_rules.capacity(kit) == 3
    extra = item_rules.make_item("gold", "vision")
    assert item_rules.can_equip(kit, extra, "CM") is not None


def test_the_extender_takes_a_slot_and_nets_four():
    extender = item_rules.make_item("icon", item_rules.SLOT_EXTENDER_STAT, item_rules.KIND_ANY)
    kit = [extender]
    assert item_rules.capacity(kit) == 5
    for stat in ("speed", "shooting", "power", "vision"):
        item = item_rules.make_item("gold", stat)
        assert item_rules.can_equip(kit, item, "CM") is None
        kit.append(item)
    assert len(kit) == 5  # the extender plus four real buffs
    assert item_rules.can_equip(kit, item_rules.make_item("gold", "agility"), "CM") is not None


def test_only_one_extender_per_card():
    extender = item_rules.make_item("icon", item_rules.SLOT_EXTENDER_STAT, item_rules.KIND_ANY)
    assert item_rules.can_equip([extender], dict(extender, id="other"), "CM") is not None


def test_one_item_per_stat():
    """Three speed items on every man measured W14-D5-L1 against the same XI
    unkitted; three mixed ones are W10-D4-L6. Stacking one stat is the exploit
    the rule exists to close."""
    kit = [item_rules.make_item("gold", "speed")]
    assert item_rules.can_equip(kit, item_rules.make_item("icon", "speed"), "CM") is not None
    assert item_rules.can_equip(kit, item_rules.make_item("bronze", "shooting"), "CM") is None


def test_a_stacked_document_keeps_only_one_per_stat():
    card = _card(speed=70)
    card.items = [item_rules.make_item("icon", "speed") for _ in range(3)]
    loaded = _round_trip(card)
    assert len(loaded.items) == 1
    assert loaded.attributes.speed == 82


def test_keeper_items_do_not_fit_outfielders():
    gk_item = item_rules.make_item("gold", "agility", item_rules.KIND_KEEPER)
    assert item_rules.can_equip([], gk_item, "CM") is not None
    assert item_rules.can_equip([], gk_item, "GK") is None


# --- applying them ----------------------------------------------------------


def test_effective_attributes_does_not_touch_the_base_card():
    attrs = Attributes(shooting=90)
    buffed = item_rules.effective_attributes(attrs, [item_rules.make_item("icon", "shooting")])
    assert buffed.shooting == 102
    assert attrs.shooting == 90, "the rolled card was mutated"


def test_items_cannot_push_past_the_ceiling():
    attrs = Attributes(speed=STAT_CEILING - 1)
    buffed = item_rules.effective_attributes(attrs, [item_rules.make_item("icon", "speed")])
    assert buffed.speed == STAT_CEILING


def test_tendencies_and_height_are_not_sellable():
    assert "shoot_tendency" not in item_rules.BUFFABLE_STATS
    assert "height" not in item_rules.BUFFABLE_STATS
    attrs = Attributes(height=180)
    buffed = item_rules.effective_attributes(attrs, [{"id": "x", "r": "icon", "s": "height", "v": 12, "k": "outfield"}])
    assert buffed.height == 180


# --- storage ----------------------------------------------------------------


def _round_trip(card):
    return fields_to_player(player_to_fields(card), PLAYER_CLASS_MAP, Midfielder)


def test_saving_a_kitted_card_twice_does_not_stack_the_buff():
    """The trap: fields_to_player buffs .attributes, so a naive save would
    write the buffed number back and add the item again on the next load."""
    card = _card(shooting=80)
    card.items = [item_rules.make_item("gold", "shooting")]
    fields = player_to_fields(card)
    assert fields["attributes"]["shooting"] == 80

    loaded = _round_trip(card)
    assert loaded.attributes.shooting == 84
    assert loaded.base_attributes.shooting == 80

    for _ in range(3):
        loaded = _round_trip(loaded)
    assert loaded.attributes.shooting == 84, "the buff compounded across saves"
    assert player_to_fields(loaded)["attributes"]["shooting"] == 80


def test_a_card_with_no_items_round_trips_unchanged():
    card = _card(shooting=80)
    loaded = _round_trip(card)
    assert loaded.items == []
    assert loaded.attributes.shooting == 80


def test_documents_written_before_items_existed_still_load():
    fields = player_to_fields(_card())
    del fields["items"]
    loaded = fields_to_player(fields, PLAYER_CLASS_MAP, Midfielder)
    assert loaded.items == []


def test_an_overstuffed_document_is_trimmed_not_trusted():
    card = _card()
    card.items = [item_rules.make_item("icon", s) for s in
                  ("speed", "shooting", "power", "vision", "agility", "passing")]
    loaded = _round_trip(card)
    assert len(loaded.items) == item_rules.ITEM_SLOTS_BASE


def test_junk_in_the_array_is_dropped_rather_than_raised():
    assert item_rules.sanitize([None, 7, {"s": "nonsense"}, {}]) == []


# --- end to end -------------------------------------------------------------


@pytest.mark.slow
def test_kitted_xi_beats_an_unkitted_one():
    """Four items a man, same tier both sides, same seeds. If the kitted side
    doesn't win more, items are cosmetic."""
    base = generate_starter_roster("4-4-2", "gold", seed=7)

    def kit(roster):
        out = copy.deepcopy(roster)
        for p in out:
            kind = item_rules.kind_for_position(p.position)
            stats = item_rules.stats_for_kind(kind)[:3]
            p.items = [item_rules.make_item("icon", s, kind) for s in stats]
            p.base_attributes = p.attributes
            p.attributes = item_rules.effective_attributes(p.attributes, p.items)
        return out

    kitted_goals = plain_goals = 0
    for seed in range(40, 52):
        match = game(
            Team("Kitted", kit(base)),
            Team("Plain", copy.deepcopy(base)),
            seed=seed,
            formation_home="4-4-2",
            formation_away="4-4-2",
        )
        match.run_match(max_steps=10800, render=False)
        kitted_goals += match.scores[0]
        plain_goals += match.scores[1]

    assert kitted_goals > plain_goals, (
        f"items did nothing: kitted {kitted_goals} - {plain_goals} plain"
    )
