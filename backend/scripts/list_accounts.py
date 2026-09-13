"""Read-only diagnostic: lists every users/{uid} doc and whether it has a
published lobby/{uid} entry -- run this to see the real current opponent
pool for Quick Match (see mobile/README.md's "Quick Match" section) before
deciding whether a bot-fallback opponent is actually needed.

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

    lobby_uids = {doc.id for doc in db.collection("lobby").stream()}

    print(f"{'uid':<30} {'display_name':<20} {'formation':<10} {'roster':<7} {'in lobby?'}")
    user_count = 0
    for doc in db.collection("users").stream():
        user_count += 1
        fields = doc.to_dict() or {}
        roster_size = len(fields.get("roster_player_ids", []))
        print(
            f"{doc.id:<30} {fields.get('display_name', '?'):<20} "
            f"{fields.get('formation', '?'):<10} {roster_size:<7} "
            f"{'yes' if doc.id in lobby_uids else 'no'}"
        )

    print(f"\n{user_count} total users/ docs, {len(lobby_uids)} with a published lobby/ entry.")


if __name__ == "__main__":
    main()
