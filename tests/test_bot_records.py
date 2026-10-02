"""A stored bot's doc picks up its side of every match: record and card stats."""

from __future__ import annotations

import asyncio

import pytest

from engine import RATED_MATCHES_FOR_AVERAGE, generate_starter_roster, player_to_fields
from services.match import bot_doc_after_match, bot_profile_from_doc, record_bot_result, run_match


def _bot_doc(**over) -> dict:
    roster = generate_starter_roster("4-4-2", "gold", seed=7)
    return {"display_name": "Bot", "formation": "4-4-2", "players": [player_to_fields(p) for p in roster], **over}


def _play(profile: dict, goals_by_index: dict[int, int]) -> None:
    """Stands in for run_match: every card plays, some score."""
    for index, card in enumerate(profile["roster"]):
        card.statistics["matches_played"] += 1
        card.statistics["goals"] += goals_by_index.get(index, 0)
        card.statistics["rating_sum"] += 7.0
        card.statistics["rating_count"] += 1


def test_the_bot_record_moves_with_the_result():
    doc = _bot_doc(wins=3, draws=1, losses=2)
    profile = bot_profile_from_doc("bot_x", doc)
    assert bot_doc_after_match(doc, profile, 2, 1)["wins"] == 4
    assert bot_doc_after_match(doc, profile, 1, 1)["draws"] == 2
    assert bot_doc_after_match(doc, profile, 0, 1)["losses"] == 3


def test_a_doc_with_no_record_yet_starts_from_zero():
    doc = _bot_doc()
    fields = bot_doc_after_match(doc, bot_profile_from_doc("bot_x", doc), 3, 0)
    assert (fields["wins"], fields["draws"], fields["losses"]) == (1, 0, 0)


def test_card_stats_are_written_back():
    doc = _bot_doc()
    profile = bot_profile_from_doc("bot_x", doc)
    _play(profile, {9: 2})
    players = bot_doc_after_match(doc, profile, 2, 0)["players"]
    assert players[9]["statistics"]["goals"] == 2
    assert all(p["statistics"]["matches_played"] == 1 for p in players)
    assert players[9]["fname"] == doc["players"][9]["fname"]


def test_an_overlapping_match_against_the_same_bot_still_counts():
    """Both matches loaded the bot at 0 goals; the second to finish must add
    to the first's write, not overwrite it."""
    doc = _bot_doc()
    profile = bot_profile_from_doc("bot_x", doc)
    _play(profile, {9: 1})
    doc["players"][9]["statistics"]["goals"] = 2  # the other match already landed
    doc["players"][9]["statistics"]["matches_played"] = 1
    stats = bot_doc_after_match(doc, profile, 1, 0)["players"][9]["statistics"]
    assert (stats["goals"], stats["matches_played"]) == (3, 2)


def test_avg_rating_appears_once_enough_matches_are_rated():
    doc = _bot_doc()
    for fields in doc["players"]:
        fields["statistics"].update(rating_sum=6.0 * (RATED_MATCHES_FOR_AVERAGE - 1), rating_count=RATED_MATCHES_FOR_AVERAGE - 1)
    profile = bot_profile_from_doc("bot_x", doc)
    _play(profile, {})
    stats = bot_doc_after_match(doc, profile, 0, 0)["players"][0]["statistics"]
    assert stats["rating_count"] == RATED_MATCHES_FOR_AVERAGE
    assert stats["avg_rating"] == round(stats["rating_sum"] / stats["rating_count"], 2)


def test_a_doc_whose_xi_changed_only_gets_the_record():
    doc = _bot_doc()
    profile = bot_profile_from_doc("bot_x", doc)
    fields = bot_doc_after_match({**doc, "players": doc["players"][:10]}, profile, 1, 0)
    assert "players" not in fields and fields["wins"] == 1


def test_a_throwaway_bot_writes_nothing():
    """No loaded_statistics means no bots/{id} doc; returning before any
    Firestore call is the whole test."""
    roster = generate_starter_roster("4-4-2", "gold", seed=7)
    asyncio.run(record_bot_result("bot_throwaway", {"roster": roster}, 1, 0))


@pytest.mark.slow
def test_a_real_match_writes_back_what_the_response_shows():
    doc = _bot_doc(wins=5)
    bot = bot_profile_from_doc("bot_x", doc)
    caller = {"display_name": "Me", "formation": "4-3-3", "roster": generate_starter_roster("4-3-3", "gold", seed=3)}
    result = run_match(caller, bot, seed=11)
    my_score, bot_score = result["score"]
    fields = bot_doc_after_match(doc, bot, bot_score, my_score)
    assert [p["statistics"] for p in fields["players"]] == [p["statistics"] for p in result["roster"][11:]]
    assert fields["wins"] + fields["draws"] + fields["losses"] == 6
