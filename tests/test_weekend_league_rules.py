"""The weekend league and the trophy counter: the Friday-to-Sunday window,
the one global table, the snapshot pages, and who gets a trophy.

Ranking and the verdict rules are the shared ones (test_tournament_rules.py);
this file tests what the weekend league configures differently, plus the
trophy helpers every format's settlement now goes through.

Pure functions only. No Firestore, no clock.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import config
from services import tournament as t

WE = t.WEEKEND
W = t.WEEKLY
D = t.DAILY
ISTANBUL = timezone(timedelta(hours=3))
PERIOD = "2026-10-11"  # Sunday 18:00 Istanbul -> Sunday 18 Oct 18:00
FLOOR = WE.promotion_floor


def fake_increment(n):
    return ("inc", n)


def entry(uid, points=0, played=30, gf=0, ga=0):
    return {"uid": uid, "display_name": uid, "points": points, "played": played,
            "goals_for": gf, "goals_against": ga, "wins": points // 3,
            "joined_at_iso": "2026-10-16T15:00:00+00:00"}


def outcomes(entries):
    return {r["uid"]: r["outcome"] for r in t.snapshot_rows(entries, WE)}


# ------------------------------------------------------------------ the window


def test_the_period_ends_sunday_at_18_istanbul():
    end = t.period_end(PERIOD, WE).astimezone(ISTANBUL)
    assert end.weekday() == 6 and end.hour == 18 and end.minute == 0
    assert date.fromisoformat(config.WEEKEND_LEAGUE_PERIOD_ANCHOR).weekday() == 6


def test_every_period_id_is_a_sunday():
    for moment in (datetime(2026, 10, 14, tzinfo=timezone.utc), datetime(2025, 3, 1, tzinfo=timezone.utc)):
        assert date.fromisoformat(t.period_id_for(moment, WE)).weekday() == 6


def test_play_opens_friday_at_18_istanbul():
    opens = datetime(2026, 10, 16, 18, tzinfo=ISTANBUL)
    assert not t.is_open(PERIOD, opens - timedelta(seconds=1), WE)
    assert t.opens_in(PERIOD, opens - timedelta(seconds=1), WE) == 1
    assert t.is_open(PERIOD, opens, WE)
    assert t.opens_in(PERIOD, opens, WE) == 0


def test_the_window_stays_open_to_the_last_second():
    end = t.period_end(PERIOD, WE)
    assert t.is_open(PERIOD, end - timedelta(seconds=1), WE)
    # One second later it's the next period, which is closed until Friday.
    nxt = t.period_id_for(end, WE)
    assert nxt == "2026-10-18" and not t.is_open(nxt, end, WE)


def test_daily_and_weekly_are_always_open():
    now = datetime(2026, 10, 13, 3, tzinfo=timezone.utc)
    for mode in (D, W):
        assert t.opens_in(t.period_id_for(now, mode), now, mode) == 0


def test_a_monday_waits_until_friday():
    monday = datetime(2026, 10, 12, 18, tzinfo=ISTANBUL)
    assert t.opens_in(PERIOD, monday, WE) == 4 * 24 * 3600


# ------------------------------------------------------------- the global table


def test_first_on_the_floor_wins_the_league():
    got = outcomes([entry("a", FLOOR + 9), entry("b", FLOOR + 3), entry("c", 3)])
    assert got == {"a": "promote", "b": "stay", "c": "stay"}


def test_first_below_the_floor_wins_nothing():
    assert outcomes([entry("a", FLOOR - 1), entry("b", 3), entry("c", 0)])["a"] == "stay"


def test_two_players_cannot_win_it():
    assert outcomes([entry("a", FLOOR + 30), entry("b", 0)])["a"] == "stay"


def test_nobody_is_relegated_and_the_winner_is_clamped():
    rows = t.snapshot_rows([entry(f"p{i}", 90 - i * 3) for i in range(30)], WE)
    assert {r["outcome"] for r in rows} == {"promote", "stay"}
    winner = rows[0]
    assert winner["to_tier"] == winner["from_tier"] == WE.top_tier and winner["tier_clamped"]


def test_placement_rewards_follow_position_across_a_big_table():
    rows = t.snapshot_rows([entry(f"p{i:03d}", 300 - i) for i in range(150)], WE)
    assert rows[0]["rewards"] == config.WEEKEND_LEAGUE_TIERS[1]["rewards"][1]
    assert rows[9]["rewards"] == config.WEEKEND_LEAGUE_TIERS[1]["rewards"][10]
    assert rows[10]["rewards"] == {}


def test_the_weekend_league_settles_as_global():
    assert t.settlement_mode(5000, WE) == "global"
    assert t.settlement_mode(6, D) == "positional"


def test_pages_slice_out_of_their_chunk():
    chunk_size, page_size = config.WEEKEND_LEAGUE_STANDINGS_CHUNK, config.LEADERBOARD_PAGE_SIZE
    chunk1 = [{"position": p} for p in range(chunk_size + 1, 2 * chunk_size + 1)]
    page = (chunk_size // page_size) + 2  # third page of the second chunk
    got = t.page_slice(chunk1, page, page_size, chunk_size)
    assert [r["position"] for r in got] == list(range(page * page_size + 1, page * page_size + page_size + 1))


def test_page_of_a_position():
    assert t.page_of(1, 10) == 0
    assert t.page_of(10, 10) == 0
    assert t.page_of(11, 10) == 1


def test_the_weekend_league_has_its_own_collection_and_slot():
    assert len({D.collection, W.collection, WE.collection}) == 3
    fields = t.enter_fields(PERIOD, t.GLOBAL_GROUP, WE)
    assert list(fields[t.ENTRIES_FIELD]) == ["weekend"]
    assert t.mode_for("weekend") is WE


def test_the_fallback_bot_is_gold():
    """Stored bots of every tier fill the pool; only the throwaway one rolls gold."""
    assert WE.top_tier == WE.bottom_tier == 1
    assert t.bot_card_rates(1, WE) is config.TOURNAMENT_TIERS[1]["bot_card_rates"]


# --------------------------------------------------------------------- trophies


def row(position, outcome, from_tier=2, to_tier=None, rewards=None):
    return {"uid": "u", "position": position, "outcome": outcome, "from_tier": from_tier,
            "to_tier": from_tier - 1 if to_tier is None and outcome == "promote" else (to_tier or from_tier),
            "rewards": rewards or {}}


def test_only_first_with_a_promote_verdict_wins_a_trophy():
    assert t.wins_trophy(row(1, "promote"))
    assert not t.wins_trophy(row(2, "promote"))  # daily's 2nd also goes up, but isn't 1st
    assert not t.wins_trophy(row(1, "stay"))     # 1st under the floor


def test_trophy_fields_count_up_by_mode_and_tier():
    got = t.trophy_fields(row(1, "promote", from_tier=3), "2026-10-10", D, fake_increment)
    slot = got[t.TROPHIES_FIELD]["daily"]["3"]
    assert slot["count"] == ("inc", 1)
    assert slot["last"] == t.period_end("2026-10-10", D).isoformat()
    assert t.trophy_fields(row(2, "promote"), "2026-10-10", D, fake_increment) == {}


def test_member_settlement_carries_tier_rewards_and_trophy_together():
    r = row(1, "promote", from_tier=1, to_tier=1, rewards={"bucks": 40, "medals": 0})
    user_fields, entry_fields = t.member_settlement(r, PERIOD, t.GLOBAL_GROUP, WE, fake_increment)
    assert user_fields["bucks"] == ("inc", 40)
    assert "medals" not in user_fields  # zero amounts aren't written
    assert user_fields[t.TIERS_FIELD] == {"weekend": 1}
    assert user_fields[t.ENTRIES_FIELD] == {"weekend": None}
    assert user_fields[t.TROPHIES_FIELD]["weekend"]["1"]["count"] == ("inc", 1)
    assert entry_fields["settled"] and entry_fields["final_position"] == 1


def test_member_settlement_without_a_trophy_writes_none():
    user_fields, _ = t.member_settlement(row(4, "stay"), "2026-10-10", "t2-g0000", D, fake_increment)
    assert t.TROPHIES_FIELD not in user_fields


def test_the_cabinet_is_weekend_then_weekly_then_daily_top_tier_first():
    doc = {t.TROPHIES_FIELD: {
        "daily": {"3": {"count": 4, "last": "a"}, "1": {"count": 1, "last": "b"}},
        "weekly": {"2": {"count": 2, "last": "c"}},
        "weekend": {"1": {"count": 1, "last": "d"}},
    }}
    got = [(x["mode"], x["tier"]) for x in t.trophy_list(doc)]
    assert got == [("weekend", 1), ("weekly", 2), ("daily", 1), ("daily", 3)]
    first = t.trophy_list(doc)[0]
    assert first["kind"] == "champion" and first["mode_name"] == "Weekend League"
    assert t.trophy_list(doc)[1]["kind"] == "promotion"


def test_an_empty_or_odd_cabinet_reads_as_empty():
    assert t.trophy_list(None) == []
    assert t.trophy_list({t.TROPHIES_FIELD: "nope"}) == []
    assert t.trophy_list({t.TROPHIES_FIELD: {"daily": {"9": {"count": 3}}, "weekly": {"1": {"count": 0}}}}) == []
