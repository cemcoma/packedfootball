"""Dev tool: does each tactic play differently, and does any of them win too much?

Both sides field the SAME eleven, so the only difference is the tactic. Every
seed is played both ways round.

Usage:
    make tactics                                   # every tactic v balanced, gold
    make tactics SEEDS=24
    python3 packedfootball/scripts/tactic_report.py --tier diamond --matrix

The targets (game_config.TACTICS is a set of sidegrades, not upgrades):

    any tactic v any other      40-60% of the points either way
    goals/match                 inside 2.4-4.0 whatever the pairing
    fingerprints                possession: poss% and passes up
                                wing play: crosses up
                                long ball: long balls up, passes down, free kicks won up
"""

from __future__ import annotations

import argparse
import copy
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game_config import TACTICS  # noqa: E402
from gameEngine import game  # noqa: E402
from packEngine import generate_starter_roster  # noqa: E402
from replay import ActionType, decode_replay  # noqa: E402

REGULATION_FRAMES = 10800


class _Team:
    def __init__(self, name, players):
        self.name = name
        self.players = players


class _CountingGame(game):
    """Counts possession and long balls/punts per side on top of the real engine."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.possession_frames = [0, 0]
        self.long_balls = [0, 0]

    def step(self):
        super().step()
        if self.ball_controller >= 0:
            self.possession_frames[0 if self.ball_controller < 11 else 1] += 1

    def _start_punt_support(self, kicker, landing):
        self.long_balls[0 if kicker < 11 else 1] += 1
        super()._start_punt_support(kicker, landing)


def play(tactic: str, other: str, seeds: range, tier: str, formation: str) -> dict:
    xi = generate_starter_roster(formation, tier, seed=1)
    tot = {"w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "n": 0}
    side = {k: [0.0, 0.0] for k in ("poss", "passes", "completed", "shots", "crosses", "long", "fk_won", "fouls")}
    for seed, tactic_home in itertools.product(seeds, (True, False)):
        match = _CountingGame(
            _Team("H", copy.deepcopy(xi)), _Team("A", copy.deepcopy(xi)),
            seed=seed, record_replay=True, formation_home=formation, formation_away=formation,
            tactics_home={"style": tactic if tactic_home else other},
            tactics_away={"style": other if tactic_home else tactic},
        )
        match.run_match(max_steps=REGULATION_FRAMES, render=False)
        me, them = (0, 1) if tactic_home else (1, 0)
        gf, ga = match.scores[me], match.scores[them]
        tot["gf"] += gf
        tot["ga"] += ga
        tot["n"] += 1
        tot["w" if gf > ga else "d" if gf == ga else "l"] += 1

        stats = match.match_summary()
        events = decode_replay(match.replay.encode())["events"]
        frames = max(1, sum(match.possession_frames))
        for k, team in enumerate((me, them)):
            slots = range(0, 11) if team == 0 else range(11, 22)
            side["poss"][k] += 100.0 * match.possession_frames[team] / frames
            side["passes"][k] += sum(stats[i]["passes"] for i in slots)
            side["completed"][k] += sum(stats[i]["passes_completed"] for i in slots)
            side["fouls"][k] += sum(stats[i]["fouls"] for i in slots)
            side["shots"][k] += sum(stats[i]["shots"] for i in slots)
            side["crosses"][k] += sum(1 for e in events if e["type"] == int(ActionType.CROSS) and e["team"] == team)
            side["fk_won"][k] += sum(1 for e in events if e["type"] == int(ActionType.FREE_KICK) and e["team"] == team)
            side["long"][k] += match.long_balls[team]
    n = tot["n"]
    tot.update({k: [v[0] / n, v[1] / n] for k, v in side.items()})
    return tot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=8, help="seeds per pairing, each played both ways (default 8)")
    parser.add_argument("--tier", default="gold")
    parser.add_argument("--formation", default="4-4-2")
    parser.add_argument("--start-seed", type=int, default=11)
    parser.add_argument("--tactics", nargs="*", default=[t for t in TACTICS if t != "balanced"])
    parser.add_argument("--matrix", action="store_true", help="every pairing, not just each v balanced")
    args = parser.parse_args()

    seeds = range(args.start_seed, args.start_seed + args.seeds)
    names = list(args.tactics)
    pairs = list(itertools.combinations(["balanced"] + names, 2)) if args.matrix else [(t, "balanced") for t in names]
    pairs = [(a, b) for a, b in pairs if a != b]

    print(f"\n  TACTICS -- {args.seeds * 2} matches per pairing, {args.tier} XI both sides, {args.formation}\n")
    header = (
        f"  {'pairing':>26}{'W-D-L':>10}{'pts%':>6}{'goals':>10}"
        f"{'poss%':>11}{'passes':>11}{'pass%':>11}{'shots':>11}{'crosses':>11}{'long':>9}{'FK won':>10}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    all_goals = []
    for a, b in pairs:
        r = play(a, b, seeds, args.tier, args.formation)
        pts = 100.0 * (3 * r["w"] + r["d"]) / (3 * r["n"])
        pct = [100.0 * r["completed"][k] / max(1.0, r["passes"][k]) for k in (0, 1)]
        all_goals.append((r["gf"] + r["ga"]) / r["n"])

        def pair(v, fmt="{:.0f}"):
            return f"{fmt.format(v[0])}/{fmt.format(v[1])}"

        wdl = f"{r['w']}-{r['d']}-{r['l']}"
        print(
            f"  {a + ' v ' + b:>26}{wdl:>10}{pts:>5.0f}%"
            f"{r['gf'] / r['n']:>5.1f}-{r['ga'] / r['n']:<4.1f}"
            f"{pair(r['poss']):>11}{pair(r['passes']):>11}{pair(pct):>11}{pair(r['shots'], '{:.1f}'):>11}"
            f"{pair(r['crosses'], '{:.1f}'):>11}{pair(r['long'], '{:.1f}'):>9}{pair(r['fk_won'], '{:.1f}'):>10}"
        )
    print(f"\n  first/second side of each pairing. pts% is the first side's share of the points."
          f"\n  goals/match over all pairings {sum(all_goals) / max(1, len(all_goals)):.2f}\n")


if __name__ == "__main__":
    main()
