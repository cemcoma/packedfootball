"""Dev tool: goals per match at every card tier, same tier on both sides.

The question this answers: does a change to the engine's feel constants
(game_config.PLAYER_BASE_SPEED, POSSESSION_RADIUS, PLAYER_RADIUS, the
gameEngine RECEIVE_*/PASS_* knobs) still leave a ladder that rises from
bronze to icon, with scorelines that look like football rather than 0-0 or
7-6?

This is the balance harness, not a test -- nothing is asserted. It is the
same idea as tests/test_tier_scorelines.py (`make test-tiers`) but faster to
iterate with: pick the sample size, pick the tiers, and get passing and
throw-in numbers alongside the scorelines.

Usage:
    make tiers                                   # 8 seeds a tier
    make tiers SEEDS=16
    python3 packedfootball/scripts/tier_report.py --seeds 4 --tiers gold icon
    python3 packedfootball/scripts/tier_report.py --formation 4-3-3

Runtime is about 1.5s per match: seeds x tiers x 1.5s. 8 seeds over 7 tiers
is roughly 90 seconds.

What to look for:

    goals/match       2.4-4.0 is the agreed band; short matches, so a lot of
                      0-0 draws is the failure mode, not high scores
    the ladder        should RISE bronze -> icon. A dip in the middle means a
                      stat has saturated for the tiers above it
    pass%             completions / attempts, both sides
    throw-ins         a spike means passes are overhit and running out of play
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gameEngine import game  # noqa: E402
from packEngine import generate_starter_roster  # noqa: E402
from replay import ActionType  # noqa: E402

REGULATION_FRAMES = 10800  # 90:00

ALL_TIERS = ("bronze", "silver", "gold", "platinum", "diamond", "special", "icon")


class _Team:
    def __init__(self, name, players):
        self.name = name
        self.players = players


def play_tier(tier: str, seeds: range, formation: str) -> dict:
    """One tier against itself. The two XIs are rolled from DIFFERENT seeds so
    it is two squads of that tier, not one against a mirror of itself."""
    home = generate_starter_roster(formation, tier, seed=1000 + hash(tier) % 500)
    away = generate_starter_roster(formation, tier, seed=2000 + hash(tier) % 500)

    scores, shots, completed, attempted, throws, corners = [], 0, 0, 0, 0, 0
    for seed in seeds:
        match = game(
            _Team("H", copy.deepcopy(home)),
            _Team("A", copy.deepcopy(away)),
            seed=seed,
            record_replay=True,
            formation_home=formation,
            formation_away=formation,
        )
        match.run_match(max_steps=REGULATION_FRAMES, render=False)

        stats = match.match_summary()
        scores.append((match.scores[0], match.scores[1]))
        shots += sum(stats[i]["shots"] for i in range(22))
        completed += sum(stats[i]["passes_completed"] for i in range(22))
        attempted += sum(stats[i]["passes"] for i in range(22))
        events = match.replay._events
        throws += sum(1 for e in events if e[1] == ActionType.THROW_IN)
        corners += sum(1 for e in events if e[1] == ActionType.CORNER)

    n = len(scores)
    return {
        "scores": scores,
        "goals": sum(h + a for h, a in scores) / n,
        "shots": shots / n,
        "pass_pct": 100.0 * completed / max(attempted, 1),
        "throws": throws / n,
        "corners": corners / n,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=8, help="matches per tier (default 8)")
    parser.add_argument("--tiers", nargs="*", default=list(ALL_TIERS), help="which tiers to run")
    parser.add_argument("--formation", default="4-4-2")
    parser.add_argument("--start-seed", type=int, default=21)
    args = parser.parse_args()

    seeds = range(args.start_seed, args.start_seed + args.seeds)

    from game_config import PLAYER_BASE_SPEED, POSSESSION_RADIUS, PLAYER_RADIUS

    print(
        f"\n  SAME-TIER MATCHUPS -- {args.seeds} matches per tier, {args.formation}"
        f"\n  base_speed {PLAYER_BASE_SPEED}  possession_radius {POSSESSION_RADIUS}"
        f"  player_radius {PLAYER_RADIUS}\n"
    )
    header = f"  {'tier':>10}{'goals':>8}{'shots':>8}{'pass%':>8}{'throws':>8}{'corners':>9}   scorelines"
    print(header)
    print("  " + "-" * (len(header) + 8))

    rows = []
    for tier in args.tiers:
        row = play_tier(tier, seeds, args.formation)
        rows.append((tier, row))
        line = " ".join(f"{h}-{a}" for h, a in row["scores"])
        print(
            f"  {tier:>10}{row['goals']:>8.1f}{row['shots']:>8.1f}"
            f"{row['pass_pct']:>7.0f}%{row['throws']:>8.1f}{row['corners']:>9.1f}   {line}"
        )

    if len(rows) > 1:
        overall = sum(r["goals"] for _, r in rows) / len(rows)
        first, last = rows[0][1]["goals"], rows[-1][1]["goals"]
        print(f"\n  mean goals/match {overall:.2f}   {rows[0][0]} {first:.1f} -> {rows[-1][0]} {last:.1f}")
        dips = [
            rows[i][0]
            for i in range(1, len(rows) - 1)
            if rows[i][1]["goals"] < rows[i - 1][1]["goals"] - 0.4
            and rows[i][1]["goals"] < rows[i + 1][1]["goals"] - 0.4
        ]
        if dips:
            print(f"  dip in the ladder at: {', '.join(dips)}  (a stat may have saturated)")
    print()


if __name__ == "__main__":
    main()
