"""Attacking moves against a set defender: going round him (take_on), and the duel that decides it.

Cheap tests: one decision each, no full matches.
"""

import numpy as np

from conftest import quiesce
from game_config import take_on_skill
from player.player import MOVE_DRIBBLE_KEEP, TAKE_ON_BEYOND, TAKE_ON_WIDTH
from test_rest_defence import _state_for

ST = 9   # 4-4-2 home striker, attacking y=100

NOBODY = [[60.0, 5.0]] * 11   # opponents parked out of the way; index 0 is their keeper


def _facing(match, man, *others, keeper=(35.0, 98.0), me=(35.0, 70.0), **extra):
    opponents = np.array(NOBODY, dtype=float)
    opponents[0] = keeper
    opponents[1] = man
    for k, o in enumerate(others):
        opponents[2 + k] = o
    return _state_for(match, ST, has_ball=True, my_pos=np.array(me), ball_pos=np.array(me),
                      opponents=opponents, enemy_goal=np.array([35.0, 100.0]), **extra)


def test_he_goes_round_the_man_on_the_clear_side(match):
    # The man is straight in front; a second opponent sits level with him, off to the low-x side.
    state = _facing(match, (35.0, 73.0), (30.0, 72.0))
    spot, _ = match.all_players[ST]._take_on_route(state)
    assert spot[0] == 35.0 + TAKE_ON_WIDTH, "away from the other man"
    assert spot[1] == 73.0 + TAKE_ON_BEYOND, "past him, not level"


def test_a_covered_man_is_not_taken_on(match):
    state = _facing(match, (35.0, 73.0), (36.0, 77.0))   # a second man goal-side of him
    assert match.all_players[ST]._take_on_route(state) is None


def test_the_keeper_is_not_the_man_to_beat(match):
    state = _facing(match, (60.0, 5.0), keeper=(35.0, 73.0))
    assert match.all_players[ST]._take_on_route(state) is None


def test_a_side_once_taken_is_kept(match):
    state = _facing(match, (35.0, 73.0), (30.0, 72.0), intent="take_on+1")
    route = match.all_players[ST]._take_on_route(state)
    assert route is None or route[1] == 1, "the crowded side, because he already went that way"


def test_a_way_round_replaces_most_of_the_straight_dribble(match):
    moves, dribble = match.all_players[ST]._carve_attack_moves(_facing(match, (35.0, 73.0)), 100.0)
    assert moves["take_on"] > 0.0 and dribble == 100.0 * MOVE_DRIBBLE_KEEP


class _FixedRoll:
    """The match rng with random() pinned, so the tackle roll is known."""
    def __init__(self, rng, value):
        self._rng, self._value = rng, value

    def random(self, *a, **kw):
        return self._value

    def __getattr__(self, name):
        return getattr(self._rng, name)


def test_a_take_on_duel_reads_dribbling_not_just_ball_control(match):
    quiesce(match)
    holder, tackler = ST, 13
    attrs = match.all_players[holder].attributes
    attrs.ballcontrol, attrs.dribbling, attrs.agility = 10, 99, 99
    match.all_players[tackler].attributes.tackling = 60
    match.positions[tackler] = match.positions[holder] + np.array([0.0, 1.0])
    match.rng = _FixedRoll(match.rng, 0.45)   # steals at 0.40 + (60 - 10)/100; not at 0.40 + (60 - 63)/100

    match.ball_controller = holder
    match.intent[holder] = "take_on+1"
    match._resolve_action(tackler, {"type": "tackle", "stat": 60})
    assert match.ball_controller == holder, f"his {take_on_skill(attrs):.0f} take-on skill should have held it"

    match.player_stun_cooldown[:] = 0
    match.intent[holder] = None
    match._resolve_action(tackler, {"type": "tackle", "stat": 60})
    assert match.ball_controller != holder, "standing still, ball control 10 loses it"


# ------------------------------------------------- carrying it across, and the shot from the edge

from player.player import ACROSS_DIST   # noqa: E402


def test_he_carries_it_across_to_where_the_shot_is_on(match):
    # 22 out, a man straight in the shot's way; off to the high-x side the lane is clear.
    state = _facing(match, (35.0, 84.0), (28.0, 86.0), me=(35.0, 78.0))
    spot, _ = match.all_players[ST]._across_route(state)
    assert spot[0] == 35.0 + ACROSS_DIST and spot[1] == 78.0, "sideways, at the same depth"


def test_no_carry_when_the_shot_is_already_on(match):
    state = _facing(match, (45.0, 84.0), me=(35.0, 78.0))
    assert match.all_players[ST]._across_route(state) is None


def test_no_carry_from_too_far_out(match):
    state = _facing(match, (35.0, 64.0), me=(35.0, 58.0))
    assert match.all_players[ST]._across_route(state) is None


def test_a_carry_that_opened_the_lane_ends_in_the_shot(match):
    state = _facing(match, (45.0, 84.0), me=(35.0, 78.0), intent="across+1")
    assert match.all_players[ST]._latched_attack_move(state) == "shoot"


def _edge_shots(match, man):
    state = _facing(match, man, me=(35.0, 78.0), dist_to_goal=22.0, vec_to_goal=np.array([0.0, 22.0]),
                    my_heading=np.array([0.0, 1.0]), past_halfspace=True, team_possession=1)
    return sum(match.all_players[ST]._decide_on_ball_attack(state) == "shoot" for _ in range(300))


def test_a_striker_shoots_from_the_edge_only_with_the_lane_open(match):
    # A man standing off just to the side of the line blocks the run in, not the shot. Straight
    # on the line he blocks both. (With the run open he carries it closer: _better_shot_ahead.)
    shut, open_ = _edge_shots(match, (35.0, 84.0)), _edge_shots(match, (37.2, 84.0))
    assert shut == 0 and open_ >= 5, f"{open_} shots in 300 with the shot on"
