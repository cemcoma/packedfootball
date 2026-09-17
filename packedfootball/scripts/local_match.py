"""Dev tool: simulates one match ON THIS MACHINE and writes a JSON file in
the exact shape of a /match/quick response, so the Godot client can play
it back through the normal MatchSession path -- playback, opponent squad,
result and stats screens all work -- without the backend, Firestore or a
network connection being involved at any point. Nothing is persisted:
no stats written, no credits, no energy.

Driven by Play.tscn's TESTING panel (editor-only, see Play.gd), which is
how the engine's decision interval gets A/B'd for feel against its CPU
cost: "adaptive" is what production runs -- every-2-frames rounds, but
each player only re-decides as often as their distance to the ball
warrants (gameEngine's ADAPTIVE_* constants); 2/3/4/6 force a fixed
interval for everyone, 2 being the old production behaviour. The output carries
"sim_seconds" (CPU time of run_match) and "decisions" (player decisions
taken) so feel and cost can be compared on the same screen.

The home side is your real squad when --home-roster is given (Play.gd
writes it from GameProfile: formation + the 11 cards in slot order, in
player_to_fields shape) and a generated squad of --home-tier otherwise.
The away side is always a freshly rolled bot of --opponent-tier, same as
backend/services/match.py's _generate_bot_opponent.

Usage:
    python3 packedfootball/scripts/local_match.py --out /tmp/match.json \\
        [--decision-interval 2] [--opponent-tier gold] [--home-roster squad.json] [--seed N]

Any failure is written to --out as {"error": "..."} rather than left to a
stack trace, since the caller (Godot) can't see this process's stderr.
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import secrets
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# gameEngine before formations -- they import each other, and only this
# order resolves (see backend/engine.py's own note on the same trap).
from gameEngine import ENGINE_VERSION, game  # noqa: E402
from formations import FORMATIONS  # noqa: E402
from game_state import fields_to_player, player_to_fields  # noqa: E402
from packEngine import PLAYER_CLASS_MAP, TIER_RANGES, generate_starter_roster  # noqa: E402
from player.classes.midfielder import Midfielder  # noqa: E402
from replay import FORMAT_VERSION as REPLAY_FORMAT_VERSION  # noqa: E402

# Same shirt the backend gives every bot (config.BOT_KIT) -- not imported
# from there because backend/config.py drags in Firebase settings.
BOT_KIT = "v1;pattern=stripes;primary=c8102e;secondary=121216"
DEFAULT_HOME_KIT = "v1;pattern=solid;primary=1e6fe0;secondary=ffffff"


class _Team:
    def __init__(self, name, players):
        self.name = name
        self.players = players


def _bot_profile(tier: str, rng: random.Random) -> dict:
    formation = rng.choice(list(FORMATIONS.keys()))
    return {
        "display_name": f"{tier.capitalize()} Bot",
        "formation": formation,
        "roster": generate_starter_roster(formation, tier, seed=rng.getrandbits(63)),
        "kit": BOT_KIT,
    }


def _home_profile(args, rng: random.Random) -> dict:
    if args.home_roster is None:
        profile = _bot_profile(args.home_tier, rng)
        profile["display_name"] = "You (generated)"
        profile["kit"] = DEFAULT_HOME_KIT
        return profile

    data = json.loads(Path(args.home_roster).read_text())
    players = [fields_to_player(f, PLAYER_CLASS_MAP, Midfielder) for f in data["players"]]
    if len(players) != 11:
        raise ValueError(f"home roster has {len(players)} players, need 11")
    formation = data.get("formation", "4-4-2")
    if formation not in FORMATIONS:
        raise ValueError(f"unknown formation {formation!r}")
    return {
        "display_name": data.get("display_name") or "You",
        "formation": formation,
        "roster": players,
        "kit": data.get("kit") or DEFAULT_HOME_KIT,
    }


def run(args) -> dict:
    adaptive = args.decision_interval == "adaptive"
    rng = random.Random(args.seed)
    home = _home_profile(args, rng)
    away = _bot_profile(args.opponent_tier, rng)

    match = game(
        _Team(home["display_name"], home["roster"]),
        _Team(away["display_name"], away["roster"]),
        seed=args.seed,
        record_replay=True,
        formation_home=home["formation"],
        formation_away=away["formation"],
        decision_interval=2 if adaptive else int(args.decision_interval),
        adaptive_decisions=adaptive,
    )
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    match.run_match(max_steps=10800, render=False)
    cpu_seconds, wall_seconds = time.process_time() - cpu_start, time.perf_counter() - wall_start

    # Mirrors backend/services/match.run_match + routers/matches.quick_match,
    # key for key, so MatchSession.set_from_match_response takes it as-is.
    return {
        "seed": args.seed,
        "engine_version": ENGINE_VERSION,
        "replay_format_version": REPLAY_FORMAT_VERSION,
        "score": list(match.scores),
        "opponent_display_name": away["display_name"],
        "opponent_is_bot": True,
        "credits_earned": 0,
        "replay": base64.b64encode(match.replay.encode()).decode(),
        "roster": [player_to_fields(p) for p in home["roster"]] + [player_to_fields(p) for p in away["roster"]],
        "player_match_stats": match.match_summary(),
        "added_time": [frames // 2 for frames in match.added_time_frames],
        "kits": [home["kit"], away["kit"]],
        "formations": [home["formation"], away["formation"]],
        # Local-only extras, ignored by MatchSession and shown by Play.gd.
        "decision_interval": args.decision_interval,
        "decisions": match._decisions_made,
        "sim_seconds": round(cpu_seconds, 2),
        "wall_seconds": round(wall_seconds, 2),
        "home_display_name": home["display_name"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True, help="Where to write the match JSON")
    parser.add_argument("--decision-interval", default="adaptive", help="'adaptive' (production) or a fixed frame count for everyone (2 = old production)")
    parser.add_argument("--opponent-tier", choices=list(TIER_RANGES.keys()), default="gold")
    parser.add_argument("--home-tier", choices=list(TIER_RANGES.keys()), default="gold", help="Only used without --home-roster")
    parser.add_argument("--home-roster", type=Path, default=None, help="JSON: {formation, players: [player fields...], display_name, kit}")
    parser.add_argument("--seed", type=int, default=None, help="Match seed (random if omitted)")
    args = parser.parse_args()
    if args.seed is None:
        args.seed = secrets.randbits(63)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = run(args)
    except Exception as exc:  # noqa: BLE001 -- the whole point is to report it to the caller
        args.out.write_text(json.dumps({"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}))
        print(traceback.format_exc(), file=sys.stderr)
        return 1

    args.out.write_text(json.dumps(result))
    print(
        f"Score {result['score'][0]}-{result['score'][1]}  interval={args.decision_interval}  "
        f"decisions={result['decisions']}  cpu={result['sim_seconds']}s wall={result['wall_seconds']}s  -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
