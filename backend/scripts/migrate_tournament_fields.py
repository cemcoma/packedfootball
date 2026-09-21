"""Move each account's tournament state into the keyed maps.

users/{uid} used to carry one flat field per format-and-question:

    daily_tournament_tier            tournament_day_id
    weekly_tournament_tier           tournament_group_id
                                     tournament_last_settled_day
                                     tournament_last_group_id

and now carries three maps keyed by format, the shape ad_counters uses:

    tournament_tiers    {"daily": 2, "weekly": 3}
    tournament_entries  {"daily": {"period_id": ..., "group_id": ...}, ...}
    tournament_last     {"daily": {"period_id": ..., "group_id": ...}, ...}

Only the DAILY league ever wrote the old fields -- the weekly one was never
deployed under them -- so that is all this reads.

SAFE IN EITHER ORDER relative to the deploy. A format whose new slot already
exists is left alone, so running this after someone has played on the new
code cannot roll them back. Nothing is deleted unless --drop-old is passed,
so a run can be repeated, and the old fields stay readable until you are
happy.

    python3 backend/scripts/migrate_tournament_fields.py --dry-run
    python3 backend/scripts/migrate_tournament_fields.py
    python3 backend/scripts/migrate_tournament_fields.py --drop-old

An account with no tournament history needs nothing: every accessor reads an
absent map as "never played", which is the same answer the old code gave for
an absent field.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import firestore

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "packedfootball"))

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")
firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})

from admin_firestore_client import AdminFirestoreClient  # noqa: E402
from services import tournament as t  # noqa: E402

# old flat field -> what it becomes. Daily only; see the module docstring.
OLD_TIER = "daily_tournament_tier"
OLD_ENTERED = "tournament_day_id"
OLD_GROUP = "tournament_group_id"
OLD_LAST_PERIOD = "tournament_last_settled_day"
OLD_LAST_GROUP = "tournament_last_group_id"
OLD_FIELDS = (OLD_TIER, OLD_ENTERED, OLD_GROUP, OLD_LAST_PERIOD, OLD_LAST_GROUP,
              "weekly_tournament_tier", "weekly_tournament_period_id",
              "weekly_tournament_group_id", "weekly_tournament_last_settled_period",
              "weekly_tournament_last_group_id")


def plan_for(doc: dict) -> dict:
    """What this account's daily state should become, or {} for nothing to do.

    A slot that already exists in the new maps is NOT rewritten: the new code
    is the authority once it has run, and a re-run must never undo it.
    """
    fields: dict = {}

    raw_tier = doc.get(OLD_TIER)
    has_new_tier = isinstance(doc.get(t.TIERS_FIELD), dict) and t.DAILY.key in doc[t.TIERS_FIELD]
    if isinstance(raw_tier, (int, float)) and not isinstance(raw_tier, bool) and not has_new_tier:
        fields[t.TIERS_FIELD] = {t.DAILY.key: int(raw_tier)}

    for old_period, old_group, field in (
        (OLD_ENTERED, OLD_GROUP, t.ENTRIES_FIELD),
        (OLD_LAST_PERIOD, OLD_LAST_GROUP, t.LAST_FIELD),
    ):
        period, group = doc.get(old_period), doc.get(old_group)
        stored = doc.get(field)
        if isinstance(stored, dict) and stored.get(t.DAILY.key) is not None:
            continue  # the new code already owns this slot
        if isinstance(period, str) and period and isinstance(group, str) and group:
            fields[field] = {t.DAILY.key: {"period_id": period, "group_id": group}}

    return fields


def describe(uid: str, doc: dict, fields: dict) -> str:
    name = doc.get("display_name") or uid[:8]
    if not fields:
        return f"  {name:<18} ({uid[:8]})  nothing to move"
    parts = []
    if t.TIERS_FIELD in fields:
        parts.append(f"tier -> {fields[t.TIERS_FIELD][t.DAILY.key]}")
    for field, label in ((t.ENTRIES_FIELD, "entry"), (t.LAST_FIELD, "last")):
        if field in fields:
            slot = fields[field][t.DAILY.key]
            parts.append(f"{label} -> {slot['period_id']}/{slot['group_id']}")
    return f"  {name:<18} ({uid[:8]})  " + ", ".join(parts)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print the plan, write nothing.")
    parser.add_argument("--drop-old", action="store_true",
                        help="Also delete the old flat fields. Run this only once the "
                             "new code is deployed and the maps look right.")
    args = parser.parse_args()

    client = AdminFirestoreClient("migrate-script")
    users = await client.list_collection("users")
    print(f"{len(users)} account(s)\n")

    moved = 0
    for doc in sorted(users, key=lambda d: d.get("display_name") or d["id"]):
        uid = doc["id"]
        fields = plan_for(doc)
        print(describe(uid, doc, fields))
        if args.drop_old:
            stale = [f for f in OLD_FIELDS if f in doc]
            if stale:
                print(f"      dropping {', '.join(stale)}")
                for field in stale:
                    fields[field] = firestore.DELETE_FIELD
        if fields and not args.dry_run:
            await client.set_document(f"users/{uid}", fields, merge=True)
            moved += 1

    print()
    if args.dry_run:
        print("dry run -- nothing was written")
    else:
        print(f"wrote {moved} account(s)")


if __name__ == "__main__":
    asyncio.run(main())
