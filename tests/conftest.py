"""Shared fixtures for the engine test suite.

`packedfootball/` is not an installed package -- its modules import each
other as top-level names (`from player.player import player`), exactly the
way packedfootball/scripts/dump_test_replay.py and backend/main.py both set
up. So the first thing this file does is put that directory on sys.path;
without it every `from gameEngine import ...` below fails.

Everything here is seeded. The engine is built around a reproducible
`np.random.default_rng(seed)`, and a test that doesn't pin its seed will
pass or fail depending on the day.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packedfootball"))
sys.path.insert(0, str(ROOT / "backend"))

from gameEngine import (  # noqa: E402
    GOAL_WIDTH,
    PITCH_HEIGHT,
    PITCH_WIDTH,
    game,
)
from packEngine import PACK_DATABASE, PackManager  # noqa: E402

# Goal mouth, derived rather than hardcoded -- see gameEngine's own constants.
GOAL_X_MIN = PITCH_WIDTH / 2 - GOAL_WIDTH / 2
GOAL_X_MAX = PITCH_WIDTH / 2 + GOAL_WIDTH / 2
GOAL_CENTER_X = PITCH_WIDTH / 2

# Team A (players 0-10) defends y=0 and attacks y=PITCH_HEIGHT; team B is the
# mirror. See gameEngine._goal_for_player.
TEAM_A_GOAL_Y = 0.0
TEAM_B_GOAL_Y = PITCH_HEIGHT


class Team:
    """Minimal stand-in for whatever the caller passes as a team -- the engine
    only ever reads `.name` and `.players` (see backend/main.py's own _Team).
    """

    def __init__(self, name, players):
        self.name = name
        self.players = players


def _assemble_xi(pool):
    """One 4-4-2 XI, one player per formation slot BY POSITION.

    Slot order is GK, LB, CB, CB, RB, CM, CM, CM, CM, ST, ST. The engine
    trusts slot order completely and never checks `.position` against the
    formation, so a mis-slotted roster silently behaves as its real class --
    a keeper in the LB slot stays glued to its own goal line. Same reasoning
    as packedfootball/scripts/dump_test_replay.py's build_teams().
    """

    def take(positions, n):
        chosen = [p for p in pool if p.position in positions][:n]
        for p in chosen:
            pool.remove(p)
        return chosen

    xi = (
        take(["GK"], 1)
        + take(["LB"], 1)
        + take(["CB"], 2)
        + take(["RB"], 1)
        + take(["CM"], 4)
        + take(["ST", "LW", "RW"], 2)
    )
    if len(xi) != 11:
        raise RuntimeError(f"Could not assemble a full XI (got {len(xi)}/11)")
    return xi


@pytest.fixture(scope="session")
def _roster_template():
    """Two XIs, built once. Opening enough packs to cover every position group
    is the slow part of any engine test, so it happens once per session and
    every test gets a deep copy (see `rosters`) -- the engine mutates player
    objects (statistics), so sharing them between tests would leak state.
    """
    pm = PackManager(PACK_DATABASE, seed=55)
    pool = []
    while len(pool) < 400:
        pool += pm.open_pack("jumbo")  # the Jumbo pack: mixed positions (icon_forward is forwards-only)
    return _assemble_xi(pool), _assemble_xi(pool)


@pytest.fixture
def rosters(_roster_template):
    home, away = _roster_template
    return copy.deepcopy(home), copy.deepcopy(away)


@pytest.fixture
def make_match(rosters):
    """Factory for a fresh, seeded match. Default seed is fixed so a test that
    doesn't care still behaves identically run to run.
    """
    home, away = rosters

    def _make(seed: int = 7, record_replay: bool = False, **kwargs):
        return game(
            Team("Home", home),
            Team("Away", away),
            seed=seed,
            record_replay=record_replay,
            **kwargs,
        )

    return _make


@pytest.fixture
def match(make_match):
    return make_match()


# --------------------------------------------------------------- ball helpers

def quiesce(g):
    """Clears every timer that makes tick() early-return, so physics tests can
    drive the ball directly.

    A freshly constructed game is mid-kickoff (`kickoff_timer = 60`, the ball
    held by a striker under a forced-pass obligation), and tick() bails out
    before touching ball physics while any of these are set.
    """
    g.kickoff_timer = 0
    g.restart_timer = 0
    g.restart_type = None
    g.restart_team = None
    g.restart_player = None
    g.goal_pause_timer = 0
    g.halftime_pause_timer = 0
    g.out_of_play = False
    g.must_pass_next = False
    g.must_pass_player = -1
    g.kickoff_pass_required = False
    g.kickoff_pass_player = -1
    g.ball_controller = -1
    g.ball_release_player = -1
    g.ball_release_cooldown = 0
    return g


def launch_ball(g, x, y, vx, vy, height=0.0, event="shot", toucher=None):
    """Puts a loose ball at (x, y) travelling at (vx, vy).

    `toucher` sets last_touch_player/last_touch_team, which is what decides
    corner-vs-goal-kick and who gets credited for a goal.
    """
    quiesce(g)
    g.ball[0] = float(x)
    g.ball[1] = float(y)
    g.ball[2] = float(vx)
    g.ball[3] = float(vy)
    g.ball[4] = float(height)
    g.ball_event = event
    if toucher is not None:
        g.last_touch_player = int(toucher)
        g.last_touch_team = 0 if int(toucher) < 11 else 1
    return g


def tick_until(g, predicate, max_ticks: int = 600, dt: float = 1 / 60):
    """Ticks physics only (no AI) until `predicate(g)` is true.

    Deliberately does NOT call step() -- these tests are about ball physics
    and restart bookkeeping, and letting 22 AI players chase the ball would
    make the outcome depend on their decisions rather than the code under
    test. Returns the tick count, or -1 if the predicate never fired.
    """
    for i in range(max_ticks):
        g.tick(dt)
        if predicate(g):
            return i
    return -1


def freeze_players_away_from(g, x, y, radius: float = 12.0):
    """Moves any player within `radius` of a point far away.

    Ball capture is automatic and proximity-based (gameEngine.step's nearest-
    player scan), but even with step() disabled, a shot fired through a
    crowded box can be intercepted by tick()-side logic. Physics tests use
    this to guarantee a clean, uncontested ball.
    """
    target = np.array([float(x), float(y)])
    for i in range(22):
        if np.linalg.norm(g.positions[i] - target) < radius:
            g.positions[i] = np.array([1.0, 50.0]) if i < 11 else np.array([69.0, 50.0])
    return g
