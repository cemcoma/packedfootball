"""Who gets a loose ball: a blocker who kills it keeps it, and the passer's side is
offered its own pass once the teammate lockout (TEAMMATE_RELEASE_BLOCK_FRAMES) is over."""

import numpy as np
import pytest

from conftest import freeze_players_away_from, launch_ball

BLOCKER = 2               # a home centre-back
PASSER, RECEIVER = 6, 7   # two home midfielders


def test_a_block_that_drops_dead_stays_with_the_blocker(match):
    launch_ball(match, 35.0, 30.0, 0.0, -3.0, event="pass", toucher=20)
    freeze_players_away_from(match, 35.0, 30.0)
    match.positions[BLOCKER] = np.array([35.0, 30.0])
    match.velocity[BLOCKER] = 0.0

    assert match._deflect_off(BLOCKER, ball_speed=3.0, ball_height=0.0) is True
    match.step()

    assert match.ball_controller == BLOCKER


@pytest.mark.parametrize("team_cooldown, offered", [(0, True), (3, False)])
def test_the_passers_side_is_offered_the_ball_only_after_the_team_lockout(match, monkeypatch, team_cooldown, offered):
    launch_ball(match, 35.0, 40.0, 0.0, 1.0, event="pass", toucher=PASSER)
    freeze_players_away_from(match, 35.0, 40.0)
    match.positions[PASSER] = np.array([35.0, 30.0])     # clear of the zone round the passer
    match.positions[RECEIVER] = np.array([35.0, 40.5])
    match.ball_release_player = PASSER
    match.ball_release_cooldown = 6
    match.ball_release_team_cooldown = team_cooldown
    asked = []
    monkeypatch.setattr(match, "_attempt_capture", lambda i: asked.append(i) or False)

    match.step()

    assert (RECEIVER in asked) is offered
