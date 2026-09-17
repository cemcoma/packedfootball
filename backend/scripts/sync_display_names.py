"""Backfills display_names/{key} reservations for every existing users/{uid}
doc, so accounts created before names became unique hold their name the
same way new ones do (see backend/services/account.py).

Walks users/ in creation order (document create_time), so when two
accounts already share a name the OLDER one keeps it and the newer one is
reported -- not renamed. Renaming someone is a decision, not a migration;
the printed list is what to act on (the newer account's next visit to
Settings will refuse the name it lost, and they pick another).

Names that fail today's rules (too short, a slash in them) are reported
the same way and left alone.

Only writes reservations that don't exist yet, so it is safe to re-run.

Usage:
    python3 backend/scripts/sync_display_names.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import firestore

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "packedfootball"))
from services.account import DisplayNameError, display_name_key, validate_display_name  # noqa: E402

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, write nothing")
    args = parser.parse_args()

    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()

    users = sorted(db.collection("users").stream(), key=lambda d: d.create_time)
    reserved, skipped, conflicts, invalid = 0, 0, [], []
    for doc in users:
        name = (doc.to_dict() or {}).get("display_name") or ""
        try:
            validate_display_name(name)
        except DisplayNameError as exc:
            invalid.append((doc.id, name, exc.reason))
            continue
        ref = db.collection("display_names").document(display_name_key(name))
        existing = ref.get()
        if existing.exists:
            holder = (existing.to_dict() or {}).get("uid")
            if holder == doc.id:
                skipped += 1
            else:
                conflicts.append((doc.id, name, holder))
            continue
        if not args.dry_run:
            ref.set({"uid": doc.id})
        reserved += 1

    print(f"{len(users)} users: {reserved} reserved{' (dry run)' if args.dry_run else ''}, {skipped} already held.")
    for uid, name, holder in conflicts:
        print(f"  CONFLICT  {uid}  {name!r} is held by {holder}")
    for uid, name, reason in invalid:
        print(f"  INVALID   {uid}  {name!r}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
