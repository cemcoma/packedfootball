"""Offside (gameEngine._offside_snapshot / _call_offside) and the run in behind it
invites (player._in_behind_run / _in_behind_target).

Offside is judged when the pass is played -- past the second-last defender and the
ball, in their half, level is onside -- and called when that man goes to play it.
The run in behind is built to be onside at that moment.
"""

from pathlib import Path

import numpy as np

from conftest import Team
from gameEngine import game
from packEngine import generate_starter_roster
from replay import ActionType


def _match():
    m = game(Team("H", generate_starter_roster("4-4-2", "gold", seed=1)),
             Team("A", generate_starter_roster("4-4-2", "gold", seed=2)), seed=5, record_replay=True)
    m.kickoff_timer = 0
    return m


def _set_line(m, line_y):
    """Team A attacks y=100. Team B's keeper on his line, its back four at line_y,
    everyone else of team B well upfield."""
    m.positions[11] = (35.0, 99.0)
    for i, x in zip(range(12, 16), (15.0, 28.0, 42.0, 55.0)):
        m.positions[i] = (x, line_y)
    for i, x in zip(range(16, 22), (15.0, 28.0, 42.0, 55.0, 30.0, 40.0)):
        m.positions[i] = (x, 40.0)
    m.velocity[:] = 0.0


def _pass_from(m, passer, to, event_type="pass"):
    m.ball_controller = passer
    m.ball[0:2] = m.positions[passer]
    direction = np.asarray(to, dtype=float) - m.positions[passer]
    m._release_ball(passer, direction, 20.0, event_type=event_type)
    m.ball_release_cooldown = 0
    m.ball_release_team_cooldown = 0


def _receive(m, receiver):
    m.ball[0:2] = m.positions[receiver]
    m.ball[2:4] = (0.0, 0.0)
    m.ball[4] = 0.0
    return m._attempt_capture(receiver)


def _events(m, action):
    return [e for e in m.replay._events if e[1] == int(action)]


# ------------------------------------------------------------------- offside


def test_a_man_past_the_line_is_flagged_when_he_plays_it():
    m = _match()
    _set_line(m, 70.0)
    m.positions[6] = (35.0, 50.0)   # passer
    m.positions[9] = (35.0, 78.0)   # striker, beyond the line
    _pass_from(m, 6, m.positions[9])
    assert not _receive(m, 9)
    assert m.restart_type == "free_kick" and m.restart_team == 1
    assert _events(m, ActionType.OFFSIDE)


def test_an_onside_man_plays_on():
    m = _match()
    _set_line(m, 70.0)
    m.positions[6] = (35.0, 50.0)
    m.positions[9] = (35.0, 69.8)   # level, within the tolerance: onside
    _pass_from(m, 6, m.positions[9])
    _receive(m, 9)
    assert m.restart_type is None
    assert not _events(m, ActionType.OFFSIDE)


def test_nobody_is_offside_in_his_own_half():
    m = _match()
    _set_line(m, 30.0)                # team B pushed right up
    m.positions[6] = (35.0, 20.0)
    m.positions[9] = (35.0, 45.0)     # past their line, but in his own half
    _pass_from(m, 6, m.positions[9])
    assert m._offside_snap is None


def test_a_throw_in_cannot_be_offside():
    m = _match()
    _set_line(m, 70.0)
    m.positions[6] = (1.0, 50.0)
    m.positions[9] = (35.0, 78.0)
    _pass_from(m, 6, m.positions[9], event_type="throw_in")
    assert m._offside_snap is None


def test_the_kick_that_restarts_a_corner_cannot_be_offside():
    m = _match()
    _set_line(m, 70.0)
    m.positions[6] = (1.0, 99.0)
    m.positions[9] = (35.0, 95.0)
    m._offside_exempt = True          # set as a corner's restart ends
    _pass_from(m, 6, m.positions[9], event_type="cross")
    assert m._offside_snap is None


def test_a_defender_playing_it_first_clears_the_offside():
    m = _match()
    _set_line(m, 70.0)
    m.positions[6] = (35.0, 50.0)
    m.positions[9] = (35.0, 78.0)
    _pass_from(m, 6, m.positions[9])
    m._register_touch(13)             # a centre-back gets a touch on it
    assert m._offside_snap is None


def test_offside_has_a_banner_in_playback():
    gd = (Path(__file__).resolve().parent.parent / "mobile/scripts/screens/MatchPlayback.gd").read_text()
    assert 'ReplayReader.ActionType.OFFSIDE: "OFFSIDE"' in gd


# ------------------------------------------------------------- the run in behind


def _attack_state(line_y, runner_y, passer_y=45.0, ball_y=None):
    """Team A (0-10) attacking y=100; teammate 9 is the runner, 6 the passer."""
    teammates = np.array([[35.0, 5.0], [12.0, 30.0], [27.0, 25.0], [43.0, 25.0], [58.0, 30.0],
                          [15.0, 45.0], [35.0, passer_y], [45.0, 45.0], [58.0, 45.0], [33.0, runner_y], [20.0, 50.0]])
    opponents = np.array([[35.0, 99.0], [15.0, line_y], [28.0, line_y], [42.0, line_y], [55.0, line_y],
                          [15.0, 58.0], [28.0, 58.0], [42.0, 58.0], [55.0, 58.0], [10.0, 50.0], [60.0, 50.0]])
    return {
        "a_direction": 1, "teammates": teammates, "opponents": opponents,
        "ball_pos": np.array([35.0, passer_y if ball_y is None else ball_y]),
        "teammate_vel": np.zeros((11, 2)), "opponent_pace": np.full(11, 7.0),
    }


def test_offside_line_is_the_second_last_defender_or_the_ball():
    striker = generate_starter_roster("4-4-2", "gold", seed=1)[9]
    state = _attack_state(line_y=70.0, runner_y=68.0)
    assert abs(striker._offside_line(state) - 30.0) < 1e-9
    state["ball_pos"] = np.array([35.0, 80.0])   # the ball beyond the line counts instead
    assert abs(striker._offside_line(state) - 20.0) < 1e-9


def test_the_run_in_behind_stays_onside():
    striker = generate_starter_roster("4-4-2", "gold", seed=1)[9]
    state = _attack_state(line_y=70.0, runner_y=60.0)
    state["my_pos"] = state["teammates"][9]
    target = striker._in_behind_run(state)["target"]
    assert not striker._is_offside(state, target)
    assert float(target[1]) > 66.0, "right up on the shoulder, not hanging back"


def test_the_ball_goes_behind_the_line_for_a_runner_on_the_shoulder():
    mid = generate_starter_roster("4-4-2", "gold", seed=1)[6]
    state = _attack_state(line_y=60.0, runner_y=58.5)
    state["my_pos"] = state["teammates"][6]
    target = mid._in_behind_target(state)
    assert target is not None and float(target[1]) > 60.0


def test_no_ball_in_behind_a_deep_line():
    mid = generate_starter_roster("4-4-2", "gold", seed=1)[6]
    state = _attack_state(line_y=90.0, runner_y=88.5, passer_y=70.0)
    state["my_pos"] = state["teammates"][6]
    assert mid._in_behind_target(state) is None


def test_passers_do_not_pick_a_man_stood_offside():
    mid = generate_starter_roster("4-4-2", "gold", seed=1)[6]
    state = _attack_state(line_y=70.0, runner_y=80.0)     # 9 is offside
    state["my_pos"] = state["teammates"][6]
    target = mid._best_progressive_pass_target(state)
    assert target is None or not mid._is_offside(state, target)


# ------------------------------------------------------------------ give and go


def test_the_give_and_go_run_stops_short_of_the_line():
    m = _match()
    _set_line(m, 70.0)
    m.ball[0:2] = (35.0, 50.0)
    assert m._onside_y(6, 85.0) < 70.0, "pulled back onside"
    assert m._onside_y(6, 60.0) == 60.0, "a run that stays onside is left alone"


def test_nobody_checks_his_run_when_their_line_is_in_his_half():
    m = _match()
    _set_line(m, 40.0)                # their back four pushed into team A's half
    m.ball[0:2] = (35.0, 30.0)
    assert m._onside_y(6, 75.0) == 75.0


def test_the_wall_pass_pulls_when_the_runner_is_free_and_onside():
    mid = generate_starter_roster("4-4-2", "gold", seed=1)[6]
    state = _attack_state(line_y=70.0, runner_y=60.0)    # 9 ahead of the passer, onside
    state["my_pos"] = state["teammates"][6]
    state["give_and_go"] = 9
    assert mid._wall_pass_pull(state) > 0.0
    state["teammates"][9] = (33.0, 80.0)                 # now offside
    assert mid._wall_pass_pull(state) == 0.0
    state["give_and_go"] = -1
    assert mid._wall_pass_pull(state) == 0.0
