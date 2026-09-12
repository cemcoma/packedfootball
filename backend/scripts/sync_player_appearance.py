"""Backfills a placeholder `appearance` field onto existing Firestore
players/{id} docs that predate it -- e.g. any card created before
packEngine.PackManager started rolling one at generation time (see
PackManager._generate_appearance()). Every NEWLY generated card (a pack
open, or the bronze starter roster) already gets a genuinely random,
per-card appearance at creation time; this script is only for docs that
exist from before that and so have no "appearance" field at all.

Rather than one universal placeholder for every backfilled card (which
would make literally every legacy card -- most commonly a whole bronze
starter squad, all one tier -- look identical), the assigned look is
looked up by the card's own tier (TIER_DEFAULT_APPEARANCE below), so at
least tiers read as visually distinct from each other while testing. This
is still a fixed, non-random stand-in per tier, not a substitute for real
per-card randomness -- every same-tier legacy card gets the SAME look.

Only touches docs that don't already have an "appearance" field, so it's
safe to re-run: a card that already has one (backfilled once already, or
genuinely rolled by a pack open since the field was introduced) is left
alone, same "don't clobber real state" spirit as sync_pack_definitions.py
leaving active/times_opened untouched.

Usage:
    python3 backend/scripts/sync_player_appearance.py [--dry-run] [--player-id ID]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import firestore

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "packedfootball"))
from player.player import DEFAULT_APPEARANCE  # fallback for an unrecognized/missing tier

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")

# One fixed, hand-picked look per tier -- deliberately NOT randomized here
# (that's PackManager._generate_appearance()'s job for real, newly-created
# cards); just distinct enough tier-to-tier to eyeball while testing.
TIER_DEFAULT_APPEARANCE = {
    "bronze":   {"skin_tone": 0, "hair_style": 1, "hair_color": 0, "face": 0, "shoe_color": 0},
    "silver":   {"skin_tone": 1, "hair_style": 2, "hair_color": 4, "face": 0, "shoe_color": 1},
    "gold":     {"skin_tone": 2, "hair_style": 3, "hair_color": 2, "face": 1, "shoe_color": 2},
    "platinum": {"skin_tone": 3, "hair_style": 4, "hair_color": 3, "face": 1, "shoe_color": 3},
    "diamond":  {"skin_tone": 4, "hair_style": 2, "hair_color": 4, "face": 2, "shoe_color": 4},
    "special":  {"skin_tone": 1, "hair_style": 3, "hair_color": 3, "face": 4, "shoe_color": 2},
    "icon":     {"skin_tone": 2, "hair_style": 4, "hair_color": 2, "face": 3, "shoe_color": 4},
}


def _default_for_tier(tier) -> dict:
    return TIER_DEFAULT_APPEARANCE.get(tier, DEFAULT_APPEARANCE)


def _target_snapshots(db, player_id: str | None):
    if player_id is not None:
        snap = db.collection("players").document(player_id).get()
        return [snap] if snap.exists else []
    return list(db.collection("players").stream())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without writing anything")
    parser.add_argument("--player-id", type=str, default=None, help="Sync only this player doc id (default: every players/ doc)")
    args = parser.parse_args()

    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()

    snapshots = _target_snapshots(db, args.player_id)
    if args.player_id is not None and not snapshots:
        print(f"players/{args.player_id}: no such doc")
        return

    updated = 0
    skipped = 0

    for snap in snapshots:
        fields = snap.to_dict() or {}
        existing_appearance = fields.get("appearance")
        if isinstance(existing_appearance, dict) and existing_appearance:
            skipped += 1
            continue

        tier = fields.get("tier")
        appearance = _default_for_tier(tier)
        name = f"{fields.get('fname', '?')} {fields.get('lname', '?')}"
        print(f"players/{snap.id} ({name}, tier={tier!r}): appearance -> {appearance}")
        updated += 1

        if not args.dry_run:
            snap.reference.set({"appearance": appearance}, merge=True)

    mode = "DRY RUN -- nothing written." if args.dry_run else "Done."
    print(f"\n{mode} {updated} updated, {skipped} already had an appearance.")


if __name__ == "__main__":
    main()
