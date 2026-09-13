"""Fetches and displays pack data currently living in Firestore.

Useful for verifying that sync_pack_definitions.py worked, checking 
operational state fields (like available_at, visible, active), or just 
inspecting the live database without having to click through the 
Firebase Console.

Usage:
    python3 backend/scripts/list_packs.py [--pack-id N]
"""

import argparse
import os
import pprint

import firebase_admin
from firebase_admin import firestore

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")

def main():
    parser = argparse.ArgumentParser(description="List packs currently in Firestore.")
    parser.add_argument("--pack-id", type=str, default=None, help="Fetch only this pack id (default: all packs)")
    args = parser.parse_args()

    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()

    packs_ref = db.collection("packs")

    if args.pack_id:
        doc = packs_ref.document(args.pack_id).get()
        if not doc.exists:
            print(f"packs/{args.pack_id}: Not found in Firestore.")
            return
        docs = [doc]
    else:
        # Sort by document ID (which are strings, so "10" comes before "2")
        # If you want numeric sorting, you'll need to fetch and sort in memory.
        docs = packs_ref.stream()

    count = 0
    for doc in docs:
        count += 1
        print(f"\n=== packs/{doc.id} ===")
        
        data = doc.to_dict()
        
        # pprint handles Firestore Datetime objects safely, unlike json.dumps
        pprint.pprint(data, sort_dicts=False, width=80)

    print(f"\nTotal packs found: {count}")


if __name__ == "__main__":
    main()