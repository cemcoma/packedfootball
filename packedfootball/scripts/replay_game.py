"""Dev tool: re-simulates a recorded match ON THIS MACHINE from its
games/{id} document and writes the result in the exact shape of a
/match/quick response, so the Godot client plays it back through the
normal MatchSession path -- the same trick as local_match.py, pointed at
a real match instead of a fresh one.

This is how a bug report (POST /match/report, MatchResult's "Something
went wrong?") gets looked at: the report names a game id, the game doc
holds the seed and both rosters exactly as played (backend/services/
match.teams_snapshot), and seed + rosters + formations put through the
same gameEngine.game call backend/services/match.run_match makes give
back the identical replay -- PROVIDED the engine here is the one that
produced it. ENGINE_VERSION is checked against the doc's and a mismatch
is reported in the output ("engine_mismatch"), because a seed only
reproduces a match against the code that ran it; check out the tag for
that version if you need the exact replay rather than "this match with
today's engine".

The doc comes either straight from Firestore (--game-id, through
firebase_admin with your own Application Default Credentials -- the same
way backend/scripts/*.py run) or from a JSON dump written by
backend/scripts/list_match_reports.py --dump-dir (--game-file), which
needs no credentials at all. Any bug reports filed against the game are
fetched too and passed through under "reports", so the panel that plays
it can show what the reporter said.

Driven by the "Check a reported match" half of Play.tscn's TESTING
panel (editor-only, see Play.gd).

Usage:
    python3 packedfootball/scripts/replay_game.py --out /tmp/replay.json \\
        (--game-id ID | --game-file dump.json)

Any failure is written to --out as {"error": "..."} rather than left to a
stack trace, since the caller (Godot) can't see this process's stderr.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
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
from packEngine import PLAYER_CLASS_MAP  # noqa: E402
from player.classes.midfielder import Midfielder  # noqa: E402
from replay import FORMAT_VERSION as REPLAY_FORMAT_VERSION  # noqa: E402

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")


class _Team:
    def __init__(self, name, players):
        self.name = name
        self.players = players


def _fetch(game_id: str) -> tuple[dict, list[dict]]:
    """The games/{id} doc and every match_reports doc filed against it."""
    import firebase_admin
    from firebase_admin import firestore
    from google.cloud.firestore_v1 import FieldFilter

    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()
    snap = db.collection("games").document(game_id).get()
    if not snap.exists:
        raise KeyError(f"no games/{game_id}")
    reports = [
        d.to_dict() or {}
        for d in db.collection("match_reports").where(filter=FieldFilter("game_id", "==", game_id)).stream()
    ]
    return snap.to_dict() or {}, reports


def _side(snapshot: dict, label: str) -> dict:
    players = [fields_to_player(f, PLAYER_CLASS_MAP, Midfielder) for f in snapshot.get("players") or []]
    if len(players) != 11:
        raise ValueError(f"{label} side has {len(players)} players in the snapshot, need 11")
    formation = snapshot.get("formation", "4-4-2")
    if formation not in FORMATIONS:
        raise ValueError(f"{label} side has unknown formation {formation!r}")
    return {
        "display_name": snapshot.get("display_name") or label,
        "formation": formation,
        "roster": players,
        "kit": snapshot.get("kit") or "",
    }


def run(doc: dict, reports: list[dict], game_id: str) -> dict:
    teams = doc.get("teams") or {}
    home = _side(teams.get("initiator") or {}, "initiator")
    away = _side(teams.get("opponent") or {}, "opponent")
    seed = int(doc["seed"])
    recorded_engine = str(doc.get("engine_version", ""))

    # Exactly backend/services/match.run_match's call, argument for
    # argument -- anything different here and the seed reproduces a
    # different match.
    match = game(
        _Team(home["display_name"], home["roster"]),
        _Team(away["display_name"], away["roster"]),
        seed=seed,
        record_replay=True,
        formation_home=home["formation"],
        formation_away=away["formation"],
    )
    cpu_start = time.process_time()
    match.run_match(max_steps=10800, render=False)
    cpu_seconds = time.process_time() - cpu_start

    recorded_score = doc.get("score")
    score = list(match.scores)
    return {
        "seed": seed,
        "engine_version": ENGINE_VERSION,
        "replay_format_version": REPLAY_FORMAT_VERSION,
        "score": score,
        "opponent_display_name": away["display_name"],
        "opponent_is_bot": bool(doc.get("opponent_is_bot")),
        "credits_earned": 0,
        "replay": base64.b64encode(match.replay.encode()).decode(),
        "roster": [player_to_fields(p) for p in home["roster"]] + [player_to_fields(p) for p in away["roster"]],
        "player_match_stats": match.match_summary(),
        "added_time": [frames // 2 for frames in match.added_time_frames],
        "kits": [home["kit"], away["kit"]],
        "formations": [home["formation"], away["formation"]],
        # Local-only extras, ignored by MatchSession and shown by the CHECK
        # panel. A score that differs from the recorded one is the clearest
        # sign the engine has moved since the match was played.
        "game_id": game_id,
        "home_display_name": home["display_name"],
        "recorded_engine_version": recorded_engine,
        "engine_mismatch": recorded_engine != ENGINE_VERSION,
        "recorded_score": recorded_score,
        "score_mismatch": isinstance(recorded_score, list) and list(recorded_score) != score,
        "mode": doc.get("mode"),
        "sim_seconds": round(cpu_seconds, 2),
        "reports": [
            {k: r.get(k) for k in ("uid", "category", "description", "status")}
            for r in reports
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True, help="Where to write the match JSON")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--game-id", help="games/{id} to fetch from Firestore")
    source.add_argument("--game-file", type=Path, help="A games/{id} doc dumped as JSON (list_match_reports.py --dump-dir)")
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        if args.game_file is not None:
            doc = json.loads(args.game_file.read_text())
            reports: list[dict] = []
            game_id = args.game_file.stem
        else:
            doc, reports = _fetch(args.game_id)
            game_id = args.game_id
        result = run(doc, reports, game_id)
    except Exception as exc:  
        args.out.write_text(json.dumps({"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}))
        print(traceback.format_exc(), file=sys.stderr)
        return 1

    args.out.write_text(json.dumps(result))
    warn = ""
    if result["engine_mismatch"]:
        warn = f"  ENGINE MISMATCH: recorded {result['recorded_engine_version']}, running {ENGINE_VERSION}"
    print(
        f"Score {result['score'][0]}-{result['score'][1]} (recorded {result['recorded_score']})  "
        f"cpu={result['sim_seconds']}s  -> {args.out}{warn}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
