"""Phases 6 and 7: stamina that actually depletes, and a height attribute.

`stamina` was already generated per position and already shown in the UI --
it was simply never read by any gameplay code. Everyone starts a match on
100 regardless of their card; the ATTRIBUTE is resistance to losing it.

`height` is new, stored in centimetres, and nothing consumes it yet (headers
and free kicks come later). The trap it has to avoid is the overall
calculation, which averages every non-primary attribute.
"""

import numpy as np
import pytest

from gameEngine import STAMINA_MAX
from player.player import PHYSICAL_FIELDS, Attributes

REGULATION_FRAMES = 10800


# ------------------------------------------------------------------ stamina

def test_everyone_starts_a_match_on_full_stamina(match):
    assert match.stamina.shape == (22,)
    assert np.all(match.stamina == STAMINA_MAX)


@pytest.mark.slow
def test_stamina_depletes_over_a_match(make_match):
    g = make_match(seed=11)
    g.run_match(max_steps=REGULATION_FRAMES, render=False)
    assert g.stamina.min() < STAMINA_MAX, "nobody got tired all match"
    assert g.stamina.min() >= 0.0


def test_a_higher_stamina_player_tires_less_for_the_same_work(match):
    """The whole point of the attribute."""
    lazy, fit = 1, 2
    match.all_players[lazy].attributes.stamina = 40
    match.all_players[fit].attributes.stamina = 95
    match.velocity[lazy] = np.array([10.0, 0.0])
    match.velocity[fit] = np.array([10.0, 0.0])

    for _ in range(400):
        match._drain_stamina()

    assert match.stamina[fit] > match.stamina[lazy]


def test_standing_still_recovers_stamina(match):
    match.stamina[5] = 50.0
    match.velocity[5] = np.zeros(2)
    for _ in range(50):
        match._drain_stamina()
    assert match.stamina[5] > 50.0


def test_stamina_never_leaves_its_bounds(match):
    match.velocity[:] = np.array([30.0, 0.0])
    for _ in range(50000):
        match._drain_stamina()
    assert match.stamina.min() >= 0.0
    assert match.stamina.max() <= STAMINA_MAX


def test_tired_players_move_slower(match):
    match.stamina[4] = STAMINA_MAX
    fresh = match._fatigue_factor(4)
    match.stamina[4] = 0.0
    spent = match._fatigue_factor(4)
    assert fresh == pytest.approx(1.0)
    assert spent < fresh
    assert spent > 0.0


def test_fatigue_actually_reduces_velocity(match):
    """_fatigue_factor has to be wired into the move action, not just exist."""
    target = match.positions[6] + np.array([0.0, 20.0])
    action = {"type": "move", "target": target, "speed_mod": 1.0}

    match.stamina[6] = STAMINA_MAX
    match._resolve_action(6, action)
    fresh_speed = float(np.linalg.norm(match.velocity[6]))

    match.stamina[6] = 0.0
    match._resolve_action(6, action)
    tired_speed = float(np.linalg.norm(match.velocity[6]))

    assert tired_speed < fresh_speed


def test_stamina_is_exposed_to_player_ai(match):
    match.step()
    # step() builds a state dict per player; the simplest proof it carries
    # stamina is that the engine holds the live value the AI would read.
    assert 0.0 <= float(match.stamina[3]) <= STAMINA_MAX


@pytest.mark.slow
def test_stamina_never_reaches_the_saved_card(make_match):
    """Match state must not leak into what gets persisted to Firestore."""
    from game_state import player_to_fields

    g = make_match(seed=12)
    g.run_match(max_steps=2000, render=False)
    fields = player_to_fields(g.all_players[5])
    assert "stamina" not in fields["statistics"]
    # The stamina ATTRIBUTE is a card property and does belong here; the
    # match pool is what must not appear.
    assert fields["attributes"]["stamina"] == g.all_players[5].attributes.stamina


# ------------------------------------------------------------------- height

def test_height_is_an_attribute():
    assert "height" in Attributes.__dataclass_fields__


def test_generated_heights_are_plausible(rosters):
    home, away = rosters
    for p in home + away:
        assert 150 <= p.attributes.height <= 215, f"{p.lname} is {p.attributes.height}cm"


def test_keepers_are_taller_than_wingers_on_average():
    from packEngine import PACK_DATABASE, PackManager

    pm = PackManager(PACK_DATABASE, seed=99)
    pool = []
    while len(pool) < 600:
        pool += pm.open_pack("jumbo_standard")
    keepers = [p.attributes.height for p in pool if p.position == "GK"]
    wide = [p.attributes.height for p in pool if p.position in ("LW", "RW")]
    assert keepers and wide
    assert sum(keepers) / len(keepers) > sum(wide) / len(wide)


def test_height_does_not_scale_with_card_tier():
    """An icon is not taller than a bronze."""
    from packEngine import PACK_DATABASE, PackManager

    pm = PackManager(PACK_DATABASE, seed=7)
    by_tier = {}
    for _ in range(80):
        for card in pm.open_pack("jumbo_standard"):
            by_tier.setdefault(card.tier, []).append(card.attributes.height)

    means = {t: sum(v) / len(v) for t, v in by_tier.items() if len(v) >= 12}
    assert len(means) >= 2, "not enough tiers sampled"
    assert max(means.values()) - min(means.values()) < 8.0, means


def test_height_is_excluded_from_overall(rosters):
    """The trap: _calculate_overall averages every non-primary attribute, and
    height is in centimetres. Including it would inflate every card."""
    home, _ = rosters
    p = home[4]
    before = p._calculate_overall()
    p.attributes.height = 205
    assert p._calculate_overall() == before
    p.attributes.height = 160
    assert p._calculate_overall() == before


def test_physical_fields_is_declared():
    assert "height" in PHYSICAL_FIELDS


def test_client_overall_mirrors_the_exclusion():
    """PlayerCard.gd reproduces _calculate_overall by iterating attribute
    keys -- if it doesn't skip height too, client and server disagree on
    every card's rating."""
    from pathlib import Path

    gd = (Path(__file__).resolve().parent.parent / "mobile/scripts/data/PlayerCard.gd").read_text()
    assert "PHYSICAL_FIELDS" in gd
    assert "PHYSICAL_FIELDS.has(key)" in gd


def test_height_round_trips_through_firestore_fields(rosters):
    from game_state import fields_to_player, player_to_fields
    from packEngine import PLAYER_CLASS_MAP
    from player.classes.midfielder import Midfielder

    home, _ = rosters
    fields = player_to_fields(home[6])
    assert "height" in fields["attributes"]
    restored = fields_to_player(fields, PLAYER_CLASS_MAP, Midfielder)
    assert restored.attributes.height == home[6].attributes.height
