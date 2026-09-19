"""Creates the Firestore packs/{slug} doc for every pack in
pack_database.PACK_DATABASE that doesn't have one yet. Existing docs are
never touched -- changing one is sync_pack_definitions.py's job -- so this
is safe to run any time a pack is added to the catalog: it creates the
newcomer and reports the rest as already there.

A new doc is the pack's definitional fields (the same set the sync pushes)
plus its starting operational state, taken from the catalog entry where it
spells one out and defaulted otherwise: `active` (False unless the entry
says True -- a freshly seeded pack is not on sale until someone flips it),
`times_opened` 0, and `visible` / `available_at` / `expires_at` / `max_opens`
only when the entry carries them. From then on those fields belong to
Firestore alone, exactly as for every other pack.

Also lists any live pack the catalog doesn't know -- a slug renamed in code
but not in Firestore, or a doc made by hand -- since that is the one
mismatch neither this nor the sync can fix on its own.

Usage:
    python3 backend/scripts/seed_packs.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import firestore

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "packedfootball"))
from pack_database import PACK_DATABASE  # noqa: E402
from sync_pack_definitions import DEFINITION_FIELDS  # noqa: E402  (same directory)

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")

# Firestore-only state a new doc starts with. Carried from the catalog entry
# when present (a promo's planned available_at, a capped pack's max_opens),
# otherwise left absent -- absent already means "unlimited / never expires /
# not previewed" to /pack/list.
OPERATIONAL_FIELDS = ("visible", "available_at", "expires_at", "max_opens")


def initial_doc(config: dict) -> dict:
    doc = {field: config[field] for field in DEFINITION_FIELDS if field in config}
    doc["active"] = bool(config.get("active", False))
    doc["times_opened"] = 0
    doc.update({field: config[field] for field in OPERATIONAL_FIELDS if field in config})
    return doc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, write nothing")
    args = parser.parse_args()

    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()
    packs = db.collection("packs")

    live = {snap.id for snap in packs.select(["__name__"]).stream()}
    created = 0
    for slug, config in PACK_DATABASE.items():
        if slug in live:
            print(f"packs/{slug}: exists")
            continue
        doc = initial_doc(config)
        state = {k: doc[k] for k in ("active", *OPERATIONAL_FIELDS) if k in doc}
        print(f"packs/{slug}: {'would create' if args.dry_run else 'creating'} {config['name']!r} with {state}")
        created += 1
        if not args.dry_run:
            packs.document(slug).set(doc)

    for slug in sorted(live - set(PACK_DATABASE)):
        print(f"packs/{slug}: live but not in PACK_DATABASE -- renamed in code, or made by hand?")

    print(f"{created} pack(s) {'would be' if args.dry_run else ''} created; {len(live)} already live.".replace("  ", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
