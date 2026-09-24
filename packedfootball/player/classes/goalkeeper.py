from game_config import pass_power, GOAL_WIDTH, PITCH_HEIGHT, PITCH_WIDTH, pace_ability, stat_ability
from gameEngine import possession_radius
from player.player import _norm2, player, ActionProfile
import numpy as np



GOAL_CENTER_X = PITCH_WIDTH / 2.0
KEEPER_LINE_HALF_WIDTH = GOAL_WIDTH / 2.0 + 0.5
KEEPER_LINE_OFFSET = 1.0
PENALTY_BOX_DEPTH = 18.0
PENALTY_BOX_HALF_WIDTH = 21.0
SWEEP_MAX_DISTANCE = 16.0
SWEEP_SAFE_BALL_SPEED = 10.0
KEEPER_AUTHORITY_DEPTH = 8.0
# Within this, a dive becomes a real save attempt instead of repositioning.
# Matches gameEngine.SAVE_ENGAGE_DISTANCE, so the keeper commits exactly when
# the engine is willing to resolve a save.
DIVE_COMMIT_DISTANCE = 6.0


class GoalkeeperActionProfile(ActionProfile):
    role_name = "goalkeeper"
    allowed_actions = {
        "stop", "pass", "clear", "hold_defense",
        "recover", "recover_slow", "contain", "capture", "dive", "save", "sweep"
    }
    action_biases = {
        "pass": 0.2, "clear": 3.0, "hold_defense": 2.0,
        "recover": 3.0, "contain": 1.2, "capture": 1.5, "dive": 2.0, "sweep": 1.0
    }

KEEPER_CLEAR_SHARE = 0.5      # the other half goes to a centre-half
KEEPER_OUTBALL_MAX_DEPTH = 30.0


class Goalkeeper(player):
    primary_stats = ("passing", "agility", "ballcontrol")
    primary_weight: float = 1.0

    def __init__(self, fname, lname, tier, position, attributes=None, country=None, hometown=None, appearance=None):
        super().__init__(fname, lname, tier, position, attributes, country, hometown, appearance)
        self.action_profile = GoalkeeperActionProfile()
        self.allowed_actions = set(self.action_profile.get_allowed_actions())
        self.action_biases = dict(self.action_profile.get_action_biases())

    def _own_goal_y(self, state: dict) -> float:
        return 0.0 if state.get("a_direction", 1) == 1 else PITCH_HEIGHT

    def _get_keeper_line(self, state: dict) -> float:
        """The y the keeper rests on: just off its own goal line."""
        goal_y = self._own_goal_y(state)
        return KEEPER_LINE_OFFSET if goal_y == 0.0 else PITCH_HEIGHT - KEEPER_LINE_OFFSET

    def _in_own_box(self, state: dict, point) -> bool:
        """Is `point` inside the keeper's own penalty area?"""
        goal_y = self._own_goal_y(state)
        depth = abs(float(point[1]) - goal_y)
        return depth <= PENALTY_BOX_DEPTH and abs(float(point[0]) - GOAL_CENTER_X) <= PENALTY_BOX_HALF_WIDTH

    def _clamp_to_box(self, state: dict, point) -> np.ndarray:
        """Keeps a sweep target inside the keeper's own penalty area."""
        goal_y = self._own_goal_y(state)
        x = float(np.clip(point[0], GOAL_CENTER_X - PENALTY_BOX_HALF_WIDTH, GOAL_CENTER_X + PENALTY_BOX_HALF_WIDTH))
        if goal_y == 0.0:
            y = float(np.clip(point[1], 0.0, PENALTY_BOX_DEPTH))
        else:
            y = float(np.clip(point[1], PITCH_HEIGHT - PENALTY_BOX_DEPTH, PITCH_HEIGHT))
        return np.array([x, y], dtype=float)

    def _centre_back_target(self, state: dict) -> np.ndarray:
        """The nearest defender square of him, which is where a keeper rolls it.

        Teammates carry no role in state, so they are picked by shape instead:
        behind the halfway line and not far up the pitch. Falls back to the
        closest man so this always returns somewhere.
        """
        mates = np.asarray(state.get("teammates", []), dtype=float)
        my_pos = np.asarray(state["my_pos"], dtype=float)
        goal_dir = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        deep = [
            tm for tm in mates
            if not np.array_equal(tm, my_pos)
            and (float(tm[1]) - float(my_pos[1])) * goal_dir < KEEPER_OUTBALL_MAX_DEPTH
        ]
        pool = deep if deep else [tm for tm in mates if not np.array_equal(tm, my_pos)]
        if not pool:
            return my_pos
        return min(pool, key=lambda tm: _norm2(np.asarray(tm) - my_pos))

    def _build_action(self, decision: str, state: dict) -> dict | None:
        if decision == "stop":
            return None

        elif decision == "pass":
            best_target = self._centre_back_target(state)
            dist = _norm2(best_target - state["my_pos"])
            required_power = pass_power(dist, self.attributes.power, 1.25, 50.0)
            actual_power = required_power
            return {"type": "pass", "target": best_target, "power": actual_power}

        elif decision == "clear":
            forward_y = PITCH_HEIGHT if state.get("a_direction", 1) == 1 else 0.0
            wide_x = state["rng"].choice([0.0, PITCH_WIDTH])
            target = np.array([wide_x + state["rng"].uniform(-15, 15), forward_y])
            return {"type": "pass", "target": target, "power": min(1.0, self.attributes.power / 40.0), "pass_type": "clearance"}

        elif decision == "dive":
            # Close enough to actually reach it -- throw yourself at it. The
            # engine's _attempt_save handles the dive movement and the single
            # save roll (which already penalises how far there is to go), so
            # a dive genuinely stops shots rather than only repositioning.
            dist_to_ball = float(_norm2(state["ball_pos"] - state["my_pos"]))
            if dist_to_ball <= DIVE_COMMIT_DISTANCE:
                return {"type": "save", "stat": self.attributes.agility}

            # Still coming -- get across to where it will cross the line.
            keeper_y = self._get_keeper_line(state)
            crossing = state.get("goal_crossing")
            intercept_x = float(crossing["x"]) if crossing else float(state["ball_pos"][0])

            # Fuzziness: Lower vision creates larger positional misjudgments
            intercept_x += state["rng"].normal(0, max(0.0, (100 - self.attributes.vision) / 40.0))

            target_x = np.clip(
                intercept_x,
                GOAL_CENTER_X - KEEPER_LINE_HALF_WIDTH,
                GOAL_CENTER_X + KEEPER_LINE_HALF_WIDTH,
            )
            burst_speed = max(1.2, (pace_ability(self.attributes.speed) * 0.4 + stat_ability(self.attributes.agility) * 1.6))

            return {"type": "move", "target": np.array([target_x, keeper_y]), "speed_mod": burst_speed}

        elif decision == "sweep": #go out 1on1 like stuff
            landing = self._predict_ball_landing_target(state)
            target = self._clamp_to_box(state, landing)
            return {
                "type": "move",
                "target": target,
                "speed_mod": max(0.8, pace_ability(self.attributes.speed)),
            }

        elif decision in {"hold_defense", "contain", "recover", "recover_slow"}:
            keeper_y = self._get_keeper_line(state)

            # Shuffle across the mouth to cover the ball's angle. Y is pinned
            # to the resting line: this is the "get home and set" behaviour,
            # deliberately distinct from sweeping.
            target_x = np.clip(
                state["ball_pos"][0],
                GOAL_CENTER_X - KEEPER_LINE_HALF_WIDTH,
                GOAL_CENTER_X + KEEPER_LINE_HALF_WIDTH,
            )

            speed = 0.9 if decision in {"contain", "recover"} else 0.5
            # Caught upfield? Get back at full pace regardless of decision.
            if abs(float(state["my_pos"][1]) - keeper_y) > PENALTY_BOX_DEPTH * 0.5:
                speed = 1.0
            return {"type": "move", "target": np.array([target_x, keeper_y]), "speed_mod": pace_ability(self.attributes.speed) * speed}

        elif decision == "save":
            return {"type": "save", "stat": self.attributes.agility}

        elif decision == "capture":
            return {"type": "capture", "stat": self.attributes.ballcontrol + 15}

        return None

    def _decide_on_ball_attack(self, state: dict) -> str:
        return self._decide_on_ball_defense(state)

    def _decide_on_ball_defense(self, state: dict) -> str:
        # No must_pass_next branch: a clearance releases the ball just as a pass
        # does, so a goal kick can take the same 50/50. Forcing "pass" there sent
        # every goal kick short, which is not what a keeper does.

        # A keeper does one of two things: hoof it, or give it to a centre-half.
        # He does not look for a progressive pass like an outfielder -- that is
        # what had him trying to thread balls upfield from his own six-yard box.
        if state.get("pressure_count", 0) > 0:
            return "clear"
        return "clear" if state["rng"].random() < KEEPER_CLEAR_SHARE else "pass"

    def _decide_off_ball_attack(self, state: dict) -> str:
        # Own team has the ball upfield: hold the line, stay set.
        return "hold_defense"

    def _decide_off_ball_defense(self, state: dict) -> str:
        """Shot-stopping always outranks sweeping.

        Order is deliberate and unchanged at the top: capture -> save -> dive
        come first, so a keeper never abandons its line for a loose ball while
        a shot is actually coming at it. "sweep" is a new branch that slots in
        BELOW those, and only fires for a ball that is loose, in the keeper's
        own box, nearer to the keeper than to any teammate, and not travelling
        dangerously toward goal.
        """
        my_pos = state["my_pos"]
        ball_pos = state["ball_pos"]
        dist_to_ball = float(_norm2(ball_pos - my_pos))
        ball_vel = state.get("ball_velocity", np.zeros(2, dtype=float))
        ball_speed = float(_norm2(ball_vel))
        own_goal_y = self._own_goal_y(state)

        moving_to_goal = (own_goal_y == 0.0 and ball_vel[1] < -1.0) or (own_goal_y == PITCH_HEIGHT and ball_vel[1] > 1.0)

        if dist_to_ball < 1.5:
            return "capture"

        # Is this ball actually going in? The engine works out where it will
        # cross our goal line (gameEngine.predict_goal_crossing) and hands it
        # over in state. Without this the keeper dove at everything -- 63% of
        # all "saves" were of balls already heading wide or over the bar.
        crossing = state.get("goal_crossing")
        threatening = bool(crossing) and bool(crossing.get("on_target"))

        if threatening and dist_to_ball < 4.0:
            return "save"

        if threatening and ball_speed > 10.0 and float(crossing.get("time", 99.0)) < 1.2:
            return "dive"

        # Deliberately NOT gated on `not moving_to_goal`: almost every loose
        # ball near a keeper drifts goalwards to some degree, and excluding
        # all of them meant the keeper never left its line at all. What
        # disqualifies a ball is SPEED -- a real shot is already claimed by
        # the save/dive branches above.
        dangerous = moving_to_goal and ball_speed > SWEEP_SAFE_BALL_SPEED
        if state.get("is_loose", False) and not dangerous and dist_to_ball <= SWEEP_MAX_DISTANCE:
            landing = self._predict_ball_landing_target(state)
            if self._in_own_box(state, landing):
                my_dist = float(_norm2(landing - my_pos))
                teammates = np.asarray(state.get("teammates", []))
                closer = 0
                if teammates.size > 0:
                    closer = int(np.sum(np.linalg.norm(teammates - landing, axis=1) < my_dist - 0.1))
                # `teammates` includes the keeper itself, so its own distance
                # is never strictly less than my_dist and doesn't count.
                near_own_goal = abs(float(landing[1]) - own_goal_y) <= KEEPER_AUTHORITY_DEPTH
                if closer == 0 or near_own_goal:
                    return "sweep"

        return "contain"

    def _decide_loose_ball(self, state: dict) -> str:
        return self._decide_off_ball_defense(state)
