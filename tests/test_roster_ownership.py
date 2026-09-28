"""The backend's squad is read from ids the client can write, so what it loads
must be limited to cards the account actually owns."""

from __future__ import annotations

import asyncio

from game_state import GameState, player_to_fields
from packEngine import PACK_DATABASE, PLAYER_CLASS_MAP, Midfielder, PackManager


class _FakeClient:
    def __init__(self, uid: str, docs: dict):
        self.uid = uid
        self._docs = docs

    async def get_document(self, path: str):
        return self._docs.get(path)


def _card_doc(owner: str, seed: int) -> dict:
    card = PackManager(PACK_DATABASE, seed=seed).open_pack("standard_gold")[0]
    return {**player_to_fields(card), "owner_uid": owner}


def _state(docs: dict) -> GameState:
    return GameState(_FakeClient("me", docs), PLAYER_CLASS_MAP, Midfielder)


def test_a_card_owned_by_someone_else_is_not_loaded():
    docs = {"players/mine": _card_doc("me", 1), "players/theirs": _card_doc("rival", 2)}
    loaded = asyncio.run(_state(docs).load_players(["mine", "theirs"]))
    assert [p.player_id for p in loaded] == ["mine"]


def test_the_same_card_listed_twice_loads_once():
    docs = {"players/mine": _card_doc("me", 1)}
    loaded = asyncio.run(_state(docs).load_players(["mine"] * 11))
    assert [p.player_id for p in loaded] == ["mine"]
