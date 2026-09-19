"""Fetches and displays pack data currently living in Firestore, and the
pack_types/ docs whose `order` decides the shop's category order.

Useful for verifying that sync_pack_definitions.py worked, checking 
operational state fields (like available_at, visible, active), or just 
inspecting the live database without having to click through the 
Firebase Console.

Usage:
    python3 backend/scripts/list_packs.py [--pack-id SLUG]
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

    if not args.pack_id:
        types = sorted(
            ((snap.id, snap.to_dict() or {}) for snap in db.collection("pack_types").stream()),
            key=lambda item: (item[1].get("order") is None, item[1].get("order", 0), item[0]),
        )
        print("=== pack_types (shop category order) ===")
        for pack_type, doc in types:
            print(f"  {doc.get('order')!r:>6}  {pack_type}")
        if not types:
            print("  (none -- run seed_packs.py; every type sorts as unordered until then)")

    if args.pack_id:
        doc = packs_ref.document(args.pack_id).get()
        if not doc.exists:
            print(f"packs/{args.pack_id}: Not found in Firestore.")
            return
        docs = [doc]
    else:
        docs = packs_ref.stream()  # by document id: the slugs, alphabetical

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