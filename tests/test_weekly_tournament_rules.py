"""The weekly league: week keys, ten-player tables, and mode isolation.

The rules themselves are the daily league's -- services/tournament.py has one
implementation and hands it a Mode -- so this file does not re-test ranking or
the promote/stay/relegate logic. What it tests is everything that IS different:
the seven-day grid, the ten-row positional table, and the thing with no
equivalent in a single-format world -- that the two leagues cannot touch each
other's documents, fields or tiers.

Everything here is a pure function of its arguments. No Firestore, no clock.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import config
from services import tournament as t

W = t.WEEKLY
D = t.DAILY

CAP = W.group_capacity
FLOOR = W.promotion_floor
DROP = W.relegation_floor


def entry(uid, points=0, played=None, gf=0, ga=0, wins=0, joined="2026-09-21T09:00:00+00:00"):
    return {
        "uid": uid,
        "display_name": uid.title(),
        "points": points,
        "played": W.matches_per_period if played is None else played,
        "goals_for": gf,
        "goals_against": ga,
        "wins": wins,
        "joined_at_iso": joined,
    }


def full_group(points):
    return [entry(f"p{i}", pts, gf=pts) for i, pts in enumerate(points)]


def outcomes(entries, tier=2, group_size=None):
    rows = t.apply_rules(t.rank_rows(entries), tier, group_size=group_size, mode=W)
    return {r["uid"]: r["outcome"] for r in rows}


# A full ten-player table, comfortably spread so position is unambiguous.
TEN = [FLOOR + 40, FLOOR + 30, FLOOR + 20, FLOOR + 10, FLOOR,
       DROP + 10, DROP + 5, DROP, DROP - 10, DROP - 20]


# ----------------------------------------------------------------- week keys


def test_a_week_is_exactly_seven_days():
    assert t.period_end("2026-09-21", W) - t.period_start("2026-09-21", W) == timedelta(days=7)


def test_a_week_starts_on_a_monday():
    """The anchor fixes WHICH weekday a week begins on, and nothing else."""
    assert date.fromisoformat(config.WEEKLY_TOURNAMENT_PERIOD_ANCHOR).weekday() == 0
    for period_id in ("2026-09-21", "2026-01-05", "2025-12-29"):
        assert date.fromisoformat(period_id).weekday() == 0
        assert t.period_id_for(t.period_start(period_id, W), W) == period_id


def test_the_week_rolls_over_at_the_same_hour_as_the_day():
    """One reset time to learn. If this fails the two leagues have drifted
    apart and a player has two clocks to keep track of."""
    assert W.offset_hours == D.offset_hours
    assert t.period_start("2026-09-21", W).hour == config.TOURNAMENT_DAY_OFFSET_HOURS % 24


def test_the_weekly_reset_lands_at_noon_in_istanbul():
    istanbul = timezone(timedelta(hours=3))
    assert t.period_start("2026-09-21", W).astimezone(istanbul).hour == 12


def test_every_moment_inside_a_week_belongs_to_it():
    start = t.period_start("2026-09-21", W)
    assert t.period_id_for(start, W) == "2026-09-21"
    assert t.period_id_for(start + timedelta(days=6, hours=23), W) == "2026-09-21"
    assert t.period_id_for(start - timedelta(seconds=1), W) == "2026-09-14"
    assert t.period_id_for(start + timedelta(days=7), W) == "2026-09-28"


def test_weeks_before_the_anchor_still_land_on_a_monday():
    """Floor division, not truncation -- a date before the origin must not
    round the wrong way and hand out a Sunday."""
    old = datetime(2024, 3, 13, 15, tzinfo=timezone.utc)
    assert date.fromisoformat(t.period_id_for(old, W)).weekday() == 0


def test_previous_period_ids_step_a_week_at_a_time():
    assert t.previous_period_ids("2026-09-21", 3, W) == ["2026-08-31", "2026-09-07", "2026-09-14"]


def test_joining_closes_in_the_final_day():
    end = t.period_end("2026-09-21", W)
    cutoff = timedelta(seconds=W.join_cutoff_seconds)
    assert t.joining_is_closed("2026-09-21", end - cutoff + timedelta(seconds=1), W)
    assert not t.joining_is_closed("2026-09-21", end - cutoff - timedelta(seconds=1), W)


def test_a_week_is_still_open_days_before_the_end():
    start = t.period_start("2026-09-21", W)
    assert not t.joining_is_closed("2026-09-21", start + timedelta(days=5), W)


# ---------------------------------------------- the ten-player table


def test_a_group_of_ten_settles_positionally():
    assert t.settlement_mode(CAP, W) == "positional"
    assert t.settlement_mode(CAP - 1, W) == "threshold"


def test_the_daily_capacity_is_a_short_group_here():
    """Six is a full table in the daily league and a short one in this,
    which is exactly the bug a shared constant would have caused."""
    assert t.settlement_mode(config.TOURNAMENT_GROUP_CAPACITY, W) == "threshold"


def test_a_full_group_promotes_the_top_three():
    got = outcomes(full_group(TEN))
    assert [got[f"p{i}"] for i in (0, 1, 2)] == ["promote"] * 3


def test_a_full_group_relegates_the_bottom_three():
    got = outcomes(full_group(TEN))
    assert [got[f"p{i}"] for i in (7, 8, 9)] == ["relegate"] * 3


def test_the_middle_four_stay():
    got = outcomes(full_group(TEN))
    assert [got[f"p{i}"] for i in (3, 4, 5, 6)] == ["stay"] * 4


def test_fourth_place_over_the_floor_does_not_promote():
    """Position beats points, same as the daily league."""
    got = outcomes(full_group([FLOOR + 40, FLOOR + 30, FLOOR + 20, FLOOR + 10,
                               DROP, DROP, DROP, DROP, DROP, DROP]))
    assert got["p3"] == "stay"


def test_seventh_place_under_the_floor_does_not_relegate():
    points = [FLOOR + 40, FLOOR + 30, FLOOR + 20] + [DROP - 1] * 7
    got = outcomes(full_group(points))
    assert got["p6"] == "stay"
    assert got["p7"] == "relegate"


def test_the_top_three_still_need_the_floor():
    got = outcomes(full_group([FLOOR - 1] * 10))
    assert [got[f"p{i}"] for i in (0, 1, 2)] == ["stay"] * 3


def test_the_promotion_floor_is_reachable_inside_the_schedule():
    """A floor above what the format's matches can pay would make promotion
    impossible and nobody would find out until a week had run."""
    assert FLOOR <= W.matches_per_period * W.points["win"]
    assert DROP < FLOOR


def test_a_short_weekly_group_falls_back_to_thresholds():
    got = outcomes([entry("a", FLOOR), entry("b", FLOOR - 1), entry("c", DROP - 1)])
    assert got["a"] == "promote" and got["b"] == "stay" and got["c"] == "relegate"


def test_a_solo_weekly_group_cannot_promote():
    assert outcomes([entry("a", FLOOR + 40)])["a"] == "stay"


# -------------------------------------------------------------------- rewards


def test_every_one_of_the_ten_positions_is_paid():
    """A ten-row table against a six-row payout would silently pay four
    players nothing for a week's work."""
    for tier in W.tiers:
        rows = t.apply_rules(t.rank_rows(full_group(TEN)), tier, mode=W)
        assert len(rows) == CAP
        for row in rows:
            assert row["rewards"].get("credits", 0) > 0, (tier, row["position"])


def test_weekly_placement_credits_fall_with_position():
    for tier in W.tiers:
        table = t.rewards_table(tier, W)
        credits = [table[pos]["credits"] for pos in sorted(table)]
        assert credits == sorted(credits, reverse=True), tier


def test_a_week_never_pays_less_than_a_day_for_the_same_position():
    """Fifty matches over seven days against ten in one. Finishing 4th in a
    week paying less than 4th in a day would make the format pointless, and
    it is an easy thing to do by accident while tuning one table."""
    for tier in config.TOURNAMENT_TIERS:
        for position, daily_payout in t.rewards_table(tier, D).items():
            weekly_payout = t.rewards_table(tier, W)[position]
            for currency, amount in daily_payout.items():
                assert weekly_payout.get(currency, 0) >= amount, (tier, position, currency)


def test_the_weekly_table_covers_every_seat_in_a_full_group():
    """A ten-player group against a six-row table would pay four people
    nothing for a week."""
    for tier in W.tiers:
        assert sorted(t.rewards_table(tier, W)) == list(range(1, CAP + 1)), tier


def test_weekly_bucks_exist_only_on_the_top_tier_podium():
    for tier in W.tiers:
        for position, payout in t.rewards_table(tier, W).items():
            if payout.get("bucks", 0):
                assert tier == W.top_tier
                assert position in W.promote_positions


def test_a_weekly_no_show_earns_nothing():
    rows = t.apply_rules(t.rank_rows([entry("ghost", 0, played=0)]), 3, mode=W)
    assert rows[0]["rewards"] == {}


def test_weekly_rewards_are_copies_not_the_config_table():
    rows = t.apply_rules(t.rank_rows(full_group(TEN)), 3, mode=W)
    rows[0]["rewards"]["medals"] = 999
    assert config.WEEKLY_TOURNAMENT_TIERS[3]["rewards"][1]["medals"] != 999


# ---------------------------------------------------- the full-week reward


def test_the_full_week_reward_needs_all_fifty_matches():
    assert W.matches_per_period == config.WEEKLY_TOURNAMENT_MATCHES_PER_WEEK
    short = t.full_period_state({"played": W.matches_per_period - 1}, W)
    assert short["claimable"] is False and short["required"] == W.matches_per_period

    done = t.full_period_state({"played": W.matches_per_period}, W)
    assert done["claimable"] is True
    assert done["reward"] == config.WEEKLY_TOURNAMENT_FULL_WEEK_REWARD


def test_a_full_daily_run_does_not_complete_a_week():
    assert t.full_period_state({"played": config.TOURNAMENT_MATCHES_PER_DAY}, W)["claimable"] is False


def test_the_full_week_reward_is_not_claimable_twice():
    state = t.full_period_state({"played": W.matches_per_period, "full_period_claimed": True}, W)
    assert state["claimable"] is False and state["claimed"] is True


def test_an_entry_claimed_under_the_old_flag_is_not_re_paid():
    """Daily entries written before this feature carry full_day_claimed.
    Reading only the new name would pay those players twice."""
    state = t.full_period_state(
        {"played": config.TOURNAMENT_MATCHES_PER_DAY, "full_day_claimed": True}, D
    )
    assert state["claimed"] is True and state["claimable"] is False


# ------------------------------------------------ the two leagues are separate


def test_the_modes_write_to_different_collections():
    assert W.collection != D.collection
    assert t.period_path("2026-09-21", W).startswith(W.collection + "/")
    assert t.period_path("2026-09-21", D).startswith(D.collection + "/")


def merged(doc: dict, update: dict) -> dict:
    """Firestore's set(merge=True): a nested map MERGES into the stored one,
    anything else replaces it. Modelled here because the whole point of the
    map layout is that one league's write cannot reach the other's keys, and
    that property lives in this merge rather than in our own code."""
    out = dict(doc)
    for key, value in update.items():
        out[key] = merged(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def both_leagues() -> dict:
    """A profile entered in, and ranked by, both formats."""
    doc = {}
    for mode, tier, period, group in [(D, 1, "2026-09-23", "t1-g0000"),
                                      (W, 2, "2026-09-21", "t2-g0003")]:
        doc = merged(doc, {t.TIERS_FIELD: {mode.key: tier}})
        doc = merged(doc, t.enter_fields(period, group, mode))
    return doc


def test_each_league_reads_its_own_slot():
    doc = both_leagues()
    assert t.tier_of(doc, D) == 1 and t.tier_of(doc, W) == 2
    assert t.entered_period(doc, D) == "2026-09-23"
    assert t.entered_period(doc, W) == "2026-09-21"
    assert t.entered_group(doc, D) == "t1-g0000"
    assert t.entered_group(doc, W) == "t2-g0003"
    assert t.is_entered(doc, "2026-09-21", W)
    assert not t.is_entered(doc, "2026-09-21", D)


def test_settling_one_league_leaves_the_other_untouched():
    """The isolation that matters most: settling the weekly league must not
    move a player's daily tier or release their daily seat."""
    doc = merged(both_leagues(), t.settle_fields(3, "2026-09-21", "t2-g0003", W))

    assert t.tier_of(doc, W) == 3                 # moved
    assert t.entered_period(doc, W) == ""         # seat released
    assert t.last_period(doc, W) == "2026-09-21"  # result pointer left behind

    assert t.tier_of(doc, D) == 1                 # untouched
    assert t.entered_period(doc, D) == "2026-09-23"
    assert t.entered_group(doc, D) == "t1-g0000"
    assert t.last_period(doc, D) == ""


def test_entering_one_league_leaves_the_other_untouched():
    doc = merged(both_leagues(), t.enter_fields("2026-09-24", "t1-g0007", D))
    assert t.entered_group(doc, D) == "t1-g0007"
    assert t.entered_group(doc, W) == "t2-g0003"


def test_the_formats_key_the_maps_differently():
    keys = [mode.key for mode in t.MODES.values()]
    assert len(set(keys)) == len(keys), keys


def test_a_weekly_tier_defaults_to_the_bottom_and_clamps():
    assert t.tier_of(None, W) == W.bottom_tier
    assert t.tier_of({t.TIERS_FIELD: {"daily": 1}}, W) == W.bottom_tier
    assert t.tier_of({t.TIERS_FIELD: {"weekly": 99}}, W) == W.bottom_tier
    assert t.tier_of({t.TIERS_FIELD: {"weekly": -5}}, W) == W.top_tier
    assert t.tier_of({t.TIERS_FIELD: {"weekly": True}}, W) == W.bottom_tier


def test_a_profile_that_never_played_reads_as_empty_everywhere():
    """Every account in the database on the day this ships."""
    for doc in (None, {}, {"credits": 100}, {t.TIERS_FIELD: None}):
        for mode in t.MODES.values():
            assert t.tier_of(doc, mode) == mode.bottom_tier
            assert t.entered_period(doc, mode) == ""
            assert t.entered_group(doc, mode) == ""
            assert t.last_period(doc, mode) == ""
            assert not t.is_entered(doc, "2026-09-21", mode)


def test_both_modes_draw_from_the_same_bots():
    """'The same bots as the daily tournament' -- one seeding run, one pool
    per tier, whatever the format."""
    assert t.bot_pool_path(2) == "bot_pools/2"
    for tier in W.tiers:
        assert t.bot_card_rates(tier, W) is t.bot_card_rates(tier, D)


def test_a_group_id_collides_across_modes_but_a_path_does_not():
    """Group ids are per-tier counters and WILL repeat between formats; the
    collection root is what keeps the documents apart."""
    gid = t.group_id_for(3, 0)
    assert t.entry_path("2026-09-21", gid, "u", W) != t.entry_path("2026-09-21", gid, "u", D)


def test_mode_for_rejects_an_unknown_key():
    assert t.mode_for("weekly") is W
    assert t.mode_for("daily") is D
    try:
        t.mode_for("monthly")
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown mode must raise, not fall back to daily")


def test_weekly_match_results_use_the_weekly_points_table():
    fields, earned, outcome = t.result_fields({}, 2, 1, "g1", W)
    assert outcome == "win" and earned == W.points["win"]
    assert fields["points"] == W.points["win"]


# ------------------------------------------------ the tier table's own shape


def test_every_tier_block_is_complete():
    """One entry per tier holds the name, the bots and the payouts. A block
    missing a key would fail at a different moment for each one -- a blank
    league name on a screen, bots rolled as silver, a position paying
    nothing -- so it is worth failing here instead."""
    for mode in t.MODES.values():
        assert mode.tiers, mode.key
        for tier, block in mode.tiers.items():
            assert set(block) == {"name", "bot_card_rates", "rewards"}, (mode.key, tier)
            assert block["name"], (mode.key, tier)
            assert block["bot_card_rates"], (mode.key, tier)
            assert block["rewards"], (mode.key, tier)


def test_the_tier_edges_come_from_the_table():
    """Derived, not written down twice -- a fourth tier is one more entry."""
    for mode in t.MODES.values():
        assert mode.top_tier == min(mode.tiers), mode.key
        assert mode.bottom_tier == max(mode.tiers), mode.key
        assert mode.default_tier == mode.bottom_tier, mode.key


def test_bot_card_rates_are_a_distribution():
    for mode in t.MODES.values():
        for tier in mode.tiers:
            rates = t.bot_card_rates(tier, mode)
            assert abs(sum(rates.values()) - 1.0) < 1e-6, (mode.key, tier, rates)


def test_an_unknown_tier_reads_as_empty_not_an_error():
    assert t.tier_config(99, W) == {}
    assert t.rewards_table(99, W) == {}
    assert t.bot_card_rates(99, W) is None
    assert t.tier_name(99, W) == "Tier 99"
