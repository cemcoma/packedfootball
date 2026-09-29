"""Direct free kicks are flown (free_kick.py), not rolled.

The module tests pin the physics; the engine tests force a strike with
free_kick.plan_strike monkeypatched and check the match plays it out in time:
the save, block or goal lands when the ball gets there, not on the strike.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import free_kick
from conftest import freeze_players_away_from, launch_ball
from gameEngine import FK_PASS_CHANCE, FK_PASS_CHANCE_MAX, FK_PASS_DESPERATION
from game_config import FK_KEEPER_OFF_LINE, GOAL_WIDTH, PITCH_HEIGHT, PITCH_WIDTH
from replay import ActionType

CENTRE = PITCH_WIDTH / 2.0
SPOT = (35.0, 75.0)


# ---------------------------------------------------------------- the module

def _ball(spot, direction, speed, vz):
    d = np.asarray(direction, dtype=float)
    d = d / np.hypot(*d)
    return np.array([spot[0], spot[1], d[0] * speed, d[1] * speed, 0.0, vz], dtype=float)


def test_a_grounded_ball_moves_as_the_engine_moves_it(make_match):
    g = make_match()
    freeze_players_away_from(g, 35.0, 50.0, radius=30.0)
    launch_ball(g, 35.0, 50.0, 8.0, 6.0, height=0.0, event="pass")
    g.ball[5] = 0.0
    ball = g.ball.copy()
    g.tick(1 / 60)
    free_kick.advance(ball, np.zeros(2))
    assert np.allclose(ball, g.ball)


def test_side_spin_bends_it_to_the_left_of_travel():
    straight = free_kick.predict_crossing(_ball(SPOT, (0, 1), 28.0, 4.0), [0.0, 0.0], PITCH_HEIGHT)
    bent = free_kick.predict_crossing(_ball(SPOT, (0, 1), 28.0, 4.0), [1.0, 0.0], PITCH_HEIGHT)
    assert bent["x"] < straight["x"] - 1.0  # going up the pitch, left is -x


def test_top_spin_dips_it():
    flat = free_kick.predict_crossing(_ball(SPOT, (0, 1), 28.0, 8.0), [0.0, 0.0], PITCH_HEIGHT)
    dipped = free_kick.predict_crossing(_ball(SPOT, (0, 1), 28.0, 8.0), [0.0, 1.0], PITCH_HEIGHT)
    assert dipped["z"] < flat["z"] - 1.0


def test_the_prediction_is_the_flight():
    ball, spin = _ball(SPOT, (-0.1, 1), 27.0, 7.0), [0.8, 0.5]
    predicted = free_kick.predict_crossing(ball, spin, PITCH_HEIGHT)
    flown, sp = ball.copy(), list(spin)
    while flown[1] < PITCH_HEIGHT:
        free_kick.advance(flown, sp)
    assert abs(flown[0] - predicted["x"]) < 0.3
    assert abs(flown[4] - predicted["z"]) < 0.3


@pytest.mark.parametrize("spin", [(0.0, 0.0), (0.9, 0.0), (0.0, 0.9)])
def test_the_launch_is_solved_to_its_target(spin):
    target = (CENTRE - 2.5, 1.6)
    unit, vz = free_kick.solve_launch(SPOT, target, PITCH_HEIGHT, 28.0, np.array(spin))
    hit = free_kick.predict_crossing(_ball(SPOT, unit, 28.0, vz), spin, PITCH_HEIGHT)
    assert abs(hit["x"] - target[0]) < 0.05 and abs(hit["z"] - target[1]) < 0.05


def _scene(wall=(), keeper_at=(CENTRE, 97.0)):
    positions = np.array([[5.0, 5.0]] * 22)
    for n, i in enumerate(wall):
        positions[i] = [CENTRE + (n - 1) * 1.0, SPOT[1] + 9.15]
    positions[21] = keeper_at
    return positions


def _flight(strike, positions, wall=()):
    keeper = SimpleNamespace(vision=70, agility=70, composure=70, ballcontrol=70)
    return free_kick.FreeKickFlight(
        strike, SPOT, PITCH_HEIGHT, 21, keeper, 2.9,
        bodies=[i for i in range(21) if i != 0], reaches=np.full(22, 2.4),
        wall=wall, rng=np.random.default_rng(0),
    )


def _strike(direction, speed, vz, spin=(0.0, 0.0)):
    d = np.asarray(direction, dtype=float)
    return free_kick.FreeKickStrike(d / np.hypot(*d), speed, vz, np.array(spin), "test", (0.0, 0.0))


def _fly(flight, ball, positions, velocity=None):
    velocity = np.zeros((22, 2)) if velocity is None else velocity
    for _ in range(200):
        positions += velocity / 60.0
        contact = flight.step(ball, positions, velocity)
        if contact is not None:
            return contact
        if ball[1] >= PITCH_HEIGHT:
            return None
    return None


def test_a_low_ball_into_the_wall_comes_back_off_it():
    positions = _scene(wall=(12, 13, 14))
    strike = _strike((0, 1), 28.0, 2.0)
    ball = _ball(SPOT, strike.direction, strike.speed, strike.vz)
    contact = _fly(_flight(strike, positions, wall=(12, 13, 14)), ball, positions)
    assert contact == ("wall", 13)
    assert ball[3] < 0.0


def test_a_ball_over_the_wall_is_not_blocked_by_it():
    positions = _scene(wall=(12, 13, 14))
    strike = _strike((0, 1), 28.0, 11.0)
    ball = _ball(SPOT, strike.direction, strike.speed, strike.vz)
    contact = _fly(_flight(strike, positions, wall=(12, 13, 14)), ball, positions)
    assert contact is None or contact[0] not in ("wall", "body")


def test_the_keeper_saves_one_struck_at_him():
    positions = _scene()
    strike = _strike((0, 1), 24.0, 3.0)
    ball = _ball(SPOT, strike.direction, strike.speed, strike.vz)
    contact = _fly(_flight(strike, positions), ball, positions)
    assert contact is not None and contact[0] in ("keeper_catch", "keeper_parry")


def test_the_keeper_cannot_get_across_to_a_corner_he_is_nowhere_near():
    positions = _scene(keeper_at=(CENTRE + 10.0, 97.0))
    unit, vz = free_kick.solve_launch(SPOT, (CENTRE - 3.0, 1.0), PITCH_HEIGHT, 30.0, np.zeros(2))
    strike = _strike(unit, 30.0, vz)
    ball = _ball(SPOT, strike.direction, strike.speed, strike.vz)
    assert _fly(_flight(strike, positions), ball, positions) == ("keeper_beaten", 21, True)


# ----------------------------------------------------------------- the engine

def _aimed(target, speed=28.0, spin=(0.0, 0.0)):
    """A plan_strike that hits `target` exactly: no AI, no execution error."""
    def plan(attrs, spot, goal_y, wall_centre, wall_reach, keeper_x, rng, intent=None):
        unit, vz = free_kick.solve_launch(spot, target, goal_y, speed, np.array(spin))
        return free_kick.FreeKickStrike(unit, speed, vz, np.array(spin), "test", target)
    return plan


def _shooting_free_kick(g, monkeypatch, remove_wall=False):
    g.kickoff_timer = 0
    monkeypatch.setattr(g, "_fk_pass_chance", lambda team: 0.0)
    g._begin_restart("free_kick", 0, out_x=SPOT[0], out_y=SPOT[1])
    assert g.free_kick_kind == "shooting"
    if remove_wall:
        for i in g._fk_wall:
            g.positions[i] = [60.0, 40.0]
        g._fk_wall = []
    return g.restart_player


def _play(g, max_ticks=400):
    """Step and tick like run_match until the flight is over; the events since."""
    first = len(g.replay._events)
    flown = False
    for _ in range(max_ticks):
        if g.match_clock_frames % g.decision_interval == 0:
            g.step()
        g.tick(1 / 60)
        flown = flown or g._fk_flight is not None
        if flown and g._fk_flight is None:
            break
    return [(tick, ActionType(kind), idx) for tick, kind, idx, _ in g.replay._events[first:]]


def _first(events, kind):
    return next(e for e in events if e[1] == kind)


def test_a_save_lands_when_the_ball_gets_there(make_match, monkeypatch):
    g = make_match(record_replay=True)
    taker = _shooting_free_kick(g, monkeypatch, remove_wall=True)
    keeper = g._keeper_indices[1]
    monkeypatch.setattr(free_kick, "plan_strike", _aimed((float(g.positions[keeper][0]), 1.0), speed=24.0))
    events = _play(g)
    shot, save = _first(events, ActionType.SHOOT), _first(events, ActionType.SAVE)
    assert shot[2] == taker and save[2] == keeper
    assert save[0] - shot[0] >= 30, "the save was on the strike, not the arrival"
    assert ActionType.GOAL not in [e[1] for e in events]
    assert g.match_stats[keeper]["saves"] == 1
    assert g.match_stats[taker]["shots_on_target"] == 1


def test_into_the_wall_is_a_block_off_the_wall(make_match, monkeypatch):
    g = make_match(record_replay=True)
    _shooting_free_kick(g, monkeypatch)
    wall = list(g._fk_wall)
    monkeypatch.setattr(free_kick, "plan_strike", _aimed((CENTRE, 0.6)))
    events = _play(g)
    block = _first(events, ActionType.BLOCK)
    assert block[2] in wall
    assert block[0] - _first(events, ActionType.SHOOT)[0] >= 10
    assert g.active_shot_id == -1 and g.last_touch_team == 1
    assert g.ball[3] < 0.0  # coming back off them


def test_a_keeper_out_of_position_is_beaten_and_it_goes_in(make_match, monkeypatch):
    g = make_match(record_replay=True)
    taker = _shooting_free_kick(g, monkeypatch, remove_wall=True)
    keeper = g._keeper_indices[1]
    g.positions[keeper][0] = CENTRE + 10.0
    monkeypatch.setattr(free_kick, "plan_strike", _aimed((CENTRE - 2.8, 1.0), speed=30.0))
    events = _play(g)
    kinds = [e[1] for e in events]
    assert ActionType.SAVE_FAILED in kinds
    assert _first(events, ActionType.GOAL)[2] == taker
    assert g.scores[0] == 1


def test_a_wide_one_is_a_goal_kick_and_not_on_target(make_match, monkeypatch):
    g = make_match(record_replay=True)
    taker = _shooting_free_kick(g, monkeypatch, remove_wall=True)
    monkeypatch.setattr(free_kick, "plan_strike", _aimed((CENTRE - GOAL_WIDTH / 2.0 - 1.0, 1.0)))
    events = _play(g)
    assert _first(events, ActionType.SHOT_OFF_TARGET)[2] == taker
    assert ActionType.GOAL_KICK in [e[1] for e in events]
    assert g.match_stats[taker]["shots_on_target"] == 0


def test_the_open_play_save_roll_never_runs_on_a_free_kick(make_match, monkeypatch):
    g = make_match(record_replay=True)
    _shooting_free_kick(g, monkeypatch, remove_wall=True)
    keeper = g._keeper_indices[1]
    monkeypatch.setattr(free_kick, "plan_strike", _aimed((float(g.positions[keeper][0]) + 1.0, 1.2)))

    def no_roll(*args, **kwargs):
        raise AssertionError("_save_chance rolled on a free kick in flight")
    monkeypatch.setattr(g, "_save_chance", no_roll)
    _play(g)


def test_the_clock_runs_through_the_flight(make_match, monkeypatch):
    g = make_match(record_replay=True)
    _shooting_free_kick(g, monkeypatch, remove_wall=True)
    monkeypatch.setattr(free_kick, "plan_strike", _aimed((CENTRE - 2.0, 1.0)))
    start = g.match_clock_frames
    _play(g)
    assert g.match_clock_frames - start > 10 + 30


# ------------------------------------------------------- shoot or play it in

def test_played_in_when_the_roll_says_so(make_match, monkeypatch):
    g = make_match(record_replay=True)
    g.kickoff_timer = 0
    monkeypatch.setattr(g, "_fk_pass_chance", lambda team: 1.0)
    g._begin_restart("free_kick", 0, out_x=SPOT[0], out_y=SPOT[1])
    taker = g.restart_player
    assert g.free_kick_kind == "played_in"
    assert g.must_pass_next and g.must_pass_player == taker
    assert g.pending_restart_pass_type == "cross"
    assert g.replay._events[-1][1] == ActionType.FREE_KICK
    keeper = g._keeper_indices[1]
    assert g.positions[keeper][1] == pytest.approx(PITCH_HEIGHT - FK_KEEPER_OFF_LINE[1])


def test_desperation_plays_more_of_them_in(match):
    assert match._fk_pass_chance(0) == pytest.approx(FK_PASS_CHANCE)
    match.scores[1] = 1
    match.halftime_clock_frames = match.regulation_half_frames
    match.match_clock_frames = 2 * match.regulation_half_frames
    assert match._fk_pass_chance(0) == pytest.approx(FK_PASS_CHANCE + FK_PASS_DESPERATION)
    match.scores[1] = 3
    assert match._fk_pass_chance(0) == pytest.approx(FK_PASS_CHANCE_MAX)


def test_nobody_but_the_wall_stands_in_the_shooting_lane(make_match, monkeypatch):
    g = make_match()
    taker = _shooting_free_kick(g, monkeypatch)
    spot = np.array(g.ball[0:2])
    goal = np.array([CENTRE, PITCH_HEIGHT])
    unit = (goal - spot) / np.linalg.norm(goal - spot)
    across = np.array([-unit[1], unit[0]])
    length = float(np.linalg.norm(goal - spot))
    for i in range(22):
        if i in g._keeper_indices or i in g._fk_wall or i == taker:
            continue
        rel = g.positions[i] - spot
        along = float(rel @ unit)
        if 0.0 < along <= length:
            assert abs(float(rel @ across)) >= GOAL_WIDTH / 2.0 * along / length, f"{i} is in the lane"
