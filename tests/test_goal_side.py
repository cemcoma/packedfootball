"""Pressing and containing the man on the ball: get between him and goal, where he is going --
not run at where he is, which a quicker man simply goes past.

Cheap tests: one decision each, no full matches.
"""

import numpy as np

from player.classes.defender import CB_STAND_DEPTH
from player.player import GOAL_SIDE_CONTAIN, GOAL_SIDE_PRESS
from test_rest_defence import _state_for

LB, CB, CM, ST = 1, 2, 6, 9   # 4-4-2, home side, defending y=0


def _carrier_running_at_goal(match, index, **extra):
    """Their man on the ball at (35, 40), running at our goal; me off to the side of him."""
    return _state_for(match, index, ball_pos=np.array([35.0, 40.0]), ball_velocity=np.array([0.0, -8.0]),
                      my_pos=np.array([22.0, 34.0]), team_possession=-1, is_loose=False, **extra)


def _off_the_goal_line(point, carrier):
    """How far `point` is off the line from the carrier to the middle of our goal."""
    to_goal = np.array([35.0, 0.0]) - carrier
    rel = np.asarray(point) - carrier
    return abs(float(rel[0] * to_goal[1] - rel[1] * to_goal[0])) / float(np.linalg.norm(to_goal))


def test_defenders_press_goal_side_of_where_he_is_going(match):
    target = match.all_players[CB]._build_action("press", _carrier_running_at_goal(match, CB))["target"]
    assert target[1] < 40.0 - GOAL_SIDE_PRESS, "in front of him, toward goal"
    assert _off_the_goal_line(target, np.array([35.0, 40.0])) < 0.5, "on his line to goal"


def test_midfielders_and_forwards_still_close_on_the_ball(match):
    for index in (CM, ST):
        target = match.all_players[index]._build_action("press", _carrier_running_at_goal(match, index))["target"]
        assert target[1] > 34.0, "at him, not dropping in front of him"


def test_containing_stands_off_further_than_pressing(match):
    state = _carrier_running_at_goal(match, CB)
    press = match.all_players[CB]._build_action("press", state)["target"]
    contain = match.all_players[CB]._build_action("contain", state)["target"]
    assert contain[1] < press[1]
    assert np.isclose(press[1] - contain[1], GOAL_SIDE_CONTAIN - GOAL_SIDE_PRESS)


def test_a_loose_ball_is_still_gone_for(match):
    state = _carrier_running_at_goal(match, CB)
    state.update(is_loose=True, ball_velocity=np.zeros(2))
    target = match.all_players[CB]._build_action("press", state)["target"]
    assert target[1] > 34.0, "toward the ball, not back toward goal"


def _coming_at(match, index, carrier_y, my_y):
    return _state_for(match, index, ball_pos=np.array([35.0, carrier_y]), ball_velocity=np.array([0.0, -8.0]),
                      my_pos=np.array([35.0, my_y]), team_possession=-1, is_loose=False)


def test_a_centre_back_does_not_back_off_into_his_box(match):
    target = match.all_players[CB]._build_action("contain", _coming_at(match, CB, carrier_y=28.0, my_y=23.0))["target"]
    assert target[1] == CB_STAND_DEPTH and target[0] == 35.0, "his ground, in the man's path"


def test_a_centre_back_in_his_box_steps_out_to_meet_him(match):
    # Where he will be in a second is inside the box; the press would wait for him there.
    target = match.all_players[CB]._build_action("press", _coming_at(match, CB, carrier_y=26.0, my_y=12.0))["target"]
    assert target[1] == CB_STAND_DEPTH


def test_once_he_is_at_the_box_it_is_the_ordinary_press(match):
    target = match.all_players[CB]._build_action("press", _coming_at(match, CB, carrier_y=CB_STAND_DEPTH + 0.5, my_y=12.0))["target"]
    assert target[1] < CB_STAND_DEPTH


def test_only_centre_backs_stand_their_ground(match):
    state = _coming_at(match, LB, carrier_y=28.0, my_y=23.0)
    assert match.all_players[LB]._build_action("contain", state)["target"][1] < CB_STAND_DEPTH
