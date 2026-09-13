"""Read-only diagnostic: lists every users/{uid} doc and its roster
completeness -- run this to see the real current opponent pool for Quick
Match (see mobile/README.md's "Quick Match" section), since
`_pick_opponent_profile` in `main.py` picks candidates straight from
`users/{uid}` (roster_player_ids length == 11), no other collection involved.

Never writes anything. Safe to run any time against production.

Usage:
    python3 backend/scripts/list_accounts.py
"""

from __future__ import annotations

import os

import firebase_admin
from firebase_admin import firestore

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")


def main():
    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()

    print(f"{'uid':<30} {'display_name':<20} {'formation':<10} {'roster':<7} {'quick-match ready?'}")
    user_count = 0
    for doc in db.collection("users").stream():
        user_count += 1
        fields = doc.to_dict() or {}
        roster_size = len(fields.get("roster_player_ids", []))
        print(
            f"{doc.id:<30} {fields.get('display_name', '?'):<20} "
            f"{fields.get('formation', '?'):<10} {roster_size:<7} "
            f"{'yes' if roster_size == 11 else 'no'}"
        )

    print(f"\n{user_count} total users/ docs.")


if __name__ == "__main__":
    main()
