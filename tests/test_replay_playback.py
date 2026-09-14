"""The replay has to be *playable*, not just well-formed.

MatchPlayback.gd clamps its playback cursor to the last sample's tick:

    playback_tick += delta * TICKS_PER_SECOND
    if playback_tick > last_tick:
        playback_tick = last_tick

and only dispatches events at or before that cursor:

    while events[i]["tick"] <= current_tick:

So any event recorded past the final sample is unreachable. For FULLTIME
that means the client sits on the last frame forever and never transitions
to the result screen -- the match visibly never ends.

This bit us for real: samples are only written every sample_interval_ticks,
and once stoppage time was added the final whistle stopped landing on a
multiple of that, so every single match ended up unplayable.
"""

import pytest

from replay import ActionType, decode_replay

REGULATION_FRAMES = 10800


@pytest.fixture(scope="module")
def replays():
    """A handful of full matches, decoded. ~9s each, so built once."""
    import copy

    import conftest as C
    from gameEngine import game

    pm = C.PackManager(C.PACK_DATABASE, seed=55)
    pool = []
    while len(pool) < 400:
        pool += pm.open_pack(3)
    home, away = C._assemble_xi(pool), C._assemble_xi(pool)

    out = []
    for seed in (7, 42, 2024):
        g = game(
            C.Team("H", copy.deepcopy(home)),
            C.Team("A", copy.deepcopy(away)),
            seed=seed,
            record_replay=True,
        )
        g.run_match(max_steps=REGULATION_FRAMES, render=False)
        out.append((seed, g, decode_replay(g.replay.encode())))
    return out


@pytest.mark.slow
def test_fulltime_is_reachable_by_playback(replays):
    """The regression: the client must actually be able to reach FULL TIME."""
    for seed, _g, d in replays:
        last_sample = d["samples"][-1]["tick"]
        fulltime = [e["tick"] for e in d["events"] if e["type"] == int(ActionType.FULLTIME)]
        assert fulltime, f"seed {seed}: no FULLTIME event at all"
        assert fulltime[0] <= last_sample, (
            f"seed {seed}: FULLTIME at tick {fulltime[0]} is past the last sample "
            f"({last_sample}) -- playback can never fire it and the match never ends"
        )


@pytest.mark.slow
def test_no_event_is_stranded_past_the_last_sample(replays):
    """Same trap, generalised: nothing should be unreachable."""
    names = {int(a): a.name for a in ActionType}
    for seed, _g, d in replays:
        last_sample = d["samples"][-1]["tick"]
        stranded = [(names.get(e["type"], e["type"]), e["tick"]) for e in d["events"] if e["tick"] > last_sample]
        assert not stranded, f"seed {seed}: unreachable events {stranded} (last sample {last_sample})"


@pytest.mark.slow
def test_events_are_in_tick_order(replays):
    """Playback walks events with a single forward index and never rewinds."""
    for seed, _g, d in replays:
        ticks = [e["tick"] for e in d["events"]]
        assert ticks == sorted(ticks), f"seed {seed}: events out of order"


@pytest.mark.slow
def test_samples_are_in_tick_order(replays):
    for seed, _g, d in replays:
        ticks = [s["tick"] for s in d["samples"]]
        assert ticks == sorted(ticks), f"seed {seed}: samples out of order"


@pytest.mark.slow
def test_halftime_and_fulltime_both_present_once(replays):
    for seed, _g, d in replays:
        for action in (ActionType.HALFTIME, ActionType.FULLTIME):
            count = sum(1 for e in d["events"] if e["type"] == int(action))
            assert count == 1, f"seed {seed}: {action.name} appears {count} times"


@pytest.mark.slow
def test_fulltime_is_the_last_event(replays):
    for seed, _g, d in replays:
        assert d["events"][-1]["type"] == int(ActionType.FULLTIME), f"seed {seed}"


@pytest.mark.slow
def test_goal_events_match_the_final_score(replays):
    for seed, g, d in replays:
        goals = sum(1 for e in d["events"] if e["type"] == int(ActionType.GOAL))
        assert goals == sum(g.scores), f"seed {seed}: {goals} GOAL events vs score {g.scores}"


def test_replay_wire_format_is_unchanged():
    """ReplayReader.gd parses these sizes by hand -- changing any of them
    silently misparses every replay on the client."""
    import replay as r

    assert r.MAGIC == b"PFRP"
    assert r.FORMAT_VERSION == 1
    assert r._HEADER_SIZE == 15
    assert r._SAMPLE_SIZE == 191
    assert r._EVENT_SIZE == 7
    assert r.POSITION_SCALE == 100.0


def test_action_type_values_match_the_client():
    """The Godot enum is hand-mirrored and never validated at runtime."""
    from pathlib import Path

    gd = (Path(__file__).resolve().parent.parent / "mobile/scripts/data/ReplayReader.gd").read_text()
    for action in ActionType:
        assert f"{action.name} = {int(action)}" in gd, f"{action.name} missing/renumbered in ReplayReader.gd"
