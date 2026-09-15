"""Energy regeneration.

Energy is stored as a value plus the moment that value was true, and every
reader derives the current amount from the pair -- there is no job ticking it,
because nothing in this backend runs on a timer.

That makes the arithmetic the whole feature, and it has one classic bug: a
naive implementation resets the anchor to `now` on every read, so a player who
checks back every 44 minutes never regenerates a single point. Most of this
file exists to pin that down.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import config
from services import energy

MAX = config.ENERGY_MAX
STEP = timedelta(seconds=config.ENERGY_REGEN_SECONDS)

T0 = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------- regen


def test_full_bar_does_not_grow():
    assert energy.regen(MAX, T0, T0 + STEP * 5)[0] == MAX


def test_full_bar_keeps_its_anchor_at_now():
    """Nothing to bank at the cap, so the next 45 minutes run from the SPEND,
    not from whenever the bar happened to fill."""
    _, anchor = energy.regen(MAX, T0 - STEP * 9, T0)
    assert anchor == T0


def test_one_interval_gives_one_point():
    got, anchor = energy.regen(3, T0, T0 + STEP)
    assert got == 4
    assert anchor == T0 + STEP


def test_partial_interval_gives_nothing():
    got, _ = energy.regen(3, T0, T0 + STEP - timedelta(seconds=1))
    assert got == 3


def test_partial_interval_leaves_the_anchor_alone():
    """THE regression test for this module.

    Returning `now` when nothing was earned is the bug that makes frequent
    checking punish the player: every read would restart the clock.
    """
    _, anchor = energy.regen(3, T0, T0 + STEP - timedelta(seconds=1))
    assert anchor == T0, "a read that earns nothing must not move the anchor"


def test_remainder_carries_forward():
    """89 minutes is one point AND 44 minutes of credit toward the next."""
    almost_two = STEP * 2 - timedelta(seconds=60)
    got, anchor = energy.regen(3, T0, T0 + almost_two)
    assert got == 4
    # The anchor advanced by exactly ONE interval, not to `now` -- so the
    # leftover 44 minutes are still on the clock.
    assert anchor == T0 + STEP
    # ... and one more minute is enough to collect the second point.
    assert energy.regen(got, anchor, T0 + almost_two + timedelta(seconds=60))[0] == 5


def test_checking_often_is_never_worse_than_waiting():
    """Read every 44 minutes for 10 intervals; must match one 10-interval wait.

    This is the whole point of carrying the remainder, and it fails loudly on
    any implementation that resets the anchor on a no-op read.
    """
    impatient, anchor = 0, T0
    now = T0
    for _ in range(20):
        now += timedelta(seconds=config.ENERGY_REGEN_SECONDS - 60)
        impatient, anchor = energy.regen(impatient, anchor, now)

    patient, _ = energy.regen(0, T0, now)
    assert impatient == patient


def test_regen_never_exceeds_the_cap():
    assert energy.regen(0, T0, T0 + STEP * 999)[0] == MAX


def test_gain_from_empty_to_full_takes_max_intervals():
    assert energy.regen(0, T0, T0 + STEP * (MAX - 1))[0] == MAX - 1
    assert energy.regen(0, T0, T0 + STEP * MAX)[0] == MAX


# ------------------------------------------------------- reading a profile


def test_missing_fields_mean_a_full_bar():
    """Every account predates this feature, so absent must mean full -- that
    is what lets this ship with no migration script."""
    got, _ = energy.from_profile({}, T0)
    assert got == MAX


def test_none_profile_means_a_full_bar():
    assert energy.from_profile(None, T0)[0] == MAX


def test_stored_value_is_clamped_into_range():
    assert energy.from_profile({"energy": 999, "energy_updated_at": T0.isoformat()}, T0)[0] == MAX
    assert energy.from_profile({"energy": -5, "energy_updated_at": T0.isoformat()}, T0)[0] == 0


def test_malformed_timestamp_falls_back_to_now():
    got, _ = energy.from_profile({"energy": 2, "energy_updated_at": "not a date"}, T0)
    assert got == 2  # no regen credited, but no crash either


def test_naive_timestamp_is_read_as_utc():
    """A value written before this build started stamping a zone must still
    compare, rather than raising on aware-vs-naive subtraction."""
    naive = T0.replace(tzinfo=None).isoformat()
    got, _ = energy.from_profile({"energy": 2, "energy_updated_at": naive}, T0 + STEP)
    assert got == 3


def test_bool_is_not_an_energy_value():
    """bool is an int subclass in Python, and True would otherwise sail
    through as 1 energy."""
    assert energy.from_profile({"energy": True, "energy_updated_at": T0.isoformat()}, T0)[0] == MAX


# ------------------------------------------------------------- describing


def test_describe_at_full_reports_no_wait():
    d = energy.describe(MAX, T0, T0)
    assert d["seconds_to_next"] == 0
    assert d["seconds_to_full"] == 0


def test_describe_counts_down_within_an_interval():
    d = energy.describe(3, T0, T0 + timedelta(seconds=60))
    assert d["seconds_to_next"] == config.ENERGY_REGEN_SECONDS - 60


def test_describe_seconds_to_full_covers_every_missing_point():
    d = energy.describe(MAX - 3, T0, T0)
    # One full interval for the next point, then two more.
    assert d["seconds_to_full"] == config.ENERGY_REGEN_SECONDS * 3


def test_describe_never_returns_a_timestamp():
    """The client ticks a countdown locally from seconds, which is what keeps
    it immune to device-clock skew."""
    d = energy.describe(5, T0, T0)
    assert all(not isinstance(v, (datetime, str)) for v in d.values())


# ---------------------------------------------------------------- spending


def test_spending_from_a_full_bar_starts_the_clock():
    fields = energy.spend_fields(MAX, T0 - STEP * 3, 1, now=T0)
    assert fields["energy"] == MAX - 1
    assert fields["energy_updated_at"] == T0.isoformat()


def test_spending_from_a_partial_bar_keeps_the_carried_anchor():
    """Spending must not throw away regen progress already banked."""
    anchor = T0 - timedelta(seconds=600)
    fields = energy.spend_fields(4, anchor, 1, now=T0)
    assert fields["energy"] == 3
    assert fields["energy_updated_at"] == anchor.isoformat()


def test_spending_cannot_go_negative():
    assert energy.spend_fields(0, T0, 1, now=T0)["energy"] == 0


@pytest.mark.parametrize("cost", [1, 2, 3])
def test_spend_subtracts_the_cost(cost):
    assert energy.spend_fields(5, T0, cost, now=T0)["energy"] == 5 - cost
