"""The shooting / goalkeeping rebalance.

Keepers used to reach everything, and measuring why turned up four separate
problems rather than one:

  1. `shots_on_target` counted keeper TOUCHES, not shots on target -- 63% of
     all "saves" were of balls already going wide or over the bar.
  2. Keepers committed to those shots in the first place, because the only
     question they asked was "is the ball coming this way", never "would it
     go in".
  3. The save roll ignored the shot completely: a full-stretch dive at a
     screamer was exactly as likely to succeed as a tame roller.
  4. The save was re-rolled every step while the ball was near, so 111 shots
     produced 74 save rolls.

Everything here tests the fix for one of those. The numbers are anchored to
the agreed spec: a 100-rated keeper saves ~100% of an easy shot (slow,
straight at them) and ~50% of a hard one (fast, at full stretch).
"""

import numpy as np
import pytest

from conftest import GOAL_CENTER_X, launch_ball, quiesce
from gameEngine import (
    GOAL_HEIGHT,
    HARD_SHOT_SPEED,
    KEEPER_BEATEN_FRAMES,
    KEEPER_REACH,
    MAX_DIFFICULTY_PENALTY,
    SAVE_COMMIT_MARGIN,
)

KEEPER_A = 0    # defends y=0
SHOOTER_B = 20  # an away forward, used as `last_shot_player`


class FakeAttrs:
    """Just the fields _save_chance and the gather roll read."""

    def __init__(self, rating):
        self.agility = rating
        self.vision = rating
        self.ballcontrol = rating
        self.composure = rating


def set_up_shot(g, cross_x, speed=20.0, keeper_x=GOAL_CENTER_X, distance=4.0, height=0.0):
    """Puts a live shot in flight at keeper A's goal (y=0).

    The ball travels straight down the y axis from `distance` out, so it
    crosses the goal line at exactly `cross_x` -- moving the aim point is how
    these tests make a shot on target, wide, or over. The keeper stands on
    its line at `keeper_x`.

    Returns the shot id. Note it deliberately does NOT reset
    save_attempted_shot: the engine never does either, it relies on ids being
    unique, and clearing it here would hide the very latch under test.
    """
    quiesce(g)
    g.positions[KEEPER_A] = np.array([float(keeper_x), 1.0])
    g.velocity[KEEPER_A] = np.zeros(2)
    g.player_stun_cooldown[KEEPER_A] = 0

    launch_ball(g, cross_x, distance, 0.0, -abs(speed), height=height, event="shot", toucher=SHOOTER_B)

    g._shot_counter += 1
    g.active_shot_id = g._shot_counter
    g.last_shot_player = SHOOTER_B
    return g.active_shot_id


# ------------------------------------------------------------ the save curve

def test_a_perfect_keeper_saves_an_easy_shot(match):
    """Slow ball, straight at them: the agreed ~100% anchor."""
    chance = match._save_chance(FakeAttrs(100), ball_speed=5.0, lateral=0.0)
    assert chance >= 0.95


def test_a_perfect_keeper_is_even_money_on_the_hardest_shot(match):
    """Fastest ball, full-stretch dive: the agreed ~50% anchor."""
    chance = match._save_chance(FakeAttrs(100), ball_speed=HARD_SHOT_SPEED, lateral=KEEPER_REACH)
    assert chance == pytest.approx(1.0 - MAX_DIFFICULTY_PENALTY, abs=0.02)


def test_save_chance_falls_as_the_shot_gets_faster(match):
    speeds = [5.0, 15.0, 25.0, HARD_SHOT_SPEED]
    chances = [match._save_chance(FakeAttrs(80), s, lateral=1.0) for s in speeds]
    assert chances == sorted(chances, reverse=True)
    assert chances[0] > chances[-1], "ball speed doesn't affect the save at all"


def test_save_chance_falls_the_further_the_keeper_must_move(match):
    """The 'how far do they have to dive' half of the difficulty."""
    laterals = [0.0, 2.0, 4.0, KEEPER_REACH]
    chances = [match._save_chance(FakeAttrs(80), ball_speed=20.0, lateral=x) for x in laterals]
    assert chances == sorted(chances, reverse=True)
    assert chances[0] > chances[-1], "dive distance doesn't affect the save at all"


def test_a_better_keeper_saves_more_of_the_same_shot(match):
    """The whole point of card quality. Before the rebalance the save roll
    barely depended on the keeper at all."""
    bronze = match._save_chance(FakeAttrs(48), ball_speed=25.0, lateral=3.0)
    icon = match._save_chance(FakeAttrs(97), ball_speed=25.0, lateral=3.0)
    assert icon > bronze + 0.1


def test_beyond_full_stretch_is_no_worse_than_full_stretch(match):
    """Difficulty terms are clamped, so an absurd input can't drive the save
    chance negative or below the floor."""
    far = match._save_chance(FakeAttrs(80), ball_speed=999.0, lateral=999.0)
    stretch = match._save_chance(FakeAttrs(80), ball_speed=HARD_SHOT_SPEED, lateral=KEEPER_REACH)
    assert far == pytest.approx(stretch)
    assert 0.02 <= far <= 0.99


def test_even_a_terrible_keeper_saves_something(match):
    assert match._save_chance(FakeAttrs(1), ball_speed=HARD_SHOT_SPEED, lateral=KEEPER_REACH) >= 0.02


# ------------------------------------------------------- one attempt per shot

def test_a_save_is_rolled_once_per_shot(match, monkeypatch):
    """The bug this replaces: while the ball was within 4 units and heading
    goalward the keeper got a fresh independent roll every single step.
    """
    rolls = []
    real = match._save_chance

    def counting(*args, **kwargs):
        rolls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(match, "_save_chance", counting)

    set_up_shot(match, cross_x=GOAL_CENTER_X)
    for _ in range(10):
        match._attempt_save(KEEPER_A)

    assert len(rolls) == 1, f"one shot, {len(rolls)} save rolls"


def test_the_latch_is_per_shot_not_forever(match, monkeypatch):
    """A keeper who used their attempt on one shot still gets one at the next.

    Checked with the keeper explicitly back on their feet, so this is the
    shot-id latch being tested and not the beaten-keeper timer.
    """
    monkeypatch.setattr(match, "_save_chance", lambda *a, **k: 0.0)  # always beaten

    set_up_shot(match, cross_x=GOAL_CENTER_X)
    assert match._attempt_save(KEEPER_A) is False
    match.player_stun_cooldown[KEEPER_A] = 0
    assert match._attempt_save(KEEPER_A) is False, "same shot, second attempt"

    second = set_up_shot(match, cross_x=GOAL_CENTER_X)
    match.player_stun_cooldown[KEEPER_A] = 0
    match._attempt_save(KEEPER_A)
    assert match.save_attempted_shot[KEEPER_A] == second, "new shot got no attempt"


def test_a_keeper_does_not_burn_its_attempt_on_a_distant_shot(match):
    """The engage gate. A shot struck from 40 units out must not resolve the
    keeper's single save the instant it leaves the boot.
    """
    set_up_shot(match, cross_x=GOAL_CENTER_X, distance=40.0, speed=18.0)
    assert match._attempt_save(KEEPER_A) is False
    assert match.save_attempted_shot[KEEPER_A] == -1, "attempt was consumed from 40 units out"


def test_a_keeper_ignores_a_ball_going_well_wide(match):
    """No attempt, no stun, no stat -- the keeper simply doesn't dive."""
    inner_min, _ = match.goal_frame_bounds()
    set_up_shot(match, cross_x=inner_min - SAVE_COMMIT_MARGIN - 5.0)

    assert match._attempt_save(KEEPER_A) is False
    assert match.save_attempted_shot[KEEPER_A] == -1
    assert match.player_stun_cooldown[KEEPER_A] == 0
    assert match.match_stats[KEEPER_A]["saves"] == 0


def test_a_keeper_ignores_a_ball_flying_over_the_bar(match):
    set_up_shot(match, cross_x=GOAL_CENTER_X, height=GOAL_HEIGHT + 8.0)
    crossing = match.predict_goal_crossing(0)
    assert crossing["z"] > GOAL_HEIGHT, "test setup: ball wasn't actually high"

    assert match._attempt_save(KEEPER_A) is False
    assert match.save_attempted_shot[KEEPER_A] == -1


# ------------------------------------------------------- the beaten keeper

def test_a_beaten_keeper_goes_down(match, monkeypatch):
    monkeypatch.setattr(match, "_save_chance", lambda *a, **k: 0.0)
    set_up_shot(match, cross_x=GOAL_CENTER_X)

    assert match._attempt_save(KEEPER_A) is False
    assert match.player_stun_cooldown[KEEPER_A] == KEEPER_BEATEN_FRAMES


def test_a_beaten_keeper_cannot_rescue_the_rebound(match, monkeypatch):
    """The case that made this a timer instead of a shot-id lock: the ball
    clips the post, slows to a crawl and comes back. A keeper lying on the
    floor must not quietly reclaim it through the capture path.
    """
    monkeypatch.setattr(match, "_save_chance", lambda *a, **k: 0.0)
    set_up_shot(match, cross_x=GOAL_CENTER_X)
    match._attempt_save(KEEPER_A)

    # Rebound, right at their feet, barely moving.
    match.ball[0:2] = match.positions[KEEPER_A]
    match.ball[2:4] = np.array([0.0, 0.5])
    match.ball[4] = 0.0
    match.ball_event = "neutral"
    match.ball_capture_player = -1
    match.ball_capture_cooldown = 0
    match.ball_release_player = -1
    match.ball_release_cooldown = 0

    assert not any(match._attempt_capture(KEEPER_A) for _ in range(20))
    assert match.ball_controller == -1


def test_a_keeper_back_on_their_feet_can_claim_the_ball(match):
    """The other half of the timer: it has to expire."""
    quiesce(match)
    match.player_stun_cooldown[KEEPER_A] = 0
    match.ball[0:2] = match.positions[KEEPER_A]
    match.ball[2:4] = np.zeros(2)
    match.ball[4] = 0.0
    match.ball_event = "neutral"

    claimed = False
    for _ in range(10):
        match.ball[0:2] = match.positions[KEEPER_A]
        match.ball_capture_player = -1
        match.ball_capture_cooldown = 0
        if match._attempt_capture(KEEPER_A):
            claimed = True
            break
    assert claimed, "an un-stunned keeper never claimed a dead ball at its feet"


def test_being_beaten_wears_off(match, monkeypatch):
    monkeypatch.setattr(match, "_save_chance", lambda *a, **k: 0.0)
    set_up_shot(match, cross_x=GOAL_CENTER_X)
    match._attempt_save(KEEPER_A)

    before = int(match.player_stun_cooldown[KEEPER_A])
    match.step()
    assert int(match.player_stun_cooldown[KEEPER_A]) < before, "the keeper is down forever"


# ---------------------------------------------------- on-target accounting

def test_predicted_crossing_decides_on_target_not_the_keeper(match):
    inner_min, inner_max = match.goal_frame_bounds()

    set_up_shot(match, cross_x=GOAL_CENTER_X)
    assert match.predict_goal_crossing(0)["on_target"] is True

    set_up_shot(match, cross_x=inner_max + 3.0)
    assert match.predict_goal_crossing(0)["on_target"] is False

    set_up_shot(match, cross_x=inner_min - 3.0)
    assert match.predict_goal_crossing(0)["on_target"] is False


def test_saving_an_on_target_shot_credits_the_shooter(match, monkeypatch):
    monkeypatch.setattr(match, "_save_chance", lambda *a, **k: 1.0)  # always saved
    set_up_shot(match, cross_x=GOAL_CENTER_X)

    assert match._attempt_save(KEEPER_A) is True
    assert match.match_stats[KEEPER_A]["saves"] == 1
    assert match.match_stats[SHOOTER_B]["shots_on_target"] == 1


def test_a_shot_going_just_wide_is_not_on_target_even_when_saved(match, monkeypatch):
    """SAVE_COMMIT_MARGIN means a keeper still reacts to one whistling past
    the post -- that touch counts as a save, but the shot was never on target
    and must not be counted as one. This is precisely the accounting bug that
    inflated shots_on_target to 80%.
    """
    monkeypatch.setattr(match, "_save_chance", lambda *a, **k: 1.0)
    _, inner_max = match.goal_frame_bounds()
    set_up_shot(match, cross_x=inner_max + SAVE_COMMIT_MARGIN * 0.5)

    assert match.predict_goal_crossing(0)["on_target"] is False
    assert match._attempt_save(KEEPER_A) is True
    assert match.match_stats[KEEPER_A]["saves"] == 1
    assert match.match_stats[SHOOTER_B]["shots_on_target"] == 0


def test_a_goal_is_always_on_target(match):
    match.last_shot_player = SHOOTER_B
    match._award_goal(1)
    assert match.match_stats[SHOOTER_B]["shots_on_target"] == 1


def test_a_shot_is_only_credited_on_target_once(match, monkeypatch):
    """last_shot_player is cleared on credit, so a scramble in which the ball
    is saved and then bundled in can't count the same shot twice.
    """
    monkeypatch.setattr(match, "_save_chance", lambda *a, **k: 1.0)
    set_up_shot(match, cross_x=GOAL_CENTER_X)
    match._attempt_save(KEEPER_A)
    match._award_goal(1)

    assert match.match_stats[SHOOTER_B]["shots_on_target"] == 1


# -------------------------------------------------------------- the dive

def test_a_dive_is_a_real_save_attempt_when_the_ball_is_close(match):
    """`dive` used to be a move action only -- the keeper repositioned and
    the ball went in past them.
    """
    gk = match.all_players[KEEPER_A]
    match.positions[KEEPER_A] = np.array([GOAL_CENTER_X, 1.0])
    state = {
        "ball_pos": np.array([GOAL_CENTER_X + 1.0, 4.0]),
        "my_pos": np.array(match.positions[KEEPER_A]),
        "a_direction": 1,
        "rng": match.rng,
        "goal_crossing": {"x": GOAL_CENTER_X + 1.0, "z": 0.5, "time": 0.2, "on_target": True},
    }
    assert gk._build_action("dive", state)["type"] == "save"


def test_a_dive_at_a_distant_ball_is_still_just_repositioning(match):
    gk = match.all_players[KEEPER_A]
    match.positions[KEEPER_A] = np.array([GOAL_CENTER_X, 1.0])
    state = {
        "ball_pos": np.array([GOAL_CENTER_X + 2.0, 30.0]),
        "my_pos": np.array(match.positions[KEEPER_A]),
        "a_direction": 1,
        "rng": match.rng,
        "goal_crossing": {"x": GOAL_CENTER_X + 2.0, "z": 0.5, "time": 1.1, "on_target": True},
    }
    assert gk._build_action("dive", state)["type"] == "move"


def test_a_keeper_does_not_commit_to_a_shot_that_misses(match):
    """goalkeeper.py's own gate, upstream of _attempt_save."""
    gk = match.all_players[KEEPER_A]
    match.positions[KEEPER_A] = np.array([GOAL_CENTER_X, 1.0])
    base = {
        "has_ball": False,
        "ball_pos": np.array([GOAL_CENTER_X + 10.0, 6.0]),
        "ball_velocity": np.array([0.0, -25.0]),
        "my_pos": np.array(match.positions[KEEPER_A]),
        "teammates": np.array(match.positions[0:11]),
        "a_direction": 1,
        "is_loose": True,
        "rng": match.rng,
    }
    off_target = dict(base, goal_crossing={"x": GOAL_CENTER_X + 10.0, "z": 0.4, "time": 0.25, "on_target": False})
    assert gk._decide_off_ball_defense(off_target) not in ("save", "dive")

    on_target = dict(base, goal_crossing={"x": GOAL_CENTER_X, "z": 0.4, "time": 0.25, "on_target": True})
    assert gk._decide_off_ball_defense(on_target) in ("save", "dive")


# ----------------------------------------------------------- shot accuracy
#
# These exercise player._calculate_shot directly -- where the ball is AIMED,
# not where the engine's physics eventually puts it. The two are different
# questions and this is the one about the shooter.

TRIALS = 600


def aimed_shots(striker, shooting, pressure=0, seed=11):
    """Where `striker` aims TRIALS shots from 12 units straight out, with
    their shooting attribute forced to `shooting`."""
    from dataclasses import replace

    original = striker.attributes
    striker.attributes = replace(original, shooting=shooting)
    rng = np.random.default_rng(seed)
    state = {
        "a_direction": 1,
        "rng": rng,
        "my_pos": np.array([GOAL_CENTER_X, 88.0]),
        "my_heading": np.array([0.0, 1.0]),  # facing the goal, no angle penalty
        "pressure_count": pressure,
    }
    try:
        return [striker._calculate_shot(state)["target_3d"] for _ in range(TRIALS)]
    finally:
        striker.attributes = original


def on_target_rate(shots, inner_min=31.5, inner_max=38.5):
    """Fraction aimed between the posts. Bounds match goal_frame_bounds()."""
    return sum(1 for s in shots if inner_min <= s[0] <= inner_max) / len(shots)


def test_shots_are_aimed_inside_the_frame_not_at_the_post(rosters):
    """The aim point used to sit ON the inner edge of the post, which makes a
    perfectly struck shot a coin flip to go wide no matter how good the
    shooter is -- half of a symmetric spread is outside by construction, so
    the ceiling was ~50%. Aiming properly inside has to beat that clearly.
    """
    home, _ = rosters
    rate = on_target_rate(aimed_shots(home[-1], shooting=99))
    assert rate > 0.55, f"a near-perfect shooter only aims {rate:.0%} inside the posts"


def test_better_shooters_are_more_accurate(rosters):
    """Accuracy has to be earned. The old variance floor of 5.0 swamped the
    shooting attribute completely -- an icon and a bronze sprayed it equally.
    """
    home, _ = rosters
    striker = home[-1]
    good = on_target_rate(aimed_shots(striker, shooting=99))
    poor = on_target_rate(aimed_shots(striker, shooting=40))
    assert good > poor, f"shooting doesn't matter: {good:.0%} vs {poor:.0%}"


def test_pressure_makes_a_shooter_less_accurate(rosters):
    home, _ = rosters
    striker = home[-1]
    calm = on_target_rate(aimed_shots(striker, shooting=70, pressure=0))
    hurried = on_target_rate(aimed_shots(striker, shooting=70, pressure=3))
    assert hurried < calm, f"pressure does nothing: {hurried:.0%} vs {calm:.0%}"


def test_shots_are_aimed_at_both_sides_of_the_goal(rosters):
    """Two aim points, picked at random, so a keeper can't simply learn one
    side. A regression to a single point would show up here."""
    home, _ = rosters
    xs = [s[0] for s in aimed_shots(home[-1], shooting=99)]
    left = sum(1 for x in xs if x < GOAL_CENTER_X)
    assert 0.3 < left / len(xs) < 0.7, "shots all go to one side"
