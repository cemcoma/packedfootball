"""The back line off the ball: it holds up the pitch with the ball upfield instead of running
back to its formation slot, and still turns and drops for a ball played at its goal.

Cheap tests: one decision each, no full matches.
"""

import numpy as np

from player.classes.defender import DEF_LINE_MAX, DEF_LINE_SHARE
from test_rest_defence import _state_for

CB, LB = 2, 1   # 4-4-2, home side, defending y=0


def _target_y(match, index, decision, **state):
    return match.all_players[index]._build_action(decision, _state_for(match, index, **state))["target"][1]


def test_centre_back_holds_the_line_with_their_ball_upfield(match):
    y = _target_y(match, CB, "hold_defense", ball_pos=np.array([35.0, 70.0]), team_possession=-1)
    assert y == 70.0 * DEF_LINE_SHARE, "not his slot minus ten, on the six-yard line"


def test_loose_ball_upfield_holds_the_line_too(match):
    for index in (CB, LB):
        y = _target_y(match, index, "recover", ball_pos=np.array([35.0, 90.0]), is_loose=True, team_possession=0)
        assert y == DEF_LINE_MAX


def test_the_line_drops_for_a_ball_played_at_it(match):
    y = _target_y(match, CB, "recover", ball_pos=np.array([35.0, 70.0]), ball_velocity=np.array([0.0, -15.0]),
                  is_loose=True, team_possession=0)
    slot_y = match.formation[CB]["pos"][1]
    assert y == slot_y + (70.0 - 50.0) * 0.10, "back toward his slot, as before"


def test_the_line_is_never_deeper_than_it_was(match):
    slot_y = match.formation[CB]["pos"][1]
    for ball_y in (8.0, 20.0, 40.0, 60.0, 80.0):
        y = _target_y(match, CB, "hold_defense", ball_pos=np.array([35.0, ball_y]), team_possession=-1)
        assert y >= slot_y - 10.0


def test_a_centre_back_steps_into_midfield_but_no_further(match):
    assert _target_y(match, CB, "forward_run", team_possession=1) == 50.0
    assert _target_y(match, LB, "forward_run", team_possession=1) == 100.0, "a full-back goes all the way"


def test_a_full_back_stands_level_with_his_centre_backs(match):
    # Ball central 31 off goal, CBs on 29: he used to sit 10 goal-side of the ball, on 21,
    # and play everyone between him and them onside.
    y = _target_y(match, LB, "back_line", ball_pos=np.array([35.0, 31.0]), cb_line=29.0, team_possession=-1)
    assert y == 29.0


def test_a_full_back_is_level_with_a_ball_that_is_past_his_centre_backs(match):
    y = _target_y(match, LB, "back_line", ball_pos=np.array([35.0, 24.0]), cb_line=29.0, team_possession=-1)
    assert y == 24.0


def test_midfielders_keep_in_front_of_their_centre_backs(match):
    from player.player import BACK_LINE_GAP
    cdm = match.all_players[6]   # a 4-4-2 CM stands in: same rule for every midfielder and forward
    state = _state_for(match, 6, ball_pos=np.array([35.0, 45.0]), cb_line=38.0, team_possession=1)
    assert cdm._build_action("hold_attack", state)["target"][1] >= 38.0 + BACK_LINE_GAP
    state = _state_for(match, 6, ball_pos=np.array([35.0, 70.0]), cb_line=35.0, team_possession=-1)
    assert cdm._build_action("hold_defense", state)["target"][1] >= 35.0 + BACK_LINE_GAP


def test_a_tackle_is_never_made_on_a_teammate(match):
    from conftest import quiesce
    quiesce(match)
    match.ball_controller = 6
    match.positions[2] = match.positions[6] + np.array([0.5, 0.0])
    for _ in range(50):
        match._resolve_action(2, {"type": "tackle", "stat": 999})
    assert match.ball_controller == 6 and match.match_stats[2]["tackles"] == 0
    assert match.restart_type is None, "no foul, no penalty"


def test_a_ball_over_the_top_sends_the_midfield_back_too(match):
    state = _state_for(match, 6, ball_pos=np.array([35.0, 45.0]), ball_velocity=np.array([0.0, -15.0]),
                       cb_line=38.0, is_loose=True, team_possession=0)
    assert match.all_players[6]._build_action("recover", state)["target"][1] < 38.0, "no floor while it comes at goal"
