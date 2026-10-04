"""Dev tool: how much CPU one served match costs.

Plays a fixed set of matches the way backend/services/match.run_match does
(replay recorded and encoded) across formations, tactics and tiers, and
prints seconds per match. decisions/match is the guard that a speed-up came
from cheaper decisions, not fewer of them.

Usage:
    make bench
    make bench BENCH_MATCHES=24
"""

from __future__ import annotations

import argparse
import itertools
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from formations import FORMATIONS  # noqa: E402
from game_config import TACTICS  # noqa: E402
from gameEngine import game  # noqa: E402
from packEngine import generate_starter_roster  # noqa: E402

TIERS = ("bronze", "gold", "diamond", "icon")


class _Team:
    def __init__(self, name, players):
        self.name = name
        self.players = players


def fixtures(count: int, start_seed: int):
    combos = itertools.cycle(itertools.product(FORMATIONS, TACTICS, TIERS))
    for i in range(count):
        formation, tactic, tier = next(combos)
        away_formation = list(FORMATIONS)[(i + 1) % len(FORMATIONS)]
        seed = start_seed + i
        home = generate_starter_roster(formation, tier, seed=seed)
        away = generate_starter_roster(away_formation, tier, seed=seed + 1000)
        yield seed, formation, away_formation, tactic, home, away


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matches", type=int, default=12)
    parser.add_argument("--start-seed", type=int, default=1)
    args = parser.parse_args()

    wall = cpu = 0.0
    decisions = goals = replay_bytes = 0
    for seed, f_home, f_away, tactic, home, away in fixtures(args.matches, args.start_seed):
        w0, c0 = time.perf_counter(), time.process_time()
        match = game(
            _Team("Home", home), _Team("Away", away), seed=seed, record_replay=True,
            formation_home=f_home, formation_away=f_away,
            tactics_home={"style": tactic}, tactics_away={"style": "balanced"},
        )
        match.run_match(max_steps=10800, render=False)
        replay_bytes += len(match.replay.encode())
        wall += time.perf_counter() - w0
        cpu += time.process_time() - c0
        decisions += match._decisions_made
        goals += sum(match.scores)

    n = args.matches
    print(f"matches          {n}")
    print(f"wall s/match     {wall / n:.3f}")
    print(f"cpu  s/match     {cpu / n:.3f}")
    print(f"decisions/match  {decisions / n:.0f}")
    print(f"goals/match      {goals / n:.2f}")
    print(f"replay v1 bytes  {replay_bytes / n:.0f}")


if __name__ == "__main__":
    main()
