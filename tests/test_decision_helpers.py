"""The fast paths the decision layer uses instead of numpy's general ones must
give the same answers -- they exist for speed (scripts/bench_engine.py), not
to change a single decision."""

from __future__ import annotations

import numpy as np

from player.player import _ball_pressure, _count_within, _dists, _pick


def test_pick_draws_exactly_what_rng_choice_would():
    options = ["pass", "dribble", "shoot", "hold", "cross"]
    weights = np.random.default_rng(0)
    for seed in range(300):
        raw = weights.random(len(options)) * (weights.random(len(options)) > 0.3) + 1e-12
        probs = (raw / raw.sum()).tolist()
        ours, theirs = np.random.default_rng(seed), np.random.default_rng(seed)
        for _ in range(5):
            assert _pick(ours, options, probs) == theirs.choice(options, p=probs)


def test_ball_pressure_falls_back_to_counting():
    opponents = np.array([[10.0, 10.0], [11.0, 10.0], [30.0, 30.0]])
    state = {"opponents": opponents, "ball_pos": np.array([10.5, 10.0])}
    assert _ball_pressure(state) == _count_within(opponents, state["ball_pos"], 3.0) == 2
    assert _ball_pressure({**state, "ball_pressure": 0}) == 0


def test_dists_matches_norm():
    points = np.random.default_rng(1).random((11, 2)) * 70.0
    centre = np.array([35.0, 50.0])
    assert np.allclose(_dists(points, centre), np.linalg.norm(points - centre, axis=1))
