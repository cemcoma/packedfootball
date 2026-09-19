"""Pushes PACK_DATABASE's definitional fields (order, name, type,
description, price, cards_per_pack, rates, pos_rates, sprite) from
packedfootball/pack_database.py into existing Firestore packs/{slug} docs
-- WITHOUT touching
active/times_opened/max_opens/expires_at/visible/available_at, which are
operational state that only lives in Firestore (a pack you've suspended
stays suspended; real open counts aren't reset; an availability cap or
preview flag you set in Firestore isn't clobbered back to its default just
because PACK_DATABASE doesn't carry it).

This is the tool for any future case where a pack's definition changes in
code and needs to reach Firestore -- including ones the Firestore console
can't do cleanly itself, like renaming a key inside a nested map field
(pos_rates). A merge-update replaces pos_rates as a whole value, so a
renamed/removed key doesn't linger alongside the new one.

Re-run it any time PACK_DATABASE changes and Firestore needs to catch up.
It only UPDATES: a pack with no doc yet is reported and skipped -- creating
those is seed_packs.py's job, so that a typo'd slug here can't quietly
spawn a second copy of a pack.

Usage:
    python3 backend/scripts/sync_pack_definitions.py [--dry-run] [--pack-id SLUG]
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

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")
# "price_currency" is optional in PACK_DATABASE -- a pack that omits it is
# priced in credits (main.py defaults it), so the dict comprehension below
# simply skips it and nothing gets written for credit-priced packs.
DEFINITION_FIELDS = (
    "order", "name", "type", "description", "price", "price_currency", "cards_per_pack", "rates", "pos_rates", "sprite_key"
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without writing anything")
    parser.add_argument("--pack-id", type=str, default=None, help="Sync only this pack slug (default: all packs)")
    args = parser.parse_args()

    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()

    pack_ids = [args.pack_id] if args.pack_id is not None else list(PACK_DATABASE.keys())

    for pack_id in pack_ids:
        config = PACK_DATABASE.get(pack_id)
        if config is None:
            print(f"packs/{pack_id}: no such pack in PACK_DATABASE, skipping")
            continue

        doc_ref = db.collection("packs").document(str(pack_id))
        existing = doc_ref.get()
        update = {field: config[field] for field in DEFINITION_FIELDS if field in config}

        if not existing.exists:
            print(f"packs/{pack_id}: no existing doc -- this only updates existing packs; seed_packs.py creates missing ones.")
            continue

        before = existing.to_dict()
        changed_fields = [f for f in DEFINITION_FIELDS if before.get(f) != update.get(f)]

        if not changed_fields:
            print(f"packs/{pack_id}: already up to date, no changes")
            continue

        print(f"packs/{pack_id}: updating {changed_fields}")
        for f in changed_fields:
            print(f"  {f}: {before.get(f)!r} -> {update.get(f)!r}")

        if not args.dry_run:
            doc_ref.set(update, merge=True)

    mode = "DRY RUN -- nothing written." if args.dry_run else "Done."
    print(f"\n{mode}")


if __name__ == "__main__":
    main()
