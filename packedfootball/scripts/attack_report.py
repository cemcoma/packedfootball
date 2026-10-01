"""Dev tool: what the man on the ball does near goal, and what comes of it.

The attacking-moves harness. Against a set defender (goal-side within BLOCKED_RANGE)
does the carrier just dribble into him, or go around him, carry it across, hold
it up? And do those moves end in shots, passes or a lost ball?

Usage:
    make attack                     # 8 seeds a tier pairing
    make attack SEEDS=24
    python3 packedfootball/scripts/attack_report.py --seeds 16 --tactic possession

What to look for:

    blocked/free      carrier decisions within NEAR_GOAL of goal, with and without a
                      defender goal-side within BLOCKED_RANGE. "dribble" there is the
                      straight run at the goal centre -- into the man
    moves             each latched move (take_on, across, wingplay, cutting):
                      spells a match and how they end
    shots             open-play footed shots by distance from goal
"""

from __future__ import annotations

import argparse
import collections
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gameEngine import game  # noqa: E402
from packEngine import generate_starter_roster  # noqa: E402
from replay import ActionType  # noqa: E402
from player.classes.defender import Defender  # noqa: E402
from player.classes.forward import Forward  # noqa: E402
from player.classes.midfielder import Midfielder  # noqa: E402

NEAR_GOAL = 35.0
BLOCKED_RANGE = 5.0
SHOT_BANDS = ((0.0, 12.0), (12.0, 18.0), (18.0, 26.0), (26.0, 999.0))
SHOT_FOLLOW_FRAMES = 60   # a move "led to a shot" if its man shoots within this many frames of it ending
MOVES = ("take_on", "across", "wingplay", "cutting")


def _move(intent):
    """A latched intent by name -- "take_on+1" is a take_on."""
    return next((m for m in MOVES if intent and intent.startswith(m)), None)
TIERS = ("silver", "gold", "platinum", "diamond")
FORMATIONS = ("4-4-2", "4-3-3", "4-2-3-1", "3-5-2")


# Carrier decisions near goal, counted where they are made: _build_action is the one place
# a decision is named. Reset per match by _one.
DECISIONS = collections.Counter()


def _remember(cls):
    build = cls._build_action

    def wrapped(self, decision, state):
        if state.get("has_ball"):
            me = np.asarray(state["my_pos"], dtype=float)
            goal = np.asarray(state["enemy_goal"], dtype=float)
            if float(np.linalg.norm(goal - me)) <= NEAR_GOAL:
                rel = np.asarray(state["opponents"], dtype=float) - me
                ahead = (rel @ (goal - me) > 0.0) & (np.linalg.norm(rel, axis=1) < BLOCKED_RANGE)
                DECISIONS[("blocked" if ahead.any() else "free", decision)] += 1
        return build(self, decision, state)
    cls._build_action = wrapped


for _cls in (Forward, Midfielder, Defender):
    _remember(_cls)


class _Team:
    def __init__(self, name, players):
        self.name = name
        self.players = players


class _ReportGame(game):
    """Counts as it plays: shots by distance and move spells (decisions: DECISIONS)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.shots_by_band = collections.Counter()
        self.spells = collections.Counter()
        self._spell = {}   # player -> the man he was facing when the move started
        self._ended = {}   # player -> (move, frame it ended): did a shot follow?

    def _resolve_action(self, index, action):
        if action and action.get("type") == "shoot" and self.ball_controller == index:
            ended = self._ended.pop(index, None)
            if ended and self.match_clock_frames - ended[1] <= SHOT_FOLLOW_FRAMES:
                self.spells[(ended[0], "-> shot soon after")] += 1
            dist = float(np.linalg.norm(self._goal_targets[index] - self.positions[index]))
            band = next(f"{lo:.0f}-{hi:.0f}" if hi < 999 else f"{lo:.0f}+" for lo, hi in SHOT_BANDS if lo <= dist < hi)
            self.shots_by_band[band] += 1
        super()._resolve_action(index, action)

    def step(self):
        before = list(self.intent)
        first = len(self.replay._events)
        super().step()
        tackled = {int(e[3]) for e in self.replay._events[first:] if e[1] == ActionType.TACKLE}
        for i in range(22):
            old, new = _move(before[i]), _move(self.intent[i])
            if old != new and old in MOVES and i in self._spell:
                lost = (1 if i < 11 else 0) in tackled
                self.spells[(old, "tackled" if lost else self._spell_outcome(i))] += 1
                del self._spell[i]
                self._ended[i] = (old, self.match_clock_frames)
            if new in MOVES and old != new:
                self.spells[(new, "attempts")] += 1
                self._spell[i] = self._man_in_front(i)

    def _man_in_front(self, i):
        """The opponent nearest goal-side of i within BLOCKED_RANGE, or -1."""
        goal = self._goal_targets[i]
        u = (goal - self.positions[i]) / max(float(np.linalg.norm(goal - self.positions[i])), 1e-6)
        best, best_d = -1, BLOCKED_RANGE
        for k in (range(11, 22) if i < 11 else range(11)):
            rel = self.positions[k] - self.positions[i]
            d = float(np.linalg.norm(rel))
            if float(rel @ u) > 0.0 and d < best_d:
                best, best_d = k, d
        return best

    def _spell_outcome(self, i):
        c = self.ball_controller
        man = self._spell.get(i, -1)
        if c == i and man >= 0:
            goal = self._goal_targets[i]
            if float((self.positions[man] - self.positions[i]) @ (goal - self.positions[i])) < 0.0:
                return "past him"
        if self.restart_type is not None:
            return "foul won" if self.restart_team == (0 if i < 11 else 1) else "dead ball"
        if c == i:
            return "still his"
        last = self._last_actions[i]
        if last is not None and last.get("type") == "shoot":
            return "shot"
        if last is not None and last.get("type") == "pass":
            return "pass"
        if c >= 0 and (c < 11) != (i < 11):
            return "lost"
        return "loose"


def _one(job):
    tier, fh, fa, seed, tactic = job
    DECISIONS.clear()
    m = _ReportGame(
        _Team("H", generate_starter_roster(fh, tier, seed=1000 + seed)),
        _Team("A", generate_starter_roster(fa, tier, seed=5000 + seed)),
        seed=seed, record_replay=True, formation_home=fh, formation_away=fa,
        tactics_home={"style": tactic}, tactics_away={"style": tactic},
    )
    m.run_match(max_steps=10800, render=False)
    events = collections.Counter(int(e[1]) for e in m.replay._events)
    return collections.Counter(DECISIONS), m.shots_by_band, m.spells, events, sum(m.scores)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=8, help="matches per tier (default 8)")
    parser.add_argument("--start-seed", type=int, default=400)
    parser.add_argument("--tactic", default="balanced", help="both sides play it")
    parser.add_argument("--jobs", type=int, default=None)
    args = parser.parse_args()

    jobs = [(TIERS[k % len(TIERS)], FORMATIONS[k % len(FORMATIONS)], FORMATIONS[(k + 1) % len(FORMATIONS)],
             args.start_seed + k, args.tactic) for k in range(args.seeds * len(TIERS))]
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(_one, jobs))
    n = len(results)

    decisions, shots, spells, events = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    goals = 0
    for d, s, sp, ev, g in results:
        decisions.update(d)
        shots.update(s)
        spells.update(sp)
        events.update(ev)
        goals += g

    print(f"\n  ATTACK -- {n} matches, {args.tactic} both sides, silver-diamond, mixed formations\n")
    for kind in ("blocked", "free"):
        rows = {k[1]: v for k, v in decisions.items() if k[0] == kind}
        total = sum(rows.values()) or 1
        top = sorted(rows.items(), key=lambda kv: -kv[1])[:9]
        print(f"  {kind:8}{total / n:6.0f} decisions/match   " + "  ".join(f"{k} {100 * v / total:.0f}%" for k, v in top))
    print()
    for move in MOVES:
        attempts = spells[(move, "attempts")]
        if not attempts:
            continue
        ends = {k[1]: v for k, v in spells.items() if k[0] == move and k[1] not in ("attempts", "-> shot soon after")}
        done = sum(ends.values()) or 1
        ends["-> shot soon after"] = spells[(move, "-> shot soon after")]
        print(f"  {move:9}{attempts / n:5.1f}/match   " + "  ".join(f"{k} {100 * v / done:.0f}%" for k, v in sorted(ends.items(), key=lambda kv: -kv[1])))
    print()
    print("  shots by distance  " + "  ".join(f"{band}: {shots[band] / n:.1f}" for band in
                                             [f"{lo:.0f}-{hi:.0f}" if hi < 999 else f"{lo:.0f}+" for lo, hi in SHOT_BANDS]))
    on_t = events[int(ActionType.SHOOT)]
    off_t = events[int(ActionType.SHOT_OFF_TARGET)]
    print(f"  shots {(on_t + off_t) / n:.1f}/match (on target {on_t / n:.1f})   failed tackles {events[int(ActionType.ANKLEBREAKER)] / n:.1f}"
          f"   tackles won {events[int(ActionType.TACKLE)] / n:.1f}   fouls {events[int(ActionType.FOUL)] / n:.1f}")
    print(f"  goals/match {goals / n:.2f}\n")


if __name__ == "__main__":
    main()
