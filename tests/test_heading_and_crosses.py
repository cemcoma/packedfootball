"""Engine 2.3.0: the heading attribute, header contests, lofted crosses,
and the wingplay latch.

Before this the engine had no aerial game at all: any ball above 0.75 high
within 2.5 units of anyone was "blocked" into a random deflection, so
nothing could fly over a head, and a cross from the corner flag was on the
deck 0.4s later. See gameEngine's HEAD_* / CROSS_* constants.
"""

import collections
import copy
from pathlib import Path

import numpy as np
import pytest

from conftest import PITCH_HEIGHT, Team, launch_ball, quiesce
from gameEngine import (
    CROSS_ARRIVAL_HEIGHT,
    HEAD_MIN_HEIGHT,
    HEADER_SHOT_RANGE,
    game,
)
from player.player import Attributes
from replay import ActionType

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- attribute

def test_heading_is_an_attribute():
    assert "heading" in Attributes.__dataclass_fields__


def test_heading_round_trips_through_firestore_fields(rosters):
    from game_state import fields_to_player, player_to_fields
    from packEngine import PLAYER_CLASS_MAP
    from player.classes.midfielder import Midfielder

    home, _ = rosters
    fields = player_to_fields(home[2])
    assert "heading" in fields["attributes"]
    restored = fields_to_player(fields, PLAYER_CLASS_MAP, Midfielder)
    assert restored.attributes.heading == home[2].attributes.heading


def test_old_cards_without_heading_still_load():
    """A pre-2.3.0 players/{id} doc has no heading; it gets the default."""
    from game_state import fields_to_player
    from packEngine import PLAYER_CLASS_MAP
    from player.classes.midfielder import Midfielder
    from dataclasses import asdict

    attrs = asdict(Attributes())
    del attrs["heading"]
    fields = {"fname": "A", "lname": "B", "tier": "gold", "position": "CB", "attributes": attrs, "statistics": {}}
    p = fields_to_player(fields, PLAYER_CLASS_MAP, Midfielder)
    assert p.attributes.heading == Attributes().heading


def test_heading_is_primary_for_centre_backs_and_strikers():
    from player.classes.defender import CenterBack
    from player.classes.forward import Forward, Winger

    assert "heading" in CenterBack.primary_stats
    assert "heading" in Forward.primary_stats
    assert "heading" not in Winger.primary_stats


def test_client_card_mirrors_heading():
    """PlayerCard.gd reproduces the overall calculation and defaults a
    missing heading the same way the server does."""
    gd = (ROOT / "mobile/scripts/data/PlayerCard.gd").read_text()
    assert '"CB": ["defending", "tackling", "heading"]' in gd
    assert '"ST": ["shooting", "dribbling", "speed", "power", "heading"]' in gd
    assert 'card.attributes["heading"] = 50' in gd


def test_pack_roller_tiers_heading_by_position():
    """CB/ST roll it high, keepers low, everyone else across the range."""
    from packEngine import PACK_DATABASE, PackManager

    pm = PackManager(PACK_DATABASE, seed=99)
    pool = []
    while len(pool) < 800:
        pool += pm.open_pack("jumbo_standard")
    by_pos = {}
    for p in pool:
        by_pos.setdefault(p.position, []).append(p.attributes.heading)
    mean = {pos: sum(v) / len(v) for pos, v in by_pos.items() if len(v) >= 10}
    assert mean["CB"] > mean["CM"] > mean["GK"], mean
    assert mean["ST"] > mean["CM"], mean
    # Short players can still head: no correlation with height is imposed.
    wingers = [p for p in pool if p.position in ("LW", "RW")]
    assert any(p.attributes.heading >= p.attributes.speed for p in wingers)


def test_backfill_rolls_deterministically():
    import importlib.util

    spec = importlib.util.spec_from_file_location("backfill_heading", ROOT / "backend/scripts/backfill_heading.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    a = module.roll_heading("abc123", "CB", "gold")
    assert a == module.roll_heading("abc123", "CB", "gold")
    assert 62 + 4 <= a <= 70  # top half of gold's range: CB is primary


# ----------------------------------------------------------------- reach

def _stand(g, idx, x, y):
    g.positions[idx] = np.array([x, y], dtype=float)
    g.velocity[idx] = 0.0


def test_a_ball_above_reach_flies_over(match):
    """The fix for "nothing can fly over a head": no touch, no deflection."""
    g = quiesce(match)
    idx = 6
    _stand(g, idx, 35.0, 50.0)
    launch_ball(g, 35.0, 49.5, 0.0, 10.0, height=4.0, event="cross", toucher=15)
    before = np.array(g.ball, dtype=float)
    assert g._attempt_capture(idx) is False
    assert np.allclose(g.ball, before)
    assert g.ball_controller == -1


def test_reach_grows_with_height_and_heading(match):
    g = match
    short = copy.deepcopy(g.all_players[6])
    tall = copy.deepcopy(g.all_players[6])
    short.attributes.height, short.attributes.heading = 165, 30
    tall.attributes.height, tall.attributes.heading = 195, 90
    g.all_players[6] = short
    low = g._head_reach(6)
    g.all_players[6] = tall
    high = g._head_reach(6)
    assert high > low + 0.3
    assert 1.8 < low < high < 3.2


def test_keepers_never_head(match):
    g = match
    assert "GK" == g.formation[0]["role"]
    quiesce(g)
    _stand(g, 0, 35.0, 3.0)
    launch_ball(g, 35.0, 3.5, 0.0, -6.0, height=1.6, event="cross", toucher=15)
    g._attempt_capture(0)
    assert g.visual_action[0] != "header"


def test_a_ball_at_head_height_is_headed(match):
    g = quiesce(match)
    idx = 6
    g.all_players[idx].attributes.height = 190
    g.all_players[idx].attributes.heading = 95
    g._reach[idx] = g._head_reach(idx)
    _stand(g, idx, 35.0, 60.0)
    g.replay = None
    launch_ball(g, 35.0, 59.7, 0.0, 8.0, height=1.7, event="cross", toucher=15)
    g._attempt_capture(idx)
    # Either a clean header (visual set, ball re-released) or a glancing one
    # (deflection) -- the ball is never simply carried on at 1.7 high.
    assert g.ball_controller == -1
    assert g.last_touch_player == idx


def test_won_header_in_the_box_is_a_shot(match):
    g = quiesce(match)
    idx = 9  # team A striker, attacks y = 100
    g.all_players[idx].attributes.heading = 100
    g._reach[idx] = g._head_reach(idx)
    _stand(g, idx, 35.0, PITCH_HEIGHT - 10.0)
    g.rng = np.random.default_rng(1)
    launch_ball(g, 35.0, PITCH_HEIGHT - 10.2, 0.0, 6.0, height=1.7, event="cross", toucher=8)
    shots_before = g.match_stats[idx]["shots"]
    # heading 100 at 6 units/s: win chance is at the 0.95 cap, so a handful
    # of rolls always includes a clean header.
    for _ in range(10):
        g._attempt_capture(idx)
        if g.ball_event == "shot":
            break
        launch_ball(g, 35.0, PITCH_HEIGHT - 10.2, 0.0, 6.0, height=1.7, event="cross", toucher=8)
        g.ball_capture_cooldown = 0
        g.ball_capture_player = -1
        g.player_stun_cooldown[idx] = 0
    assert g.ball_event == "shot"
    assert g.last_shot_player == idx
    assert g.match_stats[idx]["shots"] == shots_before + 1
    assert g.ball[3] > 0.0  # toward y = 100
    assert np.linalg.norm(g.positions[idx] - g._goal_targets[idx]) <= HEADER_SHOT_RANGE


def test_won_header_near_own_goal_is_a_clearance(match):
    g = quiesce(match)
    idx = 2  # team A centre-back, defends y = 0
    g.all_players[idx].attributes.heading = 100
    g._reach[idx] = g._head_reach(idx)
    _stand(g, idx, 35.0, 8.0)
    g.rng = np.random.default_rng(2)
    for _ in range(10):
        launch_ball(g, 35.0, 8.3, 0.0, -6.0, height=1.7, event="cross", toucher=19)
        g.ball_capture_cooldown = 0
        g.ball_capture_player = -1
        g._attempt_capture(idx)
        if g.ball_event == "clearance":
            break
    assert g.ball_event == "clearance"
    assert g.ball[3] > 0.0  # away from own goal


# ---------------------------------------------------------------- crosses

def _play_corner(g, seed=3, frames=700):
    """Takes a corner for team A from the left flag and runs until the
    ball is next touched. Returns (launch ball state, trace of ball rows)."""
    g.rng = np.random.default_rng(seed)
    g.kickoff_timer = 0
    g._begin_restart("corner", 0, out_x=0.0, out_y=PITCH_HEIGHT)
    dt = 1 / 60
    launch = None
    trace = []
    for _ in range(frames):
        if g.match_clock_frames % g.decision_interval == 0:
            g.step()
        g.tick(dt)
        if launch is None and g.ball_controller == -1 and g.ball_event == "cross" and g.restart_type is None:
            launch = np.array(g.ball, dtype=float)
        if launch is not None:
            trace.append(np.array(g.ball, dtype=float))
            if g.ball_controller != -1 or g.out_of_play or g.ball_event != "cross":
                break
    return launch, np.array(trace)


def test_a_corner_is_a_lofted_cross(match):
    """Leaves the boot low, rises to a peak mid-flight, and comes down
    through head height inside the box -- an arc, not a ramp."""
    launch, trace = _play_corner(match)
    assert launch is not None, "the corner was never taken"
    assert launch[4] < 1.0, f"launched at {launch[4]:.2f} high -- born at its peak"
    peak = int(np.argmax(trace[:, 4]))
    assert trace[peak, 4] > 3.0, f"peaked at only {trace[peak, 4]:.2f}"
    assert 0.5 < peak / 60.0 < 1.5, f"peaked {peak / 60.0:.2f}s after the kick"
    in_box = trace[(trace[:, 1] > 82.0) & (trace[:, 0] > 14.0) & (trace[:, 0] < 56.0)]
    assert in_box.size, "the cross never reached the box"
    assert in_box[0, 4] >= HEAD_MIN_HEIGHT, f"entered the box at {in_box[0, 4]:.2f} -- on the deck"


def test_cross_flight_is_deterministic(rosters):
    home, away = rosters
    a = game(Team("H", copy.deepcopy(home)), Team("A", copy.deepcopy(away)), seed=5)
    b = game(Team("H", copy.deepcopy(home)), Team("A", copy.deepcopy(away)), seed=5)
    la, ta = _play_corner(a, seed=4)
    lb, tb = _play_corner(b, seed=4)
    assert np.allclose(la, lb)
    assert ta.shape == tb.shape and np.allclose(ta, tb)


def test_chasers_run_to_where_a_high_ball_drops(match):
    """The landing prediction is the drop point at head height, for both
    sides -- what turns a cross into a contest."""
    g = match
    p = g.all_players[6]
    state = {
        "ball_pos": np.array([10.0, 90.0]),
        "ball_velocity": np.array([20.0, 0.0]),
        "ball_height": CROSS_ARRIVAL_HEIGHT,
        "ball_vz": 9.8,  # up and back down to head height in two seconds
        "a_direction": -1,  # a defender: the ball is NOT progressive for them
        "my_pos": np.array([30.0, 90.0]),
    }
    target = p._predict_ball_landing_target(state)
    assert target[0] > 20.0, f"predicted {target} -- ignored the drop"
    assert abs(target[1] - 90.0) < 1e-6


@pytest.mark.slow
def test_headers_happen_in_real_matches(make_match):
    seen = 0
    for seed in (11, 12, 13):
        g = make_match(seed=seed, record_replay=True)
        g.run_match(render=False)
        seen += sum(1 for e in g.replay._events if e[1] == ActionType.HEADER)
    assert seen >= 3, f"only {seen} headers in three matches"


@pytest.mark.slow
def test_header_goal_is_credited_to_the_header(rosters):
    """Header at goal -> goal: the scorer is the player who headed it."""
    home, away = rosters
    found = False
    # A header that actually goes in is roughly a 1-in-60 seed here, so a
    # 39-seed window passed on luck: any engine change that shifts
    # trajectories moved the hit out of range while the rate was unchanged.
    for seed in range(1, 140):
        g = game(Team("H", copy.deepcopy(home)), Team("A", copy.deepcopy(away)), seed=seed, record_replay=True)
        g.run_match(max_steps=4000, render=False)
        events = g.replay._events
        for k, e in enumerate(events):
            if e[1] != ActionType.GOAL:
                continue
            # An own goal credits the player who put it in, on the far side
            # from the team that scored (see ENGINE_VERSION 2.2.1) -- a header
            # that missed and went in off a defender is one, so it is not the
            # attribution this test is about.
            if (e[2] < 11) != (e[3] == 0):
                continue
            prior = [x for x in events[:k] if x[1] in (ActionType.HEADER, ActionType.SHOOT)]
            if prior and prior[-1][1] == ActionType.HEADER and (prior[-1][2] < 11) == (e[3] == 0):
                assert e[2] == prior[-1][2]
                found = True
        if found:
            break
    assert found, "no header goal in 139 short matches -- corners aren't producing headers at goal"


# --------------------------------------------------------------- wingplay

# Two runners in the box (gameEngine's in_boxes: 14 < x < 56, y > 82) plus
# nine bodies nowhere near it -- a cross has somebody to aim at.
BOX_RUNNERS = np.array([[35.0, 90.0], [42.0, 88.0]] + [[30.0, 40.0]] * 9)
EMPTY_BOX = np.array([[30.0, 40.0]] * 11)


def _winger_state(g, idx, x, y, opponents, intent=None, pressure=0, teammates=None):
    return {
        "has_ball": True,
        "ball_pos": np.array([x, y]),
        "ball_velocity": np.zeros(2),
        "ball_height": 0.0,
        "my_pos": np.array([x, y], dtype=float),
        "my_velocity": np.zeros(2),
        "my_heading": np.array([0.0, 1.0]),
        "dist_to_ball": 0.0,
        "dist_to_goal": float(np.linalg.norm(np.array([35.0, 100.0]) - [x, y])),
        "vec_to_goal": np.array([35.0, 100.0]) - [x, y],
        "enemy_goal": np.array([35.0, 100.0]),
        "goal_target": np.array([35.0, 100.0]),
        "a_direction": 1,
        "in_penalty_box": False,
        "in_attacking_box": False,
        "pressure_count": pressure,
        "teammates": np.array(g.positions[0:11] if teammates is None else teammates, dtype=float),
        "opponents": np.array(opponents, dtype=float),
        "formation_pos": [12.0, 40.0],
        "my_role": "LM",
        "cb_home": True,
        "team_possession": 1,
        "past_halfspace": y > 50.0,
        "own_goal": np.array([35.0, 0.0]),
        "must_pass_next": False,
        "is_loose": False,
        "stamina": 100.0,
        "goal_crossing": None,
        "intent": intent,
        "rng": g.rng,
    }


def _wide_mid(g):
    from packEngine import generate_starter_roster

    p = generate_starter_roster("4-4-2", tier="gold", seed=3)[5]
    assert p.position == "LM"
    return p


def test_latched_winger_never_dribbles_at_goal(match):
    g = match
    p = _wide_mid(g)
    # A marker 4 units ahead on the line: not beaten, nowhere to cross from.
    opponents = np.array([[5.0, 64.0]] + [[35.0, 20.0]] * 10)
    state = _winger_state(g, 5, 5.0, 60.0, opponents, intent="wingplay")
    seen = {p._decide_on_ball_attack(state) for _ in range(200)}
    assert seen <= {"wing_run", "pass"}, seen


def test_latched_winger_crosses_from_the_zone(match):
    g = match
    p = _wide_mid(g)
    opponents = np.array([[5.0, 90.0]] + [[35.0, 20.0]] * 10)
    state = _winger_state(g, 5, 5.0, 86.0, opponents, intent="wingplay", teammates=BOX_RUNNERS)
    decisions = [p._decide_on_ball_attack(state) for _ in range(200)]
    assert decisions.count("cross") > 120, decisions.count("cross")
    assert "dribble" not in decisions and "cut_inside" not in decisions


def test_winger_goes_at_goal_instead_of_crossing_to_nobody(match):
    """The zone is only a crossing position if someone is in the box."""
    g = match
    p = _wide_mid(g)
    opponents = np.array([[5.0, 90.0]] + [[35.0, 20.0]] * 10)
    state = _winger_state(g, 5, 5.0, 86.0, opponents, intent="wingplay", teammates=EMPTY_BOX)
    assert p._box_runners(state) == 0
    assert p._decide_wingplay(state) is None
    decisions = [p._decide_on_ball_attack(state) for _ in range(200)]
    assert "cross" not in decisions
    assert decisions.count("dribble") > 150, decisions.count("dribble")
    assert p._build_action("dribble", state)["target"][1] == PITCH_HEIGHT  # at the goal


def test_a_winger_in_the_box_is_not_its_own_cross_target(match):
    """state["teammates"] holds all eleven, mine included."""
    g = match
    p = _wide_mid(g)
    opponents = np.array([[35.0, 20.0]] * 11)
    me = np.array([[16.0, 88.0]] + [[30.0, 40.0]] * 10)
    assert p._box_runners(_winger_state(g, 5, 16.0, 88.0, opponents, teammates=me)) == 0


def test_a_winger_who_beats_his_man_cuts_inside(match):
    """LW/RW: past the marker, angle at the goal rather than run the line."""
    from packEngine import generate_starter_roster

    lw = generate_starter_roster("4-3-3", tier="gold", seed=3)[8]
    assert lw.position == "LW"
    opponents = np.array([[5.0, 57.0]] + [[35.0, 20.0]] * 10)
    state = _winger_state(match, 8, 5.0, 60.0, opponents, teammates=EMPTY_BOX)
    assert lw._beat_marker(state)
    decisions = [lw._decide_on_ball_attack(state) for _ in range(200)]
    assert decisions.count("cut_inside") > 40, decisions.count("cut_inside")
    action = lw._build_action("cut_inside", state)
    assert action["target"][0] > 5.0 and action["target"][1] > 60.0  # inside and forward



def test_latch_drops_once_the_marker_is_beaten(match):
    g = match
    p = _wide_mid(g)
    # The marker is now 3 units BEHIND and nobody is goal-side.
    opponents = np.array([[5.0, 57.0]] + [[35.0, 20.0]] * 10)
    state = _winger_state(g, 5, 5.0, 60.0, opponents, intent="wingplay")
    assert p._beat_marker(state)
    assert p._decide_wingplay(state) is None


def test_unmarked_is_not_beaten(match):
    g = match
    p = _wide_mid(g)
    opponents = np.array([[35.0, 20.0]] * 11)
    state = _winger_state(g, 5, 5.0, 60.0, opponents)
    assert not p._beat_marker(state)


def test_wing_run_carries_the_latch(match):
    g = match
    p = _wide_mid(g)
    opponents = np.array([[5.0, 64.0]] + [[35.0, 20.0]] * 10)
    action = p._build_action("wing_run", _winger_state(g, 5, 5.0, 60.0, opponents))
    assert action["type"] == "move" and action["intent"] == "wingplay"
    assert action["target"][0] < 5.0  # toward the touchline
    assert action["target"][1] > 60.0  # and up the pitch


def test_central_midfielders_do_not_wing_run(match):
    from packEngine import generate_starter_roster

    cm = generate_starter_roster("4-4-2", tier="gold", seed=3)[6]
    assert cm.position == "CM"
    assert cm.get_action_bias("wing_run", 0.0) == 0.0


def test_engine_keeps_the_latch_between_decisions_and_clears_it_on_release(match):
    g = quiesce(match)
    g.intent[5] = "wingplay"
    g._release_ball(5, np.array([1.0, 0.0]), 10.0, aerial=False, event_type="pass")
    assert g.intent[5] is None


@pytest.mark.slow
def test_wingplay_produces_open_play_crosses():
    from packEngine import generate_starter_roster

    home = generate_starter_roster("4-4-2", tier="gold", seed=11)
    away = generate_starter_roster("4-4-2", tier="gold", seed=12)
    # Six seeds, because open-play crosses run about 1.9 a match and swing 0-4
    # match to match: three seeds could total 2 on a bad draw while the rate
    # itself was fine. Crossing got stricter once a cross had to have someone
    # in (or arriving into) the box to aim at, which is what exposed this.
    open_play = 0
    for seed in (1, 3, 4, 5, 6, 7):
        g = game(Team("H", copy.deepcopy(home)), Team("A", copy.deepcopy(away)), seed=seed, record_replay=True)
        g.run_match(render=False)
        events = g.replay._events
        corner_ticks = [e[0] for e in events if e[1] == ActionType.CORNER]
        open_play += sum(
            1 for e in events
            if e[1] == ActionType.CROSS and not any(0 <= e[0] - t <= 40 for t in corner_ticks)
        )
    assert open_play >= 5, f"only {open_play} open-play crosses in six matches"


# --------------------------------------------------------- attacking shape

def _off_ball_state(g, p, formation, my_pos, ball, teammates):
    st = _winger_state(g, 0, my_pos[0], my_pos[1], np.array([[35.0, 20.0]] * 11),
                       teammates=teammates)
    st["has_ball"] = False
    st["formation_pos"] = list(formation)
    st["ball_pos"] = np.array(ball, dtype=float)
    st["my_role"] = p.position
    return st


def _roster(formation, seed=11):
    from packEngine import generate_starter_roster

    return generate_starter_roster(formation, tier="gold", seed=seed)


def test_a_striker_follows_the_ball_up_the_pitch(match):
    """hold_attack used to be formation slot + 15, which left the striker on
    the halfway line while the ball was on the byline."""
    st = _roster("4-4-2")[9]
    assert st.position == "ST"
    state = _off_ball_state(match, st, (27.0, 47.0), (27.0, 62.0), (5.0, 86.0), EMPTY_BOX)
    x, y = st._build_action("hold_attack", state)["target"]
    assert y > 82.0, f"striker holds at y={y} with the ball on the byline"
    assert 14.0 < x < 56.0, f"striker holds at x={x}, outside the box"


def test_a_holding_midfielder_stays_home_while_the_attack_goes_up(match):
    """The CDM is the rest defence -- it follows barely at all."""
    cdm = _roster("4-3-3")[5]
    assert cdm.position == "CDM"
    state = _off_ball_state(match, cdm, (35.0, 23.0), (35.0, 30.0), (5.0, 86.0), EMPTY_BOX)
    _, y = cdm._build_action("hold_attack", state)["target"]
    assert y <= 23.0 + cdm.attack_push_limit, f"CDM pushed up to y={y}"
    assert y < 40.0


def test_a_central_midfielder_pushes_up_but_stops_short_of_the_striker(match):
    cm = _roster("4-4-2")[6]
    st = _roster("4-4-2")[9]
    assert cm.position == "CM" and st.position == "ST"
    ball = (5.0, 86.0)
    _, cm_y = cm._build_action("hold_attack", _off_ball_state(match, cm, (27.0, 35.0), (27.0, 50.0), ball, EMPTY_BOX))["target"]
    _, st_y = st._build_action("hold_attack", _off_ball_state(match, st, (27.0, 47.0), (27.0, 62.0), ball, EMPTY_BOX))["target"]
    assert 60.0 < cm_y < st_y, f"CM at {cm_y}, striker at {st_y}"


def test_an_empty_box_pulls_the_forwards_into_it(match):
    """The ball is in the final third with nobody in the box: go in, don't
    hold a line thirty units out."""
    st = _roster("4-4-2")[9]
    state = _off_ball_state(match, st, (27.0, 47.0), (27.0, 70.0), (5.0, 80.0), EMPTY_BOX)
    assert st._box_needs_bodies(state)
    decisions = [st._decide_off_ball_attack(state) for _ in range(300)]
    assert decisions.count("attack_box") > 120, collections.Counter(decisions)
    _, y = st._build_action("attack_box", state)["target"]
    assert y > 82.0


def test_nobody_is_pulled_in_when_the_box_is_already_filled(match):
    st = _roster("4-4-2")[9]
    state = _off_ball_state(match, st, (27.0, 47.0), (27.0, 70.0), (5.0, 80.0), BOX_RUNNERS)
    assert not st._box_needs_bodies(state)


# ------------------------------------------------------------------ client

def test_header_event_reaches_the_client():
    reader = (ROOT / "mobile/scripts/data/ReplayReader.gd").read_text()
    playback = (ROOT / "mobile/scripts/screens/MatchPlayback.gd").read_text()
    figure = (ROOT / "mobile/scripts/data/PlayerFigure.gd").read_text()
    assert "HEADER = 15" in reader
    assert 'ReplayReader.ActionType.HEADER: "header"' in playback
    assert '"header": {"kind": "jump"' in figure


def test_engine_version_bumped():
    from gameEngine import ENGINE_VERSION

    major, minor, _ = (int(v) for v in ENGINE_VERSION.split("."))
    assert (major, minor) >= (2, 3)
