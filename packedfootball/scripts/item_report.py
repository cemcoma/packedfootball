"""Dev tool: what is a kit actually worth, and does the ladder survive it?

Two questions items have to keep answering, neither of which a unit test can:

    1. Is a kit worth owning? A kitted XI against the same XI unkitted, per
       rarity. If the win column doesn't move, items are cosmetic.
    2. Does the ladder survive? A fully kitted BRONZE XI against a plain GOLD
       one. A kit is a role tool, not a tier jump, so the bronze side has to
       still lose this comfortably -- if it stops losing, items are power
       creep and the whole collection ladder is compromised.

Measured 2026-09-25 (20 matches a row, 4-4-2, mixed stats):

      gold +3x bronze  vs plain gold      W 5 D11 L 4   OVR +0.6
      gold +3x gold    vs plain gold      W 7 D 7 L 6   OVR +0.7
      gold +3x diamond vs plain gold      W 5 D 7 L 8   OVR +1.7
      gold +3x icon    vs plain gold      W10 D 4 L 6   OVR +2.7
      gold +4x icon    vs plain gold      W11 D 4 L 5   OVR +3.3
      bronze +4x icon  vs PLAIN GOLD      W 0 D 5 L15
      plain bronze     vs plain gold      W 0 D 1 L19

STATS ARE PICKED AT RANDOM per card, and that matters: the same test with
three SPEED items on every man was W14-D5-L1, which is why items.py allows
only one item per stat. Pace is the dominant stat in this engine and stacking
it is the exploit, not the size of the buffs.

Usage:
    python3 packedfootball/scripts/item_report.py
    python3 packedfootball/scripts/item_report.py --seeds 40 --tier platinum
"""

from __future__ import annotations

import argparse
import copy
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import items as item_rules  # noqa: E402
from gameEngine import game  # noqa: E402
from packEngine import generate_starter_roster  # noqa: E402

REGULATION_FRAMES = 10800


class _Team:
    def __init__(self, name, players):
        self.name = name
        self.players = players


def kit(roster: list, rarity: str, count: int, rng: random.Random) -> list:
    """A copy of `roster` with `count` items of `rarity` on every card, each on
    a DIFFERENT stat -- one per stat is the rule items.py enforces."""
    out = copy.deepcopy(roster)
    for p in out:
        kind = item_rules.kind_for_position(p.position)
        pool = list(item_rules.stats_for_kind(kind))
        stats = rng.sample(pool, min(count, len(pool)))
        p.items = [item_rules.make_item(rarity, s, kind) for s in stats]
        p.base_attributes = p.attributes
        p.attributes = item_rules.effective_attributes(p.attributes, p.items)
        p.overall = p._calculate_overall()
    return out


def overall(roster: list) -> float:
    return sum(p.overall for p in roster) / len(roster)


def play(home: list, away: list, seeds: range, label: str) -> None:
    goals_for = goals_against = wins = draws = losses = 0
    for seed in seeds:
        match = game(
            _Team("H", copy.deepcopy(home)),
            _Team("A", copy.deepcopy(away)),
            seed=seed,
            formation_home="4-4-2",
            formation_away="4-4-2",
        )
        match.run_match(max_steps=REGULATION_FRAMES, render=False)
        goals_for += match.scores[0]
        goals_against += match.scores[1]
        wins += match.scores[0] > match.scores[1]
        draws += match.scores[0] == match.scores[1]
        losses += match.scores[0] < match.scores[1]
    print(
        f"  {label:<40} {goals_for:>3}-{goals_against:<3}"
        f"  W{wins:>2} D{draws:>2} L{losses:>2}"
        f"   OVR {overall(home):.1f} v {overall(away):.1f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--tier", default="gold")
    parser.add_argument("--start-seed", type=int, default=40)
    args = parser.parse_args()

    seeds = range(args.start_seed, args.start_seed + args.seeds)
    rng = random.Random(99)
    base = generate_starter_roster("4-4-2", args.tier, seed=7)
    lower = generate_starter_roster("4-4-2", "bronze", seed=7)

    print(f"\n  {args.seeds} matches a row, 4-4-2, one item per stat, stats picked at random\n")
    for rarity in ("bronze", "gold", "diamond", "icon"):
        play(kit(base, rarity, 3, rng), base, seeds, f"{args.tier} +3x {rarity} vs plain {args.tier}")
    play(kit(base, "icon", 4, rng), base, seeds, f"{args.tier} +4x icon (max) vs plain {args.tier}")
    print()
    play(kit(lower, "icon", 4, rng), base, seeds, f"bronze +4x icon (max) vs PLAIN {args.tier.upper()}")
    play(lower, base, seeds, f"plain bronze vs plain {args.tier}")
    print()


if __name__ == "__main__":
    main()
