"""seed_bots.backfill_tactics: every stored bot ends up with a valid play style."""

from __future__ import annotations

import random

from game_config import TACTICS
from scripts.seed_bots import backfill_tactics


class _Ref:
    def __init__(self, store: dict, doc_id: str):
        self.store, self.id = store, doc_id


class _Snap:
    def __init__(self, ref: _Ref):
        self.reference = ref

    def to_dict(self):
        return dict(self.reference.store[self.reference.id])


class _Batch:
    def __init__(self, db: "_FakeDb"):
        self.db, self.writes = db, []

    def set(self, ref: _Ref, data: dict, merge: bool = False):
        assert merge, "a backfill must never replace the bot's doc"
        self.writes.append((ref, data))

    def commit(self):
        assert len(self.writes) <= 500
        self.db.commits += 1
        for ref, data in self.writes:
            ref.store[ref.id].update(data)


class _FakeDb:
    def __init__(self, bots: dict):
        self.bots, self.commits = bots, 0

    def collection(self, name: str):
        assert name == "bots"
        return self

    def stream(self):
        return [_Snap(_Ref(self.bots, doc_id)) for doc_id in self.bots]

    def batch(self):
        return _Batch(self)


def _bots() -> dict:
    return {
        "bot_none": {"display_name": "A", "formation": "4-4-2"},
        "bot_unknown": {"display_name": "B", "tactics": {"style": "tiki_taka"}},
        "bot_junk": {"display_name": "C", "tactics": "possession"},
        "bot_set": {"display_name": "D", "tactics": {"style": "long_ball"}},
    }


def test_bots_without_a_valid_style_get_a_random_one_and_keep_everything_else():
    db = _FakeDb(_bots())
    assert backfill_tactics(db, random.Random(1), dry_run=False) == 3
    for bot in db.bots.values():
        assert bot["tactics"]["style"] in TACTICS
    assert db.bots["bot_none"]["formation"] == "4-4-2"
    assert db.bots["bot_set"]["tactics"] == {"style": "long_ball"}  # never rerolled
    assert backfill_tactics(db, random.Random(1), dry_run=False) == 0  # idempotent


def test_dry_run_writes_nothing():
    db = _FakeDb(_bots())
    assert backfill_tactics(db, random.Random(1), dry_run=True) == 3
    assert db.commits == 0
    assert "tactics" not in db.bots["bot_none"]


def test_styles_are_spread_and_batches_stay_under_the_firestore_ceiling():
    db = _FakeDb({f"bot_{i}": {} for i in range(1200)})
    backfill_tactics(db, random.Random(3), dry_run=False)
    assert db.commits == 3
    assert {bot["tactics"]["style"] for bot in db.bots.values()} == set(TACTICS)
