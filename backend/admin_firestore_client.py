"""Server-side counterpart to mobile/scripts/autoload/Firestore.gd.

game_state.GameState only ever calls five async methods on whatever "client"
object it's handed (get_document, list_collection, set_document,
add_document, delete_document) plus a `.uid` attribute. On the Godot client
that object is Firestore.gd, authenticated as the signed-in user's own ID
token -- the CLIENT-TRUSTED path (see game_state.py's own module docstring).
Here it's this class instead, backed by the Admin SDK (a service account),
so GameState's exact same persistence logic can run as the authoritative
side behind the backend without being duplicated.

Four things here are NOT part of that five-method protocol and exist only
for the backend: `query_top` (leaderboards), `query_ids` (everything a user
owns, for account deletion), `delete_paths` (bulk deletion) and
`run_transaction` (anything that moves a balance). GameState never calls
any of them.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

from firebase_admin import firestore

# Taken straight from google-cloud-firestore rather than through
# firebase_admin's re-export of it. firebase-admin depends on that package, so
# it is always installed, and this is the import its own documentation uses --
# which makes it the one that can't stop resolving because a firebase-admin
# release changed what it re-exports.
from google.cloud import firestore as google_firestore


class TransactionScope:
    """The read/write surface available INSIDE a transaction.

    BY PATH ONLY. There is deliberately no list/query method: Firestore
    transactions lock everything they read, so listing a collection inside one
    locks every document in it. Gather the ids you need OUTSIDE the
    transaction and address them by path in here.

    Two rules the API enforces and this class cannot hide:

      1. EVERY READ BEFORE EVERY WRITE. get() raises the moment a write has
         been issued, rather than letting Firestore reject the whole
         transaction later with a message that doesn't say which read did it.
      2. THE BODY MAY RUN MORE THAN ONCE. On contention Firestore aborts and
         retries it, so it has to be a pure function of what it reads -- no
         counters, no appending to a list from an enclosing scope, no side
         effects other than the writes below.

    Writes are buffered by Firestore and applied on commit, so a get() after a
    set() would read the OLD value even if the ordering were allowed. Read
    everything, compute, then write.
    """

    def __init__(self, client: "AdminFirestoreClient", transaction):
        self._client = client
        self._transaction = transaction
        self._has_written = False
        self.uid = client.uid

    def _guard_read(self) -> None:
        if self._has_written:
            raise RuntimeError(
                "TransactionScope: every read must come before every write. "
                "Move this get()/get_all() above the first set()/delete()."
            )

    def get(self, path: str) -> dict | None:
        self._guard_read()
        snap = self._client._ref(path).get(transaction=self._transaction)
        return snap.to_dict() if snap.exists else None

    def get_all(self, paths: list[str]) -> dict[str, dict | None]:
        """Every path in ONE round trip, keyed by the path asked for.

        Settlement reads a group, its six entries and their six user documents;
        one round trip instead of thirteen is the difference between a
        comfortable transaction and one that keeps losing its retry race.
        """
        self._guard_read()
        if not paths:
            return {}
        refs = [self._client._ref(p) for p in paths]
        by_ref_path = {ref.path: p for ref, p in zip(refs, paths)}
        found: dict[str, dict | None] = {p: None for p in paths}
        for snap in self._client._db.get_all(refs, transaction=self._transaction):
            if snap.exists:
                found[by_ref_path[snap.reference.path]] = snap.to_dict()
        return found

    def set(self, path: str, data: dict, merge: bool = True) -> None:
        self._has_written = True
        self._transaction.set(self._client._ref(path), data, merge=merge)

    def delete(self, path: str) -> None:
        # Deleting a path that doesn't exist is a no-op, not an error.
        self._has_written = True
        self._transaction.delete(self._client._ref(path))


class AdminFirestoreClient:
    def __init__(self, uid: str):
        self.uid = uid
        self._db = firestore.client()

    def _ref(self, path: str):
        parts = path.strip("/").split("/")
        ref = self._db.collection(parts[0])
        for i, part in enumerate(parts[1:], start=1):
            ref = ref.document(part) if i % 2 == 1 else ref.collection(part)
        return ref

    async def get_document(self, path: str) -> dict | None:
        snap = await asyncio.to_thread(self._ref(path).get)
        return snap.to_dict() if snap.exists else None

    async def get_documents(self, paths: list[str]) -> dict[str, dict | None]:
        """Several docs in ONE round trip, keyed by the path asked for; None
        where a path doesn't exist. The non-transactional twin of
        TransactionScope.get_all -- for read-only fan-outs like "the owner
        of each card on this leaderboard page", where a transaction's locks
        would be pure cost."""
        if not paths:
            return {}
        refs = [self._ref(p) for p in paths]
        by_ref_path = {ref.path: p for ref, p in zip(refs, paths)}
        found: dict[str, dict | None] = {p: None for p in paths}
        for snap in await asyncio.to_thread(lambda: list(self._db.get_all(refs))):
            if snap.exists:
                found[by_ref_path[snap.reference.path]] = snap.to_dict()
        return found

    async def list_collection(self, path: str) -> list[dict]:
        docs = await asyncio.to_thread(lambda: list(self._ref(path).stream()))
        return [{"id": d.id, **(d.to_dict() or {})} for d in docs]

    async def set_document(self, path: str, data: dict, merge: bool = True) -> None:
        await asyncio.to_thread(self._ref(path).set, data, merge=merge)

    async def add_document(self, collection_path: str, data: dict, doc_id: str | None = None) -> str:
        coll_ref = self._ref(collection_path)
        if doc_id:
            await asyncio.to_thread(coll_ref.document(doc_id).set, data)
            return doc_id
        _, doc_ref = await asyncio.to_thread(coll_ref.add, data)
        return doc_ref.id

    async def delete_document(self, path: str) -> None:
        await asyncio.to_thread(self._ref(path).delete)

    async def run_transaction(self, body: Callable[[TransactionScope], Any]) -> Any:
        """Runs `body(scope)` atomically and returns whatever it returns.

        Everything the body reads is locked for the duration, so a concurrent
        transaction touching the same documents either waits or is retried.
        The classic read-then-write race -- two requests both seeing 500
        credits and both paying out -- cannot happen across the boundary.

        Raising from inside `body` rolls the whole thing back and propagates:
        nothing it wrote is applied. That is how an endpoint refuses
        (HTTPException) after a read it could only do transactionally, e.g.
        "that card is already gone".

        `body` is a PLAIN def, not async. It runs on a worker thread, because
        the SDK's transaction API is synchronous and the retry loop blocks --
        the same way every other method here bridges the blocking client into
        async. Every other function in this backend is async, so this is the
        one place the reflex is wrong; passing a coroutine function raises
        immediately rather than silently committing an empty transaction.

        See TransactionScope for the two rules the body has to follow.
        """
        if inspect.iscoroutinefunction(body):
            raise TypeError(
                "run_transaction body must be a plain def, not async def -- it "
                "runs on a worker thread and cannot be awaited. Do any awaiting "
                "before or after the transaction, never inside it."
            )

        def _run():
            @google_firestore.transactional
            def _txn(transaction):
                return body(TransactionScope(self, transaction))

            return _txn(self._db.transaction())

        return await asyncio.to_thread(_run)

    async def query_ids(self, collection: str, field: str, value) -> list[str]:
        """Ids of every doc in `collection` whose `field` equals `value`.

        A single-field equality filter, which Firestore auto-indexes, so
        like query_top this needs no composite index. Ids only: the callers
        (account deletion) address the docs by path afterwards and never
        need their contents.
        """
        query = self._db.collection(collection).where(filter=google_firestore.FieldFilter(field, "==", value))
        docs = await asyncio.to_thread(lambda: list(query.select(["__name__"]).stream()))
        return [d.id for d in docs]

    async def delete_paths(self, paths: list[str]) -> int:
        """Deletes every path, in write batches of at most 500 (Firestore's
        ceiling). Not atomic across batches, and doesn't need to be: the
        one caller (account deletion) is idempotent and re-runnable, so a
        batch that fails halfway leaves less to do next time, not a mess.
        Returns how many deletes were issued."""
        def _run() -> int:
            for start in range(0, len(paths), 500):
                batch = self._db.batch()
                for path in paths[start : start + 500]:
                    batch.delete(self._ref(path))
                batch.commit()
            return len(paths)

        return await asyncio.to_thread(_run)

    async def query_top(
        self,
        collection: str,
        order_by: str,
        limit: int,
        descending: bool = True,
        offset: int = 0,
        where: tuple[str, str, Any] | None = None,
    ) -> list[dict]:
        """Top `limit` docs in `collection` ordered by `order_by` (dotted paths
        into nested map fields, e.g. "statistics.goals", work directly),
        starting `offset` docs in. Firestore auto-indexes every field for a
        single order_by with no `where` clause, so on its own this needs no
        manually-defined composite index.

        `where` is one (field, op, value) filter -- "==" or "in" -- on top.
        A filter on one field ordered by another DOES need a composite
        index (see config.PLAYER_LEADERBOARD_STATS / firestore.indexes.json).

        Offset rather than a cursor because the leaderboard pages are
        numbered and small: Firestore bills the skipped documents as reads,
        which at ten a page and a handful of pages is nothing, and it lets
        the client jump to any page without holding a cursor.
        """
        direction = firestore.Query.DESCENDING if descending else firestore.Query.ASCENDING
        query = self._db.collection(collection)
        if where is not None:
            field, op, value = where
            query = query.where(filter=google_firestore.FieldFilter(field, op, value))
        query = query.order_by(order_by, direction=direction)
        if offset > 0:
            query = query.offset(offset)
        query = query.limit(limit)
        docs = await asyncio.to_thread(lambda: list(query.stream()))
        return [{"id": d.id, **(d.to_dict() or {})} for d in docs]
