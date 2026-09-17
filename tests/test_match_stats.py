"""Phase 4: match statistics and player ratings.

Before this, a card tracked exactly three numbers -- goals, assists and
matches_played. The engine already emitted SHOOT/PASS/TACKLE/SAVE events into
the replay stream but nothing ever counted them, and there was no rating
concept anywhere in the repo.
"""

import pytest

from player.player import DEFAULT_STATISTICS, MATCH_STAT_FIELDS

REGULATION_FRAMES = 10800
KEEPERS = (0, 11)


@pytest.fixture(scope="module")
def finished(request):
    """One full match, shared across this module -- it takes ~9s."""
    import copy
    import conftest as C
    from gameEngine import game

    pm = C.PackManager(C.PACK_DATABASE, seed=55)
    pool = []
    while len(pool) < 400:
        pool += pm.open_pack(2)
    home, away = C._assemble_xi(pool), C._assemble_xi(pool)
    g = game(C.Team("H", copy.deepcopy(home)), C.Team("A", copy.deepcopy(away)), seed=7)
    g.run_match(max_steps=REGULATION_FRAMES, render=False)
    return g


def test_new_cards_start_with_every_statistic(rosters):
    home, _ = rosters
    for key in DEFAULT_STATISTICS:
        assert key in home[0].statistics, f"missing {key}"


@pytest.mark.slow
def test_a_match_produces_shots_and_passes(finished):
    total_shots = sum(s["shots"] for s in finished.match_stats)
    total_passes = sum(s["passes"] for s in finished.match_stats)
    assert total_shots > 0
    assert total_passes > 0


@pytest.mark.slow
def test_completed_passes_never_exceed_passes(finished):
    for i, s in enumerate(finished.match_stats):
        assert s["passes_completed"] <= s["passes"], f"player {i}"


@pytest.mark.slow
def test_shots_on_target_never_exceed_shots(finished):
    for i, s in enumerate(finished.match_stats):
        assert s["shots_on_target"] <= s["shots"], f"player {i}"


@pytest.mark.slow
def test_tackles_won_never_exceed_tackles(finished):
    for i, s in enumerate(finished.match_stats):
        assert s["tackles_won"] <= s["tackles"], f"player {i}"


@pytest.mark.slow
def test_goals_conceded_matches_the_scoreline(finished):
    assert finished.match_stats[11]["goals_conceded"] == finished.scores[0]
    assert finished.match_stats[0]["goals_conceded"] == finished.scores[1]


@pytest.mark.slow
def test_clean_sheet_only_when_nothing_was_conceded(finished):
    for keeper in KEEPERS:
        conceded = finished.match_stats[keeper]["goals_conceded"]
        sheet = finished.match_stats[keeper]["clean_sheets"]
        assert sheet == (1 if conceded == 0 else 0)


@pytest.mark.slow
def test_outfield_players_never_get_clean_sheets(finished):
    for i in range(22):
        if i not in KEEPERS:
            assert finished.match_stats[i]["clean_sheets"] == 0


@pytest.mark.slow
def test_career_totals_absorb_the_match(finished):
    for i in range(22):
        career = finished.all_players[i].statistics
        for field in MATCH_STAT_FIELDS:
            assert career[field] >= finished.match_stats[i][field]


@pytest.mark.slow
def test_every_player_is_rated(finished):
    for p in finished.all_players:
        assert p.statistics["rating_count"] == 1
        assert 1.0 <= p.average_rating() <= 10.0


@pytest.mark.slow
def test_ratings_are_not_all_identical(finished):
    ratings = {p.average_rating() for p in finished.all_players}
    assert len(ratings) > 1, "rating is not responding to what players did"


def test_a_scorer_outrates_a_baseline_player(match):
    """Rating is computed from THIS match, not career totals."""
    match._match_goals[9] = 2
    scorer = match._match_rating(9)
    plain = match._match_rating(8)
    assert scorer > plain


def test_career_goals_do_not_inflate_a_match_rating(match):
    """A veteran must not start every match on a 10.0."""
    match.all_players[8].statistics["goals"] = 250
    match.all_players[8].statistics["assists"] = 300
    assert match._match_rating(8) == pytest.approx(match._match_rating(7), abs=0.5)


def test_keeper_rating_rewards_saves_and_punishes_goals(make_match):
    saver = make_match()
    saver.match_stats[0]["saves"] = 6
    beaten = make_match()
    beaten.match_stats[0]["goals_conceded"] = 4
    assert saver._match_rating(0) > beaten._match_rating(0)


def test_average_rating_is_zero_before_playing(rosters):
    home, _ = rosters
    assert home[3].average_rating() == 0.0


def test_average_rating_averages(rosters):
    home, _ = rosters
    p = home[3]
    p.record_match({f: 0 for f in MATCH_STAT_FIELDS}, 8.0)
    p.record_match({f: 0 for f in MATCH_STAT_FIELDS}, 6.0)
    assert p.average_rating() == pytest.approx(7.0)


def test_a_card_round_trips_through_firestore_fields(rosters):
    """Every statistic survives save -> load unchanged."""
    from game_state import fields_to_player, player_to_fields
    from packEngine import PLAYER_CLASS_MAP
    from player.classes.midfielder import Midfielder

    home, _ = rosters
    p = home[5]
    p.statistics["goals"] = 3
    p.statistics["saves"] = 2
    p.statistics["rating_sum"] = 14.5
    p.statistics["rating_count"] = 2

    restored = fields_to_player(player_to_fields(p), PLAYER_CLASS_MAP, Midfielder)

    assert restored.statistics == p.statistics
    assert restored.average_rating() == pytest.approx(7.25)
    for key in DEFAULT_STATISTICS:
        assert key in restored.statistics, f"{key} lost on load"


def test_loading_a_card_with_no_statistics_fails_loudly():
    """Backward compatibility was dropped deliberately -- old-format cards
    were deleted rather than migrated, so a doc without statistics is a bug
    and must not load silently with a half-populated dict."""
    from dataclasses import asdict

    from game_state import fields_to_player
    from packEngine import PLAYER_CLASS_MAP
    from player.classes.midfielder import Midfielder
    from player.player import Attributes

    legacy = {
        "fname": "Old",
        "lname": "Card",
        "tier": "bronze",
        "position": "CM",
        "country": "Nowhere",
        "hometown": "Nowhere",
        "attributes": asdict(Attributes()),
        "appearance": {},
        # no "statistics"
    }
    with pytest.raises(KeyError):
        fields_to_player(legacy, PLAYER_CLASS_MAP, Midfielder)
