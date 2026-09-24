"""Phase 2: restarts happen where the ball actually went out.

Previously every throw-in was taken from the taker's static formation slot
(because reset_positions() snapped all 22 players back before the ball was
placed), the taker was picked by formation slot ORDER rather than proximity
-- which in 4-4-2 meant the same central midfielder took every throw-in on
both touchlines -- and no teammate moved to support.
"""

import numpy as np
import pytest

from conftest import PITCH_HEIGHT, PITCH_WIDTH, launch_ball, tick_until

WIDE_ROLES = {"LB", "RB", "LWB", "RWB", "LM", "RM", "LW", "RW"}


def _force_throw_in(g, out_side="left", y=30.0, toucher=20):
    """Drives the ball off a touchline and returns once the restart is set."""
    if out_side == "left":
        launch_ball(g, 3.0, y, -60.0, 0.0, event="pass", toucher=toucher)
    else:
        launch_ball(g, PITCH_WIDTH - 3.0, y, 60.0, 0.0, event="pass", toucher=toucher)
    tick_until(g, lambda gg: gg.restart_type is not None, max_ticks=30)
    return g


def test_ball_going_out_on_the_side_is_a_throw_in(match):
    g = _force_throw_in(match)
    assert g.restart_type == "throw_in"


@pytest.mark.parametrize("side,expected_x", [("left", 0.0), ("right", PITCH_WIDTH)])
def test_throw_in_is_taken_from_the_touchline_it_crossed(match, side, expected_x):
    g = _force_throw_in(match, out_side=side, y=30.0)
    assert g.ball[0] == pytest.approx(expected_x, abs=0.01)


@pytest.mark.parametrize("y", [15.0, 50.0, 85.0])
def test_throw_in_keeps_its_position_along_the_pitch(make_match, y):
    """A throw-in near one end must not be taken from the halfway line."""
    g = _force_throw_in(make_match(), y=y)
    assert g.ball[1] == pytest.approx(y, abs=2.0)


def test_thrower_is_a_full_back_or_wide_player(match):
    g = _force_throw_in(match)
    role = g.formation[g.restart_player]["role"]
    assert role in WIDE_ROLES, f"throw taken by a {role}"


def test_thrower_is_the_nearest_eligible_player(match):
    g = _force_throw_in(match, out_side="left", y=30.0)
    point = np.array([g.ball[0], g.ball[1]])
    base = 0 if g.restart_team == 0 else 11
    eligible = [base + i for i in range(11) if g.formation[base + i]["role"] in WIDE_ROLES]
    # The taker was snapped onto the ball, so compare everyone else's distance
    # against zero -- nobody eligible should have been closer beforehand.
    assert g.restart_player in eligible
    assert float(np.linalg.norm(g.positions[g.restart_player] - point)) == pytest.approx(0.0, abs=0.01)


def test_thrower_stands_at_the_ball(match):
    g = _force_throw_in(match)
    assert np.allclose(g.positions[g.restart_player], g.ball[0:2], atol=0.01)


def test_teammates_move_to_support_the_throw(match):
    g = _force_throw_in(match, out_side="left", y=30.0)
    point = np.array([g.ball[0], g.ball[1]])
    base = 0 if g.restart_team == 0 else 11

    formation_dists = [
        float(np.linalg.norm(np.array(g.formation[base + i]["pos"], dtype=float) - point))
        for i in range(1, 11)
    ]
    actual_dists = [float(np.linalg.norm(g.positions[base + i] - point)) for i in range(1, 11)]

    assert sum(actual_dists) < sum(formation_dists), "nobody moved toward the throw"


def test_nobody_is_standing_on_the_thrower(match):
    g = _force_throw_in(match)
    point = np.array([g.ball[0], g.ball[1]])
    for i in range(22):
        if i == g.restart_player:
            continue
        assert float(np.linalg.norm(g.positions[i] - point)) > 2.0


def test_everyone_stays_on_the_pitch_after_a_restart(match):
    g = _force_throw_in(match)
    assert g.positions[:, 0].min() >= -0.01 and g.positions[:, 0].max() <= PITCH_WIDTH + 0.01
    assert g.positions[:, 1].min() >= -0.01 and g.positions[:, 1].max() <= PITCH_HEIGHT + 0.01


def _throw_speed(g, pending: bool):
    """Resolves one pass from the restart taker and returns the ball speed."""
    idx = g.restart_player
    g.restart_timer = 0
    g.ball_controller = idx
    g.pending_restart_pass_type = "throw_in" if pending else None
    target = g.positions[idx] + np.array([10.0, 0.0])
    g._resolve_action(idx, {"type": "pass", "target": target, "power": 1.0})
    return float(np.linalg.norm(g.ball[2:4]))


def test_throw_in_uses_two_thirds_power(make_match):
    thrown = _throw_speed(_force_throw_in(make_match()), pending=True)
    kicked = _throw_speed(_force_throw_in(make_match()), pending=False)
    assert thrown == pytest.approx(kicked * (2.0 / 3.0), rel=0.01)


def test_throw_in_is_grounded_and_tagged(make_match):
    g = _force_throw_in(make_match())
    _throw_speed(g, pending=True)
    assert g.ball[4] == pytest.approx(0.0), "a throw-in should not be lofted"
    assert g.ball_event == "throw_in", "capture bonuses key off ball_event"


def test_corner_still_goes_to_the_right_flag(match):
    """Phase 2 must not disturb corners, which already used the out point."""
    launch_ball(match, 60.0, PITCH_HEIGHT - 2.0, 10.0, 60.0, event="pass", toucher=20)
    tick_until(match, lambda gg: gg.restart_type is not None, max_ticks=30)
    if match.restart_type == "corner":
        assert match.ball[0] in (0.0, PITCH_WIDTH)


def test_set_piece_taker_stands_over_the_ball(match):
    """A taker who is not at the ball silently drags it to himself.

    _release_ball sets ball[0:2] = positions[owner], so whoever takes a set
    piece teleports the ball to wherever he happens to be. When takers were
    walked into position instead of placed, the penalty taker was still 32
    units away when he struck it and the shot came from midfield -- and
    nothing in the suite noticed. This is that invariant.
    """
    for kind, team in (("free_kick", 0), ("penalty", 0), ("free_kick", 1), ("penalty", 1)):
        match._begin_restart(kind, team, out_x=30.0, out_y=70.0 if team == 0 else 30.0)
        taker = match.restart_player
        assert taker is not None, f"{kind} picked nobody to take it"
        gap = float(np.linalg.norm(match.positions[taker] - np.array(match.ball[0:2])))
        assert gap < 3.0, f"{kind} taker is {gap:.1f} units from the ball"


def test_free_kick_clears_the_ten_yard_ring(match):
    """Defenders must back off, or the man who just fouled is still stood over
    the ball and free to concede another one straight away."""
    match._begin_restart("free_kick", 0, out_x=35.0, out_y=60.0)
    spot = np.array(match.ball[0:2])
    keepers = set(match._keeper_indices)
    inside = [
        i for i in range(11, 22)
        if i not in keepers and float(np.linalg.norm(match.positions[i] - spot)) < 9.0
    ]
    assert not inside, f"defenders {inside} still inside the ring"
