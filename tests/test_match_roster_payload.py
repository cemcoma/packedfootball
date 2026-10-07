"""The match response's roster is what the client swaps into its squad afterwards."""

from __future__ import annotations

import pytest

from engine import generate_starter_roster
from services.match import run_match


def _profile(name: str, seed: int, with_ids: bool) -> dict:
    roster = generate_starter_roster("4-4-2", "gold", seed=seed)
    if with_ids:
        for i, card in enumerate(roster):
            card.player_id = f"{name}_{i}"
    return {"display_name": name, "formation": "4-4-2", "roster": roster}


@pytest.mark.slow
def test_the_callers_eleven_come_back_with_ids_and_this_match_counted():
    caller = _profile("me", 3, with_ids=True)
    result = run_match(caller, _profile("them", 4, with_ids=True), seed=11)

    mine, theirs = result["roster"][:11], result["roster"][11:]
    assert [p["player_id"] for p in mine] == [f"me_{i}" for i in range(11)]
    assert all(p["statistics"]["matches_played"] == 1 for p in mine)
    # Only the caller's cards are theirs to update; the opponent's ids stay server-side.
    assert all("player_id" not in p for p in theirs)
