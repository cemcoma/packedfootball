"""The penalty shootout minigame.

Shaped like gameEngine.py on purpose: its own version and History, a seeded
rng, a ReplayRecorder fed from state transitions, and a run-to-completion
entry point. seed + both kick orders + the inputs passed to take_kick + the
version below reproduce a shootout exactly.
"""

import numpy as np
from typing import Final

from game_config import (
    GOAL_WIDTH,
    KEEPER_REACH,
    PENALTY_CERTAINTY_CAP,
    PENALTY_KEEPER_DIVE_FRACTION,
    PENALTY_PLACEMENT_MIN,
    PENALTY_PLACEMENT_SPAN,
    PENALTY_SAVE_MIN,
    PENALTY_SAVE_SPAN,
    PENALTY_SETUP_FRAMES,
    PENALTY_SHOT_SPEED,
    PENALTY_SIDES,
    PENALTY_SPOT_DISTANCE,
    PITCH_HEIGHT,
    PITCH_WIDTH,
    stat_ability,
)
from replay import ActionType, ReplayRecorder

# Bump whenever shootout behaviour changes, and stamp it on the stored result.
# MAJOR/MINOR/PATCH mean what they mean for ENGINE_VERSION (see gameEngine.py).
#
# History:
#   1.0.0  first cut: the guessing-game maths, the flown kick, the win
#          condition. Shipped unversioned; recorded here for the record.
#   1.1.0  a keeper is only credited with a save on a kick that was ON TARGET.
#          read_it was rolled independently of placement, so a ball going wide
#          counted as a save and the replay stopped it dead at the keeper --
#          2.0% of all kicks. Derived from (on_target, scored) now, so the two
#          cannot disagree.
#          The kick flies at PENALTY_SHOT_SPEED. A fixed 90-frame flight moved
#          an 11-unit spot kick at 7.3 units/s, under a third of its speed in a
#          match, and left ball velocity at zero for a client that interpolates
#          on it. Frames come from the distance now, and the ball and the
#          diving keeper both carry real velocity.
#          One strike event per kick: every kick emitted PENALTY *and* SHOOT, so
#          the client ran the shoot animation twice, and an off-target one
#          emitted three. PENALTY at the run-up then the outcome, as a match does.
#          The scene is placed: the kicker stands over the ball and the other 20
#          wait on the halfway line, instead of all 22 stacked on the centre spot.
#          A goal ends up BEHIND the line. Saves were moved off y = 0 for being
#          indistinguishable from goals; goals were left on it.
#          The dive carries KEEPER_REACH * PENALTY_KEEPER_DIVE_FRACTION, as in a
#          match, not a share of the goal's half-width -- it used to stop 0.5
#          units short of the corner it was diving for.
#          Sampled through the walk back, so the replay has no hole between
#          kicks (gameEngine 3.0.0, same bug).
#          Bad input is refused: a taker index outside the squad, an aim or dive
#          outside PENALTY_SIDES, an empty squad, or a kick after the last one.
#          State is per-team lists (scores, kicks_taken, takers) and `winner` is
#          a team index, so a result serialises without holding team objects.
#   1.2.0  the shootout moved to the y = PITCH_HEIGHT goal, the end team A
#          ATTACKS in a match. At the y = 0 end the side the player is always
#          drawn as was shooting into its own goal, which no client can render
#          the right way round. Outcomes are untouched -- the rolls never moved
#          -- but every position in a stored replay did, so an old seed draws
#          differently while meaning the same thing.
#          aim keeps gameEngine's sign: -1 is lower x, the left of a pitch
#          drawn the usual way up, which is the side the player's own Left
#          button has to send it to.
MINIGAMES_ENGINE_VERSION: Final[str] = "1.2.0"

REGULATION_KICKS: Final = 5
# A shootout that has not ended by here is a caller in a loop, not a shootout.
MAX_KICKS: Final = 200

# The client plays a replay back at 60 ticks/second.
TICKS_PER_SECOND: Final = 60.0

# Both sides shoot at the y = PITCH_HEIGHT goal, the way one end is used in a
# real shootout. That end and not the other because it is the one team A
# ATTACKS in a match (gameEngine._goal_for_player), so the side the player is
# always drawn as is shooting the way it always shoots.
SHOOTOUT_GOAL_Y: Final = PITCH_HEIGHT
# Toward the goal, from the spot. Every depth below is a distance along this,
# so the whole scene mirrors by changing these two together.
ATTACK_DIR: Final = 1.0
SPOT_Y: Final = SHOOTOUT_GOAL_Y - ATTACK_DIR * PENALTY_SPOT_DISTANCE

# How far the ball ends up either side of the line. A save stops SHORT of it
# and a goal ends PAST it: on the line the two are the same picture, and a
# replay that can't be told apart from its own result can't be checked
# against it.
SAVE_STOP_DEPTH: Final = 0.3
GOAL_STOP_DEPTH: Final = 1.2

# Share of the flight the keeper takes to complete his dive. He holds it after,
# with no drifting back onto a ball he has already been beaten by.
DIVE_COMMIT_FRACTION: Final = 0.6

# The walk back between kicks. Cosmetic: the outcome is settled before the
# first frame of flight, so this decides how it looks, never who won.
RESET_FRAMES: Final = 60

# The staged scene: how far behind the ball the kicker stands, and the two rows
# of waiting players either side of the halfway line.
TAKER_STANDOFF: Final = 1.5
WAITING_Y: Final = 50.0
WAITING_ROW_OFFSET: Final = 4.0
WAITING_SPACING: Final = 1.6


class PenaltyShootout:
    """One shootout, kick by kick.

    take_kick() resolves the next one and returns it; run() plays the whole
    thing out with both sides guessing. Either side's guess can be supplied
    instead of rolled, which is what a human playing it does -- `aim` on their
    own kicks, `dive` on the opponent's.
    """

    def __init__(self, team_a, team_b, seed=None, record_replay=False,
                 team_a_takers=None, team_b_takers=None, team_a_starts=True):
        self.teams = [team_a, team_b]
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.replay = ReplayRecorder() if record_replay else None
        self.current_tick = 0

        self.scores = [0, 0]
        self.kicks_taken = [0, 0]
        self.is_finished = False
        self.winner = None          # team index, or None while it is live
        self.history = []
        self.current_turn = 0 if team_a_starts else 1   # cointoss

        self.keepers = [self._find_keeper_idx(t) for t in self.teams]
        self.takers = [
            self._taker_order(team_a_takers, team_a),
            self._taker_order(team_b_takers, team_b),
        ]

        self.positions = np.zeros((22, 2), float)
        self.velocity = np.zeros((22, 2), float)
        self.ball = np.zeros(6, float)      # x, y, vx, vy, height, vz
        self._place_scene()

    # ------------------------------------------------------------------ setup

    def _find_keeper_idx(self, team) -> int:
        """First GK in the squad. Slot 0 keeps goal for a squad without one --
        the backend validates rosters long before a shootout is built."""
        for i, p in enumerate(team.players):
            if getattr(p, "position", "") == "GK":
                return i
        return 0

    def _taker_order(self, takers, team) -> list:
        """Kick order for one side: what was asked for, else best-first. An
        index outside the squad is a caller bug, not something to fall back on.
        """
        if not team.players:
            raise ValueError("a shootout needs at least one player a side")
        if not takers:
            return self._sort_best_takers(team)
        order = [int(i) for i in takers]
        if any(i < 0 or i >= len(team.players) for i in order):
            raise IndexError(f"taker index outside a squad of {len(team.players)}")
        return order

    def _sort_best_takers(self, team) -> list:
        return best_taker_order(team.players)

    # ------------------------------------------------------------------- maths

    def _resolve_penalty(self, taker_attrs, gk_attrs, aim=None, dive=None):
        """A penalty is a guessing game, not a shot -- see gameEngine's
        _resolve_penalty, whose scales and roll order this matches exactly.

        Returns (scored, aim, dive, on_target). A save is `on_target and not
        scored`, so a ball going wide can never be credited as one.
        """
        agility = float(getattr(gk_attrs, "agility", 50))
        vision = float(getattr(gk_attrs, "vision", 50))
        ballcontrol = float(getattr(gk_attrs, "ballcontrol", 50))

        # Capped: MIN + SPAN already lands at 0.99 and stat_ability keeps rising
        # past 100, so an item-fed taker would never miss.
        placement = min(PENALTY_CERTAINTY_CAP, PENALTY_PLACEMENT_MIN + PENALTY_PLACEMENT_SPAN * stat_ability(
            penalty_score(taker_attrs)
        ))
        save = min(PENALTY_CERTAINTY_CAP, PENALTY_SAVE_MIN + PENALTY_SAVE_SPAN * stat_ability(
            (agility * 0.6 + vision * 0.4 + ballcontrol * 0.3) / 1.3
        ))

        aim = int(self.rng.choice(PENALTY_SIDES)) if aim is None else _valid_side(aim, "aim")
        dive = int(self.rng.choice(PENALTY_SIDES)) if dive is None else _valid_side(dive, "dive")

        on_target = bool(self.rng.random() < placement)
        read_it = dive == aim and self.rng.random() < save
        return (on_target and not read_it), aim, dive, on_target

    # -------------------------------------------------------------- the kick

    def upcoming(self) -> dict:
        """Who takes the next kick and who faces it.

        A client has to be able to NAME them before anything has happened --
        the first taker is not in `history` yet, and a screen that cannot say
        whose kick it is leaves the player guessing whether to aim or dive.
        Empty once the shootout is over.
        """
        if self.is_finished:
            return {}
        team = self.current_turn
        other = 1 - team
        order = self.takers[team]
        taker_idx = order[self.kicks_taken[team] % len(order)]
        keeper_idx = self.keepers[other]
        return {
            "team": team,
            "taker_idx": taker_idx,
            "taker_name": getattr(self.teams[team].players[taker_idx], "lname", "Player"),
            "keeper_idx": keeper_idx,
            "keeper_name": getattr(self.teams[other].players[keeper_idx], "lname", "Keeper"),
            "sudden_death": min(self.kicks_taken) >= REGULATION_KICKS,
        }

    def take_kick(self, aim: int = None, dive: int = None) -> dict:
        """Resolve the next kick. `aim` is the taker's corner and `dive` the
        keeper's guess; either is rolled when not supplied."""
        if self.is_finished:
            raise RuntimeError("shootout is finished")

        up = self.upcoming()
        team, other = up["team"], 1 - up["team"]
        taker_idx, keeper_idx = up["taker_idx"], up["keeper_idx"]
        taker = self.teams[team].players[taker_idx]
        keeper = self.teams[other].players[keeper_idx]
        sudden_death = up["sudden_death"]
        kick_tick = self.current_tick

        scored, aim, dive, on_target = self._resolve_penalty(
            taker.attributes, keeper.attributes, aim, dive
        )
        saved = on_target and not scored

        self._animate_kick(
            taker_idx if team == 0 else taker_idx + 11,
            keeper_idx if other == 0 else keeper_idx + 11,
            team, aim, dive, on_target, scored,
        )

        self.scores[team] += int(scored)
        self.kicks_taken[team] += 1

        kick = {
            "kick": len(self.history) + 1,
            "tick": kick_tick,
            "team": team,
            "team_name": getattr(self.teams[team], "name", ""),
            "taker_idx": taker_idx,
            "taker_name": getattr(taker, "lname", "Player"),
            "keeper_idx": keeper_idx,
            "keeper_name": getattr(keeper, "lname", "Keeper"),
            "aim": aim,
            "dive": dive,
            "on_target": on_target,
            "scored": scored,
            "saved": saved,
            "sudden_death": sudden_death,
            "score": list(self.scores),
        }
        self.history.append(kick)
        self._check_win_condition()
        if not self.is_finished:
            self.current_turn = other
        return kick

    def _animate_kick(self, taker_idx, keeper_idx, team, aim, dive, on_target, scored):
        """Draw the kick that was already resolved. The picture has to match the
        result: a save never crosses the line, a goal does, a miss goes wide."""
        centre_x = PITCH_WIDTH / 2.0
        spot = np.array([centre_x, SPOT_Y], float)
        saved = on_target and not scored

        # Inside the frame when it is on target, outside the near post when it
        # is not. Identical to gameEngine._take_penalty, including the sign:
        # aim -1 is lower x, which is the left of a pitch drawn the usual way
        # up.
        target_x = centre_x + aim * (GOAL_WIDTH / 2.0 - 0.6)
        if not on_target:
            target_x += (GOAL_WIDTH * 0.8) * (1 if aim >= 0 else -1)
        keeper_x = centre_x + dive * KEEPER_REACH * PENALTY_KEEPER_DIVE_FRACTION

        self._place_scene(taker_idx, keeper_idx)
        self.ball[:] = [spot[0], spot[1], 0.0, 0.0, 0.0, 0.0]

        # The run-up. A match emits PENALTY at the setup and no separate strike
        # event -- the client already draws PENALTY as one.
        if self.replay:
            self.replay.event(self.current_tick, ActionType.PENALTY, player_idx=taker_idx, team=team)
        self._hold(PENALTY_SETUP_FRAMES)

        if saved:
            stop = np.array([keeper_x, SHOOTOUT_GOAL_Y - ATTACK_DIR * SAVE_STOP_DEPTH], float)
        elif scored:
            stop = np.array([target_x, SHOOTOUT_GOAL_Y + ATTACK_DIR * GOAL_STOP_DEPTH], float)
        else:
            stop = np.array([target_x, SHOOTOUT_GOAL_Y], float)

        # Struck at PENALTY_SHOT_SPEED, so the flight is as long as the distance
        # needs and the velocity on the wire is the real one.
        travel = stop - spot
        frames = max(1, int(round(float(np.hypot(*travel)) / PENALTY_SHOT_SPEED * TICKS_PER_SECOND)))
        ball_v = travel / (frames / TICKS_PER_SECOND)
        dive_v = (keeper_x - centre_x) / max(DIVE_COMMIT_FRACTION * frames / TICKS_PER_SECOND, 1e-6)

        for frame in range(1, frames + 1):
            self.current_tick += 1
            t = frame / float(frames)
            # Snapped on the last frame, not interpolated to it: the ball has to
            # come to rest exactly where the outcome said it does.
            self.ball[0:2] = stop if frame == frames else spot + travel * t
            self.ball[2:4] = ball_v if frame < frames else 0.0
            dive_t = min(1.0, t / DIVE_COMMIT_FRACTION)
            self.positions[keeper_idx][0] = centre_x + (keeper_x - centre_x) * dive_t
            self.velocity[keeper_idx][0] = dive_v if dive_t < 1.0 else 0.0
            self._sample()

        if self.replay:
            if scored:
                self.replay.event(self.current_tick, ActionType.GOAL, player_idx=taker_idx, team=team)
            elif saved:
                self.replay.event(self.current_tick, ActionType.SAVE, player_idx=keeper_idx, team=1 - team)
            else:
                self.replay.event(self.current_tick, ActionType.SHOT_OFF_TARGET, player_idx=taker_idx, team=team)

        self.velocity[keeper_idx] = 0.0
        self._hold(RESET_FRAMES, ball_controller=keeper_idx if saved else -1)

    def _place_scene(self, taker_idx=-1, keeper_idx=-1):
        """Kicker over the ball, defending keeper on his line, the other 20 on
        the halfway line -- 22 players on the centre spot is not a scene."""
        centre_x = PITCH_WIDTH / 2.0
        self.velocity[:] = 0.0
        waiting = [i for i in range(22) if i not in (taker_idx, keeper_idx)]
        for n, i in enumerate(waiting):
            row = -1.0 if i < 11 else 1.0
            self.positions[i] = [
                centre_x + (n % 10 - 4.5) * WAITING_SPACING,
                WAITING_Y + row * WAITING_ROW_OFFSET,
            ]
        if taker_idx >= 0:
            # Behind the ball, which is away from the goal.
            self.positions[taker_idx] = [centre_x, SPOT_Y - ATTACK_DIR * TAKER_STANDOFF]
        if keeper_idx >= 0:
            self.positions[keeper_idx] = [centre_x, SHOOTOUT_GOAL_Y]
        self.ball[:] = [centre_x, SPOT_Y, 0.0, 0.0, 0.0, 0.0]

    # ------------------------------------------------------------------ replay

    def _hold(self, frames: int, ball_controller: int = -1) -> None:
        """Tick through a pause, still sampling. An unsampled stoppage leaves a
        hole in the replay that the client can only jump-cut across."""
        for _ in range(frames):
            self.current_tick += 1
            self._sample(ball_controller)

    def _sample(self, ball_controller: int = -1) -> None:
        if self.replay and self.current_tick % self.replay.sample_interval_ticks == 0:
            self.replay.snapshot(
                self.current_tick, self.positions, self.velocity, self.ball, ball_controller
            )

    # ------------------------------------------------------------------ result

    def _check_win_condition(self) -> None:
        """Over as soon as a side cannot be caught, else at the END of a level
        sudden-death round -- hence the early return: past regulation the
        kicks-left counts go negative."""
        taken_a, taken_b = self.kicks_taken
        if taken_a >= REGULATION_KICKS and taken_b >= REGULATION_KICKS:
            if taken_a == taken_b and self.scores[0] != self.scores[1]:
                self._finish(0 if self.scores[0] > self.scores[1] else 1)
            return

        left_a = REGULATION_KICKS - taken_a
        left_b = REGULATION_KICKS - taken_b
        if self.scores[0] > self.scores[1] + left_b:
            self._finish(0)
        elif self.scores[1] > self.scores[0] + left_a:
            self._finish(1)

    def _finish(self, winner: int) -> None:
        self.is_finished = True
        self.winner = winner
        if self.replay:
            self.replay.event(self.current_tick, ActionType.FULLTIME, team=winner)

    @property
    def winner_team(self):
        return None if self.winner is None else self.teams[self.winner]

    def run(self) -> dict:
        """Play it out with both sides guessing."""
        while not self.is_finished:
            if len(self.history) >= MAX_KICKS:
                raise RuntimeError(f"shootout did not settle inside {MAX_KICKS} kicks")
            self.take_kick()
        return self.result()

    def result(self) -> dict:
        """What a caller stores. Team objects stay out of it -- `winner` is an
        index into the two sides that were passed in."""
        return {
            "engine_version": MINIGAMES_ENGINE_VERSION,
            "minigame": "penalty_shootout",
            "seed": self.seed,
            "is_finished": self.is_finished,
            "score": list(self.scores),
            "kicks_taken": list(self.kicks_taken),
            "winner": self.winner,
            "winner_name": None if self.winner is None else getattr(self.winner_team, "name", ""),
            "sudden_death": any(k["sudden_death"] for k in self.history),
            "kicks": self.history,
        }


def penalty_score(attributes) -> float:
    """How good a taker is from the spot: the weighting the placement roll is
    made on. Public so a screen can show the number the kick is rolled from."""
    shooting = float(getattr(attributes, "shooting", 50))
    accuracy = float(getattr(attributes, "accuracy", 50))
    return shooting * 0.8 + accuracy * 0.2


def best_taker_order(players) -> list:
    """Squad indexes, best taker first, on penalty_score so the order and the
    odds agree. The keeper sorts last on his own shooting, which is where a
    keeper belongs. Stable, so equal scores keep squad order."""
    scored = [(i, penalty_score(p.attributes)) for i, p in enumerate(players)]
    scored.sort(key=lambda entry: entry[1], reverse=True)
    return [i for i, _ in scored]


def _valid_side(value, what: str) -> int:
    """A corner outside PENALTY_SIDES would place the ball off the pitch."""
    side = int(value)
    if side not in PENALTY_SIDES:
        raise ValueError(f"{what} must be one of {PENALTY_SIDES}, got {value!r}")
    return side


def run_shootout(team_a, team_b, seed=None, record_replay=False, **kwargs) -> dict:
    """One shootout, played out and packed up. Mirrors gameEngine.run_match:
    the entry point a caller with no interest in single kicks uses."""
    shootout = PenaltyShootout(
        team_a, team_b, seed=seed, record_replay=record_replay, **kwargs
    )
    result = shootout.run()
    result["replay"] = shootout.replay.encode() if shootout.replay else None
    return result
