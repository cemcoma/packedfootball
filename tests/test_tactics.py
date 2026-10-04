"""Tactics (game_config.TACTICS, tactics.py): the plumbing, and the football.

The fast half pins the mechanics: a missing or bad tactics map plays Balanced,
each side's style reaches its own players, a long ball starts the side's push
up, an aerial duel can end in a free kick. The slow half plays full matches and
checks each style actually plays like itself -- and that a high line has the
weakness it should: a quick striker running in behind it.
"""

import copy

import numpy as np
import pytest

import gameEngine
from conftest import Team
from game_config import TACTICS, Tactic
from gameEngine import game
from packEngine import generate_starter_roster
from tactics import sanitize_tactics, tactic_for


def _match(tactics_home=None, tactics_away=None, home_tier="gold", away_tier="gold", seed=3):
    return game(
        Team("H", generate_starter_roster("4-4-2", home_tier, seed=1)),
        Team("A", generate_starter_roster("4-4-2", away_tier, seed=2)),
        seed=seed, tactics_home=tactics_home, tactics_away=tactics_away,
    )


# ------------------------------------------------------------------ plumbing


def test_balanced_is_every_default():
    """Balanced is the engine as it was: any knob added later must default to neutral."""
    assert TACTICS["balanced"] == Tactic()


@pytest.mark.parametrize("raw, style", [
    (None, "balanced"),
    ({}, "balanced"),
    ("possession", "balanced"),             # not a map
    ({"style": "possession"}, "possession"),
    ({"style": "tiki_taka"}, "balanced"),    # unknown style
    ({"style": 7}, "balanced"),
])
def test_sanitize_tactics(raw, style):
    assert sanitize_tactics(raw) == {"style": style}


def test_unknown_keys_are_dropped():
    """The client writes this map directly; nothing it invents reaches the engine."""
    assert sanitize_tactics({"style": "long_ball", "captain": "p1", "cheat": True}) == {"style": "long_ball"}


def test_tactic_for_resolves_styles():
    assert tactic_for({"style": "wing_play"}) is TACTICS["wing_play"]
    assert tactic_for(None) is TACTICS["balanced"]


def test_each_side_gets_its_own_tactic_in_state():
    match = _match({"style": "long_ball"}, {"style": "possession"})
    seen = {}
    for i in (1, 12):
        player = match.all_players[i]
        original = player.step

        def spy(state, i=i, original=original):
            seen[i] = state["tactic"]
            return original(state)

        player.step = spy
    for _ in range(200):
        match.step()
    assert seen[1] is TACTICS["long_ball"]
    assert seen[12] is TACTICS["possession"]


# ---------------------------------------------------------------- long ball


def test_long_ball_sends_the_side_up_under_it():
    match = _match({"style": "long_ball"})
    kicker = 2  # a centre-back
    match.kickoff_timer = 0
    match.ball_controller = kicker
    match.ball[0:2] = match.positions[kicker]
    match._resolve_action(kicker, {"type": "pass", "target": [35.0, 75.0], "power": 1.0, "pass_type": "long"})
    assert match.ball_controller == -1
    assert match.ball[5] > 0.0, "a long ball is hit in the air"
    assert match._punt is not None and match._punt["kicker"] == kicker
    assert match._punt["contest"], "somebody attacks the drop"


def _long_ball_state(line_y):
    """Team A kicking from its own half; their line at line_y, keeper on his line."""
    teammates = np.array([[35.0, 5.0], [12.0, 25.0], [27.0, 20.0], [43.0, 20.0], [58.0, 25.0],
                          [15.0, 40.0], [28.0, 40.0], [42.0, 40.0], [55.0, 40.0], [30.0, 55.0], [40.0, 55.0]])
    opponents = np.array([[35.0, 98.0]] + [[x, line_y] for x in (15.0, 28.0, 42.0, 55.0)]
                         + [[x, 60.0] for x in (15.0, 28.0, 42.0, 55.0)] + [[30.0, 50.0], [40.0, 50.0]])
    return {
        "a_direction": 1, "my_pos": teammates[2], "teammates": teammates, "opponents": opponents,
        "teammate_vel": np.zeros((11, 2)), "ball_pos": teammates[2],
    }


def test_long_ball_goes_over_a_high_line():
    cb = generate_starter_roster("4-4-2", "gold", seed=1)[2]
    cb.attributes.power = 90
    target = cb._long_ball_target(_long_ball_state(line_y=60.0))   # their line 40 off their goal
    assert target[1] > 60.0, "dropped in behind the line, not at the front man"


def test_long_ball_goes_to_the_front_man_against_a_deep_line():
    cb = generate_starter_roster("4-4-2", "gold", seed=1)[2]
    cb.attributes.power = 90
    target = cb._long_ball_target(_long_ball_state(line_y=88.0))   # their line 12 off their goal
    assert target[1] < 70.0, "no room behind a deep line: aimed at the striker"


# ------------------------------------------------------------ aerial fouls


def _duel(match, loser, winner):
    match.positions[winner] = np.array([35.0, 50.0])
    match.positions[loser] = np.array([35.5, 50.0])
    return match._aerial_foul(np.array([loser, winner]), np.array([10.0, 20.0]), winner)


def test_an_aerial_duel_can_end_in_a_free_kick(monkeypatch):
    monkeypatch.setattr(gameEngine, "AERIAL_FOUL_BASE", 1.0)
    match = _match()
    assert _duel(match, loser=5, winner=15)
    assert match.match_stats[5]["fouls"] == 1
    assert match.restart_type == "free_kick" and match.restart_team == 1


def test_one_foul_roll_per_ball_in_the_air(monkeypatch):
    monkeypatch.setattr(gameEngine, "AERIAL_FOUL_BASE", 1.0)
    match = _match()
    assert _duel(match, loser=5, winner=15)
    assert not _duel(match, loser=6, winner=16), "the same flight was already rolled for"


def test_teammates_going_up_together_is_no_foul(monkeypatch):
    monkeypatch.setattr(gameEngine, "AERIAL_FOUL_BASE", 1.0)
    match = _match()
    assert not _duel(match, loser=14, winner=15)


# ------------------------------------------------------------ full matches

REGULATION_FRAMES = 10800


class _Counting(game):
    """The real engine, also counting long balls/punts, passes aimed out wide, and
    how high each side's centre-backs stand while it has the ball."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.long_balls = [0, 0]
        self.passes = [0, 0]
        self.wide_passes = [0, 0]
        self.cb_depth = [[0.0, 0], [0.0, 0]]

    def _resolve_action(self, index, action):
        if action and action.get("type") == "pass" and self.ball_controller == index:
            team = 0 if index < 11 else 1
            self.passes[team] += 1
            self.wide_passes[team] += abs(float(action["target"][0]) - 35.0) >= 15.0
        super()._resolve_action(index, action)

    def step(self):
        super().step()
        if self.ball_controller < 0:
            return
        team = 0 if self.ball_controller < 11 else 1
        ys = self.positions[self._cb_indices[team], 1]
        depth = float(ys.mean()) if team == 0 else float(100.0 - ys.mean())
        self.cb_depth[team][0] += depth
        self.cb_depth[team][1] += 1

    def _start_punt_support(self, kicker, landing):
        self.long_balls[0 if kicker < 11 else 1] += 1
        super()._start_punt_support(kicker, landing)


def _play(home_xi, away_xi, home_tactics, away_tactics, seed):
    match = _Counting(
        Team("H", copy.deepcopy(home_xi)), Team("A", copy.deepcopy(away_xi)),
        seed=seed, record_replay=True, tactics_home=home_tactics, tactics_away=away_tactics,
    )
    match.run_match(max_steps=REGULATION_FRAMES, render=False)
    return match


def _side_totals(match, team):
    from replay import ActionType, decode_replay

    stats = match.match_summary()
    events = decode_replay(match.replay.encode())["events"]
    slots = range(0, 11) if team == 0 else range(11, 22)
    return {
        "passes": sum(stats[i]["passes"] for i in slots),
        "shots": sum(stats[i]["shots"] for i in slots),
        "crosses": sum(1 for e in events if e["type"] == int(ActionType.CROSS) and e["team"] == team),
        "long_balls": match.long_balls[team],
        "pass_attempts": match.passes[team],
        "wide_passes": match.wide_passes[team],
        "cb_depth": match.cb_depth[team][0] / max(1, match.cb_depth[team][1]),
        "goals": match.scores[team],
        "conceded": match.scores[1 - team],
    }


def _versus(xi, tactic, other_xi, other, seeds):
    """Totals for `tactic` (with xi) against `other` (with other_xi), every seed both ways round."""
    mine = {}
    theirs = {}
    for seed in seeds:
        for tactic_home in (True, False):
            if tactic_home:
                match = _play(xi, other_xi, {"style": tactic}, {"style": other}, seed)
            else:
                match = _play(other_xi, xi, {"style": other}, {"style": tactic}, seed)
            me = 0 if tactic_home else 1
            for acc, team in ((mine, me), (theirs, 1 - me)):
                for key, value in _side_totals(match, team).items():
                    acc[key] = acc.get(key, 0.0) + value
    n = 2 * len(seeds)
    return {k: v / n for k, v in mine.items()}, {k: v / n for k, v in theirs.items()}


@pytest.fixture(scope="module")
def styles():
    """Each style against Balanced with the same gold XI on both sides."""
    xi = generate_starter_roster("4-4-2", "gold", seed=1)
    return {t: _versus(xi, t, xi, "balanced", seeds=(21, 22, 23)) for t in ("possession", "long_ball", "wing_play")}


@pytest.mark.slow
def test_possession_keeps_passing(styles):
    mine, theirs = styles["possession"]
    assert mine["passes"] > theirs["passes"] * 1.1


@pytest.mark.slow
def test_long_ball_goes_long(styles):
    mine, theirs = styles["long_ball"]
    assert mine["long_balls"] > theirs["long_balls"] * 1.5


# ------------------------------------------------------ where the line stands


def _shape_state(style, role="CB", slot=(27.0, 15.0)):
    return {
        "a_direction": 1, "formation_pos": slot, "my_role": role, "cb_home": True,
        "own_goal": np.array([35.0, 0.0]), "ball_pos": np.array([35.0, 50.0]), "cb_line": 20.0,
        "tactic": TACTICS[style],
    }


def _target_y(player, decision, style, **kw):
    return float(player._build_action(decision, _shape_state(style, **kw))["target"][1])


def test_possession_holds_a_high_line_and_long_ball_a_deep_one():
    xi = generate_starter_roster("4-4-2", "gold", seed=1)
    cb, lb = xi[2], xi[1]
    fb = {"role": "LB", "slot": (12.0, 20.0)}
    assert _target_y(cb, "hold_attack", "possession") > _target_y(cb, "hold_attack", "balanced") > _target_y(cb, "hold_attack", "long_ball")
    assert _target_y(cb, "hold_defense", "possession") > _target_y(cb, "hold_defense", "balanced")
    # The full-back holds the line with his centre-backs, whose depth carries the tactic.
    assert {_target_y(lb, "back_line", style, **fb) for style in ("possession", "balanced", "long_ball")} == {20.0}


# ------------------------------------------------------------- the wide pass


def _wide_pick_share(style, draws=300):
    """How often a central midfielder, same moment every time, picks the man out wide."""
    passer = generate_starter_roster("4-4-2", "gold", seed=1)[6]
    teammates = np.array([[35.0, 5.0], [12.0, 30.0], [27.0, 25.0], [43.0, 25.0], [58.0, 30.0],
                          [8.0, 58.0], [35.0, 45.0], [45.0, 48.0], [62.0, 58.0], [30.0, 60.0], [40.0, 61.0]])
    # The strikers are free; each wide man has somebody near him.
    opponents = np.array([[35.0, 98.0], [15.0, 80.0], [28.0, 78.0], [42.0, 78.0], [55.0, 80.0],
                          [20.0, 72.0], [32.0, 74.0], [45.0, 74.0], [55.0, 72.0], [10.0, 62.0], [60.0, 62.0]])
    rng = np.random.default_rng(0)
    state = {
        "a_direction": 1, "my_pos": teammates[6], "ball_pos": teammates[6], "teammates": teammates, "teammate_vel": np.zeros((11, 2)),
        "opponents": opponents, "opponent_vel": np.zeros((11, 2)), "opponent_pace": np.full(11, 7.0),
        "enemy_goal": np.array([35.0, 100.0]), "pressure_count": 0, "rng": rng, "tactic": TACTICS[style],
    }
    wide = sum(abs(float(passer._choose_pass_target(state)[0]) - 35.0) >= 15.0 for _ in range(draws))
    return wide / draws


def test_wing_play_looks_for_the_wide_man():
    assert _wide_pick_share("wing_play") > _wide_pick_share("balanced") + 0.10


# --------------------------------------------- a quick striker v a high line

DT = 1.0 / 60.0
_RACE_SPOTS = {
    0: (35, 2), 1: (12, 25), 2: (27, 22), 3: (43, 22), 4: (58, 25), 5: (12, 40), 6: (27, 38), 7: (43, 38),
    8: (58, 40), 9: (35, 58), 10: (22, 50),
    11: (35, 97), 12: (15, 61), 13: (28, 60), 14: (42, 60), 15: (55, 61), 16: (15, 48), 17: (28, 46),
    18: (42, 46), 19: (55, 48), 20: (30, 35), 21: (40, 35),
}


def _race(striker_tier, seed):
    """A bronze side goes long over a gold side's high line (Possession, CBs at y=60),
    its striker level with them. Who has the ball first: 0-10 is the bronze side."""
    home = generate_starter_roster("4-4-2", "bronze", seed=1)
    home[9] = generate_starter_roster("4-4-2", striker_tier, seed=5)[9]
    match = game(Team("H", home), Team("A", generate_starter_roster("4-4-2", "gold", seed=2)), seed=seed,
                 tactics_home={"style": "long_ball"}, tactics_away={"style": "possession"})
    match.kickoff_timer = 0
    for i, spot in _RACE_SPOTS.items():
        match.positions[i] = spot
    match.velocity[:] = 0.0
    match.ball_controller = 2
    match.ball[0:2] = match.positions[2]
    match._resolve_action(2, {"type": "pass", "target": [35.0, 69.0], "power": 1.0, "pass_type": "long"})
    for _ in range(300):
        if match.match_clock_frames % match.decision_interval == 0:
            match.step()
        match.tick(DT)
        if match.ball_controller >= 0:
            return match.ball_controller
    return -1


def test_a_quick_striker_wins_the_race_behind_a_high_line():
    """Possession's weakness: the space behind its high line. The centre-backs have to turn
    round (PLAYER_ACCEL) while the striker is already going, so over a dozen balls in behind
    a platinum striker gets there first a real share of the time and a bronze one doesn't."""
    seeds = range(12)
    quick = sum(_race("platinum", s) in range(0, 11) for s in seeds)
    slow = sum(_race("bronze", s) in range(0, 11) for s in seeds)
    assert quick > slow
    assert quick >= 3
