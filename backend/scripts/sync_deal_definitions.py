"""Pushes DEAL_DATABASE's definitional fields (name, description,
cost_currency, cost_amount, reward_credits, reward_bucks) from
packedfootball/deal_database.py into existing Firestore deals/{deal_id}
docs -- WITHOUT touching active/times_redeemed/max_redemptions/
max_redemptions_per_account/expires_at/visible/available_at, which are
operational state that only lives in Firestore (a deal you've suspended
stays suspended; real redemption counts aren't reset; a redemption cap or
preview flag you set in Firestore isn't clobbered back to its default just
because DEAL_DATABASE doesn't carry it).

Direct structural copy of sync_pack_definitions.py -- see that file for the
full rationale, identical here just for deals instead of packs. Re-run any
time DEAL_DATABASE changes and Firestore needs to catch up.

Usage:
    python3 backend/scripts/sync_deal_definitions.py [--dry-run] [--deal-id ID] [--activate-new]

--activate-new only affects a deal id with NO existing doc yet (the normal
case for a brand-new entry in DEAL_DATABASE) -- it still starts inactive by
default otherwise, specifically so a routine re-sync can never silently
flip a deal live. It never touches an EXISTING doc's own `active` value,
paused or not -- that would break the same "never clobber operational
state" guarantee this script exists to uphold.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import firestore

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "packedfootball"))
from deal_database import DEAL_DATABASE

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")
DEFINITION_FIELDS = ("name", "description", "cost_currency", "cost_amount", "reward_credits", "reward_bucks")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without writing anything")
    parser.add_argument("--deal-id", type=str, default=None, help="Sync only this deal id (default: all deals)")
    parser.add_argument(
        "--activate-new", action="store_true",
        help="Create a brand-new deal doc already active=true instead of active=false. Never touches an existing doc's active value.",
    )
    args = parser.parse_args()

    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()

    deal_ids = [args.deal_id] if args.deal_id is not None else list(DEAL_DATABASE.keys())

    for deal_id in deal_ids:
        config = DEAL_DATABASE.get(deal_id)
        if config is None:
            print(f"deals/{deal_id}: no such deal in DEAL_DATABASE, skipping")
            continue

        doc_ref = db.collection("deals").document(deal_id)
        existing = doc_ref.get()
        update = {field: config[field] for field in DEFINITION_FIELDS if field in config}

        if not existing.exists:
            initial_active = args.activate_new
            print(f"deals/{deal_id}: no existing doc -- creating it with definitional fields plus active={initial_active}")
            if not initial_active:
                print(f"  (flip active to true, and set expires_at/max_redemptions/etc, in the Firestore console --")
                print(f"  or re-run with --activate-new)")
            if not args.dry_run:
                doc_ref.set({**update, "active": initial_active, "times_redeemed": 0})
            continue

        before = existing.to_dict()
        changed_fields = [f for f in DEFINITION_FIELDS if before.get(f) != update.get(f)]

        if not changed_fields:
            print(f"deals/{deal_id}: already up to date, no changes")
            continue

        print(f"deals/{deal_id}: updating {changed_fields}")
        for f in changed_fields:
            print(f"  {f}: {before.get(f)!r} -> {update.get(f)!r}")

        if not args.dry_run:
            doc_ref.set(update, merge=True)

    mode = "DRY RUN -- nothing written." if args.dry_run else "Done."
    print(f"\n{mode}")


if __name__ == "__main__":
    main()
