"""Contracts: the roll, signing, reviving, storage, and the out-of-contract penalty."""

from __future__ import annotations

import contracts
import items as item_rules
from conftest import Team
from game_config import CONTRACT_FIRST_MATCHES, CONTRACT_MAX_RANGE
from gameEngine import CONTRACT_PENALTY, OUT_OF_POSITION_PENALTY, _penalty_factor, game
from game_state import fields_to_player, player_to_fields
from packEngine import PLAYER_CLASS_MAP, generate_starter_roster
from player.classes.midfielder import Midfielder
from services.match import use_contracts


def _contract_item(matches=15):
    return item_rules.make_item("silver", item_rules.CONTRACT_STAT, item_rules.KIND_ANY, value=matches)


def test_fresh_rolls_inside_the_ranges_for_every_tier():
    for tier, (lo, hi) in CONTRACT_MAX_RANGE.items():
        for _ in range(50):
            c = contracts.fresh(tier)
            assert lo <= c["max"] <= hi
            assert c["signed"] == 1
            assert CONTRACT_FIRST_MATCHES[0] <= c["left"] <= CONTRACT_FIRST_MATCHES[1]


def test_a_document_from_before_contracts_loads_with_the_default():
    fields = player_to_fields(generate_starter_roster(seed=1)[0])
    del fields["contract"]
    card = fields_to_player(fields, PLAYER_CLASS_MAP, Midfielder)
    assert card.contract == {"max": CONTRACT_MAX_RANGE["bronze"][1], "signed": 1, "left": CONTRACT_FIRST_MATCHES[1]}


def test_a_contract_survives_the_storage_round_trip():
    card = generate_starter_roster(seed=2)[0]
    card.contract = {"max": 5, "signed": 3, "left": 7}
    loaded = fields_to_player(player_to_fields(card), PLAYER_CLASS_MAP, Midfielder)
    assert loaded.contract == {"max": 5, "signed": 3, "left": 7}


def test_signing_waits_for_the_contract_to_end():
    assert contracts.can_sign({"max": 5, "signed": 1, "left": 1}) is not None


def test_signing_stops_at_max():
    assert contracts.can_sign({"max": 3, "signed": 3, "left": 0}) is not None


def test_signing_adds_the_matches_and_counts_the_contract():
    c = {"max": 5, "signed": 2, "left": 0}
    assert contracts.can_sign(c) is None
    assert contracts.sign(c, _contract_item(17)) == {"max": 5, "signed": 3, "left": 17}


def test_needs_revive_only_when_ended_and_out_of_contracts():
    assert contracts.needs_revive({"max": 3, "signed": 3, "left": 0})
    assert not contracts.needs_revive({"max": 3, "signed": 3, "left": 4})
    assert not contracts.needs_revive({"max": 3, "signed": 2, "left": 0})


def test_a_match_takes_one_from_every_starter_still_under_contract():
    roster = generate_starter_roster(seed=3)
    roster[5].contract["left"] = 0
    before = [p.contract["left"] for p in roster]
    use_contracts({"roster": roster})
    assert [p.contract["left"] for p in roster] == [max(0, b - 1) for b in before]


def test_an_out_of_contract_player_plays_at_half():
    home, away = generate_starter_roster(seed=4), generate_starter_roster(seed=5)
    home[5].contract["left"] = 0
    card_speed = home[5].attributes.speed
    g = game(Team("A", home), Team("B", away), seed=1, formation_home="4-4-2", formation_away="4-4-2")
    played, card = g.all_players[5].attributes, home[5].attributes
    assert played.speed == round(card_speed * CONTRACT_PENALTY)
    assert card.speed == card_speed  # the card itself is never touched
    assert played.height == card.height  # physicals and tendencies are not skills
    assert played.pass_tendency == card.pass_tendency
    assert g.all_players[6].attributes is home[6].attributes


def test_penalties_never_stack():
    card = generate_starter_roster(seed=6)[0]
    card.contract["left"] = 0
    assert _penalty_factor(card, card.position) == CONTRACT_PENALTY
    assert _penalty_factor(card, "ST") == CONTRACT_PENALTY  # out of position too: still just the worse one
    card.contract["left"] = 3
    assert _penalty_factor(card, "ST") == OUT_OF_POSITION_PENALTY
    assert _penalty_factor(card, card.position) == 1.0
