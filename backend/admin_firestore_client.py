"""Server-side counterpart to packedfootball/firebase_client.py.

game_state.GameState only ever calls five async methods on whatever "client"
object it's handed (get_document, list_collection, set_document,
add_document, delete_document) plus a `.uid` attribute. On the game client
that object is firebase_client.FirebaseClient, authenticated as the signed-in
user's own ID token -- the CLIENT-TRUSTED path. Here it's this class instead,
backed by the Admin SDK (a service account), so GameState's exact same
persistence logic can run as the authoritative side behind the backend
without being duplicated.
"""

from __future__ import annotations

import asyncio

from firebase_admin import firestore


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
