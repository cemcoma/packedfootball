"""Full-backs cover the middle when no centre-back is home.

The breakaway-from-a-corner problem: with both CBs in the opposition box
the full-backs used to sit on their flanks (or wander up), so a clearance
to a lone striker met an empty centre. Now the engine tells every player
whether one of their CBs is holding the middle (state["cb_home"]), and a
full-back without one tucks in (defender.py's "cover"), and at an own
corner the non-box attackers start on a rest-defence line behind halfway.

Cheap tests: one decision each, no full matches.
"""

import numpy as np
import pytest

from conftest import quiesce
from game_config import pace_ability
from gameEngine import PITCH_HEIGHT, PITCH_WIDTH
from player.classes.defender import COVER_HALF_GAP, HANDBACK_PACE, STAND_IN_BALL_GAP, STAND_IN_LINE, STAND_IN_ZONE


def _state_for(match, index, **overrides):
    """A minimal off-ball state dict for player `index`, as step() would
    build it, with cb_home/my_role settable."""
    home = index < 11
    base = {
        "has_ball": False,
        "ball_pos": np.array([35.0, 90.0 if home else 10.0]),  # far away, in the other box
        "ball_velocity": np.zeros(2),
        "ball_height": 0.0,
        "my_pos": match.positions[index],
        "my_velocity": match.velocity[index],
        "my_heading": match.heading[index],
        "dist_to_ball": 60.0,
        "dist_to_goal": 50.0,
        "vec_to_goal": np.array([0.0, 50.0]),
        "enemy_goal": np.array([35.0, 100.0 if home else 0.0]),
        "goal_target": np.array([35.0, 100.0 if home else 0.0]),
        "a_direction": 1 if home else -1,
        "in_penalty_box": False,
        "in_attacking_box": False,
        "pressure_count": 0,
        "teammates": match.positions[0:11] if home else match.positions[11:22],
        "opponents": match.positions[11:22] if home else match.positions[0:11],
        "formation_pos": match.formation[index]["pos"],
        "my_role": match.formation[index]["role"],
        "cb_home": True,
        "team_possession": 1,
        "past_halfspace": False,
        "own_goal": np.array([35.0, 0.0 if home else PITCH_HEIGHT]),
        "must_pass_next": False,
        "is_loose": False,
        "stamina": 100.0,
        "goal_crossing": None,
        "rng": match.rng,
    }
    base.update(overrides)
    return base


def _fullback(match, team=0):
    base = 0 if team == 0 else 11
    for i in range(base, base + 11):
        if match.formation[i]["role"] in ("LB", "RB", "LWB", "RWB"):
            return i
    raise AssertionError("fixture formation has no full-back")


def test_fullback_covers_the_middle_when_no_cb_is_home(match):
    fb = _fullback(match)
    player = match.all_players[fb]
    state = _state_for(match, fb, cb_home=False)

    assert player._decide_off_ball_attack(state) == "cover"
    assert player._decide_off_ball_defense(state) == "cover"

    action = player._build_action("cover", state)
    assert action["type"] == "move"
    x, y = action["target"]
    assert (x - PITCH_WIDTH / 2.0) * np.sign(match.formation[fb]["pos"][0] - PITCH_WIDTH / 2.0) > -COVER_HALF_GAP
    assert abs(x - PITCH_WIDTH / 2.0) < STAND_IN_ZONE, "in the middle, not on the flank"
    assert y == pytest.approx(STAND_IN_LINE), "up at halfway, where a man behind him is offside"


def test_fullback_keeps_its_flank_when_a_cb_is_home(match):
    fb = _fullback(match)
    player = match.all_players[fb]
    state = _state_for(match, fb, cb_home=True)
    # Many rolls: "cover" must never come up while a CB is holding the middle.
    for _ in range(50):
        assert player._decide_off_ball_attack(state) != "cover"
        assert player._decide_off_ball_defense(state) != "cover"


def test_own_corner_leaves_a_rest_defence_in_the_middle(match):
    """At an attacking corner every attacker not sent into the box (bar the
    keeper and the taker) stands behind halfway, around the centre."""
    quiesce(match)
    match._begin_restart("corner", team=0, out_x=60.0)
    a_box = {2, 3, 6, 7, 9, 10}
    rest = [i for i in range(1, 11) if i not in a_box and i != match.restart_player]
    assert rest, "nothing left to form a rest defence with"
    for i in rest:
        x, y = match.positions[i]
        assert y < 50.0, f"player {i} is not behind halfway ({y})"
        assert abs(x - PITCH_WIDTH / 2.0) < 20.0, f"player {i} is out wide ({x})"


# -------------------------------------------------- standing in at centre-back (5.2.0)

LB, LCB, RCB, RB = 1, 2, 3, 4   # 4-4-2, home side


def _counter(match, lcb_y, rcb_y=70.0, lb=(28.0, 20.0)):
    """Their counter at our goal (y=0) with the ball in our half; positions for _update_stand_ins."""
    quiesce(match)
    match.ball[0:2] = [40.0, 30.0]
    pos = match.positions.tolist()
    pos[LB], pos[LCB], pos[RCB] = list(lb), [27.0, lcb_y], [43.0, rcb_y]
    return pos


def test_each_full_back_stands_in_for_the_centre_back_on_his_side(match):
    assert match._fb_partner[LB] == LCB and match._fb_partner[RB] == RCB


def test_a_centre_back_coming_home_does_not_release_the_full_back(match):
    """The bug: the CB got back inside CB_HOME_DEPTH and both full-backs went back to their flanks,
    leaving the striker. He stays in until his own CB is level with him."""
    pos = _counter(match, lcb_y=70.0)
    match._update_stand_ins([False, True], -1, pos)
    assert match._stand_in[LB] and match._stand_in[RB]

    pos[LCB] = [27.0, 35.0]   # home again, still 15 up from him
    match._update_stand_ins([True, True], -1, pos)
    assert match._stand_in[LB] and match._stand_in[RB]

    pos[LCB] = [27.0, 20.5]   # level
    match._update_stand_ins([True, True], -1, pos)
    assert not match._stand_in[LB]
    assert match._stand_in[RB], "his own CB is still upfield"


def test_our_ball_with_his_centre_back_home_releases_him(match):
    pos = _counter(match, lcb_y=70.0)
    match._update_stand_ins([False, True], -1, pos)
    pos[LCB] = [27.0, 35.0]
    match._update_stand_ins([True, True], 1, pos)
    assert not match._stand_in[LB]


def _standing_in(match, striker, **overrides):
    away = np.array([[35.0, 90.0]] * 11)
    away[9] = striker
    fields = {"stand_in": True, "team_possession": -1, "ball_pos": np.array([50.0, 60.0]),
              "opponents": away, "opponent_vel": np.zeros((11, 2)), **overrides}
    return _state_for(match, LB, **fields)


def test_standing_in_he_holds_halfway_in_his_mans_lane(match):
    """Not 22 deep, which played every long ball onside: a striker behind him is left offside."""
    player = match.all_players[LB]
    state = _standing_in(match, [30.0, 30.0])
    assert player._decide_off_ball_defense(state) == "cover"
    x, y = player._build_action("cover", state)["target"]
    assert (x, y) == pytest.approx((30.0, STAND_IN_LINE))

    x, y = player._build_action("cover", _standing_in(match, [28.0, 58.0]))["target"]
    assert y == pytest.approx(STAND_IN_LINE)
    assert 28.0 < x < 30.0, "where the striker's run to goal crosses the line"


def test_their_ball_past_the_line_takes_him_back_with_it(match):
    player = match.all_players[LB]
    state = _standing_in(match, [30.0, 30.0], ball_pos=np.array([20.0, 35.0]))
    assert player._cover_target(state, None)[1] == pytest.approx(35.0 - STAND_IN_BALL_GAP)


def test_a_ball_played_in_behind_drops_him_to_where_it_comes_down(match):
    player = match.all_players[LB]
    state = _standing_in(match, [30.0, 30.0], ball_pos=np.array([35.0, 70.0]), ball_velocity=np.array([0.0, -20.0]),
                         ball_height=1.0, ball_vz=8.0, is_loose=True)
    assert player._cover_target(state, None)[1] < STAND_IN_LINE - 5.0


def test_standing_in_he_plays_centre_back_not_full_back(match):
    """Near the ball he does not hold the back line off the CBs' (upfield) line, and he stands his
    ground at the edge of the box like a CB."""
    player = match.all_players[LB]
    state = _standing_in(match, [30.0, 30.0], ball_pos=np.array([40.0, 30.0]), my_pos=np.array([33.0, 22.0]))
    assert not player._holds_back_line(state)
    assert player._plays_cb(state)


def test_released_he_walks_back_to_his_flank(match):
    player = match.all_players[LB]
    state = _state_for(match, LB, my_pos=np.array([30.0, 20.0]), stand_in=False, intent="stand_in",
                       team_possession=-1, ball_pos=np.array([35.0, 60.0]))
    action = player._build_action("back_line", state)
    assert action["intent"] == "handback"
    assert action["speed_mod"] == pytest.approx(pace_ability(player.attributes.speed) * HANDBACK_PACE)

    action = player._build_action("back_line", {**state, "intent": None})
    assert action["speed_mod"] > pace_ability(player.attributes.speed) * HANDBACK_PACE
