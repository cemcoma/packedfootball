"""Phase 1: the goal frame -- posts, crossbar, and reliable goal detection.

Three separate bugs this pins down, all reported as "sometimes a goal,
sometimes a kickoff without a goal, sometimes a corner":

1. A ball leaving through the goal mouth faster than ~48 units/s skipped
   goal detection entirely and restarted as a scoreless kickoff, because
   tick()'s out-of-bounds branch ran before _check_goal().
2. Ball height was never consulted, so a shot sailing over the bar scored.
3. There were no posts at all -- a ball on the goal-line at the post's exact
   x counted as a goal instead of rebounding.

These tests drive physics only (no AI); see conftest.tick_until.
"""

import numpy as np
import pytest

from conftest import (
    GOAL_CENTER_X,
    GOAL_X_MAX,
    GOAL_X_MIN,
    TEAM_B_GOAL_Y,
    freeze_players_away_from,
    launch_ball,
    tick_until,
)

# A shot by player 9 (a Home striker) at the goal Home attacks (y = 100).
SHOOTER = 9
SCORING_TEAM = 0


def _shoot(g, x, vy, y0=99.0, height=0.0, vx=0.0):
    launch_ball(g, x, y0, vx, vy, height=height, event="shot", toucher=SHOOTER)
    freeze_players_away_from(g, x, y0, radius=25.0)
    return g


def _settle(g, ticks=40):
    """Runs physics until the ball is resolved one way or the other."""
    start = list(g.scores)
    tick_until(g, lambda gg: gg.scores != start or gg.restart_type is not None, max_ticks=ticks)
    return g


@pytest.mark.parametrize("vy", [30.0, 60.0, 120.0, 300.0])
def test_shot_through_the_mouth_always_scores(match, vy):
    """Regression for the reported bug: goal detection must not depend on a
    tick happening to sample the ball inside a narrow band near the line."""
    g = _settle(_shoot(match, GOAL_CENTER_X, vy))
    assert g.scores[SCORING_TEAM] == 1, f"vy={vy} failed to register a goal"
    assert g.restart_type != "kickoff" or g.scores[SCORING_TEAM] == 1


def test_shot_over_the_crossbar_is_not_a_goal(match):
    g = _settle(_shoot(match, GOAL_CENTER_X, 30.0, height=5.0))
    assert g.scores == [0, 0]
    assert g.restart_type in ("goal_kick", "corner")


def test_shot_under_the_crossbar_scores(match):
    """Boundary check: just below the bar is still a goal."""
    g = _settle(_shoot(match, GOAL_CENTER_X, 30.0, height=1.0))
    assert g.scores[SCORING_TEAM] == 1


def test_shot_wide_of_the_post_is_not_a_goal(match):
    g = _settle(_shoot(match, GOAL_X_MAX + 3.0, 30.0))
    assert g.scores == [0, 0]
    assert g.restart_type in ("goal_kick", "corner")


def test_shot_at_the_post_rebounds_and_stays_live(match):
    """A ball striking the post is not a goal, and is not dead either."""
    g = _shoot(match, GOAL_X_MAX, 30.0)
    tick_until(g, lambda gg: gg.ball[2] != 0.0 or gg.ball[1] < 99.0, max_ticks=10)
    assert g.scores == [0, 0], "hitting the post must not score"
    assert g.restart_type is None, "a post rebound must leave the ball in play"


def test_post_rebound_reverses_the_ball(match):
    """The rebound is a real reflection: the ball comes back off the frame
    rather than continuing through it."""
    g = _shoot(match, GOAL_X_MAX, 40.0)
    for _ in range(6):
        g.tick(1 / 60)
        if g.ball[3] < 0:
            break
    assert g.ball[3] < 0, "ball should be travelling back out after hitting the post"
    assert g.ball[1] <= TEAM_B_GOAL_Y


def test_inside_face_post_rebound_can_still_score(match):
    """In off the post. The rebound leaves the ball live, so the very next
    crossing is evaluated by the same code and can be a goal."""
    # Angled shot striking the inside of the far post and deflecting across.
    g = _shoot(match, GOAL_X_MAX - 0.05, 30.0, y0=99.0, vx=6.0)
    _settle(g, ticks=60)
    # Either it went in off the post, or it came back out -- both are legal
    # outcomes; what must never happen is the ball vanishing into a kickoff.
    assert g.restart_type != "kickoff" or g.scores[SCORING_TEAM] == 1


def test_a_goal_credits_the_scorer(match):
    g = _settle(_shoot(match, GOAL_CENTER_X, 60.0))
    assert g.scores[SCORING_TEAM] == 1
    assert g.all_players[SHOOTER].statistics["goals"] == 1


def test_own_half_goal_scores_for_the_other_team(match):
    """Symmetry: crossing y=0 scores for team B (players 11-21)."""
    launch_ball(match, GOAL_CENTER_X, 1.0, 0.0, -60.0, event="shot", toucher=20)
    freeze_players_away_from(match, GOAL_CENTER_X, 1.0, radius=25.0)
    _settle(match)
    assert match.scores[1] == 1


def test_goal_frame_bounds_are_derived_not_hardcoded():
    """The keeper and the engine must agree on where the posts are."""
    import gameEngine as ge

    assert ge.GOAL_HEIGHT > 0
    assert hasattr(ge, "GOAL_POST_RADIUS"), "posts need a real width"
    assert GOAL_X_MIN == pytest.approx(ge.PITCH_WIDTH / 2 - ge.GOAL_WIDTH / 2)
    assert GOAL_X_MAX == pytest.approx(ge.PITCH_WIDTH / 2 + ge.GOAL_WIDTH / 2)
