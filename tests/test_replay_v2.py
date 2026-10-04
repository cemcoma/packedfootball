"""Replay format v2 carries the same match as v1, within its quantisation.

v2 is what current clients ask for (X-Replay-Format: 2); v1 stays the default
for installs that don't. ReplayReader.gd mirrors _decode_v2 -- `make
replay-check` runs the same comparison through Godot.
"""

from __future__ import annotations

import base64
import copy
import gzip

import numpy as np
import pytest

from conftest import Team
from deps import replay_format
from engine import generate_starter_roster
from gameEngine import game
from replay import V2_POS_SCALE, V2_VEL_SCALE, ReplayRecorder, decode_replay
from services.match import run_match

POS_TOLERANCE = 0.5 / V2_POS_SCALE + 1e-9
VEL_TOLERANCE = 0.5 / V2_VEL_SCALE + 1e-9


@pytest.fixture(scope="module")
def short_match(_roster_template):
    home, away = (copy.deepcopy(xi) for xi in _roster_template)
    match = game(Team("Home", home), Team("Away", away), seed=11, record_replay=True)
    match.run_match(max_steps=1200, render=False)
    return match


def test_v2_is_gzipped_and_much_smaller(short_match):
    v1, v2 = short_match.replay.encode(), short_match.replay.encode_v2()
    assert v2[:2] == b"\x1f\x8b"
    assert len(v2) < len(v1) / 2.5


def test_v2_decodes_to_the_v1_match(short_match):
    a = decode_replay(short_match.replay.encode())
    b = decode_replay(short_match.replay.encode_v2())
    assert a["sample_interval_ticks"] == b["sample_interval_ticks"]
    assert a["events"] == b["events"]
    assert len(a["samples"]) == len(b["samples"]) > 0
    for sa, sb in zip(a["samples"], b["samples"]):
        assert sa["tick"] == sb["tick"]
        assert sa["ball_controller"] == sb["ball_controller"]
        assert sa["ball"] == sb["ball"]  # the ball keeps v1's precision
        for pa, pb in zip(sa["players"], sb["players"]):
            assert abs(pa["x"] - pb["x"]) <= POS_TOLERANCE and abs(pa["y"] - pb["y"]) <= POS_TOLERANCE
            assert abs(pa["vx"] - pb["vx"]) <= VEL_TOLERANCE and abs(pa["vy"] - pb["vy"]) <= VEL_TOLERANCE


def test_deltas_wrap_across_the_int16_range():
    """A jump wider than int16 (here the ball, -320 to +320) must come back exact."""
    recorder = ReplayRecorder()
    positions, velocity = np.zeros((22, 2)), np.zeros((22, 2))
    for tick, ball_x in ((0, -320.0), (6, 320.0), (12, -320.0)):
        recorder.snapshot(tick, positions, velocity, np.array([ball_x, 50.0, 0.0, 0.0, 0.0, 0.0]), -1)
    samples = decode_replay(recorder.encode_v2())["samples"]
    assert [s["ball"]["x"] for s in samples] == [-320.0, 320.0, -320.0]


def test_empty_replay_round_trips():
    decoded = decode_replay(ReplayRecorder().encode_v2())
    assert decoded["samples"] == [] and decoded["events"] == []


def test_only_an_explicit_2_gets_v2():
    assert replay_format("2") == 2
    assert replay_format(" 2 ") == 2
    for header in ("1", "", "3", "v2"):
        assert replay_format(header) == 1


@pytest.mark.slow
def test_run_match_serves_the_format_asked_for():
    def profile(seed):
        return {"display_name": "X", "formation": "4-4-2", "roster": generate_starter_roster("4-4-2", "gold", seed=seed)}

    v1 = base64.b64decode(run_match(profile(1), profile(2), seed=5)["replay"])
    v2 = base64.b64decode(run_match(profile(1), profile(2), seed=5, replay_format=2)["replay"])
    assert v1[:4] == b"PFRP" and gzip.decompress(v2)[:5] == b"PFRP\x02"
    assert len(decode_replay(v1)["samples"]) == len(decode_replay(v2)["samples"])
