"""Backfills attributes.heading on every players/{id} doc that predates
engine 2.3.0 (the attribute's introduction), rolled the same way a new card
rolls it: packEngine's position tier (CB/ST primary, GK nerfed, everyone
else the full tier range).

Seeded by the doc id, so a re-run rolls the same number and the script is
safe to run twice. Docs that already carry a heading are left alone.

Usage:
    python3 backend/scripts/backfill_heading.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import firestore

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "packedfootball"))
from game_config import TIER_RANGES  # noqa: E402
from packEngine import POSITION_STAT_TIERS, _roll_skill_stat  # noqa: E402

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")


def roll_heading(doc_id: str, position: str, tier: str) -> int:
    stat_type = POSITION_STAT_TIERS.get(position, {}).get("heading", "secondary")
    min_s, max_s = TIER_RANGES.get(tier, (40, 50))
    return _roll_skill_stat(random.Random(doc_id), stat_type, min_s, max_s)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, write nothing")
    args = parser.parse_args()

    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()

    filled, skipped, malformed = 0, 0, []
    for doc in db.collection("players").stream():
        fields = doc.to_dict() or {}
        attrs = fields.get("attributes")
        if not isinstance(attrs, dict):
            malformed.append(doc.id)
            continue
        if "heading" in attrs:
            skipped += 1
            continue
        value = roll_heading(doc.id, str(fields.get("position", "")), str(fields.get("tier", "")))
        if not args.dry_run:
            doc.reference.update({"attributes.heading": value})
        filled += 1

    print(f"{filled} filled{' (dry run)' if args.dry_run else ''}, {skipped} already had heading.")
    for doc_id in malformed:
        print(f"  MALFORMED  {doc_id}  no attributes map")
    return 0


if __name__ == "__main__":
    sys.exit(main())
