"""Dev tool: runs one seeded match and writes its encoded replay to a .bin
file the Godot scaffold in mobile/ can load directly -- lets the Godot-side
rendering/interpolation get built and iterated on without needing the
backend (or a network connection) at all.

Not a one-off migration script like backend/scripts/seed_packs.py -- keep
this one around and re-run it whenever you want a fresh test fixture (e.g.
after tweaking gameEngine.py, or to get a replay with a different seed/
matchup to test against).

Usage:
    python3 packedfootball/scripts/dump_test_replay.py [--seed N] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packEngine import PackManager, PACK_DATABASE  # noqa: E402
from gameEngine import game  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parent.parent.parent / "mobile" / "test_data" / "sample_match.bin"


class _Team:
    def __init__(self, name, players):
        self.name = name
        self.players = players


def build_teams(roster_seed: int):
    """Assembles two proper 4-4-2 lineups, one player per formation slot by
    actual position -- NOT just "the next 11 cards to come out of a pack" in
    whatever order, which can (and did) put e.g. a Goalkeeper in the LB slot.
    gameEngine.py trusts slot order completely; it never checks .position
    against the formation dict itself, so a mis-slotted roster makes that
    player behave exactly like their real class (a keeper glued to their own
    goal line) while LOOKING like a broken outfield player.
    """
    pm = PackManager(PACK_DATABASE, seed=roster_seed)
    pool = []
    while len(pool) < 400:  # generous margin so every position group is covered
        pool += pm.open_pack(3)

    def take(positions: list, n: int) -> list:
        chosen = [p for p in pool if p.position in positions][:n]
        for p in chosen:
            pool.remove(p)
        return chosen

    def build_one_team():
        # Formation slot order: GK, LB, LCB, RCB, RB, LM, LCM, RCM, RM, LS, RS
        starting_xi = (
            take(["GK"], 1)
            + take(["LB"], 1)
            + take(["CB"], 2)
            + take(["RB"], 1)
            + take(["CM"], 4)
            + take(["ST", "LW", "RW"], 2)
        )
        if len(starting_xi) != 11:
            raise RuntimeError(
                f"Could not assemble a full XI from the pack pool (got {len(starting_xi)}/11) -- "
                "increase the pool size or try a different --roster-seed."
            )
        return starting_xi

    return _Team("Home", build_one_team()), _Team("Away", build_one_team())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7, help="Match simulation seed")
    parser.add_argument("--roster-seed", type=int, default=55, help="Seed for generating the two test rosters")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output .bin path")
    args = parser.parse_args()

    team_home, team_away = build_teams(args.roster_seed)
    match = game(team_home, team_away, seed=args.seed, record_replay=True)
    match.run_match(max_steps=10800, render=False)  # 90 real-minute match, matching packedfootball/main.py's own loop

    data = match.replay.encode()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)

    # Companion roster metadata: the replay itself only ever carries array
    # indices (0-21), never names -- a real client gets names from the
    # match-start payload instead. This local scaffold has no such payload
    # yet, so it needs its own small sidecar file to look names up by index.
    roster = {
        "home_name": team_home.name,
        "away_name": team_away.name,
        "players": [
            {"fname": p.fname, "lname": p.lname, "position": p.position}
            for p in (team_home.players + team_away.players)
        ],
    }
    roster_path = args.out.with_suffix(".json")
    roster_path.write_text(json.dumps(roster, indent=2))

    print(f"Score: {match.scores[0]}-{match.scores[1]}")
    print(f"Wrote {len(data)} bytes ({len(data) / 1024:.1f} KB) to {args.out}")
    print(f"Wrote roster metadata to {roster_path}")


if __name__ == "__main__":
    main()
