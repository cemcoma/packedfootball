"""Closer shots are truer, and an open run at the keeper is carried closer
before it is shot."""

from __future__ import annotations

import numpy as np

import player.player as player_module
from packEngine import generate_starter_roster
from player.player import SHOT_PATIENCE_RANGE

GOAL = np.array([35.0, 100.0])
NOBODY = np.array([[35.0, 20.0]] * 11)


def _striker():
    st = generate_starter_roster("4-4-2", tier="gold", seed=3)[9]
    assert st.position == "ST"
    return st


def _state(y, opponents=NOBODY, seed=0):
    pos = np.array([35.0, y])
    to_goal = GOAL - pos
    dist = float(np.linalg.norm(to_goal))
    return {
        "has_ball": True, "my_pos": pos, "ball_pos": pos, "ball_velocity": np.zeros(2),
        "my_heading": to_goal / dist, "my_velocity": np.zeros(2),
        "dist_to_goal": dist, "vec_to_goal": to_goal, "enemy_goal": GOAL, "goal_target": GOAL,
        "a_direction": 1, "in_attacking_box": y > 82.0, "in_penalty_box": y > 82.0,
        "pressure_count": 0, "opponents": np.asarray(opponents, dtype=float),
        "teammates": np.array([[30.0, 40.0]] * 11), "teammate_vel": np.zeros((11, 2)),
        "formation_pos": [35.0, 85.0], "my_role": "ST", "intent": None, "past_halfspace": True,
        "rng": np.random.default_rng(seed),
    }


def _spread(st, y):
    """Miss distance from the corner he went for (32.2 or 37.8)."""
    state = _state(y)
    xs = np.array([st._calculate_shot(state)["target_3d"][0] for _ in range(400)])
    return float(np.mean(np.abs(xs - np.where(xs < 35.0, 32.2, 37.8))))


def test_a_closer_shot_is_a_truer_one():
    st = _striker()
    assert _spread(st, 92.0) < 0.6 * _spread(st, 75.0)


def test_an_open_run_from_the_edge_is_worth_carrying_on():
    st = _striker()
    assert st._better_shot_ahead(_state(84.0))
    blocked = np.array([[35.0, 90.0]] + [[35.0, 20.0]] * 10)
    assert not st._better_shot_ahead(_state(84.0, opponents=blocked))
    assert not st._better_shot_ahead(_state(100.0 - SHOT_PATIENCE_RANGE + 2.0))


def test_the_keeper_does_not_count_as_a_blocked_lane():
    st = _striker()
    keeper_on_his_line = np.array([[35.0, 99.0]] + [[35.0, 20.0]] * 10)
    assert st._better_shot_ahead(_state(84.0, opponents=keeper_on_his_line))


def test_he_shoots_less_with_a_better_shot_ahead(monkeypatch):
    st = _striker()

    def shoot_share(patient):
        monkeypatch.setattr(player_module.player, "_better_shot_ahead", lambda self, s: patient)
        state = _state(84.0)
        return sum(st._decide_on_ball_attack(state) == "shoot" for _ in range(400)) / 400

    assert shoot_share(True) < 0.6 * shoot_share(False)
