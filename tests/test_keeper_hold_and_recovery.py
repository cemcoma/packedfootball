"""A beaten defender sprints back goal-side; a keeper who picks the ball up
holds it while the field backs off, then punts it as far as his power allows."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import player.player as player_module
from conftest import freeze_players_away_from, launch_ball, quiesce
from game_config import (
    PITCH_HEIGHT,
    PITCH_WIDTH,
    RECOVERY_CB_LANE,
    RECOVERY_DEFENDING_BONUS,
    RECOVERY_PRESS_RANGE,
    RECOVERY_SPRINT,
    pace_ability,
    stat_ability,
)
from gameEngine import (
    KEEPER_BACKOFF_OPPONENTS,
    KEEPER_BACKOFF_TEAMMATES,
    KEEPER_HANDS_HEIGHT,
    KEEPER_HOLD_FRAMES,
)
from replay import ActionType

KEEPER = 0          # team A's keeper, defending y = 0
CENTRE_BACK = 2
MIDFIELDER = 6      # a CM in a 4-4-2; slot 5 is LM
LEFT_MID = 5
STRIKER = 9
CARRIER = 20        # a team B forward, attacking y = 0


# ------------------------------------------------------------ recovery runs

def _carrier_through(g, carrier_at=(35.0, 30.0)):
    """Team B's forward on the ball, running at team A's goal."""
    quiesce(g)
    g.positions[CARRIER] = carrier_at
    g.velocity[CARRIER] = [0.0, -6.0]
    g.ball_controller = CARRIER
    g.ball[0:2] = carrier_at
    g.ball[2:4] = g.velocity[CARRIER]
    return g


def _who_recovers(g, monkeypatch) -> set:
    runners = set()
    original = player_module.player._recovery_run

    def spy(self, state):
        runners.add(next(i for i, p in enumerate(g.all_players) if p is self))
        return original(self, state)
    monkeypatch.setattr(player_module.player, "_recovery_run", spy)
    g.step()
    return runners


def test_beaten_defenders_and_midfielders_run_back(make_match, monkeypatch):
    g = _carrier_through(make_match(adaptive_decisions=False))
    g.positions[CENTRE_BACK] = [36.0, 40.0]
    g.positions[MIDFIELDER] = [30.0, 42.0]
    g.positions[STRIKER] = [40.0, 44.0]
    runners = _who_recovers(g, monkeypatch)
    assert {CENTRE_BACK, MIDFIELDER} <= runners
    assert STRIKER not in runners, "forwards keep their own behaviour"


def test_attacking_and_wide_midfielders_hold_their_position(make_match, monkeypatch):
    g = _carrier_through(make_match(adaptive_decisions=False))
    g.positions[LEFT_MID] = [30.0, 42.0]
    assert LEFT_MID not in _who_recovers(g, monkeypatch)
    assert g._last_actions[LEFT_MID]["speed_mod"] < pace_ability(g.all_players[LEFT_MID].attributes.speed)
    for role in ("CAM", "LM", "RM"):
        state = _run_state(g, LEFT_MID) | {"my_role": role, "rng": g.rng}
        assert g.all_players[LEFT_MID]._decide_off_ball_defense(state) == "hold_defense"


def test_a_centre_mid_recovers_a_touch_slower_than_a_holding_mid(make_match):
    g = _carrier_through(make_match())
    g.positions[MIDFIELDER] = [30.0, 42.0]
    mid = g.all_players[MIDFIELDER]
    cm = mid._recovery_run(_run_state(g, MIDFIELDER) | {"my_role": "CM"})["speed_mod"]
    cdm = mid._recovery_run(_run_state(g, MIDFIELDER) | {"my_role": "CDM"})["speed_mod"]
    assert cm == pytest.approx(0.9 * cdm)


def test_a_defender_goal_side_of_the_ball_does_not(make_match, monkeypatch):
    g = _carrier_through(make_match(adaptive_decisions=False))
    g.positions[CENTRE_BACK] = [35.0, 22.0]
    assert CENTRE_BACK not in _who_recovers(g, monkeypatch)


def _run_state(g, i):
    return {
        "my_pos": g.positions[i], "ball_pos": np.array(g.ball[0:2]),
        "ball_velocity": np.array(g.ball[2:4]), "own_goal": g._own_goals[i],
        "team_possession": -1, "is_loose": False, "a_direction": 1,
        "formation_pos": g.formation[i]["pos"], "my_role": g.formation[i]["role"],
    }


def test_the_run_is_flat_out_and_faster_with_defending(make_match):
    g = _carrier_through(make_match())
    g.positions[CENTRE_BACK] = [36.0, 40.0]
    defender = g.all_players[CENTRE_BACK]
    action = defender._recovery_run(_run_state(g, CENTRE_BACK))
    pace = pace_ability(defender.attributes.speed)
    expected = pace * RECOVERY_SPRINT * (1.0 + RECOVERY_DEFENDING_BONUS * stat_ability(defender.attributes.defending))
    assert action["speed_mod"] == pytest.approx(expected)
    assert action["speed_mod"] > pace

    weak, strong = copy.deepcopy(defender), copy.deepcopy(defender)
    weak.attributes.defending, strong.attributes.defending = 40, 95
    state = _run_state(g, CENTRE_BACK)
    assert strong._recovery_run(state)["speed_mod"] > weak._recovery_run(state)["speed_mod"]


def test_a_centre_back_beaten_by_a_winger_covers_the_middle(make_match):
    g = _carrier_through(make_match(), carrier_at=(62.0, 35.0))
    g.positions[CENTRE_BACK] = [50.0, 48.0]
    target = g.all_players[CENTRE_BACK]._recovery_run(_run_state(g, CENTRE_BACK))["target"]
    assert abs(target[0] - PITCH_WIDTH / 2.0) <= RECOVERY_CB_LANE + 1e-6, "went to the winger"
    assert target[1] < g.ball[1], "not goal-side of the ball"


def test_a_full_back_beaten_on_his_flank_takes_the_flank(make_match):
    g = _carrier_through(make_match(), carrier_at=(62.0, 35.0))
    right_back = next(i for i in range(11) if g.formation[i]["role"] == "RB")
    g.positions[right_back] = [58.0, 48.0]
    target = g.all_players[right_back]._recovery_run(_run_state(g, right_back))["target"]
    assert target[0] > PITCH_WIDTH / 2.0 + RECOVERY_CB_LANE
    assert target[1] < g.ball[1]


def test_the_back_line_recovers_to_one_depth(make_match):
    g = _carrier_through(make_match(), carrier_at=(62.0, 35.0))
    line = [i for i in range(11) if g.formation[i]["role"] in ("CB", "LB", "RB")]
    for n, i in enumerate(line):
        g.positions[i] = [15.0 + 12.0 * n, 50.0]
    depths = {round(float(g.all_players[i]._recovery_run(_run_state(g, i))["target"][1]), 6) for i in line}
    assert len(depths) == 1


def test_within_press_range_he_goes_at_the_carrier(make_match):
    g = _carrier_through(make_match(), carrier_at=(62.0, 35.0))
    g.positions[CENTRE_BACK] = [60.0, 40.0]
    target = g.all_players[CENTRE_BACK]._recovery_run(_run_state(g, CENTRE_BACK))["target"]
    assert target[0] > PITCH_WIDTH / 2.0 + RECOVERY_CB_LANE, "stayed in the middle with the man on him"
    assert np.linalg.norm(target - g.ball[0:2]) < RECOVERY_PRESS_RANGE


def test_a_centre_back_holds_the_middle_until_the_winger_is_on_him(make_match):
    g = _carrier_through(make_match(adaptive_decisions=False), carrier_at=(62.0, 35.0))
    g.velocity[CARRIER] = [0.0, 0.0]
    g.ball[2:4] = [0.0, 0.0]
    g.positions[CENTRE_BACK] = [43.0, 26.0]   # goal-side, 20 units in from the winger
    g.step()
    action = g._last_actions[CENTRE_BACK]
    assert abs(action["target"][0] - PITCH_WIDTH / 2.0) <= RECOVERY_CB_LANE + 1e-6

    g.positions[CENTRE_BACK] = [57.0, 31.0]   # now he is on him
    g.step()
    assert g.all_players[CENTRE_BACK]._holds_the_middle(_run_state(g, CENTRE_BACK)) is False


# -------------------------------------------------------------- the hold

def _keeper_with_it(g):
    quiesce(g)
    g.positions[KEEPER] = [35.0, 4.0]
    g.ball[0:2] = g.positions[KEEPER]
    g._keeper_gather(KEEPER)
    return g


def test_a_catch_is_held_in_his_hands(match):
    g = _keeper_with_it(match)
    assert g.keeper_holding == KEEPER and g.keeper_hold_timer == KEEPER_HOLD_FRAMES
    g.tick(1 / 60)
    assert g.ball[4] == pytest.approx(KEEPER_HANDS_HEIGHT)


def test_a_loose_ball_he_picks_up_is_held(match):
    g = match
    freeze_players_away_from(g, 35.0, 5.0, radius=10.0)
    g.positions[KEEPER] = [35.0, 4.0]
    for _ in range(30):
        launch_ball(g, 35.2, 4.3, 0.0, -0.5, event="neutral", toucher=CARRIER)
        g.ball_capture_player = -1
        if g._attempt_capture(KEEPER):
            break
    assert g.ball_controller == KEEPER
    assert g.keeper_holding == KEEPER


def test_a_back_pass_at_his_feet_is_not_picked_up(match):
    g = match
    freeze_players_away_from(g, 35.0, 5.0, radius=10.0)
    g.positions[KEEPER] = [35.0, 4.0]
    for _ in range(30):
        launch_ball(g, 35.2, 4.3, 0.0, -3.0, event="pass", toucher=CENTRE_BACK)
        g.ball_capture_player = -1
        g._attempt_capture(KEEPER)
    assert g.keeper_holding == -1


def test_nobody_can_tackle_him(match):
    g = _keeper_with_it(match)
    g.positions[CARRIER] = [35.5, 4.5]
    g._resolve_action(CARRIER, {"type": "tackle", "stat": 999})
    assert g.ball_controller == KEEPER


def test_he_waits_before_he_lets_it_go(make_match):
    g = _keeper_with_it(make_match())
    for n in range(400):
        if g.match_clock_frames % g.decision_interval == 0:
            g.step()
        g.tick(1 / 60)
        if g.ball_controller != KEEPER:
            break
    assert n + 1 >= KEEPER_HOLD_FRAMES


def test_the_field_backs_off(make_match, monkeypatch):
    g = _keeper_with_it(make_match(adaptive_decisions=False))
    g.positions[CARRIER] = [37.0, 6.0]
    g.positions[CENTRE_BACK] = [34.0, 5.0]
    start = float(np.linalg.norm(g.positions[CARRIER] - g.positions[KEEPER]))

    resolved = []
    original = g._resolve_action
    monkeypatch.setattr(g, "_resolve_action", lambda i, a: (resolved.append((i, a)), original(i, a))[1])
    for _ in range(KEEPER_HOLD_FRAMES - 4):
        if g.match_clock_frames % g.decision_interval == 0:
            g.step()
        g.tick(1 / 60)

    keeper_at = g.positions[KEEPER]
    for i, action in resolved:
        if i == KEEPER or not action:
            continue
        assert action.get("type") not in ("tackle", "capture")
        if action.get("type") != "move":
            continue
        radius = KEEPER_BACKOFF_TEAMMATES if i < 11 else KEEPER_BACKOFF_OPPONENTS
        assert np.linalg.norm(np.asarray(action["target"]) - keeper_at) >= radius - 0.2
    assert np.linalg.norm(g.positions[CARRIER] - keeper_at) > start + 5.0


# -------------------------------------------------------------- the punt

@pytest.mark.parametrize("power, reach", [(40, 0.4), (30, 0.4), (90, 2 / 3), (120, 2 / 3)])
def test_punt_reach_follows_power(match, power, reach):
    keeper = copy.deepcopy(match.all_players[KEEPER])
    keeper.attributes.power = power
    assert keeper._punt_reach() == pytest.approx(PITCH_HEIGHT * reach)


def test_more_power_kicks_further(match):
    weak, strong = copy.deepcopy(match.all_players[KEEPER]), copy.deepcopy(match.all_players[KEEPER])
    weak.attributes.power, strong.attributes.power = 55, 80
    assert strong._punt_reach() > weak._punt_reach()


def test_a_punt_comes_down_on_its_target(make_match, monkeypatch):
    g = _keeper_with_it(make_match(record_replay=True))
    freeze_players_away_from(g, 35.0, 30.0, radius=45.0)
    g.positions[KEEPER] = [35.0, 4.0]
    g.player_stun_cooldown[KEEPER] = 0
    g.ball_capture_player = -1
    monkeypatch.setattr(g, "_fuzz_pass_direction", lambda i, unit, kind: unit)
    target = np.array([35.0, 50.0])
    g._resolve_action(KEEPER, {"type": "pass", "target": target, "power": 1.0, "pass_type": "punt"})
    assert g.replay._events[-1][1] == ActionType.CLEARANCE
    flying = False
    for _ in range(400):
        g.tick(1 / 60)
        flying = flying or g.ball[4] > 0.0
        if flying and g.ball[4] == 0.0:
            break
    assert np.linalg.norm(np.array(g.ball[0:2]) - target) < 1.5


# ------------------------------------------------------- going up for the punt

def _punted(make_match, monkeypatch):
    g = _keeper_with_it(make_match(adaptive_decisions=False))
    g.player_stun_cooldown[KEEPER] = 0
    g.ball_capture_player = -1
    monkeypatch.setattr(g, "_fuzz_pass_direction", lambda i, unit, kind: unit)
    target = np.array([35.0, 50.0])
    g._resolve_action(KEEPER, {"type": "pass", "target": target, "power": 1.0, "pass_type": "punt"})
    return g, target


def test_his_side_goes_up_for_the_punt(make_match, monkeypatch):
    g, landing = _punted(make_match, monkeypatch)
    punt = g._punt
    assert punt is not None and len(punt["contest"]) == 2 and len(punt["ring"]) == 3
    before = {i: g.positions[i].copy() for i in punt["rest"]}
    resolved = {}
    original = g._resolve_action
    monkeypatch.setattr(g, "_resolve_action", lambda i, a: (resolved.__setitem__(i, a), original(i, a))[1])
    g.tick(1 / 60)
    g.tick(1 / 60)
    g.step()
    for i in punt["contest"]:
        assert np.linalg.norm(resolved[i]["target"] - landing) < 1e-6
    for i in punt["ring"]:
        assert np.linalg.norm(resolved[i]["target"] - landing) < 8.0
    pushed = [i for i in punt["rest"] if resolved.get(i) and resolved[i]["target"][1] > before[i][1]]
    assert pushed, "nobody behind the drop pushed up"


def test_the_support_ends_when_somebody_has_it(make_match, monkeypatch):
    g, _ = _punted(make_match, monkeypatch)
    g.ball_controller = CARRIER
    g.step()
    assert g._punt is None
