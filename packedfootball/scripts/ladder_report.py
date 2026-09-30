"""Dev tool: how often does the WORSE side take something off the better one?

tier_report.py plays a tier against itself, which says whether a tier's
football looks right. This says whether the GAP between two tiers is fair --
the question a player actually asks when a diamond squad turns up.

Every pair is played with the seeds both ways round, so a home-side bias in
the engine cannot be read as the underdog doing well.

Usage:
    make ladder                                      # 6 seeds a pair
    make ladder SEEDS=12
    python3 packedfootball/scripts/ladder_report.py --pairs bronze:diamond

Runtime is about 1.5s per match: pairs x seeds x 2 x 1.5s.

The targets this is tuned against:

    adjacent tier              25-35% wins, 45-55% unbeaten
    two tiers                  15-20% wins
    four tiers (bronze:diamond) ~10% wins
    six tiers (bronze:icon)     3-6% wins

Read the shots column when a win rate is 0: a side that cannot work an
opening cannot draw 0-0 either, so shots dry up before wins do and that is
the first thing to fix.
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gameEngine import game  # noqa: E402
from packEngine import generate_starter_roster  # noqa: E402

REGULATION_FRAMES = 10800  # 90:00

# Every adjacent step, then the gaps the plan names a target for.
DEFAULT_PAIRS = (
    ("bronze", "silver"),
    ("silver", "gold"),
    ("gold", "platinum"),
    ("platinum", "diamond"),
    ("diamond", "special"),
    ("special", "icon"),
    ("bronze", "gold"),
    ("bronze", "diamond"),
    ("bronze", "icon"),
    ("bronze", "bronze"),
    ("icon", "icon"),
    ("platinum","special")
)


class _Team:
    def __init__(self, name, players):
        self.name = name
        self.players = players


def play_pair(low: str, high: str, seeds: range, formation: str) -> dict:
    """The two XIs are rolled once and reused, so every seed is the same two
    squads meeting again rather than a fresh roll that could flatter either."""
    low_xi = generate_starter_roster(formation, low, seed=1)
    high_xi = generate_starter_roster(formation, high, seed=2)

    wins = draws = losses = 0
    low_goals = high_goals = low_shots = 0
    scores = []
    for seed in seeds:
        for low_at_home in (True, False):
            home = copy.deepcopy(low_xi if low_at_home else high_xi)
            away = copy.deepcopy(high_xi if low_at_home else low_xi)
            match = game(
                _Team("H", home),
                _Team("A", away),
                seed=seed,
                formation_home=formation,
                formation_away=formation,
            )
            match.run_match(max_steps=REGULATION_FRAMES, render=False)

            low_side, high_side = (0, 1) if low_at_home else (1, 0)
            scored, conceded = match.scores[low_side], match.scores[high_side]
            low_goals += scored
            high_goals += conceded

            stats = match.match_summary()
            low_slots = range(0, 11) if low_at_home else range(11, 22)
            low_shots += sum(stats[i]["shots"] for i in low_slots)

            scores.append((scored, conceded))
            if scored > conceded:
                wins += 1
            elif scored == conceded:
                draws += 1
            else:
                losses += 1

    n = len(scores)
    return {
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "win_pct": 100.0 * wins / n,
        "unbeaten_pct": 100.0 * (wins + draws) / n,
        "low_goals": low_goals / n,
        "high_goals": high_goals / n,
        "low_shots": low_shots / n,
        "scores": scores,
    }


def _parse_pair(text: str) -> tuple[str, str]:
    low, _, high = text.partition(":")
    if not high:
        raise argparse.ArgumentTypeError(f"pairs look like low:high, not {text!r}")
    return low, high


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=6, help="seeds per pair, each played both ways (default 6)")
    parser.add_argument("--pairs", nargs="*", type=_parse_pair, default=list(DEFAULT_PAIRS))
    parser.add_argument("--formation", default="4-4-2")
    parser.add_argument("--start-seed", type=int, default=11)
    parser.add_argument("--scorelines", action="store_true", help="print every scoreline too")
    args = parser.parse_args()

    seeds = range(args.start_seed, args.start_seed + args.seeds)

    from game_config import SPEED_COMPRESS, STAT_CURVE_COMPRESS, STAT_CURVE_GAMMA, STAT_CURVE_PIVOT

    print(
        f"\n  TIER GAPS -- {args.seeds * 2} matches per pair ({args.seeds} seeds both ways), {args.formation}"
        f"\n  gamma {STAT_CURVE_GAMMA}  compress {STAT_CURVE_COMPRESS}  pivot {STAT_CURVE_PIVOT}"
        f"  speed_compress {SPEED_COMPRESS}\n"
    )
    header = (
        f"  {'matchup':>22}{'W-D-L':>10}{'win%':>7}{'unb%':>7}"
        f"{'goals':>12}{'total':>7}{'shots':>7}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))

    for low, high in args.pairs:
        row = play_pair(low, high, seeds, args.formation)
        wdl = f"{row['wins']}-{row['draws']}-{row['losses']}"
        goals = f"{row['low_goals']:.1f}-{row['high_goals']:.1f}"
        print(
            f"  {low + ' v ' + high:>22}{wdl:>10}{row['win_pct']:>6.0f}%{row['unbeaten_pct']:>6.0f}%"
            f"{goals:>12}{row['low_goals'] + row['high_goals']:>7.1f}{row['low_shots']:>7.1f}"
        )
        if args.scorelines:
            print(f"  {'':>22}{' '.join(f'{h}-{a}' for h, a in row['scores'])}")
    print("\n  win%/unb% and shots are the WORSE side's. goals are low-high.\n")


if __name__ == "__main__":
    main()
