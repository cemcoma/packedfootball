"""Renames position strings on stored cards after a position key was split
in packedfootball/game_config.py -- the WB -> LWB / RWB split.

A card stores the literal position it was rolled with, and a match is
refused when a card's position can't fill its formation slot (see
services.match.validate_formation_positions). After the split a 3-5-2 side
built around two "WB" cards can't play at all: "WB" is neither of the new
slot roles nor similar to them. This walks every card still carrying an
old position and picks its new one from where the card stands:

  - a card in a saved XI takes the flank of its slot -- the LWB/RWB slot
    it occupies, or failing that the side of the slot (an LB/LM/LW slot
    -> LWB, an RB/RM/RW slot -> RWB);
  - a benched card is split evenly by a hash of its id, so packs already
    opened end up with wing-backs on both sides.

Two collections carry cards: players/{id} (real managers' cards, with the
XI order on users/{uid}.roster_player_ids) and bots/{id} (the seeder's XIs,
embedded in slot order). games/{id} team snapshots carry positions too,
but they are the record of what was played and are left alone -- replaying
a pre-split 3-5-2 game therefore no longer reproduces it exactly.

Safe to re-run: a second pass finds nothing.

Usage:
    python3 backend/scripts/rename_positions.py [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import firestore
from google.cloud.firestore_v1 import FieldFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "packedfootball"))
from game_config import FORMATIONS  # noqa: E402

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")

# old position -> (left-side name, right-side name). Extend when a position
# is split again; a split that is already fully applied matches zero docs.
RENAMES = {
    "WB": ("LWB", "RWB"),
}


def _flank_of_role(role: str, pair: tuple[str, str]) -> str | None:
    """The new name a card in a `role` slot should take: the slot's own name
    when the slot IS one of the pair, else the side the slot is on, else None."""
    if role in pair:
        return role
    if role.startswith("L"):
        return pair[0]
    if role.startswith("R"):
        return pair[1]
    return None


def _flank_of_id(doc_id: str, pair: tuple[str, str]) -> str:
    """An even, stable split for cards that stand in no slot."""
    return pair[int(hashlib.sha1(doc_id.encode()).hexdigest(), 16) % 2]


def _slot_roles_by_card(db, owner_uids: set[str]) -> dict[str, str]:
    """player_id -> the role of the XI slot it is saved in, for every owner
    given. One get_all per hundred owners."""
    roles: dict[str, str] = {}
    uids = sorted(owner_uids)
    for start in range(0, len(uids), 100):
        refs = [db.document(f"users/{uid}") for uid in uids[start : start + 100]]
        for snap in db.get_all(refs):
            if not snap.exists:
                continue
            doc = snap.to_dict() or {}
            slots = FORMATIONS.get(doc.get("formation"))
            if not slots:
                continue
            for i, player_id in enumerate(doc.get("roster_player_ids") or []):
                if i in slots and player_id:
                    roles[player_id] = slots[i]["role"]
    return roles


def rename_player_cards(db, dry_run: bool) -> int:
    total = 0
    for old, pair in RENAMES.items():
        docs = list(db.collection("players").where(filter=FieldFilter("position", "==", old)).stream())
        print(f"players/: {old} -> {'/'.join(pair)}: {len(docs)} card(s)")
        total += len(docs)
        if not docs:
            continue
        slot_roles = _slot_roles_by_card(db, {(d.to_dict() or {}).get("owner_uid") for d in docs} - {None})
        updates = []
        for doc in docs:
            new = _flank_of_role(slot_roles.get(doc.id, ""), pair) or _flank_of_id(doc.id, pair)
            where = f"in XI as {slot_roles[doc.id]}" if doc.id in slot_roles else "benched"
            print(f"  {doc.id}  {old} -> {new}  ({where})")
            updates.append((doc.reference, new))
        if dry_run:
            continue
        for start in range(0, len(updates), 500):
            batch = db.batch()
            for ref, new in updates[start : start + 500]:
                batch.update(ref, {"position": new})
            batch.commit()
    return total


def rename_bot_cards(db, dry_run: bool) -> int:
    """The seeder embeds each bot's XI in slot order, so the slot's role
    decides directly."""
    changed_cards = 0
    batch = db.batch()
    pending = 0
    for snap in db.collection("bots").stream():
        doc = snap.to_dict() or {}
        players = list(doc.get("players") or [])
        slots = FORMATIONS.get(doc.get("formation"), {})
        touched = False
        for i, fields in enumerate(players):
            pair = RENAMES.get(fields.get("position"))
            if pair is None:
                continue
            role = slots[i]["role"] if i in slots else ""
            new = _flank_of_role(role, pair) or _flank_of_id(f"{snap.id}:{i}", pair)
            print(f"  bots/{snap.id} slot {i} ({role or 'no slot'}): {fields['position']} -> {new}")
            fields["position"] = new
            touched = True
            changed_cards += 1
        if touched and not dry_run:
            batch.update(snap.reference, {"players": players})
            pending += 1
            if pending == 500:
                batch.commit()
                batch = db.batch()
                pending = 0
    if pending:
        batch.commit()
    print(f"bots/: {changed_cards} embedded card(s)")
    return changed_cards


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, write nothing")
    args = parser.parse_args()

    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()

    total = rename_player_cards(db, args.dry_run) + rename_bot_cards(db, args.dry_run)
    print(f"{total} card(s) {'would be' if args.dry_run else ''} renamed.".replace("  ", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
