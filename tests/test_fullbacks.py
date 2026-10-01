"""Full-backs in the attack: the ball-side one keeps up with play and overlaps, the far one
stays home, and the carrier plays the overlap in once he is closed down.

Cheap tests: one decision each, no full matches.
"""

import numpy as np

from conftest import quiesce
from player.classes.defender import FB_ATTACK_LIMIT, OVERLAP_INSIDE_X
from player.player import OVERLAP_PASS_WEIGHT, OFFSIDE_MARGIN
from test_rest_defence import _state_for

LB, RB, LM = 1, 4, 5   # 4-4-2, home side, attacking up the pitch


def _with_ball(match, index, ball, **overrides):
    return _state_for(match, index, ball_pos=np.array(ball, dtype=float), **overrides)


def test_ball_side_fullback_overlaps(match):
    state = _with_ball(match, LB, [20.0, 60.0], intent="overlap")
    assert match.all_players[LB]._decide_off_ball_attack(state) == "overlap"

    action = match.all_players[LB]._build_action("overlap", state)
    assert action["intent"] == "overlap", "the carrier is told he is coming"
    assert action["target"][1] > 60.0, "past the ball"
    assert action["target"][0] < 20.0, "outside a carrier who is in off the line"


def test_far_side_fullback_never_overlaps(match):
    state = _with_ball(match, RB, [20.0, 60.0])
    decisions = {match.all_players[RB]._decide_off_ball_attack(state) for _ in range(60)}
    assert "overlap" not in decisions


def test_no_overlap_without_a_centre_back_home(match):
    state = _with_ball(match, LB, [20.0, 60.0], intent="overlap", cb_home=False)
    assert match.all_players[LB]._decide_off_ball_attack(state) == "cover"


def test_overlap_goes_inside_a_carrier_on_the_touchline(match):
    state = _with_ball(match, LB, [3.0, 60.0])
    x = match.all_players[LB]._build_action("overlap", state)["target"][0]
    assert x == 3.0 + OVERLAP_INSIDE_X, "the underlap"


def test_overlap_stays_onside(match):
    state = _with_ball(match, LB, [20.0, 88.0])
    fb = match.all_players[LB]
    target_y = fb._build_action("overlap", state)["target"][1]
    assert 100.0 - target_y >= fb._offside_line(state) + OFFSIDE_MARGIN - 1e-9


def test_ball_side_fullback_keeps_up_with_play(match):
    slot_y = match.formation[LB]["pos"][1]
    near = match.all_players[LB]._build_action("hold_attack", _with_ball(match, LB, [20.0, 85.0]))
    far = match.all_players[RB]._build_action("hold_attack", _with_ball(match, RB, [20.0, 85.0]))
    assert slot_y + 15.0 < near["target"][1] <= slot_y + FB_ATTACK_LIMIT
    assert far["target"][1] == match.formation[RB]["pos"][1] + 15.0, "the far one stays home"


def test_fullback_carries_it_up_his_flank(match):
    state = _with_ball(match, LB, match.positions[LB], has_ball=True)
    action = match.all_players[LB]._build_action("dribble", state)
    assert action["target"][0] == match.positions[LB][0], "up the line, not across the middle"


def test_carrier_plays_in_a_free_overlap_once_closed_down(match):
    mates = match.positions[0:11].copy()
    opponents = match.positions[11:22].copy()
    mates[LM] = [12.0, 60.0]
    mates[LB] = [5.0, 68.0]            # ahead of him, outside, onside, free
    opponents[2] = [13.0, 63.0]        # the man on the carrier
    state = _state_for(match, LM, has_ball=True, ball_pos=mates[LM], my_pos=mates[LM],
                       teammates=mates, opponents=opponents, overlap=LB,
                       teammate_vel=np.zeros((11, 2)), opponent_vel=np.zeros((11, 2)))
    winger = match.all_players[LM]
    assert winger._wall_pass_pull(state) == OVERLAP_PASS_WEIGHT
    target = winger._choose_pass_target(state)
    assert np.linalg.norm(target - mates[LB]) < 3.0


def test_engine_tells_teammates_who_is_overlapping(make_match):
    match = quiesce(make_match(adaptive_decisions=False))
    match.intent[LB] = "overlap"
    seen = {}
    for i in (LM, LB, 15):
        original = match.all_players[i].step
        def spy(state, i=i, original=original):
            seen[i] = state["overlap"]
            return original(state)
        match.all_players[i].step = spy
    match.step()
    assert seen == {LM: LB, LB: -1, 15: -1}, "his teammates, not himself or the other side"
