"""Header aim is calibrated: on target about half the time at heading 70, 70%
at 100, and still improving with items up to STAT_CEILING."""

from __future__ import annotations

import numpy as np
import pytest

from conftest import quiesce

HEADER = 9


def _on_target_rate(g, heading, trials=2000, seed=3):
    rng = np.random.default_rng(seed)
    attrs = g.all_players[HEADER].attributes
    attrs.heading = heading
    attrs.composure = heading
    hits = 0
    for _ in range(trials):
        pos = np.array([rng.uniform(28.0, 42.0), rng.uniform(84.0, 94.0)])
        g.positions[:] = [[5.0, 5.0]] * 22
        g.positions[HEADER] = pos
        for k in range(rng.choice([0, 1, 2], p=[0.5, 0.4, 0.1])):
            g.positions[12 + k] = pos + rng.uniform(-2.0, 2.0, size=2)
        g.ball[:] = [pos[0], pos[1], 0.0, 0.0, rng.uniform(1.5, 2.2), 0.0]
        g.ball_controller = -1
        g._header_at_goal(HEADER, float(g.ball[4]))
        hits += g.last_shot_on_target
    return hits / trials


@pytest.fixture
def g(make_match):
    return quiesce(make_match())


def test_a_70_header_is_on_target_about_half_the_time(g):
    assert 0.44 <= _on_target_rate(g, 70) <= 0.56


def test_a_100_header_is_on_target_about_70_percent(g):
    assert 0.64 <= _on_target_rate(g, 100) <= 0.76


def test_items_keep_making_him_better_up_to_130(g):
    rates = [_on_target_rate(g, h) for h in (70, 100, 115, 130)]
    assert rates == sorted(rates), rates
    assert rates[-1] > rates[1] + 0.05, rates
