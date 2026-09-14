"""Fetches and displays deal data currently living in Firestore.

Useful for verifying that sync_deal_definitions.py worked, checking
operational state fields (like active, expires_at, max_redemptions,
max_redemptions_per_account, times_redeemed), or just inspecting the live
database without having to click through the Firebase Console. Direct
structural copy of list_packs.py -- see that file, identical here just for
deals instead of packs.

Usage:
    python3 backend/scripts/list_deals.py [--deal-id ID]
"""

import argparse
import os
import pprint

import firebase_admin
from firebase_admin import firestore

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")

def main():
    parser = argparse.ArgumentParser(description="List deals currently in Firestore.")
    parser.add_argument("--deal-id", type=str, default=None, help="Fetch only this deal id (default: all deals)")
    args = parser.parse_args()

    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()

    deals_ref = db.collection("deals")

    if args.deal_id:
        doc = deals_ref.document(args.deal_id).get()
        if not doc.exists:
            print(f"deals/{args.deal_id}: Not found in Firestore.")
            return
        docs = [doc]
    else:
        docs = deals_ref.stream()

    count = 0
    for doc in docs:
        count += 1
        print(f"\n=== deals/{doc.id} ===")

        data = doc.to_dict()

        # pprint handles Firestore Datetime objects safely, unlike json.dumps
        pprint.pprint(data, sort_dicts=False, width=80)

    print(f"\nTotal deals found: {count}")


if __name__ == "__main__":
    main()
