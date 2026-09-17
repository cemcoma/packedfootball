"""Do better players make for higher-scoring games?

Same-tier matchups all the way up the ladder -- bronze XI vs bronze XI,
silver vs silver, ... icon vs icon -- and the scorelines they produce. The
worry being tested: a bronze league that's all 0-0 and 1-0, while an icon
league is 4-3 every week (or the reverse: everyone scoring the same
regardless of quality, which would mean the attributes aren't reaching
the box).

The three special_* tiers are one bucket here: same generator, adjacent
ranges, and the question is about the ladder's shape, not about the
difference between a Conference and a UCL card.

The printed table is the point:

    make test-tiers

The assertion is deliberately loose -- direction only -- so the table
stays informative rather than the test flipping on a seed. Marked `slow`:
it simulates whole matches.
"""

import pytest

from conftest import Team
from gameEngine import game
from packEngine import generate_starter_roster

pytestmark = pytest.mark.slow

REGULATION_FRAMES = 10800
SEEDS = (21, 22, 23, 24)

# Ladder order. special_ucl stands in for the whole special bucket -- its
# range sits between the other two specials' and diamond/icon.
TIERS = ("bronze", "silver", "gold", "platinum", "diamond", "special_ucl", "icon")


def _label(tier: str) -> str:
    return "special" if tier.startswith("special") else tier


@pytest.fixture(scope="module")
def ladder():
    """{tier: [(home_goals, away_goals, home_shots, away_shots), ...]} for
    every same-tier matchup, one match per seed. The two XIs are rolled
    from different seeds so it's two squads of the tier, not one against
    a mirror of itself."""
    results = {}
    for tier in TIERS:
        legs = []
        for seed in SEEDS:
            home = generate_starter_roster("4-4-2", tier=tier, seed=seed * 10 + 1)
            away = generate_starter_roster("4-3-3", tier=tier, seed=seed * 10 + 2)
            match = game(Team("Home", home), Team("Away", away), seed=seed, formation_away="4-3-3")
            match.run_match(max_steps=REGULATION_FRAMES, render=False)
            stats = match.match_summary()
            legs.append(
                (
                    match.scores[0],
                    match.scores[1],
                    sum(s["shots"] for s in stats[:11]),
                    sum(s["shots"] for s in stats[11:]),
                )
            )
        results[tier] = legs
    return results


@pytest.fixture(scope="module")
def goals_per_match(ladder):
    """Prints the table once per run and hands back {tier: goals per match}."""
    print(f"\n  SAME-TIER MATCHUPS -- {len(SEEDS)} matches per tier (seeds {', '.join(map(str, SEEDS))})\n")
    print(f"  {'tier':>9}  {'scorelines':<28}  {'goals/match':>11}  {'shots/match':>11}")
    per_match = {}
    for tier in TIERS:
        legs = ladder[tier]
        goals = sum(h + a for h, a, _, _ in legs) / len(legs)
        shots = sum(hs + as_ for _, _, hs, as_ in legs) / len(legs)
        per_match[tier] = goals
        scorelines = " ".join(f"{h}-{a}" for h, a, _, _ in legs)
        print(f"  {_label(tier):>9}  {scorelines:<28}  {goals:>11.1f}  {shots:>11.1f}")
    print()
    return per_match


def test_icon_matches_score_more_than_bronze_ones(goals_per_match):
    """Direction only: the top of the ladder produces more goals per match
    than the bottom. Nothing about the shape in between, which is what the
    printed table is for."""
    assert goals_per_match["icon"] > goals_per_match["bronze"], (
        f"icon v icon {goals_per_match['icon']:.1f} goals/match, "
        f"bronze v bronze {goals_per_match['bronze']:.1f}"
    )
