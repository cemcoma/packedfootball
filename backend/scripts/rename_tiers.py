"""Renames tier strings on existing players/{id} docs after a tier key was
renamed in packedfootball/packEngine.py's TIER_RANGES -- e.g. the
special_ucl -> special_champ / special_uel -> special_cont rename.

A card's tier is stored as the literal key it was rolled with, and the
client looks its art up by that string (sprites/player_cards/<tier>.png),
so a renamed key leaves every card rolled under the old name with no art,
the unknown-tier release value and no colour. This walks players/ and
rewrites the ones that carry an old name.

Pack definitions are NOT touched here: packs/{id} rates carry the tier
keys too, and scripts/sync_pack_definitions.py already pushes those from
PACK_DATABASE -- run it as well. games/{id} "teams" snapshots also carry
tier strings, but nothing reads them back for display, so they are left
as the historical record they are.

One where-query per old name, so it costs reads only for the docs that
actually change, and it is safe to re-run: a second pass finds nothing.

Usage:
    python3 backend/scripts/rename_tiers.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys

import firebase_admin
from firebase_admin import firestore
from google.cloud.firestore_v1 import FieldFilter

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")

# old tier key -> new tier key. Extend when a key is renamed again; a rename
# that is already fully applied simply matches zero docs.
RENAMES = {
    "special_ucl": "special_champ",
    "special_uel": "special_cont",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, write nothing")
    args = parser.parse_args()

    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()

    total = 0
    for old, new in RENAMES.items():
        query = db.collection("players").where(filter=FieldFilter("tier", "==", old))
        docs = list(query.select(["__name__"]).stream())
        print(f"{old} -> {new}: {len(docs)} card(s)")
        total += len(docs)
        if args.dry_run:
            continue
        for start in range(0, len(docs), 500):
            batch = db.batch()
            for doc in docs[start : start + 500]:
                batch.update(doc.reference, {"tier": new})
            batch.commit()

    print(f"{total} card(s) {'would be' if args.dry_run else ''} renamed.".replace("  ", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
