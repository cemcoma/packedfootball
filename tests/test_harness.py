"""Smoke tests for the fixtures themselves.

If these fail, nothing else in the suite means anything.
"""

import numpy as np

from conftest import GOAL_CENTER_X, launch_ball, quiesce, tick_until


def test_rosters_are_full_and_correctly_slotted(rosters):
    home, away = rosters
    assert len(home) == 11 and len(away) == 11
    # Slot 0 is the goalkeeper slot in every formation; the engine relies on
    # index 0/11 actually being a keeper (see _begin_restart's goal kick).
    assert home[0].position == "GK"
    assert away[0].position == "GK"


def test_match_constructs_with_22_players(match):
    assert len(match.all_players) == 22
    assert match.positions.shape == (22, 2)
    assert match.scores == [0, 0]


def test_rosters_are_isolated_between_tests(make_match):
    """The engine mutates player statistics in place, so each test must get
    its own copies or stats leak across tests."""
    m = make_match()
    m.all_players[9].scored()
    assert m.all_players[9].statistics["goals"] == 1


def test_seeded_matches_are_reproducible(make_match):
    a = make_match(seed=123)
    b = make_match(seed=123)
    a.run_match(max_steps=400, render=False)
    b.run_match(max_steps=400, render=False)
    assert a.scores == b.scores
    assert np.allclose(a.positions, b.positions)


def test_quiesce_lets_the_ball_move(match):
    """A fresh game is mid-kickoff and tick() early-returns before physics."""
    quiesce(match)
    match.ball[:] = [35.0, 50.0, 0.0, 20.0, 0.0]
    y0 = match.ball[1]
    match.tick(1 / 60)
    assert match.ball[1] > y0


def test_tick_until_reports_no_fire(match):
    launch_ball(match, GOAL_CENTER_X, 50.0, 0.0, 0.0)
    assert tick_until(match, lambda g: g.ball[1] > 99.0, max_ticks=10) == -1
