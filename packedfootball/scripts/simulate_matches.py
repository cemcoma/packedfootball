"""Dev tool: simulate N seeded matches and print what the shooting and
goalkeeping actually looked like.

This is the balance harness, not a test. Unit tests can tell you the save
formula returns the right number for a given input; only a pile of real
matches can tell you whether the constants in gameEngine.py add up to
football. Every keeper/shooting constant in the engine was tuned against
this output.

Usage:
    make sim                          # 10 matches
    make sim MATCHES=30 SEED=5
    python3 packedfootball/scripts/simulate_matches.py --matches 30

What to look for (the targets the current constants were tuned to):

    shots on target   ~60%      accuracy is meant to be earned, not random
    save rate         65-75%    saves / (saves + goals) on genuine shots
    goals/match       2-3
    wide/over saves   ~0        a keeper diving at a ball going wide is a bug
    ball airborne     >5%       below this, nothing ever looks lofted

Every number below is measured, never asserted -- read the table, change a
constant in gameEngine.py, run it again.
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gameEngine import game  # noqa: E402
from packEngine import PACK_DATABASE, PackManager  # noqa: E402

REGULATION_FRAMES = 10800  # 90:00, see gameEngine.FRAMES_PER_CLOCK_SECOND
AIRBORNE_HEIGHT = 0.05     # above this the ball counts as off the turf


class _Team:
    def __init__(self, name, players):
        self.name = name
        self.players = players


def build_teams(roster_seed: int):
    """Two 4-4-2 XIs, one card per slot BY POSITION -- same assembly as
    dump_test_replay.py. The engine trusts slot order and never checks a
    card's position against the formation, so a mis-slotted roster behaves
    as its real class (a keeper in the LB slot never leaves its goal line)
    and quietly poisons every number in this table.
    """
    pm = PackManager(PACK_DATABASE, seed=roster_seed)
    pool = []
    while len(pool) < 400:
        pool += pm.open_pack("jumbo_standard")

    def take(positions, n):
        chosen = [p for p in pool if p.position in positions][:n]
        for p in chosen:
            pool.remove(p)
        return chosen

    def build_one():
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

    return build_one(), build_one()


def instrument(match):
    """Wraps the two methods that can't be measured from the final stats.

    - tick() for how much of the match the ball spends in the air. The engine
      keeps no history, so it has to be sampled live.
    - _attempt_save() for whether each save was of a ball that was actually
      going in. This is the number that exposed the old bug where 63% of all
      "saves" were of shots already heading wide or over the bar.
    """
    counters = {"ticks": 0, "airborne": 0, "attempts": 0, "attempts_off_target": 0,
                "saves_off_target": 0}

    real_tick = match.tick
    real_save = match._attempt_save

    def tick(dt=1 / 60):
        result = real_tick(dt)
        counters["ticks"] += 1
        if float(match.ball[4]) > AIRBORNE_HEIGHT:
            counters["airborne"] += 1
        return result

    def attempt_save(index):
        defending_team = 0 if index < 11 else 1
        crossing = match.predict_goal_crossing(defending_team)
        saves_before = match.match_stats[index]["saves"]
        stun_before = int(match.player_stun_cooldown[index])

        result = real_save(index)

        saved = match.match_stats[index]["saves"] > saves_before
        # A keeper that was beaten is put on the floor, and only _attempt_save
        # sets that particular cooldown -- so a 0 -> down transition across
        # this call is exactly "tried and missed".
        beaten = stun_before == 0 and int(match.player_stun_cooldown[index]) > 0 and not saved

        if saved or beaten:
            counters["attempts"] += 1
            if not (crossing and crossing["on_target"]):
                counters["attempts_off_target"] += 1
                if saved:
                    counters["saves_off_target"] += 1
        return result

    match.tick = tick
    match._attempt_save = attempt_save
    return counters


def simulate(seed: int, home, away):
    match = game(_Team("Home", copy.deepcopy(home)), _Team("Away", copy.deepcopy(away)), seed=seed)
    counters = instrument(match)
    match.run_match(max_steps=REGULATION_FRAMES, render=False)

    stats = match.match_summary()

    def total(key):
        return sum(row[key] for row in stats)

    return {
        "seed": seed,
        "score": tuple(match.scores),
        "goals": int(sum(match.scores)),
        "shots": total("shots"),
        "on_target": total("shots_on_target"),
        "saves": total("saves"),
        "passes": total("passes"),
        "passes_completed": total("passes_completed"),
        "posts": match.post_hits,
        "clock": match.match_clock_frames,
        **counters,
    }


def pct(part, whole):
    return f"{100.0 * part / whole:5.1f}%" if whole else "    --"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--matches", type=int, default=10, help="How many matches to simulate")
    parser.add_argument("--seed", type=int, default=1, help="First match seed; +1 per match")
    parser.add_argument("--roster-seed", type=int, default=55, help="Seed for the two test rosters")
    args = parser.parse_args()

    home, away = build_teams(args.roster_seed)

    print(f"Simulating {args.matches} matches (seeds {args.seed}..{args.seed + args.matches - 1})\n")
    print(f"  {'seed':>5}  {'score':>7}  {'shots':>6}  {'on tgt':>7}  {'saves':>6}  {'posts':>6}")

    rows = []
    for i in range(args.matches):
        row = simulate(args.seed + i, home, away)
        rows.append(row)
        print(
            f"  {row['seed']:>5}  {row['score'][0]:>3}-{row['score'][1]:<3}  {row['shots']:>6}"
            f"  {row['on_target']:>7}  {row['saves']:>6}  {row['posts']:>6}"
        )

    n = len(rows)

    def agg(key):
        return sum(r[key] for r in rows)

    goals, shots, on_target = agg("goals"), agg("shots"), agg("on_target")
    saves, posts = agg("saves"), agg("posts")
    # Save rate is over shots that were genuinely on target only: a save plus
    # a goal is every on-target shot that reached the keeper.
    on_target_faced = saves + goals

    print(f"\n  {n} matches, {agg('clock') / n / 120:.1f} min of clock each\n")
    print(f"  shots/match        {shots / n:5.1f}")
    print(f"  on target          {pct(on_target, shots)}        [target ~60%]")
    print(f"  SAVE RATE          {pct(saves, on_target_faced)}        [target 65-75%]")
    print(f"  goals/match        {goals / n:5.2f}        [target 2-3]")
    print(f"  posts/match        {posts / n:5.2f}")
    print(f"  passes/match       {agg('passes') / n:5.0f}  ({pct(agg('passes_completed'), agg('passes'))} completed)")
    print(f"  ball airborne      {pct(agg('airborne'), agg('ticks'))}        [target >5%]")
    print(f"  save attempts      {agg('attempts'):5d}  ({agg('attempts_off_target')} at balls going wide/over)")
    print(f"  saves of wide/over {agg('saves_off_target'):5d}        [target 0]")

    scores = [r["score"] for r in rows]
    worst = max(scores, key=lambda s: abs(s[0] - s[1]))
    print(f"  biggest margin     {worst[0]}-{worst[1]}")
    print(f"  goals spread       {min(r['goals'] for r in rows)}-{max(r['goals'] for r in rows)} per match")


if __name__ == "__main__":
    main()
