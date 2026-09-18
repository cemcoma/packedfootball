"""Writes statistics.avg_rating onto players/{id} docs that earned it before
the field existed.

player.py's record_match now stores the career average as its own field
once a card has RATED_MATCHES_FOR_AVERAGE rated matches, because
/leaderboard/players can only order on a stored field, not on
rating_sum / rating_count. A card that crossed that line before this
deploy and hasn't played since has no such field and is missing from the
rating board until its next match; this closes that gap in one pass.

One range query on statistics.rating_count (single field, auto-indexed),
then a write per qualifying doc that lacks the field. Safe to re-run: the
second pass finds nothing to do.

Usage:
    python3 backend/scripts/backfill_avg_rating.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import firestore
from google.cloud.firestore_v1 import FieldFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "packedfootball"))
from player.player import RATED_MATCHES_FOR_AVERAGE  

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, write nothing")
    args = parser.parse_args()

    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()

    query = db.collection("players").where(
        filter=FieldFilter("statistics.rating_count", ">=", RATED_MATCHES_FOR_AVERAGE)
    )
    written, already = 0, 0
    for doc in query.stream():
        stats = (doc.to_dict() or {}).get("statistics") or {}
        if "avg_rating" in stats:
            already += 1
            continue
        count = int(stats.get("rating_count", 0))
        avg = round(float(stats.get("rating_sum", 0.0)) / count, 2) if count else 0.0
        print(f"{doc.id}  {count} rated matches -> {avg}")
        if not args.dry_run:
            doc.reference.update({"statistics.avg_rating": avg})
        written += 1

    print(f"{written} card(s) {'would be ' if args.dry_run else ''}written, {already} already had it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
