"""Phase 3: the match clock reaches 90:00, then plays added time.

Matches used to end at exactly 88:30 every time. run_match counted loop
iterations, but tick() deliberately does not advance match_clock_frames while
halftime_pause_timer is running -- so the 180-frame halftime pause silently
ate 180 frames == 90 clock-seconds == 1:30 of football, on every match.
"""

import pytest

REGULATION_FRAMES = 10800  # 90:00 at 2 frames per clock-second


def clock_seconds(g):
    return int(g.match_clock_frames / 2.0)


def mmss(g):
    total = clock_seconds(g)
    return f"{total // 60}:{total % 60:02d}"


@pytest.fixture
def played(make_match):
    def _play(seed=7):
        g = make_match(seed=seed)
        g.run_match(max_steps=REGULATION_FRAMES, render=False)
        return g

    return _play


@pytest.mark.slow
def test_match_reaches_at_least_ninety_minutes(played):
    g = played()
    assert clock_seconds(g) >= 90 * 60, f"match ended at {mmss(g)}"


@pytest.mark.slow
def test_match_no_longer_ends_at_88_30(played):
    """The exact regression: 10800 - 180 frames = 5310s = 88:30."""
    g = played()
    assert g.match_clock_frames != REGULATION_FRAMES - 180


@pytest.mark.parametrize("seed", [1, 7, 42])
@pytest.mark.slow
def test_added_time_is_played_on_both_halves(played, seed):
    g = played(seed=seed)
    assert g.added_time_frames[0] > 0
    assert g.added_time_frames[1] > 0
    expected = REGULATION_FRAMES + sum(g.added_time_frames)
    assert g.match_clock_frames >= expected


@pytest.mark.slow
def test_added_time_is_capped(played):
    from gameEngine import ADDED_TIME_MAX_FRAMES

    g = played()
    for half in g.added_time_frames:
        assert 0 < half <= ADDED_TIME_MAX_FRAMES, f"{half} frames is outside a believable range"


@pytest.mark.slow
def test_added_time_is_deterministic_for_a_seed(make_match):
    a, b = make_match(seed=31), make_match(seed=31)
    a.run_match(max_steps=REGULATION_FRAMES, render=False)
    b.run_match(max_steps=REGULATION_FRAMES, render=False)
    assert a.added_time_frames == b.added_time_frames


def test_more_stoppages_means_more_added_time(make_match):
    """Drives _compute_added_time directly -- a full match can't be forced to
    have a specific number of stoppages."""
    quiet = make_match(seed=5)
    busy = make_match(seed=5)

    busy.scores = [3, 2]
    busy.restart_count = 12
    busy.post_hits = 3

    assert busy._compute_added_time() > quiet._compute_added_time()


def test_added_time_only_counts_the_current_half(make_match):
    """Second-half added time must not re-count first-half stoppages."""
    g = make_match(seed=5)
    g.scores = [2, 1]
    g.restart_count = 8
    first = g._compute_added_time()
    second = g._compute_added_time()  # nothing new happened in between
    assert second < first


@pytest.mark.slow
def test_every_player_is_credited_with_the_match(played):
    g = played()
    assert all(p.statistics["matches_played"] == 1 for p in g.all_players)
