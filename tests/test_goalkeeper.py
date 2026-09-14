"""Phase 5: the keeper can leave its line -- carefully.

The old leash was entirely in goalkeeper.py: _get_keeper_line() always
returned y=1 or y=99, and every movement decision clamped x to [31, 39]. A
keeper would stand on its line watching a loose ball two metres in front of
it, because it had no "chase"-style decision at all (every outfield class
has one).

The risk in loosening this is a keeper wandering off and leaving an empty
net, so most of these tests are about what the keeper must STILL do.
"""

import numpy as np
import pytest

from conftest import GOAL_CENTER_X, PITCH_HEIGHT

KEEPER_A = 0  # defends y=0
KEEPER_B = 11  # defends y=100


def keeper_state(g, idx, ball_xy, ball_vel=(0.0, 0.0), is_loose=True, **overrides):
    """Builds the state dict the engine would hand this keeper.

    `goal_crossing` is computed by the engine itself rather than written by
    hand: since the rebalance, save/dive fire only for a ball predicted to
    cross inside the frame, so a hand-built state that omits the key makes
    every shot look harmless and the keeper stands still. The ball is put
    where the caller says, asked, and put back.
    """
    ball_height = float(overrides.get("ball_height", 0.0))
    saved_ball = np.array(g.ball, dtype=float)
    g.ball[0:2] = np.asarray(ball_xy, dtype=float)
    g.ball[2:4] = np.asarray(ball_vel, dtype=float)
    g.ball[4] = ball_height
    crossing = g.predict_goal_crossing(0 if idx < 11 else 1)
    g.ball[:] = saved_ball

    base = {
        "has_ball": False,
        "ball_pos": np.array(ball_xy, dtype=float),
        "ball_velocity": np.array(ball_vel, dtype=float),
        "ball_height": ball_height,
        "goal_crossing": crossing,
        "my_pos": np.array(g.positions[idx], dtype=float),
        "my_velocity": np.zeros(2),
        "my_heading": np.array([0.0, 1.0]),
        "dist_to_ball": float(np.linalg.norm(np.array(ball_xy) - g.positions[idx])),
        "a_direction": 1 if idx < 11 else -1,
        "in_penalty_box": False,
        "pressure_count": 0,
        "teammates": np.array(g.positions[0:11] if idx < 11 else g.positions[11:22], dtype=float),
        "opponents": np.array(g.positions[11:22] if idx < 11 else g.positions[0:11], dtype=float),
        "formation_pos": g.formation[idx]["pos"],
        "team_possession": 0,
        "past_halfspace": False,
        "own_goal": np.array([GOAL_CENTER_X, 0.0 if idx < 11 else PITCH_HEIGHT]),
        "must_pass_next": False,
        "is_loose": is_loose,
        "rng": g.rng,
    }
    base.update(overrides)
    return base


def _park_outfielders_away(g):
    """Leaves the keeper unambiguously nearest to its own box."""
    for i in range(1, 11):
        g.positions[i] = np.array([GOAL_CENTER_X, 60.0])
    for i in range(12, 22):
        g.positions[i] = np.array([GOAL_CENTER_X, 40.0])


def test_keeper_sweeps_for_a_loose_ball_in_its_box(match):
    _park_outfielders_away(match)
    gk = match.all_players[KEEPER_A]
    st = keeper_state(match, KEEPER_A, (GOAL_CENTER_X, 10.0))
    assert gk._decide_off_ball_defense(st) == "sweep"


def test_sweeping_actually_moves_the_keeper_off_its_line(match):
    _park_outfielders_away(match)
    gk = match.all_players[KEEPER_A]
    st = keeper_state(match, KEEPER_A, (GOAL_CENTER_X, 10.0))
    action = gk._build_action("sweep", st)
    assert action["type"] == "move"
    assert action["target"][1] > 2.0, "keeper never left the goal line"


def test_keeper_does_not_sweep_for_a_shot_coming_at_goal(match):
    """The dangerous case -- shot-stopping must always win."""
    _park_outfielders_away(match)
    gk = match.all_players[KEEPER_A]
    st = keeper_state(match, KEEPER_A, (GOAL_CENTER_X, 12.0), ball_vel=(0.0, -25.0))
    assert gk._decide_off_ball_defense(st) in ("dive", "save", "capture")


def test_keeper_still_saves_a_close_shot(match):
    gk = match.all_players[KEEPER_A]
    st = keeper_state(match, KEEPER_A, (GOAL_CENTER_X, 3.5), ball_vel=(0.0, -12.0))
    assert gk._decide_off_ball_defense(st) == "save"


def test_keeper_still_captures_a_ball_at_its_feet(match):
    gk = match.all_players[KEEPER_A]
    st = keeper_state(match, KEEPER_A, tuple(match.positions[KEEPER_A] + np.array([0.5, 0.5])))
    assert gk._decide_off_ball_defense(st) == "capture"


def test_keeper_does_not_sweep_outside_its_own_box(match):
    _park_outfielders_away(match)
    gk = match.all_players[KEEPER_A]
    st = keeper_state(match, KEEPER_A, (GOAL_CENTER_X, 55.0))
    assert gk._decide_off_ball_defense(st) == "contain"


def test_keeper_does_not_sweep_when_a_teammate_is_closer(match):
    gk = match.all_players[KEEPER_A]
    ball = (GOAL_CENTER_X, 12.0)
    match.positions[3] = np.array(ball)  # defender standing on it
    st = keeper_state(match, KEEPER_A, ball)
    assert gk._decide_off_ball_defense(st) == "contain"


def test_sweep_target_never_leaves_the_penalty_area(match):
    _park_outfielders_away(match)
    gk = match.all_players[KEEPER_A]
    st = keeper_state(match, KEEPER_A, (GOAL_CENTER_X, 16.0), ball_vel=(0.0, 30.0))
    target = gk._build_action("sweep", st)["target"]
    assert 0.0 <= target[1] <= 18.0
    assert abs(target[0] - GOAL_CENTER_X) <= 21.0


def test_contain_brings_the_keeper_home(match):
    gk = match.all_players[KEEPER_A]
    match.positions[KEEPER_A] = np.array([GOAL_CENTER_X, 15.0])  # caught upfield
    st = keeper_state(match, KEEPER_A, (GOAL_CENTER_X, 50.0))
    action = gk._build_action("contain", st)
    assert action["target"][1] < 3.0, "keeper is not returning to its line"


def test_a_stranded_keeper_sprints_back(match):
    gk = match.all_players[KEEPER_A]
    match.positions[KEEPER_A] = np.array([GOAL_CENTER_X, 16.0])
    stranded = gk._build_action("contain", keeper_state(match, KEEPER_A, (GOAL_CENTER_X, 50.0)))

    match.positions[KEEPER_A] = np.array([GOAL_CENTER_X, 1.0])
    home = gk._build_action("contain", keeper_state(match, KEEPER_A, (GOAL_CENTER_X, 50.0)))
    assert stranded["speed_mod"] > home["speed_mod"]


def test_keeper_holds_position_when_its_own_team_attacks(match):
    gk = match.all_players[KEEPER_A]
    st = keeper_state(match, KEEPER_A, (GOAL_CENTER_X, 90.0), is_loose=False)
    assert gk._decide_off_ball_attack(st) == "hold_defense"


def test_both_keepers_use_their_own_end(match):
    a = match.all_players[KEEPER_A]._get_keeper_line(keeper_state(match, KEEPER_A, (35.0, 50.0)))
    b = match.all_players[KEEPER_B]._get_keeper_line(keeper_state(match, KEEPER_B, (35.0, 50.0)))
    assert a < 5.0
    assert b > PITCH_HEIGHT - 5.0


def test_keeper_bounds_derive_from_goal_width():
    """No more magic 31/39 literals."""
    import player.classes.goalkeeper as gk_mod
    from gameEngine import GOAL_WIDTH, PITCH_WIDTH

    assert gk_mod.GOAL_CENTER_X == pytest.approx(PITCH_WIDTH / 2)
    assert gk_mod.KEEPER_LINE_HALF_WIDTH == pytest.approx(GOAL_WIDTH / 2 + 0.5)


@pytest.mark.slow
def test_sweep_actually_fires_in_a_real_match(make_match):
    """The one that matters.

    The first version of this feature passed every unit test above -- which
    build their state dicts by hand -- while never once firing in an actual
    match, because the gating conditions never lined up. Anything that stops
    the keeper leaving its line in real play must fail here.
    """
    import player.classes.goalkeeper as gk_mod

    seen = []
    real = gk_mod.Goalkeeper._decide_off_ball_defense

    def spy(self, state):
        decision = real(self, state)
        seen.append(decision)
        return decision

    gk_mod.Goalkeeper._decide_off_ball_defense = spy
    try:
        # Two seeds, because how often a keeper gets a claimable loose ball
        # varies a lot match to match -- a single seed makes this flaky
        # without making it any stricter.
        for seed in (7, 2024):
            make_match(seed=seed).run_match(max_steps=10800, render=False)
    finally:
        gk_mod.Goalkeeper._decide_off_ball_defense = real

    assert seen.count("sweep") > 0, "keeper never came off its line all match"
    # Shot-stopping must not have been traded away for it.
    assert seen.count("dive") > 0
    assert seen.count("save") > 0


def test_keeper_decisions_are_reproducible(make_match):
    """Any randomness must go through state["rng"] or replays desync."""
    a, b = make_match(seed=3), make_match(seed=3)
    _park_outfielders_away(a)
    _park_outfielders_away(b)
    da = [a.all_players[KEEPER_A]._decide_off_ball_defense(keeper_state(a, KEEPER_A, (GOAL_CENTER_X, 9.0))) for _ in range(20)]
    db = [b.all_players[KEEPER_A]._decide_off_ball_defense(keeper_state(b, KEEPER_A, (GOAL_CENTER_X, 9.0))) for _ in range(20)]
    assert da == db
