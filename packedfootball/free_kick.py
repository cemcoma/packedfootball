"""Direct free kicks as physics: a struck ball with spin, a wall that is only in
the way if the ball hits it, and a keeper who has to get there in time.

Pure (numpy + game_config) so a match and a free-kick minigame fly the same
ball. The caller owns the ball array (x, y, vx, vy, height, vz), the player
arrays and the clock; FreeKickFlight.step() advances one tick of it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from game_config import (
    BALL_AIR_FRICTION,
    BALL_GRAVITY,
    BALL_GROUND_FRICTION,
    FK_AIM_ERROR_DEG,
    FK_AIM_HEIGHT_AROUND,
    FK_AIM_HEIGHT_OVER,
    FK_AIM_INSET,
    FK_BODY_RADIUS,
    FK_BODY_RESTITUTION,
    FK_CATCH_SPEED,
    FK_KEEPER_ARM_REACH,
    FK_KEEPER_CATCH_REACH,
    FK_KEEPER_DIVE_SPEED,
    FK_KEEPER_EYE_HEIGHT,
    FK_KEEPER_REACTION,
    FK_KEEPER_REACTION_JITTER,
    FK_LIFT_ERROR,
    FK_MAGNUS_SIDE,
    FK_MAGNUS_TOP,
    FK_PARRY_RESTITUTION,
    FK_SIDE_SPIN,
    FK_SPIN_DECAY,
    FK_SPIN_ERROR,
    FK_TOP_SPIN,
    FREE_KICK_SHOT_SPEED,
    GOAL_HEIGHT,
    GOAL_POST_RADIUS,
    GOAL_WIDTH,
    PITCH_WIDTH,
    WALL_PLAYERS,
    stat_ability,
)

SIM_DT = 1.0 / 60.0
SIM_MAX_SECONDS = 3.0
# Lateral half-width of a wall: its outer bodies' centres plus their radius.
WALL_HALF_WIDTH = (WALL_PLAYERS - 1) / 2.0 + FK_BODY_RADIUS


@dataclass
class FreeKickStrike:
    direction: np.ndarray   # unit, horizontal
    speed: float
    vz: float
    spin: np.ndarray        # [side, top]; side curls left of travel when positive
    technique: str          # "over" / "around" / "intent"
    aim: tuple              # (x, z) on the goal line, before execution error


def _lerp(pair, t: float) -> float:
    return pair[0] + (pair[1] - pair[0]) * t


def goal_inner_bounds() -> tuple[float, float]:
    centre = PITCH_WIDTH / 2.0
    return centre - GOAL_WIDTH / 2.0 + GOAL_POST_RADIUS, centre + GOAL_WIDTH / 2.0 - GOAL_POST_RADIUS


def advance(ball, spin, dt: float = SIM_DT) -> None:
    """One tick of flight, in place. Same order as gameEngine.tick()'s loose
    ball; on top of it, side spin turns the velocity and top spin pulls it down."""
    vx, vy, z, vz = float(ball[2]), float(ball[3]), float(ball[4]), float(ball[5])
    ball[0] += vx * dt
    ball[1] += vy * dt
    speed = math.hypot(vx, vy)
    if (z > 0.0 or vz > 0.0) and speed > 1e-6:
        turn = FK_MAGNUS_SIDE * float(spin[0]) * dt
        if turn:
            c, s = math.cos(turn), math.sin(turn)
            vx, vy = vx * c - vy * s, vx * s + vy * c
        vz -= FK_MAGNUS_TOP * float(spin[1]) * speed * dt
    vz -= BALL_GRAVITY * dt
    z += vz * dt
    if z <= 0.0:
        z, vz = 0.0, 0.0
        spin[0] = spin[1] = 0.0   # it is rolling now
    friction = (BALL_AIR_FRICTION if z > 0.0 else BALL_GROUND_FRICTION) ** dt
    vx *= friction
    vy *= friction
    ball[2] = 0.0 if abs(vx) < 0.1 else vx
    ball[3] = 0.0 if abs(vy) < 0.1 else vy
    ball[4] = z
    ball[5] = vz
    decay = FK_SPIN_DECAY ** dt
    spin[0] = float(spin[0]) * decay
    spin[1] = float(spin[1]) * decay


def cross_plane(ball, spin, point, normal, max_seconds: float = SIM_MAX_SECONDS):
    """Fly a copy of the ball until it crosses the plane through `point` with
    `normal` (heading along it). Returns {"x", "y", "z", "time", "speed"}, or
    None if it stops or turns away first."""
    b = [float(v) for v in ball]
    sp = [float(spin[0]), float(spin[1])]
    px, py = float(point[0]), float(point[1])
    nx, ny = float(normal[0]), float(normal[1])
    before = (b[0] - px) * nx + (b[1] - py) * ny
    if before >= 0.0:
        return None
    t = 0.0
    while t < max_seconds:
        prev = (b[0], b[1], b[4])
        advance(b, sp)
        t += SIM_DT
        after = (b[0] - px) * nx + (b[1] - py) * ny
        if after >= 0.0:
            f = before / (before - after) if before != after else 1.0
            return {
                "x": prev[0] + f * (b[0] - prev[0]),
                "y": prev[1] + f * (b[1] - prev[1]),
                "z": prev[2] + f * (b[4] - prev[2]),
                "time": t - SIM_DT + f * SIM_DT,
                "speed": math.hypot(b[2], b[3]),
            }
        if b[2] == 0.0 and b[3] == 0.0:
            return None
        before = after
    return None


def predict_crossing(ball, spin, goal_y: float):
    """Where this ball crosses the goal line at goal_y, spin and all. Same
    shape as gameEngine.predict_goal_crossing, which assumes a straight line."""
    forward = 1.0 if goal_y > float(ball[1]) else -1.0
    hit = cross_plane(ball, spin, (0.0, goal_y), (0.0, forward))
    if hit is None:
        return None
    inner_min, inner_max = goal_inner_bounds()
    on_target = inner_min <= hit["x"] <= inner_max and hit["z"] < GOAL_HEIGHT
    return {"x": hit["x"], "z": hit["z"], "time": hit["time"], "on_target": on_target}


def segment_meets_circle(start, end, centre, radius: float) -> float | None:
    """How far along start->end the path first touches the circle, as a
    fraction in [0, 1], or None if it misses."""
    d = np.asarray(end, dtype=float) - np.asarray(start, dtype=float)
    f = np.asarray(start, dtype=float) - np.asarray(centre, dtype=float)
    a = float(np.dot(d, d))
    if a < 1e-12:
        return None
    b = 2.0 * float(np.dot(f, d))
    c = float(np.dot(f, f)) - radius * radius
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    root = math.sqrt(disc)
    for t in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a)):
        if 0.0 <= t <= 1.0:
            return t
    return None


def solve_launch(spot, target, goal_y: float, speed: float, spin):
    """Direction and vz that put a ball struck at `speed` with `spin` through
    target (x, z) on the goal line. Fixed-point on the aim point and vz."""
    spot = np.asarray(spot, dtype=float)
    aim_x = float(target[0])
    flight = abs(goal_y - spot[1]) / max(speed, 1e-6)
    vz = (float(target[1]) + 0.5 * BALL_GRAVITY * flight * flight) / max(flight, 1e-3)
    unit = np.array([0.0, 1.0 if goal_y > spot[1] else -1.0])
    for _ in range(10):
        vec = np.array([aim_x, goal_y]) - spot
        unit = vec / max(float(np.hypot(*vec)), 1e-9)
        ball = [spot[0], spot[1], unit[0] * speed, unit[1] * speed, 0.0, vz]
        hit = predict_crossing(ball, spin, goal_y)
        if hit is None:
            vz += 1.0
            continue
        err_x = float(target[0]) - hit["x"]
        err_z = float(target[1]) - hit["z"]
        if abs(err_x) < 0.02 and abs(err_z) < 0.02:
            break
        aim_x += err_x
        vz += err_z / max(hit["time"], 0.2)
    return unit, vz


def _wall_margin(spot, unit, speed, vz, spin, wall_centre, wall_reach) -> float:
    """How clearly the nominal strike beats the wall: over it or past its end."""
    if wall_centre is None:
        return float("inf")
    wall_centre = np.asarray(wall_centre, dtype=float)
    normal = wall_centre - np.asarray(spot, dtype=float)
    normal = normal / max(float(np.hypot(*normal)), 1e-9)
    ball = [spot[0], spot[1], unit[0] * speed, unit[1] * speed, 0.0, vz]
    hit = cross_plane(ball, spin, wall_centre, normal)
    if hit is None:
        return -float("inf")
    across = abs((hit["x"] - wall_centre[0]) * -normal[1] + (hit["y"] - wall_centre[1]) * normal[0])
    return max(hit["z"] - wall_reach, across - WALL_HALF_WIDTH)


def technique_ability(attrs) -> float:
    return stat_ability(float(getattr(attrs, "shooting", 50)) * 0.7 + float(getattr(attrs, "accuracy", 50)) * 0.3)


def plan_strike(attrs, spot, goal_y: float, wall_centre, wall_reach: float,
                keeper_x: float, rng, intent: dict | None = None) -> FreeKickStrike:
    """The taker's kick. The AI bends it round the wall or dips it over, whichever
    beats the wall more clearly; `intent` (aim_x, aim_z, power 0-1, side_spin,
    top_spin) is a human choosing instead. Execution error comes from the stats."""
    spot = np.asarray(spot, dtype=float)
    forward = 1.0 if goal_y > spot[1] else -1.0
    skill = technique_ability(attrs)
    centre = PITCH_WIDTH / 2.0

    if intent is not None:
        speed = _lerp(FREE_KICK_SHOT_SPEED, float(np.clip(intent.get("power", 1.0), 0.0, 1.0)))
        target = (float(intent["aim_x"]), float(intent["aim_z"]))
        spin = np.array([float(intent.get("side_spin", 0.0)), float(intent.get("top_spin", 0.0))])
        unit, vz = solve_launch(spot, target, goal_y, speed, spin)
        technique = "intent"
    else:
        speed = _lerp(FREE_KICK_SHOT_SPEED, stat_ability(float(getattr(attrs, "power", 50))))
        # The corner the keeper is further from; a coin toss when he is central.
        lean = float(keeper_x) - centre
        side = -1.0 if lean > 0.05 else 1.0 if lean < -0.05 else (1.0 if rng.random() < 0.5 else -1.0)
        target_x = centre + side * (GOAL_WIDTH / 2.0 - FK_AIM_INSET)
        # Curl back toward the middle: the left of travel is -x going up the pitch.
        curl = side * forward * _lerp(FK_SIDE_SPIN, skill)
        options = (
            ("over", (target_x, FK_AIM_HEIGHT_OVER), np.array([0.0, _lerp(FK_TOP_SPIN, skill)])),
            ("around", (target_x, FK_AIM_HEIGHT_AROUND), np.array([curl, 0.0])),
        )
        best = None
        for name, target_opt, spin_opt in options:
            unit_opt, vz_opt = solve_launch(spot, target_opt, goal_y, speed, spin_opt)
            margin = _wall_margin(spot, unit_opt, speed, vz_opt, spin_opt, wall_centre, wall_reach)
            if best is None or margin > best[0]:
                best = (margin, name, target_opt, spin_opt, unit_opt, vz_opt)
        _, technique, target, spin, unit, vz = best

    # Execution: the same draws for every kick, so seeds stay aligned.
    miss = 1.0 - min(1.0, skill)
    angle = math.radians(rng.normal(0.0, FK_AIM_ERROR_DEG * miss))
    lift = rng.normal(0.0, FK_LIFT_ERROR * miss)
    spin_scale = 1.0 + rng.normal(0.0, FK_SPIN_ERROR * miss)
    c, s = math.cos(angle), math.sin(angle)
    direction = np.array([unit[0] * c - unit[1] * s, unit[0] * s + unit[1] * c])
    return FreeKickStrike(
        direction=direction,
        speed=float(speed),
        vz=float(vz + lift),
        spin=np.asarray(spin, dtype=float) * spin_scale,
        technique=technique,
        aim=(float(target[0]), float(target[1])),
    )


class FreeKickFlight:
    """The kick from the boot to its first contact. step() moves the ball, walks
    the keeper across and reports what the ball met:
      ("wall", i) / ("body", i)      it hit a body below that player's reach
      ("keeper_catch", k, on_target) / ("keeper_parry", k, on_target)
      ("keeper_beaten", k, True)     on target and out of his reach; flight goes on
    Anything else (goal, post, out) is the caller's goal-frame code."""

    def __init__(self, strike: FreeKickStrike, spot, goal_y: float, keeper: int, keeper_attrs,
                 keeper_reach: float, bodies, reaches, wall, rng):
        self.spin = np.array(strike.spin, dtype=float)
        self.technique = strike.technique
        self.goal_y = float(goal_y)
        self.forward = 1.0 if goal_y > float(spot[1]) else -1.0
        self.keeper = int(keeper)
        self.keeper_reach = float(keeper_reach)
        self.bodies = [int(i) for i in bodies]
        self.reaches = np.asarray(reaches, dtype=float)
        self.wall = {int(i) for i in wall}
        self.frames = 0
        self.elapsed = 0.0
        self.keeper_done = False
        self.ball_xy = np.asarray(spot, dtype=float)
        self.heading = np.asarray(strike.direction, dtype=float)

        read = stat_ability(float(getattr(keeper_attrs, "vision", 50)) * 0.6
                            + float(getattr(keeper_attrs, "agility", 50)) * 0.4)
        self.reaction = max(0.05, _lerp(FK_KEEPER_REACTION, read) + rng.normal(0.0, FK_KEEPER_REACTION_JITTER))
        self.dive_speed = _lerp(FK_KEEPER_DIVE_SPEED, stat_ability(float(getattr(keeper_attrs, "agility", 50))))
        handling = stat_ability(float(getattr(keeper_attrs, "composure", 50)) * 0.6
                                + float(getattr(keeper_attrs, "ballcontrol", 50)) * 0.4)
        self.catch_speed = _lerp(FK_CATCH_SPEED, handling)

        # He reads it once he can see it past or over the wall (_sighted).
        self.seen_at = None if self.wall else 0.0

    def controls(self, i: int, positions) -> bool:
        """The keeper, and anyone the ball has not passed yet: they brace where
        they stand rather than run across a struck ball."""
        if i == self.keeper:
            return True
        if i not in self.bodies:
            return False
        return float(np.dot(np.asarray(positions[i]) - self.ball_xy, self.heading)) > 0.0

    def step(self, ball, positions, velocity, dt: float = SIM_DT):
        self.ball_xy = np.array([ball[0], ball[1]], dtype=float)
        self.heading = np.array([ball[2], ball[3]], dtype=float)
        for i in self.bodies:
            if self.controls(i, positions):
                velocity[i] = 0.0
        prev = np.array([ball[0], ball[1]], dtype=float)
        prev_z = float(ball[4])
        advance(ball, self.spin, dt)
        self.frames += 1
        self.elapsed += dt

        hit = self._body_contact(prev, prev_z, ball, positions)
        if hit is not None:
            return hit
        if self.seen_at is None and self._sighted(ball, positions):
            self.seen_at = self.elapsed
        self._drive_keeper(ball, positions, velocity, dt)
        return self._keeper_contact(prev, prev_z, ball, positions)

    def _body_contact(self, prev, prev_z, ball, positions):
        cur = np.array([ball[0], ball[1]], dtype=float)
        seg = cur - prev
        if float(np.dot(seg, seg)) < 1e-12:
            return None
        first = None
        for i in self.bodies:
            centre = positions[i]
            if float(np.dot(centre - prev, seg)) <= 0.0:
                continue   # behind the ball
            t = segment_meets_circle(prev, cur, centre, FK_BODY_RADIUS)
            if t is None:
                continue
            z = prev_z + t * (float(ball[4]) - prev_z)
            if z >= self.reaches[i]:
                continue   # over him
            if first is None or t < first[0]:
                first = (t, i)
        if first is None:
            return None
        t, i = first
        contact = prev + t * seg
        normal = contact - np.asarray(positions[i], dtype=float)
        norm = float(np.hypot(*normal))
        normal = normal / norm if norm > 1e-9 else -seg / float(np.hypot(*seg))
        v = np.array([ball[2], ball[3]], dtype=float)
        v = (v - 2.0 * float(np.dot(v, normal)) * normal) * FK_BODY_RESTITUTION
        ball[0:2] = np.asarray(positions[i], dtype=float) + normal * (FK_BODY_RADIUS + 0.05)
        ball[2:4] = v
        ball[4] = prev_z + t * (float(ball[4]) - prev_z)
        ball[5] = min(float(ball[5]), 0.0) * FK_BODY_RESTITUTION
        self.spin[:] = 0.0
        return ("wall" if i in self.wall else "body", i)

    def _sighted(self, ball, positions) -> bool:
        """Can the keeper see the ball? Not while his line of sight to it runs
        through a wall body below that player's reach."""
        eye = np.asarray(positions[self.keeper], dtype=float)
        to_ball = np.array([ball[0], ball[1]], dtype=float) - eye
        length_sq = float(np.dot(to_ball, to_ball))
        if length_sq < 1e-9:
            return True
        for i in self.wall:
            rel = np.asarray(positions[i], dtype=float) - eye
            t = float(np.dot(rel, to_ball)) / length_sq
            if not 0.0 < t < 1.0:
                continue
            if float(np.hypot(*(rel - t * to_ball))) > FK_BODY_RADIUS:
                continue
            if FK_KEEPER_EYE_HEIGHT + t * (float(ball[4]) - FK_KEEPER_EYE_HEIGHT) < self.reaches[i]:
                return False
        return True

    def _drive_keeper(self, ball, positions, velocity, dt):
        k = self.keeper
        if self.keeper_done:
            return
        if self.seen_at is None or self.elapsed - self.seen_at < self.reaction:
            velocity[k] = 0.0
            return
        # To where it crosses HIS plane: off his line, that is not the goal line.
        hit = cross_plane(ball, self.spin, (0.0, float(positions[k][1])), (0.0, self.forward))
        if hit is None:
            velocity[k] = 0.0
            return
        dx = hit["x"] - float(positions[k][0])
        velocity[k] = [float(np.clip(dx / dt, -self.dive_speed, self.dive_speed)), 0.0]

    def _keeper_contact(self, prev, prev_z, ball, positions):
        if self.keeper_done:
            return None
        k = self.keeper
        ky = float(positions[k][1])
        before = (float(prev[1]) - ky) * self.forward
        after = (float(ball[1]) - ky) * self.forward
        if before >= 0.0 or after < 0.0:
            return None
        self.keeper_done = True
        f = before / (before - after)
        x = float(prev[0]) + f * (float(ball[0]) - float(prev[0]))
        z = prev_z + f * (float(ball[4]) - prev_z)
        # Going in or not is read at the goal line, which he may be well off.
        line = predict_crossing(ball, self.spin, self.goal_y)
        if line is None:
            return None
        inner_min, inner_max = goal_inner_bounds()
        on_target = line["on_target"]
        if not (inner_min - 0.5 <= line["x"] <= inner_max + 0.5 and line["z"] < GOAL_HEIGHT + 0.3):
            return None   # he leaves it
        gap = abs(x - float(positions[k][0]))
        if gap > FK_KEEPER_ARM_REACH or z > self.keeper_reach:
            return ("keeper_beaten", k, True) if on_target else None

        speed = float(math.hypot(ball[2], ball[3]))
        positions[k][0] = x
        if gap <= FK_KEEPER_CATCH_REACH and speed <= self.catch_speed:
            return ("keeper_catch", k, on_target)
        # Parried: back off his hands and pushed wide of the post it was going for.
        wide = 1.0 if x >= PITCH_WIDTH / 2.0 else -1.0
        ball[0], ball[1], ball[4] = x, ky, z
        ball[2] = float(ball[2]) * FK_PARRY_RESTITUTION + wide * speed * 0.25
        ball[3] = -float(ball[3]) * FK_PARRY_RESTITUTION
        ball[5] = 2.0
        self.spin[:] = 0.0
        return ("keeper_parry", k, on_target)
