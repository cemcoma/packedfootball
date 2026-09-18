"""Read-only: lists match bug reports (POST /match/report), newest first,
with what you need to reproduce each one.

A report is small on purpose -- category, words, who, which game. The
match itself is fully reconstructible from its games/{id} doc: `seed`,
`engine_version`, and the `teams` snapshot holding both rosters exactly as
played (player_to_fields shape, formations and kits included). With
--dump-dir each listed report's game doc is written out as
<game_id>.json for exactly that: rebuild both sides with
game_state.fields_to_player, run gameEngine.game with the seed and the
formations, and the replay is the one the player watched -- provided the
engine is checked out at the reported version, since the seed only
reproduces the match against the code that produced it.

Never writes to Firestore. Safe to run any time against production.

Usage:
    python3 backend/scripts/list_match_reports.py [--all] [--limit N] [--dump-dir DIR]

Only "open" reports by default; --all includes the ones you've marked
otherwise (set `status` on the doc by hand -- "fixed", "not_a_bug", ...).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import firestore

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")


def _json_safe(value):
    """Firestore timestamps and nested maps -> something json.dumps takes."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Include reports whose status isn't 'open'")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dump-dir", type=Path, default=None, help="Write each report's games/{id} doc here as <game_id>.json")
    args = parser.parse_args()

    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()

    query = db.collection("match_reports").order_by("created_at", direction=firestore.Query.DESCENDING).limit(args.limit)
    reports = [(d.id, d.to_dict() or {}) for d in query.stream()]
    if not args.all:
        reports = [(i, r) for i, r in reports if r.get("status", "open") == "open"]

    if args.dump_dir is not None:
        args.dump_dir.mkdir(parents=True, exist_ok=True)

    for report_id, r in reports:
        created = r.get("created_at")
        when = created.strftime("%Y-%m-%d %H:%M") if hasattr(created, "strftime") else "?"
        score = r.get("score")
        score_text = f"{score[0]}-{score[1]}" if isinstance(score, list) and len(score) == 2 else "?"
        print(f"{when}  [{r.get('status', 'open')}]  {r.get('category', '?'):<14}  {r.get('mode', '?'):<10}  {score_text:<5}  game {r.get('game_id')}")
        print(f"    seed {r.get('seed')}  engine {r.get('engine_version')}  replay v{r.get('replay_format_version')}  by {r.get('uid')}")
        if r.get("description"):
            print(f"    \"{r['description']}\"")
        if args.dump_dir is not None and r.get("game_id"):
            game = db.collection("games").document(r["game_id"]).get()
            if game.exists:
                out = args.dump_dir / f"{r['game_id']}.json"
                out.write_text(json.dumps(_json_safe(game.to_dict()), indent=2))
                print(f"    -> {out}")
        print()

    print(f"{len(reports)} report(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
