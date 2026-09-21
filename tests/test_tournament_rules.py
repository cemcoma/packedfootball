"""Tournament standings, promotion and rewards.

These rules need tests rather than observation, because of a cold-start
quirk: everyone starts in the bottom tier, so at launch almost every group is
short-handed and the THRESHOLD path is the one that runs. The positional rule
-- the one actually designed -- will barely execute in production for weeks.
This file is where it gets exercised.

Everything here is a pure function of its arguments. No Firestore, no clock.
"""

from __future__ import annotations

from datetime import timedelta, timezone

import pytest

import config
from services import tournament as t

CAP = config.TOURNAMENT_GROUP_CAPACITY
FLOOR = config.TOURNAMENT_PROMOTION_FLOOR
DROP = config.TOURNAMENT_RELEGATION_FLOOR
MIN_GROUP = config.TOURNAMENT_MIN_GROUP_FOR_PROMOTION


def entry(uid, points=0, played=10, gf=0, ga=0, wins=0, joined="2026-09-15T08:00:00+00:00"):
    return {
        "uid": uid,
        "display_name": uid.title(),
        "points": points,
        "played": played,
        "goals_for": gf,
        "goals_against": ga,
        "wins": wins,
        "joined_at_iso": joined,
    }


def outcomes(entries, tier=2, group_size=None):
    rows = t.apply_rules(t.rank_rows(entries), tier, group_size=group_size)
    return {r["uid"]: r["outcome"] for r in rows}


# ------------------------------------------------------------------ ranking


def test_ranks_by_points_first():
    rows = t.rank_rows([entry("a", 10), entry("b", 22), entry("c", 16)])
    assert [r["uid"] for r in rows] == ["b", "c", "a"]
    assert [r["position"] for r in rows] == [1, 2, 3]


def test_goal_difference_breaks_a_points_tie():
    rows = t.rank_rows([entry("a", 15, gf=10, ga=9), entry("b", 15, gf=10, ga=2)])
    assert [r["uid"] for r in rows] == ["b", "a"]


def test_goals_for_breaks_a_goal_difference_tie():
    rows = t.rank_rows([entry("a", 15, gf=4, ga=2), entry("b", 15, gf=9, ga=7)])
    assert [r["uid"] for r in rows] == ["b", "a"]


def test_wins_break_a_goals_tie():
    rows = t.rank_rows([entry("a", 15, gf=5, ga=5, wins=3), entry("b", 15, gf=5, ga=5, wins=5)])
    assert [r["uid"] for r in rows] == ["b", "a"]


def test_join_time_breaks_an_otherwise_exact_tie():
    early = entry("a", 15, joined="2026-09-15T06:00:00+00:00")
    late = entry("b", 15, joined="2026-09-15T20:00:00+00:00")
    assert [r["uid"] for r in t.rank_rows([late, early])] == ["a", "b"]


def test_ordering_is_total_and_deterministic():
    """A transaction body can be RETRIED. Two runs that ordered identical
    records differently would promote different people."""
    same = [entry(u, 15) for u in ("c", "a", "b")]
    first = [r["uid"] for r in t.rank_rows(same)]
    second = [r["uid"] for r in t.rank_rows(list(reversed(same)))]
    assert first == second == ["a", "b", "c"]


def test_goal_diff_is_derived_not_required_on_input():
    rows = t.rank_rows([entry("a", 3, gf=7, ga=2)])
    assert rows[0]["goal_diff"] == 5


def test_ranking_does_not_mutate_its_input():
    original = entry("a", 5)
    t.rank_rows([original])
    assert "position" not in original and "goal_diff" not in original


# ------------------------------------------- full group: position beats points


def full_group(points):
    return [entry(f"p{i}", pts, gf=pts) for i, pts in enumerate(points)]


def test_full_group_promotes_the_top_two():
    got = outcomes(full_group([30, 28, 26, 14, 11, 6]))
    assert got["p0"] == "promote" and got["p1"] == "promote"


def test_full_group_relegates_the_bottom_two():
    got = outcomes(full_group([30, 28, 26, 14, 11, 6]))
    assert got["p4"] == "relegate" and got["p5"] == "relegate"


def test_full_group_middle_stays():
    got = outcomes(full_group([30, 28, 26, 14, 11, 6]))
    assert got["p2"] == "stay" and got["p3"] == "stay"


def test_third_place_above_the_floor_does_not_promote():
    """Position beats points. A 3rd place on 22 stays even though a short
    group would have promoted the same score."""
    got = outcomes(full_group([30, 28, 22, 14, 11, 6]))
    assert got["p2"] == "stay"


def test_fourth_place_below_the_relegation_floor_does_not_relegate():
    """Position protects. 9 points is under the floor, but 4th is a safe
    position in a full group."""
    got = outcomes(full_group([30, 28, 26, 9, 8, 6]))
    assert got["p3"] == "stay"


def test_top_two_still_need_the_floor():
    """A weak group cannot promote someone on 12 points just for winning it."""
    got = outcomes(full_group([12, 11, 9, 8, 7, 6]))
    assert got["p0"] == "stay" and got["p1"] == "stay"


def test_fifth_place_relegates_even_on_a_huge_score():
    got = outcomes(full_group([30, 29, 28, 27, 26, 25]))
    assert got["p4"] == "relegate" and got["p5"] == "relegate"


# -------------------------------------------------- short group: thresholds


def test_short_group_promotes_on_the_floor():
    got = outcomes([entry("a", FLOOR), entry("b", FLOOR - 1), entry("c", DROP)])
    assert got["a"] == "promote"
    assert got["b"] == "stay"


def test_short_group_relegates_below_the_floor():
    got = outcomes([entry("a", FLOOR), entry("b", 15), entry("c", DROP - 1)])
    assert got["c"] == "relegate"


def test_short_group_can_promote_more_than_two():
    """Everyone on or over the floor goes up when the group is short --
    three of them here -- and the one just under it stays."""
    got = outcomes([entry("a", FLOOR + 6), entry("b", FLOOR + 3), entry("c", FLOOR), entry("d", FLOOR - 1)])
    assert [got[u] for u in ("a", "b", "c")] == ["promote"] * 3
    assert got["d"] == "stay"


def test_exactly_at_the_relegation_floor_stays():
    got = outcomes([entry("a", 25), entry("b", 21), entry("c", DROP)])
    assert got["c"] == "stay"


# --------------------------------------- solo groups cannot promote anybody


def test_a_solo_group_cannot_promote():
    """The launch-day failure mode. One player, seven wins, no competition --
    without this guard the whole population reaches the top tier in a week."""
    assert outcomes([entry("a", 21)])["a"] == "stay"


def test_a_group_below_the_minimum_cannot_promote():
    small = [entry(f"p{i}", 30) for i in range(MIN_GROUP - 1)]
    assert all(v == "stay" for v in outcomes(small).values())


def test_a_group_at_the_minimum_can_promote():
    ok = [entry(f"p{i}", 30 - i) for i in range(MIN_GROUP)]
    assert outcomes(ok)["p0"] == "promote"


def test_a_solo_group_can_still_relegate():
    """Only promotion needs competition. Playing badly on your own is still
    playing badly."""
    assert outcomes([entry("a", 3)])["a"] == "relegate"


# ------------------------------------------------------------- tier edges


def test_top_tier_cannot_promote_but_records_the_verdict():
    rows = t.apply_rules(t.rank_rows(full_group([30, 28, 26, 14, 11, 6])), config.TOURNAMENT_TOP_TIER)
    winner = rows[0]
    assert winner["outcome"] == "promote"       # the rule's verdict
    assert winner["to_tier"] == config.TOURNAMENT_TOP_TIER   # the clamped effect
    assert winner["tier_clamped"] is True


def test_bottom_tier_cannot_relegate():
    rows = t.apply_rules(
        t.rank_rows(full_group([30, 28, 26, 14, 11, 6])), config.TOURNAMENT_BOTTOM_TIER
    )
    last = rows[-1]
    assert last["outcome"] == "relegate"
    assert last["to_tier"] == config.TOURNAMENT_BOTTOM_TIER
    assert last["tier_clamped"] is True


def test_middle_tier_moves_in_both_directions():
    rows = t.apply_rules(t.rank_rows(full_group([30, 28, 26, 14, 11, 6])), 2)
    assert rows[0]["to_tier"] == 1
    assert rows[-1]["to_tier"] == 3
    assert rows[0]["tier_clamped"] is False


# ---------------------------------------------------------------- no-shows


def test_a_no_show_ranks_last_and_relegates():
    got = outcomes(full_group([30, 28, 26, 14, 11]) + [entry("ghost", 0, played=0)])
    assert got["ghost"] == "relegate"


def test_a_no_show_earns_nothing_even_if_it_somehow_places():
    rows = t.apply_rules(t.rank_rows([entry("ghost", 0, played=0)]), 3)
    assert rows[0]["rewards"] == {}


# ----------------------------------------------------------------- rewards


def test_winner_of_a_real_group_collects():
    rows = t.apply_rules(t.rank_rows(full_group([30, 28, 26, 14, 11, 6])), 3)
    assert rows[0]["rewards"] == t.rewards_table(3)[1]


def test_placement_pays_by_position_not_by_promotion():
    """Finishing 2nd on 15 points in a weak group doesn't promote -- but it
    still finished 2nd, and 2nd is what the table pays for."""
    rows = t.apply_rules(t.rank_rows(full_group([FLOOR - 1, 15, 12, 10, 8, 4])), 3)
    assert rows[0]["outcome"] == "stay"
    assert rows[0]["rewards"] == t.rewards_table(3)[1]
    assert rows[1]["rewards"] == t.rewards_table(3)[2]


def test_top_tier_winner_collects_despite_the_clamp():
    rows = t.apply_rules(t.rank_rows(full_group([30, 28, 26, 14, 11, 6])), config.TOURNAMENT_TOP_TIER)
    assert rows[0]["to_tier"] == rows[0]["from_tier"]     # went nowhere
    assert rows[0]["rewards"] == t.rewards_table(config.TOURNAMENT_TOP_TIER)[1]  # paid anyway


def test_every_position_in_a_full_group_is_paid():
    """Down to last place: a bad day still pays credits."""
    for tier in config.TOURNAMENT_TIERS:
        rows = t.apply_rules(t.rank_rows(full_group([30, 28, 26, 14, 11, 6])), tier)
        for row in rows:
            assert row["rewards"].get("credits", 0) > 0, (tier, row["position"])


def test_placement_credits_fall_with_position():
    for tier in config.TOURNAMENT_TIERS:
        table = t.rewards_table(tier)
        credits = [table[pos]["credits"] for pos in sorted(table)]
        assert credits == sorted(credits, reverse=True), tier


def test_bottom_tier_pays_no_bucks_anywhere():
    for payout in t.rewards_table(config.TOURNAMENT_BOTTOM_TIER).values():
        assert payout.get("bucks", 0) == 0


def test_bucks_exist_only_on_the_top_tier_podium():
    for tier in config.TOURNAMENT_TIERS:
        for position, payout in t.rewards_table(tier).items():
            if payout.get("bucks", 0):
                assert tier == config.TOURNAMENT_TOP_TIER
                assert position in config.TOURNAMENT_PROMOTE_POSITIONS


def test_a_position_missing_from_the_table_pays_nothing():
    rows = t.apply_rules(t.rank_rows(full_group([30, 28, 26, 14, 11, 6])), 99)  # no such tier
    assert all(r["rewards"] == {} for r in rows)


def test_rewards_are_copies_not_the_config_table():
    """Settlement must never be able to mutate the config it read from."""
    rows = t.apply_rules(t.rank_rows(full_group([30, 28, 26, 14, 11, 6])), 3)
    rows[0]["rewards"]["medals"] = 999
    assert config.TOURNAMENT_TIERS[3]["rewards"][1]["medals"] != 999


# ------------------------------------------------------------- match results


@pytest.mark.parametrize(
    "mine,theirs,expected,points",
    [(3, 1, "win", 3), (2, 2, "draw", 1), (0, 4, "loss", 0)],
)
def test_result_fields_score_correctly(mine, theirs, expected, points):
    fields, earned, outcome = t.result_fields({}, mine, theirs, "g1")
    assert outcome == expected and earned == points
    assert fields["points"] == points
    assert fields["goals_for"] == mine and fields["goals_against"] == theirs


def test_result_fields_accumulate():
    fields, _, _ = t.result_fields(
        {"points": 6, "wins": 2, "goals_for": 5, "game_ids": ["a"]}, 2, 0, "b"
    )
    assert fields["points"] == 9 and fields["wins"] == 3
    assert fields["goals_for"] == 7 and fields["game_ids"] == ["a", "b"]


# ----------------------------------------------------------------- day keys


def test_a_day_is_exactly_24_hours():
    assert t.period_end("2026-09-15") - t.period_start("2026-09-15") == timedelta(days=1)


def test_the_day_rolls_over_at_the_configured_offset():
    """The boundary is wherever config says, not midnight UTC.

    Derived from TOURNAMENT_DAY_OFFSET_HOURS rather than hardcoded, so
    changing the reset hour is a config edit and not a test rewrite -- which
    is the whole reason that constant exists.
    """
    start = t.period_start("2026-09-15")
    assert start.hour == config.TOURNAMENT_DAY_OFFSET_HOURS % 24
    # A moment inside the day belongs to it; a moment before belongs to the
    # previous one.
    assert t.period_id_for(start) == "2026-09-15"
    assert t.period_id_for(start + timedelta(hours=23, minutes=59)) == "2026-09-15"
    assert t.period_id_for(start - timedelta(seconds=1)) == "2026-09-14"
    assert t.period_id_for(start + timedelta(days=1)) == "2026-09-16"


def test_the_reset_lands_at_noon_in_istanbul():
    """Turkey is UTC+3 all year, so the configured offset should put the
    rollover at 12:00 local. If this fails, the reset has drifted off noon."""
    istanbul = timezone(timedelta(hours=3))
    assert t.period_start("2026-09-15").astimezone(istanbul).hour == 12


def test_previous_period_ids_are_oldest_first():
    assert t.previous_period_ids("2026-09-15", 3) == ["2026-09-12", "2026-09-13", "2026-09-14"]


def test_joining_closes_in_the_final_hour():
    end = t.period_end("2026-09-15")
    cutoff = timedelta(seconds=config.TOURNAMENT_JOIN_CUTOFF_SECONDS)
    assert t.joining_is_closed("2026-09-15", end - cutoff + timedelta(seconds=1))
    assert not t.joining_is_closed("2026-09-15", end - cutoff - timedelta(seconds=1))


def test_seconds_remaining_never_goes_negative():
    assert t.seconds_remaining("2026-09-15", t.period_end("2026-09-15") + timedelta(hours=5)) == 0


def test_group_ids_sort_lexically_in_numeric_order():
    ids = [t.group_id_for(2, i) for i in (0, 1, 9, 10, 11)]
    assert ids == sorted(ids)


def tiers(**by_format):
    return {t.TIERS_FIELD: dict(by_format)}


def test_tier_defaults_to_the_bottom_and_clamps():
    assert t.tier_of(None) == config.TOURNAMENT_BOTTOM_TIER
    assert t.tier_of({}) == config.TOURNAMENT_BOTTOM_TIER
    assert t.tier_of({t.TIERS_FIELD: "not a map"}) == config.TOURNAMENT_BOTTOM_TIER
    assert t.tier_of(tiers(daily=99)) == config.TOURNAMENT_BOTTOM_TIER
    assert t.tier_of(tiers(daily=-5)) == config.TOURNAMENT_TOP_TIER
    assert t.tier_of(tiers(daily=True)) == config.TOURNAMENT_BOTTOM_TIER


def test_settlement_mode_names_the_path_taken():
    assert t.settlement_mode(CAP) == "positional"
    assert t.settlement_mode(CAP - 1) == "threshold"


# ---------------------------------------------------------- full-day reward


def test_full_day_is_not_claimable_until_every_match_is_played():
    state = t.full_period_state({"played": config.TOURNAMENT_MATCHES_PER_DAY - 1})
    assert state["claimable"] is False
    assert state["claimed"] is False
    assert state["played"] == config.TOURNAMENT_MATCHES_PER_DAY - 1
    assert state["required"] == config.TOURNAMENT_MATCHES_PER_DAY


def test_full_day_is_claimable_once_complete():
    state = t.full_period_state({"played": config.TOURNAMENT_MATCHES_PER_DAY})
    assert state["claimable"] is True
    assert state["reward"] == config.TOURNAMENT_FULL_DAY_REWARD


def test_full_day_is_not_claimable_twice():
    state = t.full_period_state({"played": config.TOURNAMENT_MATCHES_PER_DAY, "full_day_claimed": True})
    assert state["claimable"] is False
    assert state["claimed"] is True


def test_full_period_state_of_no_entry_is_empty_not_an_error():
    assert t.full_period_state(None)["played"] == 0


def test_full_day_reward_is_a_copy():
    t.full_period_state({})["reward"]["credits"] = 999
    assert config.TOURNAMENT_FULL_DAY_REWARD["credits"] != 999


def test_a_blank_entry_starts_unclaimed():
    from datetime import datetime, timezone
    entry = t.blank_entry("u", "U", 3, "t3-g0001", datetime(2026, 9, 18, tzinfo=timezone.utc))
    assert entry["full_period_claimed"] is False
