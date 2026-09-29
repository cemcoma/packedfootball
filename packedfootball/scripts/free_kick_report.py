"""Dev tool: what a direct free kick turns into, taker tier against keeper tier.

Free kicks are flown by free_kick.py, so nothing sets their odds directly --
this is how the FK_* constants in game_config get tuned. Each kick is a fresh
match stopped for a shooting free kick at a random spot in the shooting zone,
played on (AI and all) until the ball's flight is over.

Usage:
    make fk-report
    make fk-report KICKS=400
    python3 packedfootball/scripts/free_kick_report.py --pairs gold:gold icon:bronze

The targets:
    goal        ~7-10% overall, rising with the taker, falling with the keeper
    wall        roughly 20-30%
"""

from __future__ import annotations

import argparse
import copy
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import free_kick  # noqa: E402
from game_config import GOAL_HEIGHT, PITCH_WIDTH  # noqa: E402
from gameEngine import FK_SHOOTING_HALF_WIDTH, FK_SHOOTING_RANGE, game  # noqa: E402
from packEngine import generate_starter_roster  # noqa: E402
from replay import ActionType  # noqa: E402

DEFAULT_PAIRS = (
    ("bronze", "bronze"),
    ("gold", "gold"),
    ("icon", "icon"),
    ("icon", "bronze"),
    ("bronze", "icon"),
)
OUTCOMES = ("goal", "caught", "parried", "wall", "body", "wide", "over", "post", "other")
MAX_TICKS = 400


class _Team:
    def __init__(self, name, players):
        self.name = name
        self.players = players


def _spot(rng) -> tuple[float, float]:
    """Somewhere _free_kick_kind calls "shooting" for team 0, outside the box."""
    goal = np.array([PITCH_WIDTH / 2.0, 100.0])
    while True:
        x = PITCH_WIDTH / 2.0 + rng.uniform(-FK_SHOOTING_HALF_WIDTH, FK_SHOOTING_HALF_WIDTH)
        y = rng.uniform(100.0 - FK_SHOOTING_RANGE, 100.0)
        in_box = 14.0 < x < 56.0 and y > 82.0
        if not in_box and np.hypot(*(goal - [x, y])) <= FK_SHOOTING_RANGE:
            return x, y


def take_kick(home, away, seed: int, spot, behind: int = 0, minute: float = 0.0) -> tuple[str, str]:
    g = game(_Team("Taker", copy.deepcopy(home)), _Team("Keeper", copy.deepcopy(away)),
             seed=seed, record_replay=True)
    g.kickoff_timer = 0
    g.scores[1] = behind
    g.match_clock_frames = int(minute * 120)
    if minute > 45.0:
        g.halftime_clock_frames = g.regulation_half_frames
    g._begin_restart("free_kick", 0, out_x=spot[0], out_y=spot[1])
    if g.free_kick_kind == "played_in":
        return "in", ""
    if g.free_kick_kind != "shooting":
        return "skip", ""
    first_event = len(g.replay._events)
    posts = g.post_hits
    technique, crossing, flown = "", None, False
    for _ in range(MAX_TICKS):
        if g.match_clock_frames % g.decision_interval == 0:
            g.step()
        g.tick(1 / 60)
        if g._fk_flight is not None and not flown:
            flown = True
            technique = g._fk_flight.technique
            crossing = free_kick.predict_crossing(g.ball, g._fk_flight.spin, 100.0)
        if flown and g._fk_flight is None:
            break

    kinds = [ActionType(e[1]) for e in g.replay._events[first_event:]]
    if ActionType.GOAL in kinds:
        return "goal", technique
    if ActionType.SAVE in kinds:
        return ("caught" if g.ball_controller in g._keeper_indices else "parried"), technique
    if ActionType.BLOCK in kinds:
        blocker = [e[2] for e in g.replay._events[first_event:] if e[1] == ActionType.BLOCK][0]
        return ("wall" if blocker in g._fk_wall else "body"), technique
    if g.post_hits > posts:
        return "post", technique
    if crossing is not None and crossing["z"] >= GOAL_HEIGHT:
        return "over", technique
    if ActionType.GOAL_KICK in kinds or ActionType.CORNER in kinds:
        return "wide", technique
    return "other", technique


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kicks", type=int, default=200, help="free kicks per pair (default 200)")
    parser.add_argument("--pairs", nargs="*", default=[f"{a}:{b}" for a, b in DEFAULT_PAIRS],
                        help="taker_tier:keeper_tier")
    parser.add_argument("--behind", type=int, default=0, help="goals the taking side is behind")
    parser.add_argument("--minute", type=float, default=0.0, help="match minute of the free kick")
    args = parser.parse_args()

    print(f"\n  DIRECT FREE KICKS -- {args.kicks} shots per pair (taker v keeper), % of shots"
          f"\n  {args.behind} behind at {args.minute:.0f}'; played in = % of shooting-range free kicks")
    header = f"  {'pair':>16}" + "".join(f"{o:>8}" for o in OUTCOMES) + "  played in   over/around"
    print(header)
    print("  " + "-" * (len(header) - 2))
    total = Counter()
    for pair in args.pairs:
        taker_tier, keeper_tier = pair.split(":")
        home = generate_starter_roster("4-4-2", taker_tier, seed=1000 + len(taker_tier))
        away = generate_starter_roster("4-4-2", keeper_tier, seed=2000 + len(keeper_tier))
        rng = np.random.default_rng(7)
        counts, techniques = Counter(), Counter()
        played_in = 0
        seed = 0
        while sum(counts.values()) < args.kicks:
            seed += 1
            outcome, technique = take_kick(home, away, seed, _spot(rng), args.behind, args.minute)
            if outcome == "skip":
                continue
            if outcome == "in":
                played_in += 1
                continue
            counts[outcome] += 1
            techniques[technique] += 1
        total.update(counts)
        n = sum(counts.values())
        row = "".join(f"{100.0 * counts[o] / n:>8.1f}" for o in OUTCOMES)
        share = 100.0 * played_in / (played_in + n)
        print(f"  {pair:>16}{row}{share:>11.1f}   {techniques['over']}/{techniques['around']}")
    n = sum(total.values())
    print(f"  {'all':>16}" + "".join(f"{100.0 * total[o] / n:>8.1f}" for o in OUTCOMES))


if __name__ == "__main__":
    main()
