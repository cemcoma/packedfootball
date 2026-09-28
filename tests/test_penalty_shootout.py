"""The penalty shootout minigame.

Every test is seeded -- the engine is built around a reproducible
np.random.default_rng(seed), same as the match engine.
"""

from __future__ import annotations

import itertools

import pytest
from conftest import Team

from game_config import (
    PENALTY_SETUP_FRAMES,
    PITCH_HEIGHT,
    PENALTY_SHOT_SPEED,
    PENALTY_SIDES,
    PENALTY_SPOT_DISTANCE,
    PITCH_WIDTH,
)
from minigames import MINIGAMES_ENGINE_VERSION, PenaltyShootout, run_shootout
from minigames.minigamesEngine import (
    ATTACK_DIR,
    GOAL_STOP_DEPTH,
    REGULATION_KICKS,
    SAVE_STOP_DEPTH,
    SHOOTOUT_GOAL_Y,
    TICKS_PER_SECOND,
)
from replay import ActionType, decode_replay

GOAL_X_MIN = PITCH_WIDTH / 2 - 7.5 / 2
GOAL_X_MAX = PITCH_WIDTH / 2 + 7.5 / 2


@pytest.fixture
def sides(rosters):
    home, away = rosters
    return Team("Home", home), Team("Away", away)


def _play(sides, seed=7, record_replay=False, **kwargs):
    shootout = PenaltyShootout(*sides, seed=seed, record_replay=record_replay, **kwargs)
    while not shootout.is_finished:
        shootout.take_kick()
    return shootout


# ------------------------------------------------------------------- the rules


def test_version_is_major_minor_patch():
    parts = MINIGAMES_ENGINE_VERSION.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_a_shootout_settles_and_names_a_winner(sides):
    shootout = _play(sides, seed=3)
    assert shootout.is_finished
    assert shootout.winner in (0, 1)
    assert shootout.scores[shootout.winner] > shootout.scores[1 - shootout.winner]
    assert shootout.winner_team is shootout.teams[shootout.winner]


def test_sides_alternate(sides):
    shootout = _play(sides, seed=5)
    teams = [k["team"] for k in shootout.kicks_taken and shootout.history]
    assert teams[0] == 0
    assert all(a != b for a, b in zip(teams, teams[1:]))


def test_team_b_can_kick_first(sides):
    shootout = _play(sides, seed=5, team_a_starts=False)
    assert shootout.history[0]["team"] == 1


def test_never_more_than_one_kick_ahead(sides):
    """Nobody takes a second kick before the other side has answered the first."""
    for seed in range(40):
        shootout = _play(sides, seed=seed)
        taken = [0, 0]
        for kick in shootout.history:
            taken[kick["team"]] += 1
            assert abs(taken[0] - taken[1]) <= 1


def test_win_condition_matches_the_laws(sides):
    """Every one of the 4096 ways twelve kicks can fall, against a reference
    referee: the shootout has to stop on exactly the kick at which the result
    can no longer change -- not before, not after.
    """
    def reference(seq) -> int | None:
        scores, taken = [0, 0], [0, 0]
        for n in range(1, 13):
            team = (n - 1) % 2
            scores[team] += seq[team][taken[team]]
            taken[team] += 1
            if taken[0] >= REGULATION_KICKS and taken[1] >= REGULATION_KICKS:
                if taken[0] == taken[1] and scores[0] != scores[1]:
                    return n
                continue
            left = [REGULATION_KICKS - taken[0], REGULATION_KICKS - taken[1]]
            if scores[0] > scores[1] + left[1] or scores[1] > scores[0] + left[0]:
                return n
        return None

    for bits in itertools.product([0, 1], repeat=12):
        seq = [list(bits[:6]), list(bits[6:])]
        shootout = PenaltyShootout(*sides, seed=0)
        used = [0, 0]

        def forced(_taker, _keeper, aim=None, dive=None, _s=shootout, _u=used, _q=seq):
            team = _s.current_turn
            want = bool(_q[team][_u[team]])
            _u[team] += 1
            return want, 0, 0, True

        shootout._resolve_penalty = forced
        while not shootout.is_finished and len(shootout.history) < 12:
            shootout.take_kick()

        stopped = len(shootout.history) if shootout.is_finished else None
        assert stopped == reference(seq), f"a={seq[0]} b={seq[1]}"


def test_level_after_five_goes_to_sudden_death(sides, monkeypatch):
    shootout = PenaltyShootout(*sides, seed=1)
    monkeypatch.setattr(shootout, "_resolve_penalty", lambda *a, **k: (True, 0, 0, True))
    for _ in range(10):
        shootout.take_kick()
    assert not shootout.is_finished
    assert shootout.scores == [5, 5]
    assert shootout.take_kick()["sudden_death"] is True


# ------------------------------------------------------------------ the maths


def test_conversion_sits_in_the_designed_band(sides):
    """60-70%, the same band the match engine's spot kicks are held to."""
    kicks = [k for seed in range(200) for k in _play(sides, seed=seed).history]
    scored = sum(k["scored"] for k in kicks)
    assert 0.55 <= scored / len(kicks) <= 0.72, f"{scored}/{len(kicks)}"


def test_a_save_is_only_ever_credited_on_a_kick_that_was_on_target(sides):
    """The keeper's read used to be rolled independently of placement, so a ball
    flying wide was credited as a save (2% of all kicks) and the replay stopped
    it dead at the keeper."""
    for seed in range(300):
        for kick in _play(sides, seed=seed).history:
            assert not (kick["saved"] and not kick["on_target"])
            assert kick["saved"] == (kick["on_target"] and not kick["scored"])
            assert not (kick["scored"] and kick["saved"])


def test_a_kick_off_target_is_never_a_goal(sides):
    for seed in range(100):
        for kick in _play(sides, seed=seed).history:
            assert kick["on_target"] or not kick["scored"]


def test_the_keeper_only_saves_what_he_read(sides):
    for seed in range(100):
        for kick in _play(sides, seed=seed).history:
            assert not (kick["saved"] and kick["aim"] != kick["dive"])


def test_upcoming_names_the_next_taker_before_any_kick(sides):
    """A screen has to say whose kick it is BEFORE one has been taken, and
    history is empty then."""
    shootout = PenaltyShootout(*sides, seed=2)
    up = shootout.upcoming()
    assert up["team"] == 0
    assert up["taker_name"] and up["keeper_name"]
    assert up["sudden_death"] is False

    # And it is the taker the kick actually uses.
    kick = shootout.take_kick()
    assert kick["taker_idx"] == up["taker_idx"]
    assert kick["taker_name"] == up["taker_name"]
    assert kick["keeper_idx"] == up["keeper_idx"]


def test_upcoming_follows_the_turn(sides):
    shootout = PenaltyShootout(*sides, seed=2)
    first = shootout.upcoming()
    shootout.take_kick()
    second = shootout.upcoming()
    assert second["team"] == 1 - first["team"]
    # A side's second kick is a different taker from its first.
    shootout.take_kick()
    assert shootout.upcoming()["taker_idx"] != first["taker_idx"]


def test_upcoming_is_empty_once_it_is_over(sides):
    shootout = _play(sides, seed=4)
    assert shootout.upcoming() == {}


def test_upcoming_reports_sudden_death(sides, monkeypatch):
    shootout = PenaltyShootout(*sides, seed=1)
    monkeypatch.setattr(shootout, "_resolve_penalty", lambda *a, **k: (True, 0, 0, True))
    for _ in range(10):
        shootout.take_kick()
    assert shootout.upcoming()["sudden_death"] is True


def test_a_supplied_corner_is_the_one_taken(sides):
    for aim, dive in itertools.product(PENALTY_SIDES, PENALTY_SIDES):
        shootout = PenaltyShootout(*sides, seed=2)
        kick = shootout.take_kick(aim=aim, dive=dive)
        assert (kick["aim"], kick["dive"]) == (aim, dive)


def test_a_corner_off_the_scale_is_refused(sides):
    shootout = PenaltyShootout(*sides, seed=2)
    with pytest.raises(ValueError):
        shootout.take_kick(aim=5)
    with pytest.raises(ValueError):
        shootout.take_kick(dive=-2)


def test_same_seed_same_shootout(sides):
    first, second = _play(sides, seed=99), _play(sides, seed=99)
    assert first.history == second.history
    assert first.scores == second.scores


# ------------------------------------------------------------------ bad input


def test_an_empty_squad_is_refused(sides):
    with pytest.raises(ValueError):
        PenaltyShootout(Team("Nobody", []), sides[1], seed=1)


def test_a_taker_outside_the_squad_is_refused(sides):
    with pytest.raises(IndexError):
        PenaltyShootout(*sides, seed=1, team_a_takers=[99])


def test_a_given_kick_order_is_followed(sides):
    order = [4, 2, 9]
    shootout = PenaltyShootout(*sides, seed=1, team_a_takers=order)
    taken = [k["taker_idx"] for k in _run_team_a(shootout, 4)]
    assert taken == [4, 2, 9, 4]     # wraps, as a shootout past the squad does


def _run_team_a(shootout, n):
    out = []
    while len(out) < n and not shootout.is_finished:
        kick = shootout.take_kick()
        if kick["team"] == 0:
            out.append(kick)
    return out


def test_kicking_after_the_last_kick_raises(sides):
    shootout = _play(sides, seed=4)
    with pytest.raises(RuntimeError):
        shootout.take_kick()


# ----------------------------------------------------------------- the picture


def test_one_strike_event_per_kick(sides):
    """Every kick used to emit PENALTY *and* SHOOT -- the client draws both as a
    strike, so it ran the animation twice, and an off-target kick emitted three
    events. PENALTY at the run-up, then the outcome."""
    shootout = _play(sides, seed=13, record_replay=True)
    events = decode_replay(shootout.replay.encode())["events"]
    kicks = len(shootout.history)
    counts = {t: sum(1 for e in events if e["type"] == t) for t in ActionType}
    assert counts[ActionType.PENALTY] == kicks
    assert counts[ActionType.SHOOT] == 0
    outcomes = counts[ActionType.GOAL] + counts[ActionType.SAVE] + counts[ActionType.SHOT_OFF_TARGET]
    assert outcomes == kicks
    assert counts[ActionType.GOAL] == sum(k["scored"] for k in shootout.history)
    assert counts[ActionType.SAVE] == sum(k["saved"] for k in shootout.history)
    assert counts[ActionType.FULLTIME] == 1


def test_a_save_is_credited_to_the_keeper_s_own_side(sides):
    shootout = _play(sides, seed=13, record_replay=True)
    events = decode_replay(shootout.replay.encode())["events"]
    saves = [e for e in events if e["type"] == ActionType.SAVE]
    for save in saves:
        assert (save["player_idx"] < 11) == (save["team"] == 0)


def test_the_replay_has_no_hole_between_kicks(sides):
    """A stoppage that isn't sampled leaves a gap the client can only jump-cut
    across -- the same bug gameEngine 3.0.0 fixed for restarts."""
    shootout = _play(sides, seed=13, record_replay=True)
    decoded = decode_replay(shootout.replay.encode())
    interval = decoded["sample_interval_ticks"]
    ticks = [s["tick"] for s in decoded["samples"]]
    assert ticks, "nothing was recorded"
    assert max(b - a for a, b in zip(ticks, ticks[1:])) == interval


def test_nobody_is_standing_on_anybody(sides):
    """20 players used to sit stacked on the centre spot for the whole shootout,
    and the taker never moved to the ball."""
    shootout = _play(sides, seed=13, record_replay=True)
    for sample in decode_replay(shootout.replay.encode())["samples"]:
        spots = {(round(p["x"], 2), round(p["y"], 2)) for p in sample["players"]}
        assert len(spots) == 22


def test_the_taker_is_stood_over_the_ball_at_the_run_up(sides):
    """The kicker never moved to the spot -- the ball flew off a centre circle
    with 22 players standing in it."""
    shootout = PenaltyShootout(*sides, seed=13, record_replay=True)
    kick = shootout.take_kick()
    run_up = [
        s for s in decode_replay(shootout.replay.encode())["samples"]
        if s["tick"] <= PENALTY_SETUP_FRAMES
    ]
    assert run_up, "the run-up was never sampled"
    taker = kick["taker_idx"] + (0 if kick["team"] == 0 else 11)
    for sample in run_up:
        player = sample["players"][taker]
        gap = abs(player["x"] - sample["ball"]["x"]) + abs(player["y"] - sample["ball"]["y"])
        assert gap < 2.5, gap


def test_the_ball_carries_the_velocity_it_is_travelling_at(sides):
    """A client interpolates between samples on velocity, so the recorded
    velocity has to be the one the positions describe. It was flat zero."""
    shootout = _play(sides, seed=13, record_replay=True)
    decoded = decode_replay(shootout.replay.encode())
    dt = decoded["sample_interval_ticks"] / TICKS_PER_SECOND
    moving = 0
    for a, b in zip(decoded["samples"], decoded["samples"][1:]):
        speed = abs(a["ball"]["vx"]) + abs(a["ball"]["vy"])
        # Both ends in flight: a ball that reaches the net between two samples
        # comes to rest mid-interval, so extrapolating across that overshoots.
        if speed < 0.5 or abs(b["ball"]["vx"]) + abs(b["ball"]["vy"]) < 0.5:
            continue
        moving += 1
        # Where the velocity says it is going, against where it went.
        assert b["ball"]["x"] == pytest.approx(a["ball"]["x"] + a["ball"]["vx"] * dt, abs=0.2)
        assert b["ball"]["y"] == pytest.approx(a["ball"]["y"] + a["ball"]["vy"] * dt, abs=0.2)
    assert moving, "the ball is recorded as never moving"


def test_the_kick_flies_at_the_speed_a_match_strikes_it(sides):
    """A fixed 90-frame flight moved an 11-unit spot kick at 7.3 units/s,
    under a third of PENALTY_SHOT_SPEED."""
    shootout = PenaltyShootout(*sides, seed=13, record_replay=True)
    shootout.take_kick(aim=0, dive=1)
    samples = decode_replay(shootout.replay.encode())["samples"]
    fastest = max(abs(s["ball"]["vy"]) for s in samples)
    assert fastest == pytest.approx(PENALTY_SHOT_SPEED, rel=0.15)
    frames = PENALTY_SPOT_DISTANCE / PENALTY_SHOT_SPEED * TICKS_PER_SECOND
    assert frames < 40


def test_where_the_ball_dies_says_what_happened(sides):
    """A save stops short of the line, a goal ends past it, a miss reaches the
    line outside the frame. On the line a save and a goal are one picture.

    Measured along ATTACK_DIR rather than against a fixed y, so this still
    means the same thing if the shootout ever changes ends.
    """
    seen = set()
    for seed in range(60):
        shootout = PenaltyShootout(*sides, seed=seed, record_replay=True)
        while not shootout.is_finished:
            kick = shootout.take_kick()
            x, y = float(shootout.ball[0]), float(shootout.ball[1])
            past_the_line = (y - SHOOTOUT_GOAL_Y) * ATTACK_DIR
            if kick["scored"]:
                assert past_the_line == pytest.approx(GOAL_STOP_DEPTH)
                assert GOAL_X_MIN < x < GOAL_X_MAX
                seen.add("goal")
            elif kick["saved"]:
                assert past_the_line == pytest.approx(-SAVE_STOP_DEPTH)
                seen.add("save")
            else:
                assert past_the_line == pytest.approx(0.0)
                assert not GOAL_X_MIN < x < GOAL_X_MAX
                seen.add("miss")
    assert seen == {"goal", "save", "miss"}


def test_the_whole_shootout_happens_at_the_far_goal(sides):
    """The y = PITCH_HEIGHT end, which is the one team A attacks in a match.
    At the other end the side the player is drawn as shoots into its own net.
    """
    assert SHOOTOUT_GOAL_Y == PITCH_HEIGHT
    shootout = PenaltyShootout(*sides, seed=8, record_replay=True)
    keeper = shootout.keepers[1] + 11
    shootout.take_kick(aim=0, dive=1)
    taker = shootout.history[0]["taker_idx"]
    assert float(shootout.positions[keeper][1]) == pytest.approx(PITCH_HEIGHT)
    # The taker stands behind the ball, so further from the goal than the spot.
    assert float(shootout.positions[taker][1]) < PITCH_HEIGHT - PENALTY_SPOT_DISTANCE
    # And the ball never goes near the other end.
    for sample in decode_replay(shootout.replay.encode())["samples"]:
        assert sample["ball"]["y"] > PITCH_HEIGHT / 2.0


def test_aim_minus_one_is_the_low_x_side(sides):
    """gameEngine's sign, kept: -1 is lower x, which is the left of a pitch
    drawn the usual way up -- the side the client's Left button means."""
    left = PenaltyShootout(*sides, seed=8)
    left.take_kick(aim=-1, dive=0)
    right = PenaltyShootout(*sides, seed=8)
    right.take_kick(aim=1, dive=0)

    centre = PITCH_WIDTH / 2.0
    assert float(left.ball[0]) < centre
    assert float(right.ball[0]) > centre
    # Mirror images of each other, not two different distances.
    assert abs(float(left.ball[0]) - centre) == pytest.approx(abs(float(right.ball[0]) - centre))


def test_a_keeper_dives_to_the_side_he_was_told(sides):
    """dive shares aim's frame, so reading the corner means landing on it."""
    shootout = PenaltyShootout(*sides, seed=8)
    shootout.take_kick(aim=-1, dive=-1)
    assert shootout.history[0]["aim"] == shootout.history[0]["dive"]
    keeper = shootout.keepers[1] + 11
    # Same side of the goal as a ball aimed there.
    assert float(shootout.positions[keeper][0]) < PITCH_WIDTH / 2.0


def test_the_keeper_holds_the_side_he_committed_to(sides):
    """No drifting back onto a ball he has already been beaten by.

    Asserted as distance from the centre of the goal, so it does not care
    which way a dive to a given side carries him.
    """
    shootout = PenaltyShootout(*sides, seed=8, record_replay=True)
    shootout.take_kick(aim=-1, dive=1)
    samples = decode_replay(shootout.replay.encode())["samples"]
    keeper = shootout.keepers[1] + 11
    reach = [abs(s["players"][keeper]["x"] - PITCH_WIDTH / 2.0) for s in samples]
    assert reach[-1] > 0.0, "he never dived"
    assert max(reach) == pytest.approx(reach[-1], abs=0.05)


def test_a_dive_carries_as_far_as_it_does_in_a_match(sides):
    """It was scaled off the goal's half-width and stopped short of the corner
    it was diving for."""
    shootout = PenaltyShootout(*sides, seed=8)
    shootout.take_kick(aim=1, dive=1)
    keeper = shootout.keepers[1] + 11
    reached = abs(float(shootout.positions[keeper][0]) - PITCH_WIDTH / 2.0)
    corner = 7.5 / 2 - 0.6
    assert reached > corner


# ---------------------------------------------------------------- the payload


def test_the_result_serialises_without_the_teams(sides):
    result = run_shootout(*sides, seed=21, record_replay=True)
    assert result["engine_version"] == MINIGAMES_ENGINE_VERSION
    assert result["minigame"] == "penalty_shootout"
    assert result["seed"] == 21
    assert result["is_finished"] is True
    assert result["winner"] in (0, 1)
    assert result["winner_name"] == sides[result["winner"]].name
    assert sum(result["kicks_taken"]) == len(result["kicks"])
    assert isinstance(result["replay"], bytes) and result["replay"]
    import json
    json.dumps({k: v for k, v in result.items() if k != "replay"})


def test_run_shootout_without_a_replay_records_nothing(sides):
    assert run_shootout(*sides, seed=21)["replay"] is None
