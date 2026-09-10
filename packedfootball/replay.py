"""Compact match replay format.

Sparse position/velocity snapshots plus discrete action events -- small
enough to ship over the wire, and rich enough (velocity, not just position)
for a client to interpolate smoothly between samples instead of linearly
sliding a dot from point to point.

Recording is purely additive: gameEngine.py calls .snapshot()/.event() at
state-transition points that already exist in the simulation. Nothing here
reads randomness or influences simulation control flow, so it cannot affect
the seeded determinism the rest of the engine relies on.

Wire format:
    header:  magic(4s) version(B) sample_interval_ticks(H) num_samples(I) num_events(I)
    samples: tick(I) + 22x(x,y,vx,vy) + ball(x,y,vx,vy,height) + ball_controller(b)
             -- all positions/velocities as int16 fixed-point (POSITION_SCALE)
    events:  tick(I) type(B) player_idx(b) team(b)

Player/team display names are never in this stream -- a client already has
the roster from the match-start payload and looks names up by index.
"""

from __future__ import annotations

import struct
from enum import IntEnum

MAGIC = b"PFRP"
FORMAT_VERSION = 1
POSITION_SCALE = 100.0  # int16 fixed-point: e.g. 12.34 units <-> 1234 on the wire

_HEADER_FMT = "<4sBHII"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_SAMPLE_FMT = "<I" + "hhhh" * 22 + "hhhhh" + "b"
_SAMPLE_SIZE = struct.calcsize(_SAMPLE_FMT)
_EVENT_FMT = "<IBbb"
_EVENT_SIZE = struct.calcsize(_EVENT_FMT)


class ActionType(IntEnum):
    PASS = 0
    CLEARANCE = 1
    CROSS = 2
    SHOOT = 3
    TACKLE = 4
    ANKLEBREAKER = 5
    RECEIVED_PASS = 6
    SAVE = 7
    GOAL = 8
    KICKOFF = 9
    THROW_IN = 10
    CORNER = 11
    GOAL_KICK = 12
    HALFTIME = 13
    FULLTIME = 14


def _q(value: float) -> int:
    """Quantizes a float onto the int16 fixed-point range used on the wire."""
    return max(-32767, min(32767, int(round(value * POSITION_SCALE))))


class ReplayRecorder:
    def __init__(self, sample_interval_ticks: int = 6):
        self.sample_interval_ticks = sample_interval_ticks
        self._samples: list[tuple] = []
        self._events: list[tuple] = []

    def snapshot(self, tick: int, positions, velocity, ball, ball_controller: int) -> None:
        values = [tick]
        for i in range(22):
            values.append(_q(positions[i][0]))
            values.append(_q(positions[i][1]))
            values.append(_q(velocity[i][0]))
            values.append(_q(velocity[i][1]))
        values.append(_q(ball[0]))
        values.append(_q(ball[1]))
        values.append(_q(ball[2]))
        values.append(_q(ball[3]))
        values.append(_q(ball[4]))  # "height" -- see gameEngine.py's ball array comment
        values.append(int(ball_controller))
        self._samples.append(tuple(values))

    def event(self, tick: int, action_type: ActionType, player_idx: int = -1, team: int = -1) -> None:
        self._events.append((tick, int(action_type), player_idx, team))

    def encode(self) -> bytes:
        header = struct.pack(
            _HEADER_FMT, MAGIC, FORMAT_VERSION, self.sample_interval_ticks, len(self._samples), len(self._events)
        )
        body = bytearray(header)
        for values in self._samples:
            body += struct.pack(_SAMPLE_FMT, *values)
        for values in self._events:
            body += struct.pack(_EVENT_FMT, *values)
        return bytes(body)


def decode_replay(data: bytes) -> dict:
    """Reference decoder. Godot's GDScript reader is the real consumer of
    this format; this exists so the format can be verified (round-tripped,
    inspected) without needing Godot at all.
    """
    magic, version, interval, num_samples, num_events = struct.unpack_from(_HEADER_FMT, data, 0)
    if magic != MAGIC:
        raise ValueError(f"Bad replay magic: {magic!r}")
    if version != FORMAT_VERSION:
        raise ValueError(f"Unsupported replay format version: {version}")

    offset = _HEADER_SIZE
    samples = []
    for _ in range(num_samples):
        values = struct.unpack_from(_SAMPLE_FMT, data, offset)
        offset += _SAMPLE_SIZE
        tick = values[0]
        players = []
        idx = 1
        for _ in range(22):
            x, y, vx, vy = values[idx : idx + 4]
            players.append(
                {"x": x / POSITION_SCALE, "y": y / POSITION_SCALE, "vx": vx / POSITION_SCALE, "vy": vy / POSITION_SCALE}
            )
            idx += 4
        bx, by, bvx, bvy, bheight = values[idx : idx + 5]
        ball_controller = values[idx + 5]
        samples.append(
            {
                "tick": tick,
                "players": players,
                "ball": {
                    "x": bx / POSITION_SCALE,
                    "y": by / POSITION_SCALE,
                    "vx": bvx / POSITION_SCALE,
                    "vy": bvy / POSITION_SCALE,
                    "height": bheight / POSITION_SCALE,
                },
                "ball_controller": ball_controller,
            }
        )

    events = []
    for _ in range(num_events):
        tick, action_type, player_idx, team = struct.unpack_from(_EVENT_FMT, data, offset)
        offset += _EVENT_SIZE
        events.append({"tick": tick, "type": ActionType(action_type), "player_idx": player_idx, "team": team})

    return {"sample_interval_ticks": interval, "samples": samples, "events": events}
