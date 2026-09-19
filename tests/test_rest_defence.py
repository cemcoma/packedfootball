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

from conftest import quiesce
from gameEngine import PITCH_HEIGHT, PITCH_WIDTH
from player.classes.defender import COVER_DEPTH, COVER_HALF_GAP


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
    assert abs(x - PITCH_WIDTH / 2.0) == COVER_HALF_GAP, "one side of centre, not on the flank"
    assert y == COVER_DEPTH, "in front of its own goal"


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
