"""The daily shootout's rules: the streak, the prestige ramp, what a day pays.

Almost everything here is a pure function of its arguments: no Firestore, no
clock -- `now` goes in as a parameter, and every constant is read from config
so retuning a dial cannot break a test. The last section drives the one
transaction through a FakeTx, the way test_ads_ssv.py does.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import config
from services import minigames as m

@pytest.fixture
def sides(rosters):
    """Two XIs, for the tests that drive a real shootout to see what a
    finished session actually puts on the document."""
    from conftest import Team

    home, away = rosters
    return Team("Home", home), Team("Away", away)


CYCLE = config.PENALTY_SHOOTOUT_CYCLE_DAYS
CAP = config.PENALTY_SHOOTOUT_PRESTIGE_MAX

T0 = datetime(2026, 9, 20, 15, 0, 0, tzinfo=timezone.utc)   # 18:00 Istanbul
TODAY = m.game_date(T0)
YESTERDAY = m.previous_date(TODAY)


def _doc(**over) -> dict:
    doc = {
        m.LAST_PLAYED_FIELD: YESTERDAY,
        m.CYCLE_DAY_FIELD: 0,
        m.PRESTIGE_FIELD: 0,
        m.PAID_TODAY_FIELD: 0,
    }
    doc.update(over)
    return doc


# ------------------------------------------------------------------- the ramp


def test_day_one_at_prestige_zero_pays_what_the_old_flat_table_did():
    assert m.reward_credits(1, 0, won=False) == 100
    assert m.reward_credits(1, 0, won=True) == 300


def test_the_reward_climbs_across_the_cycle():
    days = [m.reward_credits(d, 0, won=True) for d in range(1, CYCLE + 1)]
    assert days == sorted(days)
    assert days[-1] > days[0]


def test_the_reward_climbs_with_prestige():
    ladder = [m.reward_credits(1, p, won=True) for p in range(CAP + 1)]
    assert ladder == sorted(ladder)
    assert ladder[-1] > ladder[0]


def test_day_sixteen_beats_day_one():
    """The whole point of prestiging: the cycle restarts, but higher."""
    day_1 = m.reward_credits(1, 0, won=True)
    day_16 = m.reward_credits(1, 1, won=True)     # day 16 IS day 1 of prestige 1
    assert day_16 > day_1


def test_a_new_cycle_starts_below_the_old_one_s_peak():
    """A ratchet, not a straight line -- otherwise rewards run away."""
    assert m.reward_credits(1, 1, won=True) < m.reward_credits(CYCLE, 0, won=True)


def test_winning_pays_the_multiplier_over_losing():
    for day in (1, 8, CYCLE):
        won = m.reward_credits(day, 0, won=True)
        lost = m.reward_credits(day, 0, won=False)
        assert won == pytest.approx(lost * config.PENALTY_SHOOTOUT_WIN_MULTIPLIER, abs=1)


def test_prestige_stops_compounding_at_the_cap():
    assert m.reward_credits(1, CAP + 5, won=True) == m.reward_credits(1, CAP, won=True)
    assert m.clamp_prestige(CAP + 99) == CAP


def test_losing_still_pays_on_the_hardest_day():
    """Day 15 is the biggest reward AND the hardest bot, so showing up has to
    pay on a day you cannot win."""
    assert m.reward_credits(CYCLE, 0, won=False) > m.reward_credits(1, 0, won=False)


# ---------------------------------------------------------------- the streak


def test_consecutive_days_walk_up_the_cycle():
    assert m.next_day(cycle_day=6, last_played=YESTERDAY, today=TODAY) == 7


def test_a_missed_day_drops_back_to_day_one():
    stale = m.previous_date(YESTERDAY)
    assert m.next_day(cycle_day=9, last_played=stale, today=TODAY) == 1


def test_a_missed_day_keeps_the_prestige():
    stale = m.previous_date(YESTERDAY)
    state = m.state_from_doc(_doc(last_played=stale, cycle_day=9, prestige=3), T0)
    assert state["day"] == 1
    assert state["prestige"] == 3
    moved = m.advance_fields(state, won=True)
    assert moved["fields"][m.PRESTIGE_FIELD] == 3
    assert moved["fields"][m.CYCLE_DAY_FIELD] == 1


def test_a_first_ever_attempt_is_day_one():
    assert m.state_from_doc(None, T0)["day"] == 1
    assert m.state_from_doc({}, T0)["prestige"] == 0


def test_finishing_the_cycle_prestiges_and_restarts():
    state = m.state_from_doc(_doc(cycle_day=CYCLE - 1), T0)
    assert state["day"] == CYCLE
    moved = m.advance_fields(state, won=True)
    assert moved["prestiged"] is True
    assert moved["fields"][m.PRESTIGE_FIELD] == 1
    # cycle_day counts days COMPLETED, so zero means tomorrow is day 1 again.
    assert moved["fields"][m.CYCLE_DAY_FIELD] == 0
    tomorrow = m.next_day(cycle_day=0, last_played=TODAY, today=m.game_date(T0 + timedelta(days=1)))
    assert tomorrow == 1


def test_the_cycle_bonus_lands_only_on_the_last_day():
    assert m.cycle_bonus(CYCLE) == config.PENALTY_SHOOTOUT_CYCLE_BONUS
    assert m.cycle_bonus(CYCLE - 1) == {}


def test_the_cycle_bonus_is_flat_across_prestige():
    """Hard currency, so the faucet stays bounded however high the ramp goes."""
    low = m.advance_fields(m.state_from_doc(_doc(cycle_day=CYCLE - 1, prestige=0), T0), won=True)
    high = m.advance_fields(m.state_from_doc(_doc(cycle_day=CYCLE - 1, prestige=CAP), T0), won=True)
    assert low["bonus"] == high["bonus"] == config.PENALTY_SHOOTOUT_CYCLE_BONUS


def test_playing_twice_in_a_day_does_not_advance_the_streak():
    state = m.state_from_doc(_doc(last_played=TODAY, cycle_day=7, paid_today=100), T0)
    assert state["played_today"] is True
    moved = m.advance_fields(state, won=True)
    assert moved["fields"][m.CYCLE_DAY_FIELD] == 7
    assert moved["prestiged"] is False


def test_a_rolled_day_reads_as_unplayed_without_a_write():
    """The reset is derived, never migrated -- yesterday's doc reads fresh."""
    state = m.state_from_doc(_doc(last_played=YESTERDAY, paid_today=999), T0)
    assert state["played_today"] is False
    assert state["paid_today"] == 0


# ----------------------------------------------------------------- the payout


def test_the_ad_retry_tops_up_to_one_win_and_no_more():
    lost = m.advance_fields(m.state_from_doc(_doc(), T0), won=False)
    assert lost["credits"] == m.reward_credits(1, 0, won=False)

    after = m.state_from_doc(_doc(last_played=TODAY, cycle_day=1, **{m.PAID_TODAY_FIELD: lost["credits"]}), T0)
    retried = m.advance_fields(after, won=True)
    assert lost["credits"] + retried["credits"] == m.reward_credits(1, 0, won=True)


def test_a_retry_that_loses_again_pays_nothing_more():
    first = m.advance_fields(m.state_from_doc(_doc(), T0), won=False)
    after = m.state_from_doc(_doc(last_played=TODAY, cycle_day=1, **{m.PAID_TODAY_FIELD: first["credits"]}), T0)
    assert m.advance_fields(after, won=False)["credits"] == 0


def test_owed_never_goes_negative():
    assert m.owed(100, 300) == 0
    assert m.owed(300, 100) == 200
    assert m.owed(300, 0) == 300


# -------------------------------------------------------------------- the bot


def test_the_ladder_covers_the_cycle_and_runs_bronze_to_special():
    assert len(config.PENALTY_SHOOTOUT_BOT_LADDER) == CYCLE
    assert m.bot_tier_for_day(1) == "bronze"
    assert m.bot_tier_for_day(CYCLE) == "special"


def test_the_bot_gets_no_easier_as_the_cycle_goes_on():
    order = config.PENALTY_SHOOTOUT_TIER_ORDER
    steps = [order.index(m.bot_tier_for_day(d)) for d in range(1, CYCLE + 1)]
    assert steps == sorted(steps)


def test_rates_always_sum_to_one():
    for day in range(1, CYCLE + 1):
        for prestige in range(CAP + 1):
            assert sum(m.bot_rates(day, prestige).values()) == pytest.approx(1.0)


def test_prestige_leans_the_mix_up_without_changing_the_tier():
    plain = m.bot_rates(5, 0)
    nudged = m.bot_rates(5, CAP)
    tier = m.bot_tier_for_day(5)
    assert plain == {tier: 1.0}
    assert nudged[tier] < 1.0
    assert nudged["gold"] > 0            # one step up from silver, not two
    assert "platinum" not in nudged


def test_the_top_of_the_ladder_never_rolls_an_icon():
    """An icon bot is not a difficulty setting."""
    for prestige in range(CAP + 5):
        assert m.bot_rates(CYCLE, prestige) == {"special": 1.0}
        assert "icon" not in m.bot_rates(CYCLE, prestige)


def test_the_grid_cell_is_clamped_like_the_reward_is():
    pool = {"uids": [f"bot_p{p}" for p in range(config.PENALTY_SHOOTOUT_PRESTIGE_LEVELS)]}
    assert m.bot_id_from_pool(pool, 0) == "bot_p0"
    assert m.bot_id_from_pool(pool, CAP) == f"bot_p{CAP}"
    assert m.bot_id_from_pool(pool, CAP + 10) == f"bot_p{CAP}"


def test_an_unseeded_grid_has_no_bot():
    assert m.bot_id_from_pool(None, 0) is None
    assert m.bot_id_from_pool({"uids": []}, 0) is None


# ------------------------------------------------------------------- the clock


def test_the_day_rolls_at_noon_in_istanbul():
    istanbul = timezone(timedelta(hours=3))
    midday = datetime(2026, 9, 20, 9, 0, 0, tzinfo=timezone.utc)
    assert midday.astimezone(istanbul).hour == 12
    assert m.game_date(midday - timedelta(seconds=1)) == "2026-09-19"
    assert m.game_date(midday) == "2026-09-20"


def test_the_shootout_keeps_the_same_clock_as_the_tournament():
    from services import ads

    assert m.game_date(T0) == ads.game_date(T0)


def test_the_countdown_runs_a_full_day_and_never_goes_negative():
    just_rolled = datetime(2026, 9, 20, 9, 0, 0, tzinfo=timezone.utc)
    assert m.seconds_until_reset(just_rolled) == 24 * 3600
    assert m.seconds_until_reset(just_rolled + timedelta(hours=23)) == 3600
    assert m.seconds_until_reset(T0) > 0


def test_previous_date_crosses_a_month_boundary():
    assert m.previous_date("2026-10-01") == "2026-09-30"
    assert m.previous_date("2026-03-01") == "2026-02-28"


# ---------------------------------------------------------------- the settle


class FakeTx:
    """The slice of TransactionScope settle_in_tx uses. Enforces the one rule
    that matters here -- every read before every write -- so a test catches
    the ordering Firestore would otherwise reject at commit."""

    def __init__(self, docs: dict):
        self.docs = docs
        self.writes: list[tuple[str, dict]] = []
        self._written = False

    def get_all(self, paths):
        assert not self._written, "every read must come before every write"
        return {p: self.docs.get(p) for p in paths}

    def get(self, path):
        assert not self._written, "every read must come before every write"
        return self.docs.get(path)

    def set(self, path, data, merge=True):
        self._written = True
        self.writes.append((path, data))
        if merge and self.docs.get(path):
            self.docs[path] = {**self.docs[path], **data}
        else:
            self.docs[path] = dict(data)


UID = "u1"
USER_PATH = f"users/{UID}"


def _tx(streak: dict | None = None, credits: int = 500, bucks: int = 0, status: str = "live") -> FakeTx:
    docs = {
        USER_PATH: {"credits": credits, "bucks": bucks},
        m.session_path(UID): {"status": status, "seed": 7, "day": 1, "prestige": 0},
    }
    if streak is not None:
        docs[m.state_path(UID)] = streak
    return FakeTx(docs)


def _increment(value):
    """firestore.Increment's amount, whatever the SDK calls the attribute."""
    return getattr(value, "value", value)


def test_settling_pays_by_increment_not_by_writing_a_balance():
    """A pack bought at the same moment must not be clobbered by a stale read."""
    tx = _tx(_doc())
    paid = m.settle_in_tx(tx, UID, won=True, now=T0)

    user_write = dict(w for w in tx.writes if w[0] == USER_PATH)[USER_PATH]
    assert _increment(user_write["credits"]) == m.reward_credits(1, 0, won=True)
    assert paid["rewards"]["credits"] == m.reward_credits(1, 0, won=True)
    assert paid["balances"]["credits"] == 500 + m.reward_credits(1, 0, won=True)


def test_settling_moves_the_streak_and_closes_the_session():
    tx = _tx(_doc())
    m.settle_in_tx(tx, UID, won=False, now=T0)

    assert tx.docs[m.state_path(UID)][m.CYCLE_DAY_FIELD] == 1
    assert tx.docs[m.state_path(UID)][m.LAST_PLAYED_FIELD] == TODAY
    assert tx.docs[m.session_path(UID)]["status"] == "finished"


def test_finishing_the_cycle_pays_the_bucks():
    tx = _tx(_doc(cycle_day=CYCLE - 1))
    paid = m.settle_in_tx(tx, UID, won=True, now=T0)

    assert paid["rewards"]["bucks"] == config.PENALTY_SHOOTOUT_CYCLE_BONUS["bucks"]
    assert paid["prestiged"] is True
    assert tx.docs[m.state_path(UID)][m.PRESTIGE_FIELD] == 1


def test_a_finished_session_cannot_be_settled_twice():
    tx = _tx(_doc(), status="finished")
    with pytest.raises(m.ShootoutRefused):
        m.settle_in_tx(tx, UID, won=True, now=T0)
    assert tx.writes == []


def test_a_retry_settle_pays_only_the_difference():
    already = m.reward_credits(1, 0, won=False)
    tx = _tx(_doc(last_played=TODAY, cycle_day=1, paid_today=already))
    paid = m.settle_in_tx(tx, UID, won=True, now=T0)

    assert already + paid["rewards"]["credits"] == m.reward_credits(1, 0, won=True)
    assert tx.docs[m.state_path(UID)][m.CYCLE_DAY_FIELD] == 1     # streak did not move


def test_settling_a_second_loss_writes_no_payout_at_all():
    already = m.reward_credits(1, 0, won=False)
    tx = _tx(_doc(last_played=TODAY, cycle_day=1, paid_today=already))
    paid = m.settle_in_tx(tx, UID, won=False, now=T0)

    assert paid["rewards"] == {}
    assert not any(path == USER_PATH for path, _ in tx.writes)


def test_a_first_ever_settle_needs_no_existing_streak_doc():
    tx = _tx(streak=None)
    paid = m.settle_in_tx(tx, UID, won=True, now=T0)
    assert paid["day"] == 1
    assert tx.docs[m.state_path(UID)][m.CYCLE_DAY_FIELD] == 1


# ------------------------------------------------------------- the ad retry


RETRIES = config.PENALTY_SHOOTOUT_AD_RETRIES_PER_DAY


def test_a_loss_on_the_last_attempt_can_buy_a_retry():
    assert m.can_buy_retry(won=False, attempts_used=1, allowed=1)


def test_a_win_never_offers_a_retry():
    """The retry tops up to the win reward -- after a win there is nothing
    left for it to buy."""
    assert not m.can_buy_retry(won=True, attempts_used=1, allowed=1)


def test_no_retry_is_offered_once_the_days_ads_are_spent():
    """The ad track would refuse the grant, so the button must not show."""
    allowed = 1 + RETRIES
    assert not m.can_buy_retry(won=False, attempts_used=allowed, allowed=allowed)


def test_no_ad_is_offered_while_an_attempt_is_still_unused():
    assert not m.can_buy_retry(won=False, attempts_used=1, allowed=2)


def test_the_settle_reports_the_attempts_the_profile_allows():
    """What the end screen decides its ad button from, off the profile the
    transaction already read."""
    assert m.settle_in_tx(_tx(_doc()), UID, won=False, now=T0)["attempts_allowed"] == 1

    tx = _tx(_doc())
    tx.docs[USER_PATH].update({"ad_counters": {m.RETRY_TRACK: RETRIES}, "last_ad_date": TODAY})
    assert m.settle_in_tx(tx, UID, won=False, now=T0)["attempts_allowed"] == 1 + RETRIES


# --------------------------------------------------------- what gets stored


def _firestore_offenders(value, path: str = "", in_array: bool = False) -> list:
    """Shapes Firestore's SERVER rejects, which its client library encodes
    without complaint -- so they pass every local test and fail on deploy.

    An array directly inside an array is refused outright ("Cannot convert an
    array value in an array value"); an array inside a MAP inside an array is
    fine, which is why this tracks nesting rather than depth. numpy scalars
    are not Firestore values at all.
    """
    bad = []
    if isinstance(value, (list, tuple)):
        if in_array:
            bad.append(f"{path}: array directly inside an array")
        for i, item in enumerate(value):
            bad += _firestore_offenders(item, f"{path}[{i}]", in_array=True)
    elif isinstance(value, dict):
        for key, item in value.items():
            bad += _firestore_offenders(item, f"{path}.{key}", in_array=False)
    elif type(value).__module__ == "numpy":
        bad.append(f"{path}: numpy {type(value).__name__}, not a Firestore value")
    return bad


def test_the_input_log_is_a_shape_firestore_can_store():
    """It was [[aim, dive], ...] -- an array inside an array. The library
    encoded it happily, every local test passed, and every kick failed against
    the real database."""
    log = [m.encode_input(1, None), m.encode_input(None, -1), m.encode_input(0, None)]
    assert _firestore_offenders(log, "inputs") == []
    assert m.decode_inputs({"inputs": log}) == [(1, None), (None, -1), (0, None)]

    # And the checker really does catch the shape this replaced -- a guard
    # that cannot fail would have passed on the broken version too.
    assert _firestore_offenders([[1, None], [None, -1]], "inputs") != []


def test_the_input_log_round_trips_through_what_is_stored():
    """Replaying a session depends on the log coming back in the same order
    with the same None-ness -- that is what makes the rebuild deterministic."""
    pairs = [(1, None), (None, -1), (0, None), (None, 0)]
    stored = [m.encode_input(aim, dive) for aim, dive in pairs]
    assert m.decode_inputs({"inputs": stored}) == pairs


def test_a_missing_or_empty_log_decodes_to_nothing():
    for session in (None, {}, {"inputs": None}, {"inputs": []}):
        assert m.decode_inputs(session) == []


def test_the_whole_session_doc_is_storable(sides):
    """Not just the log: the finished result goes on the same document."""
    from minigames import PenaltyShootout

    shootout = PenaltyShootout(*sides, seed=7)
    log = []
    while not shootout.is_finished:
        aim = 1 if shootout.current_turn == 0 else None
        dive = None if shootout.current_turn == 0 else -1
        shootout.take_kick(aim=aim, dive=dive)
        log.append(m.encode_input(aim, dive))

    session = {
        "game_date": TODAY,
        "attempt": 1,
        "seed": 8123456789,
        "bot_id": "bot_a1b2c3",
        "bot_name": "mertcan",
        "bot_tier": "gold",
        "day": 7,
        "prestige": 2,
        "kits": ["v1;pattern=solid;primary=c8102e;secondary=ffffff", ""],
        "inputs": log,
        "status": "finished",
        "result": shootout.result(),
    }
    assert _firestore_offenders(session, "session") == []


def test_the_streak_doc_is_storable():
    fields = m.advance_fields(m.state_from_doc(_doc(), T0), won=True)["fields"]
    assert _firestore_offenders(fields, "shootout") == []


# -- what the screen is sent ---------------------------------------------------


def test_upcoming_and_kick_carry_the_takers_look(sides):
    """The screen plays the taker's own celebration, so both the pre-kick
    `upcoming` and the kick itself carry his appearance -- without it being
    written into the engine's history, which the session doc stores."""
    from minigames import PenaltyShootout
    from routers.shootout import _with_appearance

    shootout = PenaltyShootout(*sides, seed=7)
    up = _with_appearance(shootout, shootout.upcoming())
    taker = shootout.teams[up["team"]].players[up["taker_idx"]]
    assert up["taker_appearance"] == dict(taker.appearance)
    assert "celebration" in up["taker_appearance"]

    kick = _with_appearance(shootout, shootout.take_kick(aim=1))
    assert kick["taker_appearance"] == up["taker_appearance"]
    assert "taker_appearance" not in shootout.history[0]


# -- the picked kick order -----------------------------------------------------


def test_the_picker_scores_with_the_engines_own_formula(sides):
    """The number on screen is the one the placement roll is made from, and
    Auto-select fills in the order the engine would have used on its own."""
    from minigames import PenaltyShootout, penalty_score

    squad = m.picker_squad(sides[0].players)
    assert [p["idx"] for p in squad["players"]] == list(range(len(sides[0].players)))
    for entry, player in zip(squad["players"], sides[0].players):
        assert entry["score"] == round(penalty_score(player.attributes))
        assert entry["name"] == player.lname
        assert entry["position"] == player.position
    assert squad["suggested"] == PenaltyShootout(*sides, seed=1).takers[0]
    assert squad["suggested"] == sorted(
        squad["suggested"], key=lambda i: -penalty_score(sides[0].players[i].attributes)
    )


def test_a_full_order_is_accepted_as_sent():
    order = [3, 1, 0, 2, 4, 5, 6, 7, 8, 9, 10]
    assert m.taker_order(order, 11) == order


def test_no_order_leaves_it_to_the_engine():
    assert m.taker_order(None, 11) is None


@pytest.mark.parametrize("order", [
    [0, 1, 2, 3, 4],                        # short: the best five would take them all
    [9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9],      # one striker, every kick
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9],      # a repeat standing in for someone
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11],     # outside the squad
    [],
])
def test_an_order_that_is_not_the_whole_squad_once_is_refused(order):
    with pytest.raises(ValueError):
        m.taker_order(order, 11)


def test_a_session_replays_with_the_order_it_was_started_with(sides):
    """The order is stored on the session and every /kick rebuilds from it --
    so the picked taker takes the first kick, and keeps doing so on replay."""
    from routers.shootout import _replay

    home, away = sides
    player = {"display_name": "Home", "roster": home.players}
    bot = {"display_name": "Away", "roster": away.players}
    order = list(reversed(range(len(home.players))))
    seed = 8123456790                       # even: the bot kicks first
    session = {"seed": seed, "inputs": [], "takers": order}

    shootout = _replay(player, bot, session)
    assert shootout.takers[0] == order
    shootout.take_kick(dive=0)
    first_mine = shootout.take_kick(aim=1)
    assert first_mine["team"] == 0 and first_mine["taker_idx"] == order[0]

    # A session from before the picker has no order, and plays best-first.
    legacy = _replay(player, bot, {"seed": seed, "inputs": []})
    assert legacy.takers[0] == m.picker_squad(home.players)["suggested"]


def test_a_session_with_an_order_is_storable():
    session = {"seed": 1, "inputs": [m.encode_input(1, None)], "takers": list(range(11))}
    assert _firestore_offenders(session, "session") == []
