"""Creates the Firestore packs/{slug} doc for every pack in
pack_database.PACK_DATABASE that doesn't have one yet, and the
pack_types/{type} doc for every storefront category in PACK_TYPES that
doesn't have one. Existing docs are never touched -- changing a pack is
sync_pack_definitions.py's job, and a type's order is edited in the
console -- so this is safe to run any time a pack or a type is added to
the catalog: it creates the newcomer and reports the rest as already there.

A new doc is the pack's definitional fields (the same set the sync pushes)
plus its starting operational state, taken from the catalog entry where it
spells one out and defaulted otherwise: `active` (False unless the entry
says True -- a freshly seeded pack is not on sale until someone flips it),
`times_opened` 0, and `visible` / `available_at` / `expires_at` / `max_opens`
only when the entry carries them. From then on those fields belong to
Firestore alone, exactly as for every other pack.

Also lists what neither this nor the sync can fix on its own: a live pack
the catalog doesn't know (a slug renamed in code but not in Firestore, or
a doc made by hand), a pack type with no order anywhere (it sorts last in
the shop until pack_types/{type} exists -- see services/storefront.py),
and a pack_types doc no pack uses.

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
from pack_database import PACK_DATABASE, PACK_TYPES  # noqa: E402
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

    created_types = seed_pack_types(db, args.dry_run)

    verb = "would be" if args.dry_run else ""
    print(f"{created} pack(s) and {created_types} type(s) {verb} created; {len(live)} pack(s) already live.".replace("  ", " "))
    return 0


def seed_pack_types(db, dry_run: bool) -> int:
    """pack_types/{type} {"order": n} for every PACK_TYPES entry with no doc.
    Order is the console's to change afterwards, so an existing doc is left
    exactly as it is -- even when its order differs from the code default."""
    types = db.collection("pack_types")
    live = {snap.id: (snap.to_dict() or {}) for snap in types.stream()}
    used = {config.get("type", "") for config in PACK_DATABASE.values()}

    created = 0
    for pack_type, order in PACK_TYPES.items():
        if pack_type in live:
            print(f"pack_types/{pack_type}: exists (order {live[pack_type].get('order')!r})")
            continue
        print(f"pack_types/{pack_type}: {'would create' if dry_run else 'creating'} with order {order}")
        created += 1
        if not dry_run:
            types.document(pack_type).set({"order": order})

    for pack_type in sorted(used - set(PACK_TYPES) - set(live)):
        print(f"pack_types/{pack_type}: packs use this type but it has no order anywhere -- it sorts last until it does")
    for pack_type in sorted(set(live) - used):
        print(f"pack_types/{pack_type}: live but no pack uses it")
    return created


if __name__ == "__main__":
    sys.exit(main())
