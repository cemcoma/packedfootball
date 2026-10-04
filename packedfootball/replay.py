"""Compact match replay format.

Sparse position/velocity snapshots plus discrete action events -- small
enough to ship over the wire, and rich enough (velocity, not just position)
for a client to interpolate smoothly between samples instead of linearly
sliding a dot from point to point.

Recording is purely additive: gameEngine.py calls .snapshot()/.event() at
state-transition points that already exist in the simulation. Nothing here
reads randomness or influences simulation control flow, so it cannot affect
the seeded determinism the rest of the engine relies on.

Wire format v1 (encode):
    header:  magic(4s) version(B) sample_interval_ticks(H) num_samples(I) num_events(I)
    samples: tick(I) + 22x(x,y,vx,vy) + ball(x,y,vx,vy,height) + ball_controller(b)
             -- all positions/velocities as int16 fixed-point (POSITION_SCALE)
    events:  tick(I) type(B) player_idx(b) team(b)

Wire format v2 (encode_v2) -- the same data laid out to compress, then gzipped
(~3x smaller than v1 on the wire). Sent only to clients that ask for it:
    header:  magic(4s) version(B) sample_interval_ticks(H) num_samples(I) num_events(I)
             pos_scale(H) vel_scale(H)
    ticks:   num_samples x u16, each the delta from the previous tick
    ctrl:    num_samples x ball_controller(b)
    chans:   V2_CHANNELS channels of num_samples int16 deltas (mod 2^16), channel
             after channel; every low byte first, then every high byte
             order: 22x(x,y) @pos_scale | ball x,y,height,vx,vy @POSITION_SCALE
                    | 22x(vx,vy) @vel_scale
    events:  as v1

A GOAL event's team is the side that scored and player_idx the credited
scorer -- or, for an own goal, the player who put it in, whose side then
differs from team (gameEngine._award_goal; the client reads that mismatch).

Player/team display names are never in this stream -- a client already has
the roster from the match-start payload and looks names up by index.
"""

from __future__ import annotations

import gzip
import struct

import numpy as np
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

FORMAT_VERSION_V2 = 2
V2_POS_SCALE = 50  # 0.02 units: sub-pixel at any zoom the client draws
V2_VEL_SCALE = 4   # 0.25 units/s: moves a Hermite curve by ~0.002 units
_V2_HEADER_FMT = "<4sBHIIHH"
_V2_HEADER_SIZE = struct.calcsize(_V2_HEADER_FMT)
_GZIP_MAGIC = b"\x1f\x8b"

# Columns of a v1 sample (tick dropped) in v2 channel order, and each one's scale.
_V1_BALL = 22 * 4  # ball x, y, vx, vy, height follow the 22 players
_V2_COLUMNS = (
    [p * 4 + k for p in range(22) for k in (0, 1)]
    + [_V1_BALL + k for k in (0, 1, 4, 2, 3)]
    + [p * 4 + k for p in range(22) for k in (2, 3)]
)
V2_CHANNELS = len(_V2_COLUMNS)


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
    HEADER = 15
    SHOT_OFF_TARGET = 16
    FOUL = 17
    FREE_KICK = 18
    PENALTY = 19
    SAVE_FAILED = 20
    FREE_KICK_SHOT = 21
    THROW_TAKEN = 22
    BLOCK = 23          # a free kick meeting a body (gameEngine._fk_flight_tick)
    OFFSIDE = 24        # flagged: player_idx is the man caught offside (gameEngine._call_offside)


def _q(value: float) -> int:
    """Quantizes a float onto the int16 fixed-point range used on the wire."""
    return max(-32767, min(32767, int(round(value * POSITION_SCALE))))


class ReplayRecorder:
    def __init__(self, sample_interval_ticks: int = 6):
        self.sample_interval_ticks = sample_interval_ticks
        self._samples: list[tuple] = []
        self._events: list[tuple] = []

    def snapshot(self, tick: int, positions, velocity, ball, ball_controller: int) -> None:
        # Same quantisation as _q, done on the whole sample at once: the
        # per-player layout is x, y, vx, vy, then the ball's x, y, vx, vy,
        # height (see gameEngine.py's ball array comment). The [:5] drops the
        # ball's vz: the wire carries the height it reached, not that velocity.
        # np.rint rounds
        # half-to-even exactly as Python's round() does.
        per_player = np.concatenate([np.asarray(positions, dtype=float), np.asarray(velocity, dtype=float)], axis=1)
        raw = np.concatenate([per_player.ravel(), np.asarray(ball[:5], dtype=float)]) * POSITION_SCALE
        quantised = np.clip(np.rint(raw), -32767, 32767).astype(int).tolist()
        self._samples.append((tick, *quantised, int(ball_controller)))

    def event(self, tick: int, action_type: ActionType, player_idx: int = -1, team: int = -1) -> None:
        self._events.append((tick, int(action_type), player_idx, team))

    def retype_last_shot_as_on_target(self, player_idx: int) -> None:
        """Turns that player's most recent strike into a SHOOT if it went down
        as SHOT_OFF_TARGET -- a goal is on target whatever the crossing
        prediction said when it was struck."""
        strikes = {int(ActionType.SHOOT), int(ActionType.SHOT_OFF_TARGET), int(ActionType.HEADER)}
        for i in range(len(self._events) - 1, -1, -1):
            tick, action, idx, team = self._events[i]
            if idx != player_idx or action not in strikes:
                continue
            if action == int(ActionType.SHOT_OFF_TARGET):
                self._events[i] = (tick, int(ActionType.SHOOT), idx, team)
            return

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

    def encode_v2(self, pos_scale: int = V2_POS_SCALE, vel_scale: int = V2_VEL_SCALE) -> bytes:
        samples = np.array(self._samples, dtype=np.int64).reshape(-1, 2 + 22 * 4 + 5)
        ticks, values, controllers = samples[:, 0], samples[:, 1:-1], samples[:, -1]
        tick_deltas = np.diff(ticks, prepend=0)
        if tick_deltas.size and (tick_deltas.min() < 0 or tick_deltas.max() > 0xFFFF):
            raise ValueError("replay ticks must rise by at most 65535 per sample")

        scales = np.array([pos_scale] * 44 + [POSITION_SCALE] * 5 + [vel_scale] * 44, dtype=float) / POSITION_SCALE
        channels = np.rint(values[:, _V2_COLUMNS] * scales).astype(np.int64)
        deltas = (np.diff(channels, axis=0, prepend=0) & 0xFFFF).T.astype("<u2")
        byte_planes = np.ascontiguousarray(deltas).view(np.uint8).reshape(-1, 2)

        header = struct.pack(
            _V2_HEADER_FMT, MAGIC, FORMAT_VERSION_V2, self.sample_interval_ticks,
            len(samples), len(self._events), pos_scale, vel_scale,
        )
        body = b"".join([
            header,
            tick_deltas.astype("<u2").tobytes(),
            controllers.astype(np.int8).tobytes(),
            byte_planes[:, 0].tobytes(),
            byte_planes[:, 1].tobytes(),
            b"".join(struct.pack(_EVENT_FMT, *values) for values in self._events),
        ])
        return gzip.compress(body, compresslevel=6, mtime=0)


def decode_replay(data: bytes) -> dict:
    """Reference decoder. Godot's GDScript reader is the real consumer of
    this format; this exists so the format can be verified (round-tripped,
    inspected) without needing Godot at all.
    """
    if data[:2] == _GZIP_MAGIC:
        data = gzip.decompress(data)
    magic, version, interval, num_samples, num_events = struct.unpack_from(_HEADER_FMT, data, 0)
    if magic != MAGIC:
        raise ValueError(f"Bad replay magic: {magic!r}")
    if version == FORMAT_VERSION_V2:
        return _decode_v2(data)
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

    return {"sample_interval_ticks": interval, "samples": samples, "events": _decode_events(data, offset, num_events)}


def _decode_events(data: bytes, offset: int, num_events: int) -> list[dict]:
    events = []
    for _ in range(num_events):
        tick, action_type, player_idx, team = struct.unpack_from(_EVENT_FMT, data, offset)
        offset += _EVENT_SIZE
        events.append({"tick": tick, "type": ActionType(action_type), "player_idx": player_idx, "team": team})
    return events


def _decode_v2(data: bytes) -> dict:
    _, _, interval, n, num_events, pos_scale, vel_scale = struct.unpack_from(_V2_HEADER_FMT, data, 0)
    offset = _V2_HEADER_SIZE
    ticks = np.cumsum(np.frombuffer(data, "<u2", n, offset).astype(np.int64))
    offset += 2 * n
    controllers = np.frombuffer(data, np.int8, n, offset)
    offset += n
    plane = V2_CHANNELS * n
    low = np.frombuffer(data, np.uint8, plane, offset).astype(np.int64)
    high = np.frombuffer(data, np.uint8, plane, offset + plane).astype(np.int64)
    offset += 2 * plane
    deltas = (low | (high << 8)).reshape(V2_CHANNELS, n)
    channels = np.cumsum(deltas, axis=1) & 0xFFFF
    channels = np.where(channels >= 0x8000, channels - 0x10000, channels).T.tolist()

    samples = []
    for i in range(n):
        c = channels[i]
        players = [
            {"x": c[2 * p] / pos_scale, "y": c[2 * p + 1] / pos_scale,
             "vx": c[49 + 2 * p] / vel_scale, "vy": c[50 + 2 * p] / vel_scale}
            for p in range(22)
        ]
        bx, by, bheight, bvx, bvy = (v / POSITION_SCALE for v in c[44:49])
        samples.append({
            "tick": int(ticks[i]),
            "players": players,
            "ball": {"x": bx, "y": by, "vx": bvx, "vy": bvy, "height": bheight},
            "ball_controller": int(controllers[i]),
        })
    return {"sample_interval_ticks": interval, "samples": samples, "events": _decode_events(data, offset, num_events)}
