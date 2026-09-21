"""Settle tournament periods by hand -- a daily league day, a weekly
league week, whichever format --mode names.

Three ways a period gets settled, and this is the third:

  1. lazily, when any player touches /tournament/* (the primary path)
  2. Cloud Scheduler calling POST /tournament/settle
  3. this script, when a period is stuck and you want to see why

It exists mainly because settlement is the one part of the feature with no
safe place to fail: it moves tiers and pays medals. Being able to run it
against production with --dry-run, and read the table it WOULD write before
it writes it, is worth more than any amount of staring at the code.

Run from the repo root, authenticated by your own Application Default
Credentials, exactly like the other scripts here:

    python3 backend/scripts/settle_tournaments.py --dry-run
    python3 backend/scripts/settle_tournaments.py --day 2026-09-15
    python3 backend/scripts/settle_tournaments.py --mode weekly --dry-run
    python3 backend/scripts/settle_tournaments.py --mode weekly --day 2026-09-21 --force

--mode defaults to every format. --day is a period id: a date for the daily
league, the Monday a week started on for the weekly one, so it only makes
sense alongside a single --mode.

--force re-settles a period that is already marked settled. It does NOT
re-pay anyone: the per-group `settlement.status` token and the per-user
last-settled guard both still apply inside the transaction. It only means
"walk the period again", which is what you want after fixing whatever made a
group fail the first time.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import firestore  # noqa: F401 -- initialises the SDK's firestore module

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "packedfootball"))

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")
firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})

from admin_firestore_client import AdminFirestoreClient  # noqa: E402
from services import energy as energy_service  # noqa: E402
from services import tournament as tournament_service  # noqa: E402


def _format_row(row: dict) -> str:
    rewards = row.get("rewards") or {}
    paid = ", ".join(f"{v} {k}" for k, v in rewards.items()) if rewards else "-"
    arrow = ""
    if row.get("to_tier") != row.get("from_tier"):
        arrow = f"  tier {row['from_tier']} -> {row['to_tier']}"
    elif row.get("tier_clamped"):
        arrow = "  (at the edge, stays)"
    return (
        f"    {row.get('position'):>2}. {str(row.get('display_name'))[:18]:<18} "
        f"{row.get('points', 0):>3} pts  P{row.get('played', 0):<2} "
        f"GD {row.get('goal_diff', 0):>+3}  {row.get('outcome', ''):<9} {paid}{arrow}"
    )


async def preview_period(client, period_id: str, mode) -> None:
    """What settlement WOULD do, computed with the same pure functions it
    uses -- so this can never show a table the real run disagrees with."""
    period_doc = await client.get_document(tournament_service.period_path(period_id, mode))
    if period_doc is None:
        print(f"{period_id}: no such {mode.label}")
        return

    groups = await client.list_collection(tournament_service.groups_path(period_id, mode))
    print(f"{period_id}: status={period_doc.get('status', 'open')} groups={len(groups)}")
    if period_doc.get("settle_error"):
        print(f"  last error: {period_doc['settle_error']}")

    for group in sorted(groups, key=lambda g: g["id"]):
        settled = (group.get("settlement") or {}).get("status") == "settled"
        members = group.get("member_uids") or []
        tier = int(group.get("tier", mode.default_tier))
        rule = tournament_service.settlement_mode(len(members), mode)
        print(f"  {group['id']}  tier {tier}  {len(members)} players  {rule}"
              f"{'  [SETTLED]' if settled else ''}")

        entries = await client.list_collection(
            tournament_service.entries_path(period_id, group["id"], mode)
        )
        rows = tournament_service.apply_rules(
            tournament_service.rank_rows(entries), tier, group_size=len(members), mode=mode
        )
        for row in rows:
            print(_format_row(row))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", "--period", dest="period",
                        help="A period id (YYYY-MM-DD). Default: the lookback window.")
    parser.add_argument("--mode", choices=sorted(tournament_service.MODES),
                        help="Which format. Default: every one.")
    parser.add_argument("--dry-run", action="store_true", help="Print the table, write nothing.")
    parser.add_argument("--force", action="store_true",
                        help="Walk a period already marked settled.")
    args = parser.parse_args()

    if args.period and not args.mode:
        parser.error("--day/--period needs --mode: the same date is a day to one format "
                     "and a week to the other")

    client = AdminFirestoreClient("settle-script")
    now = energy_service.now_utc()
    modes = [tournament_service.mode_for(args.mode)] if args.mode else list(
        tournament_service.MODES.values()
    )

    for mode in modes:
        current = tournament_service.period_id_for(now, mode)
        periods = [args.period] if args.period else tournament_service.previous_period_ids(
            current, mode.settle_lookback_periods, mode
        )
        print(f"[{mode.key}] current {mode.label} is {current}; "
              f"looking at {', '.join(periods)}\n")

        for period_id in periods:
            if args.dry_run:
                await preview_period(client, period_id, mode)
                print()
                continue

            if args.force:
                await client.set_document(
                    tournament_service.period_path(period_id, mode), {"status": "open"}, merge=True
                )
            result = await tournament_service.settle_period(
                client, period_id, max_groups=10_000, mode=mode
            )
            print(f"{period_id}: {result['status']} settled={result['settled']} "
                  f"remaining={result.get('remaining', 0)}")
            for err in result.get("errors") or []:
                print(f"  ERROR {err}")
        print()

    if args.dry_run:
        print("dry run -- nothing was written")


if __name__ == "__main__":
    asyncio.run(main())
