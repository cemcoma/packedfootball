import math
import copy
from dataclasses import asdict

import numpy as np
from typing import Final

from replay import ActionType, ReplayRecorder
from game_config import (  # noqa: F401
    STAT_CEILING,
    pace_ability,
    stat_ability,
    STAT_SCALE,
    BALL_AIR_FRICTION,
    BALL_GRAVITY,
    BALL_GROUND_FRICTION,
    GOAL_HEIGHT,
    GOAL_POST_RADIUS,
    GOAL_WIDTH,
    HEAD_CONTACT_HEIGHT,
    PITCH_HEIGHT,
    PITCH_WIDTH,
    PLAYER_BASE_SPEED,
    PLAYER_RADIUS,
    POSSESSION_RADIUS,
)
from formations import get_formation, is_similar_position

# Bump whenever match behaviour changes.
# Stamped onto every games/{id} doc so a reported match can be read against the engine
# that actually produced it -- seed + ENGINE_VERSION together reproduce a
# game exactly.
#
# MAJOR.MINOR.PATCH, and what each one means for a stored match:
#   MAJOR -- the sim was reshaped. An old seed no longer replays into
#            anything like the same match; old results aren't comparable.
#   MINOR -- balance or a new mechanic. An old seed replays differently,
#            but the match still means the same thing (can have differing 
#            stats and behaviour, just not major change).
#   PATCH -- a fix that doesn't change how a match is meant to play out.
#            Seeds may still diverge if the bug was in the sim itself.
#
# History:
#   1.0.0  first engine.
#   2.0.0  goal frame with posts/crossbar, throw-ins from the real out point,
#          real stoppage time, match stats + ratings, keeper can leave its
#          line, stamina, height.
#   2.1.0  shooting/goalkeeping rebalance: one save attempt per shot, save
#          odds from shot difficulty, a beaten keeper stays down, shots on
#          target counted from the predicted crossing instead of from keeper
#          touches, slower ball descent (BALL_GRAVITY).
#   2.1.1  the second half restarts on 45:00 instead of carrying on from the
#          first half's stoppage (display_clock_frames).
#   2.2.0  shots: launch height derived from the aimed height and flight
#          time instead of |unit_z| * speed (a velocity written into the
#          height field), which had the power stat lofting shots over the
#          bar -- the better the striker, the higher the miss. Shot spread
#          floor 2.1 -> 0.9 (player.SHOT_VARIANCE_FLOOR) so shooting above
#          ~68 actually differentiates. Passes leave the boot with an
#          angular error from the accuracy attribute (PASS_AIM_ERROR_*),
#          which nothing read before. Adaptive per-player decision
#          intervals ON by default (ADAPTIVE_*). Player collisions resolved
#          from a pairwise distance matrix instead of a 231-pair Python loop
#          (same rule, same order).
#   2.2.1 goalkeeping own goals: Goalkeepers used the generic outfield block branch in 
#         _attempt_capture and when the ball wasnt capture and blocked, the goal
#         could (and did) bounce in the net, resulting in an own goal with attribution
#         to the gk. Now the keeper never takes the block branch, only the save branch,
#         once per shot. Attribution: a shot on target when struck that goes in
#         off a defender is the shooter's goal (last_shot_on_target), not an own
#         goal; the replay GOAL event carries the credited scorer, and an own
#         goal is the player who put it in with player_idx on the other side
#         from team.
#   2.3.0 heading attribute + header contests (reach from height/jump, balls
#         above reach fly over), lofted crosses that arrive at head height,
#         wingplay latch for LW/RW/LM/RM (wing_run/wide_run + open-play crosses).
#         The ball has a vertical velocity (ball_vz): kicks rise and fall in
#         an arc instead of starting at their peak and dropping in a line.
#   2.4.0 a cross needs a target. With nobody in the box (player._box_runners)
#         a wide player drops the wingplay latch and goes at the goal itself,
#         and it also drops when the lane inside is open rather than running
#         the line to the byline on rails. Off the ball, hold_attack follows
#         the ball up the pitch per role (player._attack_shape_target and the
#         attack_push_* knobs) instead of sitting on a fixed formation slot
#         + 15; midfielders and forwards fill an empty box in the final third,
#         not only ahead of a cross; the run into the box is a sprint (it has
#         to beat the cross there); and the space bonuses on dribbling no
#         longer swamp shooting once you are in the box. Wide players scored
#         0.19 goals/match before this and 0.48 after, over 48 matches.
#         Replays also split the shot event: a strike the goal-crossing
#         prediction reads as missing records as SHOT_OFF_TARGET rather than
#         SHOOT, so the client can draw its trail only for shots at goal. A
#         goal retypes its own strike back to SHOOT (replay.py), since the
#         prediction projects a straight line and ignores friction. The wire
#         format is unchanged -- it is one more ActionType value.
#         Goalposts bounce the ball again. The contact normal came from the
#         goal-plane crossing, which sits level with the post's axis by
#         construction, so every rebound but a dead-centre one flipped vx
#         and kept the vy that was carrying the ball in: it crossed, struck
#         the post again, and bled out on the line (four hits in twelve
#         ticks) while the crossbar rebounded correctly. The post is now
#         intersected as the circle it is (_path_meets_post), so the normal
#         has a real y component and the ball leaves the woodwork once. A
#         glancing hit that used to die on the line now goes back into play,
#         in off the post, or wide for a goal kick.
#   3.0.0 the attribute axis runs to STAT_CEILING (130), not 100, so items and
#         boosters have somewhere to go. Every stat-derived formula divides by
#         the ceiling and its other divisors scale with it, so a stat at the
#         same fraction of the axis behaves as it did -- but a rolled card
#         (45-96) now sits lower on it. Keeper save weights summed to 1.3, so
#         min(1.0, save_stat/100) capped every keeper from ~77 up: fixed, which
#         is what flattened platinum/diamond/icon keepers into one. Attributes
#         clamps to [0, STAT_CEILING] on construction. Height no longer takes
#         the out-of-position 0.9 (it is centimetres, not a skill).
#         Passing: kick power is sized from the distance and CAPPED by the power
#         stat instead of multiplied by it (every pass past 10 units used to fly
#         ~3x too far), a pass records its intended receiver and he goes to meet
#         it, chase targets are cut off at the touchline, and reception scores on
#         the ball's speed RELATIVE to the receiver plus whether it is running
#         with him -- a hard ball taken facing the wrong way comes off him.
#         Pass choice scores lane openness (can a defender reach the line before
#         the ball?) rather than vetoing on distance alone.
#         Fouls, free kicks and penalties: a failed tackle can take the man, and
#         a foul in the box is a penalty. A penalty is a guessing game of its
#         own (see _resolve_penalty), not a shot through _save_chance, which
#         rates a slow central ball as the easiest save there is. Defenders
#         Free kicks come in three shapes, each with its own setup: a deep one
#         restarts play (the side in front pushes up, the defence drops into
#         shape), a wide or distant one is a delivery into the box set up like a
#         corner, and a close central one is struck over a wall through its own
#         check (_resolve_free_kick), since the open-play save curve knows about
#         neither a set keeper nor a wall. How many bodies go forward scales
#         with how far behind the side is. The taker must PLAY it (must_pass)
#         and the defending side clears ten yards, so a free kick can no longer
#         be dribbled out of or taken by the side that conceded it.
#         A restart's first touch keeps its own player reference: restart_player
#         is wiped at the whistle, so the old guard could never match and every
#         throw-in had been going out as an ordinary pass.
#         The engine no longer holds still for a set piece (10 frames, not 150):
#         freezing the sim only made players twitch on screen, so the buildup --
#         backing off the ball and the run-up -- is drawn by the replay instead.
#         Keepers distribute 50/50: hoof it, or roll it to the nearest defender
#         behind them. They no longer hunt for a progressive pass from the
#         six-yard box, and a goal kick takes the same 50/50 rather than always
#         going short.
#         Wingers cutting inside latch the intent, so the move runs its ~2s
#         course instead of reverting to the touchline on the next decision.
#         A direct free kick is struck flat, not lobbed: _flight_time was asked
#         for a GROUND-friction estimate for a ball flying under air friction,
#         so _launch_vz answered with an arc that peaked at 5m from 25 units
#         against a 2.5m bar -- every one outside ~18 units went over.
#         must_pass survives a loose ball, so a set-piece taker plays it instead
#         of being freed to shoot the moment the whistle went.
#         A ball can no longer travel THROUGH a player (_body_check): step()
#         only resolves a loose ball every few frames and a capture can be
#         declined, so one could cross a man clean and carry on. It is taken,
#         or it dies at his feet. A loose ball is also offered down the queue
#         rather than to the nearest man alone -- he may be inside his own
#         capture lockout, and asking only him meant a third of offers were
#         refused with somebody else stood in range.
#         Fouls roughly sixth-ed: being skinned is the more interesting outcome
#         and the game was stopping too often. An outfield clearance goes where
#         the man is FACING (within 90 degrees) instead of at a random far
#         corner that was often behind him. Restarts are sampled
#         through the stoppage: tick() returns before the snapshot, so a replay
#         used to have a hole where every stoppage was and the client could only
#         jump-cut.
#   3.1.0 the top and the bottom of the stat ladder both start telling.
#         - shooting, heading and crossing accuracy now tell all the way to
#           100. The floors on their aim spread bound at 86.5, 91 and 85, so
#           everything above was identical -- an icon shot like a gold. Same
#           shape of bug as the keeper weight sum. ~1 goal a match at icon,
#           nothing at gold.
#         - STAT_CURVE_GAMMA 1.0 -> 0.8, lifting the weak end of every stat.
#           Bronze v bronze was 0.94 goals a match (a 0-0 league, the failure
#           mode tier_report warns about) and is 1.94 over 32 matches a side;
#           gold and icon move under 0.3 either way.
#         - stat_ability keeps rising past 100 instead of clipping there (see
#           game_config.STAT_OVERDRIVE). No card rolls above 96, so this
#           changes nothing until items are equipped -- it is what makes them
#           worth owning at all. Penalties gained a certainty cap because
#           their scale already reached 0.99 at 100.
ENGINE_VERSION: Final[str] = "3.1.0"

POST_REBOUND_DAMPING: Final = 0.55 # how much goalpost eats the velocity
THROW_IN_POWER_FACTOR: Final = 2.0 / 3.0 # touch power idk random

FRAMES_PER_CLOCK_SECOND: Final = 2 # match_clock_frames / 2 = seconds, so 90:00 == 10800

ADAPTIVE_NEAR_ROUNDS: Final[int] = 1
ADAPTIVE_MID_ROUNDS: Final[int] = 3
ADAPTIVE_FAR_ROUNDS: Final[int] = 6
ADAPTIVE_NEAR_RADIUS: Final[float] = 15.0   # units from the ball -> NEAR
ADAPTIVE_MID_RADIUS: Final[float] = 35.0    # -> MID; beyond -> FAR
ADAPTIVE_PATH_RADIUS: Final[float] = 6.0
ADAPTIVE_PATH_LOOKAHEAD: Final[float] = 1.0
ADAPTIVE_KEEPER_OWN_HALF_ROUNDS: Final[int] = ADAPTIVE_NEAR_ROUNDS

REGULATION_FRAMES: Final = 10800   # 90:00, before any added time

ADDED_TIME_BASE_FRAMES: Final = 60   # 30s
ADDED_TIME_PER_GOAL: Final = 60      # 30s, celebration + restart
ADDED_TIME_PER_RESTART: Final = 20   # 10s per throw-in/corner/goal kick
ADDED_TIME_PER_POST: Final = 10      # 5s scramble
ADDED_TIME_MAX_FRAMES: Final = 840   # cap at 8:00

# A half doesn't end while an attack is live (see _attack_is_live). This caps
# how long the whistle can be held so a team knocking it around up there
# can't stall the match. 200 frames == 1:40 of clock.
MAX_WHISTLE_HOLD_FRAMES: Final = 200
DANGEROUS_ZONE_Y: Final = PITCH_HEIGHT * 2.0 / 3.0

# Sentinel for "not latched yet", since None legitimately means "ball dead".
_UNSET = object()

# Stamina. Everyone starts a match on STAMINA_MAX regardless of their card;
# the `stamina` ATTRIBUTE is !resistance! to losing it, so two players doing
# identical work tire at different rates.
STAMINA_MAX: Final = 100.0
STAMINA_DRAIN_PER_STEP: Final = 0.010    # full sprint, at reference stamina
STAMINA_REFERENCE: Final = 50            # attribute that drains at exactly 1.0x
STAMINA_RECOVERY_PER_STEP: Final = 0.010 # paid back only while barely moving
# Effort below this counts as walking/standing and earns recovery. Set low on
# purpose: at a generous threshold, recovery outpaced drain at ordinary match
# effort and nobody ever got tired.
STAMINA_RECOVERY_EFFORT: Final = 0.25
STAMINA_MIN_SPEED_FACTOR: Final = 0.65   # pace kept when completely empty

# --- Goalkeeping -----------------------------------------------------------
# A save is one roll per shot, and how likely it is depends on the SHOT, not
# just the keeper. Anchors: a 100-rated keeper saves ~100% of an easy shot
# (slow, straight at them) and ~50% of a hard one (fast, full stretch).
# Fouls. Rolled only on a failed tackle, so a clean challenge never gives one.
# Tuned for roughly six anklebreakers per foul: the game stops too much
# otherwise, and being skinned is the more interesting outcome anyway.
FOUL_BASE: Final = 0.065
FOUL_AGGRESSION_WEIGHT: Final = 0.12
FOUL_OUTPACED_WEIGHT: Final = 0.165
FOUL_FROM_BEHIND_WEIGHT: Final = 0.08
FOUL_MAX: Final = 0.36

# Free kicks: how far off the ball the wall stands, and how many are in it.
# The ENGINE barely pauses for a set piece -- just long enough to register the
# restart. The buildup (backing off the ball, the run-up) is the replay's job:
# holding the sim still for two seconds only made players twitch on screen.
FREE_KICK_SETUP_FRAMES: Final = 10
PENALTY_SETUP_FRAMES: Final = 10

# Free kicks come in three shapes, measured from the goal being attacked.
# Close and central is a shot; anywhere else in the final third is a cross;
# everything deeper is a restart of play. Each is set up by its own method.
FK_SHOOTING_RANGE: Final = 30.0
FK_SHOOTING_HALF_WIDTH: Final = 15.0
FK_CROSS_RANGE: Final = 48.0

# Bodies a chasing side commits on top of the usual number, per goal behind.
FK_CHASE_BONUS_MAX: Final = 3

# A direct free kick: harder than a penalty by a long way. Placement is whether
# he beats the wall AND hits the frame; then the keeper, who is set and
# expecting it. Real conversion is well under one in ten.
FK_PLACEMENT_MIN: Final = 0.25
FK_PLACEMENT_SPAN: Final = 0.35
FK_WALL_BLOCK: Final = 0.25
FK_SAVE_MIN: Final = 0.62
FK_SAVE_SPAN: Final = 0.25
FREE_KICK_SHOT_SPEED: Final = 30.0
FREE_KICK_TARGET_HEIGHT: Final = 1.2
# Never peak above the bar, whatever the distance solves to.
FREE_KICK_MAX_VZ: Final = 6.5
WALL_DISTANCE: Final = 9.15
WALL_PLAYERS: Final = 3
PENALTY_SHOT_SPEED: Final = 26.0

# Penalties. Both scales floor at 0.80 -- see _resolve_penalty for why.
PENALTY_PLACEMENT_MIN: Final = 0.80
PENALTY_PLACEMENT_SPAN: Final = 0.19
PENALTY_SAVE_MIN: Final = 0.80
PENALTY_SAVE_SPAN: Final = 0.19
PENALTY_SIDES: Final = (-1, 0, 1)    # left / middle / right, from the taker
PENALTY_CERTAINTY_CAP: Final = 0.99  # nobody is ever a sure thing, items or not

KEEPER_QUALITY_BASE: Final = 0.55        # save odds floor before attributes
HARD_SHOT_SPEED: Final = 37.0            # ball speed counting as "hard" (observed max)
KEEPER_REACH: Final = 6.2                # lateral units = a full-stretch dive
SAVE_DIFFICULTY_SPEED_WEIGHT: Final = 0.5
SAVE_DIFFICULTY_REACH_WEIGHT: Final = 0.5
MAX_DIFFICULTY_PENALTY: Final = 0.5      # hardest shot halves the save chance
KEEPER_BEATEN_FRAMES: Final = 90 # How long a beaten keeper is on the floor.
SAVE_COMMIT_MARGIN: Final = 1.0
# The keeper only commits once the ball is genuinely on them -- either this
# close, or this near to reaching the line. Without it a save would resolve
# the instant a shot left the boot, from clear across the box.
SAVE_ENGAGE_DISTANCE: Final = 6.0
SAVE_ENGAGE_TIME: Final = 0.45

# BALL_GRAVITY / HEAD_CONTACT_HEIGHT: see game_config.py (imported above).

# A ball this fast can only be blocked from within this distance of it.
BLOCK_FAST_SPEED: Final = 12.0
# How long the passer's TEAMMATES are frozen out of a new pass; the passer
# themselves is out for the full ball_release_cooldown. 99 = the old whole-side
# freeze (longer than any cooldown).
TEAMMATE_RELEASE_BLOCK_FRAMES = 4

# Receiving. Comfort is the RELATIVE speed a clean first touch handles; running
# with the ball widens it. Above the stun speed, facing the wrong way, the ball
# bounces off them instead of through them.
# The base was 0.8, which with the stat bonuses put every raw control chance at
# 1.08-1.22 -- clipped to 0.99, so nobody ever miscontrolled and the stride/stun
# terms below were dead. Low enough now that a hard ball taken badly can be lost.
# Give and go: how long the passer keeps running, and how far ahead he aims.
PASS_AND_MOVE_FRAMES: Final = 45
PASS_AND_MOVE_PUSH: Final = 12.0

RECEIVE_BASE: Final = 0.55
RECEIVE_STRIDE_WEIGHT: Final = 0.30
RECEIVE_COMFORT_SPEED: Final = 18.0
RECEIVE_ALIGN_BONUS: Final = 0.8
RECEIVE_STUN_SPEED: Final = 22.0
RECEIVE_STUN_FRAMES: Final = 12
RECEIVE_DEFLECT_KEEP: Final = 0.25   # pace kept by a ball that comes off a bad touch

# How long a player who muffed his touch waits before he may try again. Short,
# because the ball is usually still at his feet: a long one meant an opponent
# collected his own miscontrol for him.
CAPTURE_RETRY_FRAMES: Final = 3

# Close enough that the ball has gone THROUGH him, not merely past him.
BALL_TOUCH_RADIUS: Final = 0.45
BODY_TOUCH_KEEP: Final = 0.22   # pace left on a ball that hits a man who cannot control it
CAPTURE_RETRY_FRAMES: Final = 4  # ...and how soon he may try again

# How far down the queue a loose ball is offered before it is left to run.
LOOSE_BALL_OFFERS: Final = 3

BLOCK_FAST_RADIUS: Final = 1.5

# --- Heading ---------------------------------------------------------------
# A ball at or above HEAD_MIN_HEIGHT is an aerial ball: it flies over anyone
# whose reach (_head_reach) is below it, and is headed by anyone it isn't.
HEAD_MIN_HEIGHT: Final = 1.2
HEAD_RADIUS: Final = 1.25             # lateral distance to be in a header contest
HEAD_STANDING_BONUS: Final = 0.25    # standing reach above body height
HEADER_SIGMA_FLOOR: Final = 0.3
HEAD_JUMP_MAX: Final = 0.6           # extra reach at 100 heading/agility
KEEPER_HAND_REACH: Final = 0.9       # arms up, on top of body height
HEADER_SHOT_SPEED: Final = (14.0, 24.0)    # at heading 0 / 100
HEADER_CLEAR_SPEED: Final = (12.0, 20.0)
HEADER_FLICK_SPEED: Final = 9.0
HEADER_SHOT_RANGE: Final = 22.0      # units from the enemy goal to head at it
HEADER_CLEAR_RANGE: Final = 30.0     # units from own goal to head it away

# --- Crosses ---------------------------------------------------------------
# A cross is flighted to arrive at HEAD_CONTACT_HEIGHT after a flight time
# of distance / CROSS_FLIGHT_REF_SPEED seconds (clamped); the launch speed
# is solved from the air friction, capped by the crosser's power.
# While airborne these events fly on BALL_AIR_FRICTION, not ground friction.
LOFTED_EVENTS: Final = frozenset({"cross", "clearance"})
CROSS_ARRIVAL_HEIGHT: Final = HEAD_CONTACT_HEIGHT
CROSS_FLIGHT_REF_SPEED: Final = 22.0
CROSS_FLIGHT_MIN: Final = 0.8
CROSS_FLIGHT_MAX: Final = 1.8
CROSS_MAX_SPEED: Final = 32.0

base_kick_pow:Final = 20

# --- rest defence ------------------------------------------------------------
CB_HOME_DEPTH: Final[float] = 40.0
CB_HOME_HALF_WIDTH: Final[float] = 20.0
CORNER_REST_LINE_BEHIND_HALFWAY: Final[float] = 5.0
CORNER_REST_SPACING: Final[float] = 9.0


def _norm2(v) -> float:
    """|v| for a 2-vector -- see player.py's _norm2."""
    return math.hypot(float(v[0]), float(v[1]))

# --- pass execution error --------------------------------------------------
#
# Every pass leaves the boot with an angular error drawn from the passer's
# `accuracy` attribute -- the one thing that stat does. Angular rather than
# a fixed offset at the target, so a misplaced pass drifts further the
# longer it travels, like a real one. sigma in degrees is
# PASS_AIM_ERROR_DEGREES * (100 - accuracy) / 100, times the per-type factor:
# 8 degrees * 0.5 = 4 degrees for a 50-accuracy player, ~1 unit sideways
# on a 15-unit pass; an icon's 96 is 0.3 degrees, near enough perfect.
# Distinct from the DECISION error (vision, in player.py's target choice):
# a great reader of the game who can't strike a ball picks the right
# pass and misses it; the reverse picks the wrong one and hits it.
PASS_AIM_ERROR_DEGREES: Final[float] = 8.0
# Crosses and clearances already carry a target fuzz of their own (see
# player._choose_cross_target), and a throw-in is short and two-handed.
PASS_AIM_ERROR_BY_TYPE: Final[dict] = {
    "normal": 1.0, "through_ball": 1.0, "cross": 0.5, "clearance": 0.5, "throw_in": 0.25,
}
base_speed: Final = PLAYER_BASE_SPEED     # see game_config: shared with player.py
possession_radius: Final = POSSESSION_RADIUS
final_whistle_delay: Final = 600
OUT_OF_POSITION_PENALTY: Final = 0.9

def _apply_out_of_position_penalty(p):
    """Returns a shallow copy of p with every non-tendency Attributes field
    scaled by OUT_OF_POSITION_PENALTY (and .overall recomputed to match) --
    used only for a player playing a formation slot that differs from, but
    is_similar_position() to, their own card position. The original player
    object -- and its Attributes instance -- is never mutated: this is a
    per-match sim detail only, never touching what's persisted or shown on
    the card (see game.__init__, the only caller).

    Imports player.player locally rather than at module level: player.player
    itself imports PITCH_WIDTH/PITCH_HEIGHT from this module, so a top-level
    import here would be a genuine two-way cycle (unlike formations.py's,
    which only ever needs 2 constants already defined before it's reached).
    Deferred to call time, well after both modules have fully loaded.
    """
    from player.player import Attributes, TENDENCY_FIELDS, PHYSICAL_FIELDS

    original_fields = asdict(p.attributes)
    scaled_fields = {
        # height is centimetres, not a skill -- scaling it shrank the player.
        field: (value if field in TENDENCY_FIELDS or field in PHYSICAL_FIELDS
                else round(value * OUT_OF_POSITION_PENALTY))
        for field, value in original_fields.items()
    }
    penalized = copy.copy(p)
    penalized.attributes = Attributes(**scaled_fields)
    penalized.overall = penalized._calculate_overall()
    return penalized


def _combine_formations(formation_home: str, formation_away: str) -> dict:
    """Builds the 22-slot {index: {"pos": [x, y], "role": str}} layout used by
    the sim, taking team A's 11 slots from formation_home and team B's 11
    slots from formation_away. Both named formations already mirror their own
    base shape across both axes for indices 11-21 (see formations.py), so
    each half can be sourced independently without re-deriving the mirror.
    """
    home = get_formation(formation_home)
    away = get_formation(formation_away)
    combined = {i: home[i] for i in range(11)}
    combined.update({i: away[i] for i in range(11, 22)})
    return combined


class game:
    def __init__(self, teamA, teamB, seed=None, record_replay=False, formation_home="4-4-2", formation_away="4-4-2", decision_interval=2, adaptive_decisions=True):

        self.teamA = teamA # name, short_name, players
        self.teamB = teamB
        self.seed = seed
        self.decision_interval = max(1, int(decision_interval))
        self.adaptive_decisions = bool(adaptive_decisions)
        self._last_actions: list = [None] * 22
        self._decision_rounds = np.ones(22, dtype=int)
        self._decisions_made = 0  # counter for cost reporting (local_match.py)
        self._prev_phase = None
        self.rng = np.random.default_rng(seed)
        self.replay = ReplayRecorder() if record_replay else None

        self.formation_home = formation_home
        self.formation_away = formation_away
        self.formation = _combine_formations(formation_home, formation_away)
        self._keeper_indices = [i for i in range(22) if self.formation[i]["role"] == "GK"]
        self._cb_mask = np.array([self.formation[i]["role"] == "CB" for i in range(22)])
        # Each player's target goal and own goal, fixed for the match -- the
        # state dicts step() builds hand these out every round.
        self._goal_targets = np.array([self._goal_for_player(i) for i in range(22)], dtype=float)
        self._own_goals = np.array([[35.0, 0.0] if i < 11 else [35.0, 100.0] for i in range(22)], dtype=float)

        # A player whose card position differs from their assigned slot's
        # role only ever reaches here already validated as "similar enough"
        # -- backend/main.py's /match/simulate rejects anything else before
        # a game() is even constructed (packedfootball/main.py's own local
        # play never lets this happen either, since it only ever builds a
        # roster that matches its formation 1:1). So this only ever
        # penalizes a legitimate similar-position substitution, never an
        # arbitrary mismatch.
        raw_players = self.teamA.players + self.teamB.players
        self.all_players = [
            p if p.position == self.formation[i]["role"] else _apply_out_of_position_penalty(p)
            for i, p in enumerate(raw_players)
        ]
        # How high each player can get to a ball, fixed for the match.
        # Pace per player, cached like _reach: the decision layer needs a
        # teammate's and an opponent's top speed, not just their velocity.
        self._pace = np.array([pace_ability(p.attributes.speed) * base_speed for p in self.all_players], dtype=float)
        self._reach = np.array([self._head_reach(i) for i in range(22)], dtype=float)
        # A plan a player is latched onto across decision rounds ("wingplay"),
        # carried on the action dict's "intent" key; cleared on ball release.
        self.intent: list = [None] * 22

        self.positions = np.zeros((22,2),float) # (x,y) pairs
        self.velocity = np.zeros((22,2),float) # (vx,vy) pairs

        self.heading = np.zeros((22,2),float) # (hx,hy) pairs
        self.heading[0:11] = [0.0, 1.0] 
        self.heading[11:22] = [0.0, -1.0] 

        self.ball = np.array([35.0, 50.0, 0.0, 0.0, 0.0,],float) # (x,y,vx,vy,height)
        # Vertical velocity, units/s. Engine-only: the replay records height.
        self.ball_vz = 0.0
        self.scores = [0, 0]
        self.last_goal_team = None
        self.post_hits = 0      # woodwork strikes, feeds stoppage time
        self.restart_count = 0  # throw-ins/corners/goal kicks, feeds stoppage time

        # Added time actually played, per half, in frames. Set by run_match
        # when each half's regulation time runs out; the frontend pass reads
        # these to show "+3".
        self.added_time_frames = [0, 0]
        # Extra frames played past the announced added time because an attack
        # was still live when the whistle was due, per half.
        self.whistle_hold_frames = [0, 0]
        self._half_stoppage_mark = {"goals": 0, "restarts": 0, "posts": 0}

        from player.player import MATCH_STAT_FIELDS

        self.match_stats = [
            {field: 0 for field in MATCH_STAT_FIELDS} for _ in range(22)
        ]

        self.last_shot_player = -1
        self.last_shot_on_target = False
        self.last_pass_player = -1
        self.pass_receiver = -1
        self.pass_and_move = -1
        self.pass_and_move_timer = 0
        # Identifies the shot currently in flight so each keeper gets exactly
        # one save attempt at it. -1 means no live shot.
        self.active_shot_id = -1
        self._shot_counter = 0
        self.save_attempted_shot = [-1] * 22
        self._match_goals = [0] * 22
        self._match_assists = [0] * 22
        self.stamina = np.full(22, STAMINA_MAX, dtype=float)
       
        self.ball_controller = -1  # -1 indicates a loose ball. 0-21 corresponds to the player index currently in possession.
        self.ball_event = "neutral"
        
        self.possession_radius = possession_radius
        self.player_radius = PLAYER_RADIUS
        self.step_count = 0
        self.match_clock_frames = 0

        # Half length in clock frames, and where the first half stopped.
        # run_match overwrites the first from its own max_steps and sets the
        # second at the whistle; together they let display_clock_frames put
        # the second half back at 45:00. -1 means "first half still".
        self.regulation_half_frames = REGULATION_FRAMES // 2
        self.halftime_clock_frames = -1

        self.ball_release_cooldown = 0
        self.ball_release_team_cooldown = 0
        self.ball_release_player = -1
        self.ball_capture_cooldown = 0
        self.ball_capture_player = -1
        self.player_stun_cooldown = np.zeros(22, dtype=int)
        self.last_touch_team = None
        self.last_touch_player = -1
        self.assist_candidate = -1
        self.goal_popup = {"text": "", "timer": 0, "team": None}
        self.goal_pause_timer = 0 
        self.kickoff_timer = 0
        self.kickoff_team = 0
        self.kickoff_pass_required = False
        self.kickoff_pass_player = -1
        self.must_pass_next = False
        self.must_pass_player = -1
        self.out_of_play = False
        self.restart_type = None
        self.restart_team = None
        self.restart_player = None
        self.free_kick_kind = None
        self.pending_restart_pass_player = -1
        self.restart_timer = 0  
        # Outlives restart_type AND restart_player, both cleared the moment the
        # whistle goes, so the restart's first touch still knows what it is.
        self.pending_restart_pass_type = None
        self.camera_mode = "zoom" 
        self.visual_action = [""] * 22
        self.visual_action_timer = np.zeros(22, dtype=int)
        self.final_whistle_clock = 0
        self.halftime_pause_timer = 0
        
        self.kickoff_team = 0
        self.kickoff_timer = 60
        self.reset_positions(restart_type="kickoff", team=0)
        if self.replay:
            self.replay.event(0, ActionType.KICKOFF, team=0)


    def _resolve_player_collisions(self):
        # One pairwise distance matrix picks out the (rare) pairs that could
        # be touching; only those go through the push-apart, in the same
        # (i, j) order the old all-pairs loop used, re-measuring as it goes.
        # Candidates are taken at twice the radius so a pair pushed INTO
        # contact by an earlier pair's move is still seen. This used to be
        # 231 Python-level norm() calls per frame -- most of tick()'s cost.
        min_dist = self.player_radius
        delta_all = self.positions[:, None, :] - self.positions[None, :, :]
        dist_all = np.sqrt(np.einsum("ijk,ijk->ij", delta_all, delta_all))
        candidates = np.argwhere(np.triu(dist_all < 2.0 * min_dist, k=1))
        for i, j in candidates:
            delta = self.positions[i] - self.positions[j]
            dist = float(np.hypot(delta[0], delta[1]))

            if dist == 0.0:
                delta = np.array([0.0, 1e-3])
                dist = 1e-3

            if dist < min_dist:
                normal = delta / dist
                overlap = (min_dist - dist) / 2.0
                self.positions[i] += normal * overlap
                self.positions[j] -= normal * overlap

        self.positions[:, 0] = np.clip(self.positions[:, 0], 0.0, PITCH_WIDTH)
        self.positions[:, 1] = np.clip(self.positions[:, 1], 0.0, PITCH_HEIGHT)

        if self.ball_controller >= 0:
            self.ball[0:2] = self.positions[self.ball_controller]
            self.ball[2:4] = self.velocity[self.ball_controller]
            self.ball[4] = 0.0
            self.ball_vz = 0.0

    def _pick_role_slot(self, team: int, preferred_roles: tuple, fallback_local_index: int) -> int:
        """Finds the first slot on `team` whose formation role matches, in
        preference order. Falls back to a fixed local index (0-10) so this
        degrades to the old hardcoded-index behavior if a formation is ever
        missing every preferred role. 4-4-2's own roles line up with the old
        hardcoded indices exactly, so this is a no-op for the default formation.
        """
        base = 0 if team == 0 else 11
        for role in preferred_roles:
            for local_i in range(11):
                if self.formation[base + local_i]["role"] == role:
                    return base + local_i
        return base + fallback_local_index

    def _kickoff_player_for_team(self, team: int | None = None) -> int:
        team_id = self.kickoff_team if team is None else team
        return self._pick_role_slot(team_id, ("ST", "CF"), 9)

    def _pick_nearest_eligible(self, team: int, point: np.ndarray, preferred_roles: tuple) -> int:
        """The player on `team` best placed to take a restart at `point`.

        Falls back to any outfield player if the formation has none of the
        preferred roles -- never the keeper.
        """
        base = 0 if team == 0 else 11
        candidates = [
            base + i for i in range(11) if self.formation[base + i]["role"] in preferred_roles
        ]
        if not candidates:
            candidates = [base + i for i in range(1, 11)]  # skip the GK at local index 0
        point = np.asarray(point, dtype=float)
        return min(candidates, key=lambda idx: float(_norm2(self.positions[idx] - point)))

    def _shift_shape_toward(self, point: np.ndarray, team: int) -> None:
        """Pulls both teams toward a restart, so play doesn't resume with all
        22 players standing in their static formation slots while the ball
        sits on a touchline thirty metres away.

        The shift is RELATIVE -- everyone keeps their shape and their relative
        spacing, they just slide toward the action, with the nearest few
        teammates committing hardest so the taker actually has someone to
        throw to. Opponents shift less: they react to the restart rather than
        organising it.
        """
        point = np.asarray(point, dtype=float)
        base = 0 if team == 0 else 11
        teammates = [base + i for i in range(1, 11)]  # keeper holds their line
        opponents = [(11 if team == 0 else 0) + i for i in range(1, 11)]

        # Closest three teammates commit; the rest drift across.
        teammates.sort(key=lambda idx: float(_norm2(self.positions[idx] - point)))
        for rank, idx in enumerate(teammates):
            pull = 0.55 if rank < 3 else 0.2
            self.positions[idx] += (point - self.positions[idx]) * pull

        for idx in opponents:
            self.positions[idx] += (point - self.positions[idx]) * 0.15

        # Spread anyone who ended up stacked on the ball, and keep everyone on
        # the pitch. _resolve_player_collisions handles overlap once play
        # resumes, but a support player standing exactly on the thrower makes
        # the throw itself impossible.
        for idx in teammates + opponents:
            offset = self.positions[idx] - point
            distance = float(_norm2(offset))
            if distance < 2.5:
                direction = offset / distance if distance > 1e-8 else np.array([0.0, 1.0])
                self.positions[idx] = point + direction * 2.5
        self.positions[:, 0] = np.clip(self.positions[:, 0], 0.0, PITCH_WIDTH)
        self.positions[:, 1] = np.clip(self.positions[:, 1], 0.0, PITCH_HEIGHT)

    def _set_must_pass_for_player(self, player_idx: int):
        self.must_pass_next = True
        self.must_pass_player = player_idx
        self.kickoff_pass_required = True
        self.kickoff_pass_player = player_idx

    def _clear_must_pass(self):
        self.must_pass_next = False
        self.must_pass_player = -1
        self.kickoff_pass_required = False
        self.kickoff_pass_player = -1

    def _maybe_kickoff(self):
        if self.kickoff_timer > 0:
            self.kickoff_timer -= 1
            kickoff_player = self._kickoff_player_for_team()
            self.positions[kickoff_player] = np.array([35.0, 50.0], dtype=float)
            self.ball[:] = [35.0, 50.0, 0.0, 0.0, 0.0]
            self.ball_vz = 0.0
            self.ball_controller = kickoff_player
            self._set_must_pass_for_player(kickoff_player)
            if self.kickoff_timer == 0:
                self.out_of_play = False
                self.ball_release_player = -1
                self.ball_release_cooldown = 0
                self.ball_release_team_cooldown = 0

    def _register_touch(self, player_index: int):
        if self.last_touch_player == player_index:
            return
            
        curr_team = 0 if player_index < 11 else 1
        
        if self.last_touch_player != -1:
            prev_team = 0 if self.last_touch_player < 11 else 1
            if prev_team == curr_team:
                self.assist_candidate = self.last_touch_player
            else:
                self.assist_candidate = -1
                
        self.last_touch_player = player_index
        self.last_touch_team = curr_team

    def _trigger_goal_popup(self, team_label: str):
        self.goal_popup = {"text": f"GOAL {team_label}", "timer": 90, "team": team_label}

    def reset_positions(self, restart_type: str | None = None, team: int | None = None):
        if restart_type == "free_kick":
            # Deliberately NO formation reset. Snapping all 22 back on every
            # foul would wipe the attacking shape that won the free kick --
            # _begin_restart places only the ball, the taker and the wall.
            self.velocity[:] = 0.0
            return

        for i in range(22):
            self.positions[i] = np.array(self.formation[i]["pos"], dtype=float)
        self.velocity[:] = 0.0
        self.heading[0:11] = [0.0, 1.0]
        self.heading[11:22] = [0.0, -1.0]

        if restart_type == "kickoff":
            kickoff_player = self._kickoff_player_for_team(team)
            self.positions[kickoff_player] = np.array([35.0, 50.0], dtype=float)
            self.ball[:] = [35.0, 50.0, 0.0, 0.0, 0.0]
            self.ball_vz = 0.0
            self.ball_controller = kickoff_player
            self._set_must_pass_for_player(kickoff_player)
            return

        if restart_type == "throw_in":
            self.ball[:] = [35.0, 50.0, 0.0, 0.0, 0.0]
            self.ball_vz = 0.0
            self.ball_controller = -1
            return

        if restart_type == "penalty":
            # Everyone crowds the edge of the area waiting for the rebound --
            # only the keeper is inside it, and the taker is placed on the spot
            # by _begin_restart. They used to be left in their own defensive
            # third, which is not what a penalty looks like.
            attacking = team if team is not None else 0
            box_is_high = (1 - attacking) == 1
            edge = 79.0 if box_is_high else 21.0
            depth = -1.0 if box_is_high else 1.0
            crowd = [i for i in range(22) if i not in self._keeper_indices]
            # Alternate the sides around the D so it is not one team in a line.
            crowd.sort(key=lambda i: (i % 2, i))
            span = np.linspace(17.0, 53.0, num=len(crowd))
            for n, i in enumerate(crowd):
                self.positions[i] = np.array([
                    float(span[n]) + self.rng.uniform(-1.5, 1.5),
                    edge + depth * self.rng.uniform(0.0, 6.0),
                ])
            self.ball_controller = -1
            return

        if restart_type == "corner":
            attacking_y = 85.0 if team == 0 else 15.0
            defending_y = 92.0 if team == 0 else 8.0
            
            a_box = [2, 3, 6, 7, 9, 10] if team == 0 else [13, 14, 17, 18, 20, 21]
            d_box = [12, 13, 14, 15, 16, 17, 18, 19] if team == 0 else [1, 2, 3, 4, 5, 6, 7, 8]

            for p in a_box:
                self.positions[p] = [35.0 + self.rng.uniform(-10, 10), attacking_y + self.rng.uniform(-4, 4)]

            # Everyone else on the attacking side bar the keeper and the taker
            # -- the full-backs and the wide midfielder, in 4-4-2 -- forms a
            # rest-defence line behind halfway, centred, so a clearance meets
            # a body in the middle rather than an empty pitch.
            keeper = 0 if team == 0 else 11
            # Same pick _begin_restart makes just after this returns (it
            # snaps the taker to the flag then) -- restart_player itself is
            # still the previous restart's here.
            taker = self._pick_role_slot(team, ("RW", "LW", "RM", "LM", "LWB", "RWB"), 8)
            rest = [p for p in (range(0, 11) if team == 0 else range(11, 22)) if p not in a_box and p not in (keeper, taker)]
            rest_y = 50.0 - CORNER_REST_LINE_BEHIND_HALFWAY if team == 0 else 50.0 + CORNER_REST_LINE_BEHIND_HALFWAY
            for k, p in enumerate(rest):
                self.positions[p] = [35.0 + (k - (len(rest) - 1) / 2.0) * CORNER_REST_SPACING, rest_y]

            for p in d_box:
                self.positions[p] = [35.0 + self.rng.uniform(-12, 12), defending_y + self.rng.uniform(-3, 3)]

            self.ball[:] = [35.0, 50.0, 0.0, 0.0, 0.0]
            self.ball_vz = 0.0
            self.ball_controller = -1
            return
        if restart_type == "goal_kick":
            self.ball[:] = [35.0, 50.0, 0.0, 0.0, 0.0]
            self.ball_vz = 0.0
            self.ball_controller = -1
            return

    def _begin_restart(
        self,
        restart_type: str,
        team: int | None = None,
        out_x: float = 35.0,
        out_y: float | None = None,
    ):
        """Sets up a restart. `out_x`/`out_y` are where the ball ACTUALLY left
        the pitch -- a throw-in is taken from that point on the touchline, not
        from wherever the taker's formation slot happens to sit (which is what
        it used to do, putting every throw-in in the middle of the park).
        """
        self.out_of_play = True
        self.restart_type = restart_type
        self.restart_team = team if team is not None else (0 if self.last_touch_team is None else 1 - self.last_touch_team)
        self.restart_timer = 30
        self.ball_controller = -1
        self.ball_release_player = -1
        self.ball_release_cooldown = 0
        self.ball_release_team_cooldown = 0
        self.pending_restart_pass_type = None
        self.pending_restart_pass_player = -1
        if restart_type in ("throw_in", "corner", "goal_kick", "free_kick", "penalty"):
            self.restart_count += 1
        self.reset_positions(restart_type=restart_type, team=self.restart_team)

        if restart_type == "kickoff":
            self.kickoff_team = self.restart_team
            kickoff_player = self._kickoff_player_for_team(self.kickoff_team)
            self.positions[kickoff_player] = np.array([35.0, 50.0], dtype=float)
            self.ball[:] = [35.0, 50.0, 0.0, 0.0, 0.0]
            self.ball_vz = 0.0
            self.ball_controller = kickoff_player
            self._set_must_pass_for_player(kickoff_player)
            self.kickoff_timer = 30
        elif restart_type == "free_kick":
            spot = np.array([out_x, out_y if out_y is not None else 50.0], dtype=float)
            self.ball[:] = [spot[0], spot[1], 0.0, 0.0, 0.0]
            self.ball_vz = 0.0
            # Three different set pieces wearing one name -- see each setup.
            self.free_kick_kind = self._free_kick_kind(spot, self.restart_team)
            if self.free_kick_kind == "shooting":
                taker = self._setup_shooting_free_kick(spot, self.restart_team)
            elif self.free_kick_kind == "crossable":
                taker = self._setup_crossable_free_kick(spot, self.restart_team)
            else:
                taker = self._setup_defensive_free_kick(spot, self.restart_team)
            self.restart_player = taker
            if self.free_kick_kind != "shooting":
                # Ten yards, for every kind. Without it an opponent can stand on
                # the ball and simply take the free kick off the side that won
                # it -- and the man who fouled is back within tackling range.
                self._clear_free_kick_ring(spot, self.restart_team, {taker})
                # And he must PLAY it, not dribble away from the spot. Set
                # directly rather than via _set_must_pass_for_player, which also
                # arms the kickoff fields and those belong to a kickoff.
                self.must_pass_next = True
                self.must_pass_player = taker
            self.restart_timer = FREE_KICK_SETUP_FRAMES
            if self.replay:
                self.replay.event(
                    self.match_clock_frames,
                    ActionType.FREE_KICK_SHOT if self.free_kick_kind == "shooting"
                    else ActionType.FREE_KICK,
                    player_idx=taker, team=self.restart_team,
                )

        elif restart_type == "penalty":
            goal_y = PITCH_HEIGHT if self.restart_team == 0 else 0.0
            spot_y = goal_y - 11.0 if self.restart_team == 0 else 11.0
            self.ball[:] = [PITCH_WIDTH / 2.0, spot_y, 0.0, 0.0, 0.0]
            self.ball_vz = 0.0
            taker = self._pick_role_slot(self.restart_team, ("ST", "CF", "CAM", "LW", "RW"), 9)
            self.restart_player = taker
            back = -1.5 if self.restart_team == 0 else 1.5
            keeper = self._keeper_indices[1] if self.restart_team == 0 else self._keeper_indices[0]
            # Placed, not walked: the taker starts at his formation slot ~42
            # units away, and no plausible setup time covers that. A penalty is
            # a staged scene -- he is already stood over the ball.
            self.positions[taker] = np.array([PITCH_WIDTH / 2.0, spot_y + back])
            self.positions[keeper] = np.array([PITCH_WIDTH / 2.0, goal_y])
            self.restart_timer = PENALTY_SETUP_FRAMES
            if self.replay:
                self.replay.event(
                    self.match_clock_frames, ActionType.PENALTY,
                    player_idx=taker, team=self.restart_team,
                )

        elif restart_type == "corner":
            corner_player = self._pick_role_slot(self.restart_team, ("RW", "LW", "RM", "LM", "LWB", "RWB"), 8)
            self.restart_player = corner_player
            
            # Snap player to the left or right corner flag depending on out_x
            corner_x = 0.0 if out_x < 35.0 else PITCH_WIDTH
            corner_y = PITCH_HEIGHT if self.restart_team == 0 else 0.0
            
            self.positions[corner_player] = [corner_x, corner_y]
            self.ball[:] = [corner_x, corner_y, 0.0, 0.0, 0.0]
            self.ball_vz = 0.0
            self.ball_controller = corner_player
            self._set_must_pass_for_player(corner_player)
            
        elif restart_type == "goal_kick":
            keeper = 0 if self.restart_team == 0 else 11
            self.restart_player = keeper
            self.ball[:] = [self.positions[keeper][0], self.positions[keeper][1], 0.0, 0.0, 0.0]
            self.ball_vz = 0.0
            self.ball_controller = keeper
            self._set_must_pass_for_player(keeper)
        elif restart_type == "throw_in":
            throw_x = 0.0 if out_x < PITCH_WIDTH / 2.0 else PITCH_WIDTH
            throw_y = float(np.clip(35.0 if out_y is None else out_y, 1.0, PITCH_HEIGHT - 1.0))
            throw_point = np.array([throw_x, throw_y], dtype=float)

            # Full-backs and wide players take throw-ins, nearest one first --
            # see _pick_nearest_eligible for why proximity matters here.
            throw_player = self._pick_nearest_eligible(
                self.restart_team, throw_point, ("LB", "RB", "LWB", "RWB", "LM", "RM", "LW", "RW")
            )
            self.restart_player = throw_player

            self._shift_shape_toward(throw_point, self.restart_team)
            self.positions[throw_player] = throw_point.copy()
            self.ball[:] = [throw_x, throw_y, 0.0, 0.0, 0.0]
            self.ball_vz = 0.0
            self.ball_controller = throw_player
            self._set_must_pass_for_player(throw_player)
            # Survives restart_timer expiring (which clears restart_type), so
            # the throw itself is still thrown rather than kicked -- see
            # _resolve_action's pass branch.
            self._arm_restart_pass("throw_in", throw_player)

        if self.replay:
            restart_event = {
                "kickoff": ActionType.KICKOFF,
                "corner": ActionType.CORNER,
                "goal_kick": ActionType.GOAL_KICK,
                "throw_in": ActionType.THROW_IN,
            }.get(restart_type)
            if restart_event is not None:
                self.replay.event(self.match_clock_frames, restart_event, team=self.restart_team)

    def render(self, screen, window_size=(1280, 800)):
        try:
            import pygame
        except ImportError as exc: 
            raise RuntimeError("pygame is required for rendering. Install it with: pip install pygame") from exc

        width, height = window_size
        
        # --- Camera Logic ---
        if getattr(self, "camera_mode", "zoom") == "full":
            # Scale to fit the entire pitch 
            scale_x = width / PITCH_WIDTH
            scale_y = height / PITCH_HEIGHT
            scale = min(scale_x, scale_y)
            
            # Center the pitch if aspect ratio has empty space
            offset_x = (width - (PITCH_WIDTH * scale)) / 2.0
            offset_y = (height - (PITCH_HEIGHT * scale)) / 2.0
            camera_x = -offset_x / scale
            camera_y = -offset_y / scale
        else:
            # Zoom Camera Logic
            visible_pitch_width = 40.0
            visible_pitch_height = visible_pitch_width * (height / width)
            scale = width / visible_pitch_width

            camera_x = self.ball[0] - visible_pitch_width / 2.0
            camera_y = self.ball[1] - visible_pitch_height / 2.0
            camera_x = max(0, min(camera_x, PITCH_WIDTH - visible_pitch_width))
            camera_y = max(0, min(camera_y, PITCH_HEIGHT - visible_pitch_height))

        def to_screen(px, py):
            return int((px - camera_x) * scale), int((py - camera_y) * scale)

        def draw_pitch_rect(color, px, py, pw, ph, thickness=2):
            sx, sy = to_screen(px, py)
            pygame.draw.rect(screen, color, (sx, sy, int(pw * scale), int(ph * scale)), thickness)

        # Grass Background
        pygame.draw.rect(screen, (22, 120, 55), (0, 0, width, height))

        # Pitch Outlines
        draw_pitch_rect((255, 255, 255), 0, 0, PITCH_WIDTH, PITCH_HEIGHT, 2)
        
        # Halfway Line
        sx1, sy1 = to_screen(0, PITCH_HEIGHT / 2)
        sx2, sy2 = to_screen(PITCH_WIDTH, PITCH_HEIGHT / 2)
        pygame.draw.line(screen, (255, 255, 255), (sx1, sy1), (sx2, sy2), 2)
        
        # Center Circle and Spot
        cx, cy = to_screen(PITCH_WIDTH / 2, PITCH_HEIGHT / 2)
        pygame.draw.circle(screen, (255, 255, 255), (cx, cy), int(9.15 * scale), 2)
        pygame.draw.circle(screen, (255, 255, 255), (cx, cy), 3)

        # Top Penalty Box, 6-Yard Box, Goal
        draw_pitch_rect((255, 255, 255), 14, 0, 42, 18, 2)
        draw_pitch_rect((255, 255, 255), 26, 0, 18, 5.5, 2)
        draw_pitch_rect((200, 200, 200), 31.25, -2, 7.5, 2, 0)

        # Bottom Penalty Box, 6-Yard Box, Goal
        draw_pitch_rect((255, 255, 255), 14, 82, 42, 18, 2)
        draw_pitch_rect((255, 255, 255), 26, 94.5, 18, 5.5, 2)
        draw_pitch_rect((200, 200, 200), 31.25, 100, 7.5, 2, 0)

        # Players
        for idx, pos in enumerate(self.positions):
            sx, sy = to_screen(pos[0], pos[1])
            base_color = (50, 130, 255) if idx < 11 else (255, 90, 90)

            if self.visual_action_timer[idx] > 0:
                act = self.visual_action[idx]
                if act == "normal": color = (255, 255, 0)       # Yellow for Pass
                elif act == "clearance": color = (180, 50, 255) # Purple for Clear
                elif act == "cross": color = (255, 150, 0)      # Orange for Cross
                elif act == "shoot": color = (255, 255, 255)    # White for Shoot
                elif act == "tackle": color = (50, 255, 255)    # Cyan for Tackle
                elif act == "anklebreaker": color = (255,0,0)   # Red for broken ankle
                elif act == "recieved_pass": color = (0,255,0)  # Green for recieving pass
                elif act == "save": color = (255, 50, 150)      # Pink for saves
                elif act == "header": color = (255, 220, 120)   # Amber for headers
                else: color = (200, 200, 200)
            else:
                color = base_color
            
            radius = max(9, int(18 * (scale / (width / 40.0)))) # Scale player radius dynamically
            if self.ball_controller == idx:
                pygame.draw.circle(screen, (255, 255, 255), (sx, sy), radius + 4, 3)
            pygame.draw.circle(screen, color, (sx, sy), radius)

            # Heading Indicator
            heading = self.heading[idx]
            if _norm2(heading) > 0:
                heading = heading / _norm2(heading)
                end_x, end_y = to_screen(pos[0] + heading[0] * 1.5, pos[1] + heading[1] * 1.5)
                pygame.draw.line(screen, (255, 255, 255), (sx, sy), (end_x, end_y), 2)

            # Player Numbers
            font = pygame.font.SysFont(None, max(12, int(18 * (scale / (width / 40.0)))))
            label = font.render(str(idx), True, (0, 0, 0))
            screen.blit(label, label.get_rect(center=(sx, sy)))

            # Ball Carrier Nameplate
            if self.ball_controller == idx:
                name_font = pygame.font.SysFont(None, 26)
                name_surf = name_font.render(str(self.all_players[idx].lname), True, (255, 255, 255))
                name_rect = name_surf.get_rect(midbottom=(sx, sy - radius - 8))
                
                bg_rect = name_rect.inflate(8, 4)
                pygame.draw.rect(screen, (0, 0, 0), bg_rect)
                screen.blit(name_surf, name_rect)

        # Ball
        bx, by = to_screen(self.ball[0], self.ball[1])
        base_ball_radius = max(6, int(10 * (scale / (width / 40.0))))
        z_bonus = max(0, int(self.ball[4] * 2 * (scale / (width / 40.0))))
        pygame.draw.circle(screen, (255, 255, 255), (bx, by), base_ball_radius + z_bonus)
        pygame.draw.circle(screen, (0, 0, 0), (bx, by), base_ball_radius + z_bonus, 1)

        # HUD: Scoreboard and Clock
        hud_font = pygame.font.SysFont(None, 36)
        hud_small = pygame.font.SysFont(None, 22)
        clock_total_seconds = int(self.display_clock_frames() / 2.0)
        minutes = clock_total_seconds // 60
        seconds = clock_total_seconds % 60
        
        score_bg = pygame.Surface((180, 70))
        score_bg.set_alpha(150)
        score_bg.fill((0, 0, 0))
        screen.blit(score_bg, (10, 10))
        
        score_text = hud_font.render(f"{self.teamA.name} {self.scores[0]} - {self.scores[1]} {self.teamB.name}", True, (255, 255, 255))
        clock_text = hud_small.render(f"{minutes:02d}:{seconds:02d}", True, (255, 255, 255))
        screen.blit(score_text, (20, 18))
        screen.blit(clock_text, (20, 52))
        
        # --- UI Toggle Button ---
        btn_w, btn_h = 160, 45
        btn_x, btn_y = width - btn_w - 20, height - btn_h - 20
        pygame.draw.rect(screen, (40, 40, 40), (btn_x, btn_y, btn_w, btn_h), border_radius=8)
        pygame.draw.rect(screen, (200, 200, 200), (btn_x, btn_y, btn_w, btn_h), 2, border_radius=8)
        
        cam_text = "Camera: Full Pitch" if getattr(self, "camera_mode", "zoom") == "full" else "Camera: Zoom"
        cam_surf = hud_small.render(cam_text, True, (255, 255, 255))
        cam_rect = cam_surf.get_rect(center=(btn_x + btn_w / 2, btn_y + btn_h / 2))
        screen.blit(cam_surf, cam_rect)

        # Goal Popup
        if self.goal_popup["timer"] > 0:
            popup_font = pygame.font.SysFont(None, 72)
            popup = popup_font.render(self.goal_popup["text"], True, (255, 255, 255))
            popup_rect = popup.get_rect(center=(width / 2, height / 4))
            alpha = max(0, min(255, int((self.goal_popup["timer"] / 90.0) * 255)))
            popup.set_alpha(alpha)
            screen.blit(popup, popup_rect)
        

    def _head_reach(self, index: int) -> float:
        """Highest ball this player can get to, in pitch units (1 ~ 1m):
        body height plus a jump from heading/agility -- or, for a keeper,
        plus arms up. Keepers never head (see _attempt_capture)."""
        attrs = self.all_players[index].attributes
        body = float(getattr(attrs, "height", 180)) / 100.0
        agility = float(getattr(attrs, "agility", 50))
        if self.formation[index]["role"] == "GK":
            return body + KEEPER_HAND_REACH + 0.3 * agility / 100.0
        head_attr = float(getattr(attrs, "heading", 50))
        return body + HEAD_STANDING_BONUS + HEAD_JUMP_MAX * (0.5 * head_attr + 0.5 * agility) / 100.0

    def _fatigue_factor(self, index: int) -> float:
        """Speed multiplier from current stamina: 1.0 when fresh, down to
        STAMINA_MIN_SPEED_FACTOR when empty."""
        fraction = float(self.stamina[index]) / STAMINA_MAX
        return STAMINA_MIN_SPEED_FACTOR + (1.0 - STAMINA_MIN_SPEED_FACTOR) * fraction

    def _drain_stamina(self) -> None:
        """Charges every player for the work they did this step.

        Cost scales with how fast they're actually moving, and is divided by their stamina ATTRIBUTE relative to STAMINA_REFERENCE
        Players barely moving get a little back.
        """
        speeds = np.linalg.norm(self.velocity, axis=1)
        effort = np.clip(speeds / base_speed, 0.0, 1.5)

        resistance = np.array(
            [max(20.0, float(getattr(p.attributes, "stamina", STAMINA_REFERENCE))) for p in self.all_players],
            dtype=float,
        )
        drain = STAMINA_DRAIN_PER_STEP * effort * (STAMINA_REFERENCE / resistance)
        # Only a player who has genuinely stopped gets anything back. Scaling
        # recovery by (1 - effort) across the whole range meant a player
        # jogging at half pace recovered faster than they drained.
        idle = np.clip((STAMINA_RECOVERY_EFFORT - effort) / STAMINA_RECOVERY_EFFORT, 0.0, 1.0)
        recovery = STAMINA_RECOVERY_PER_STEP * idle

        self.stamina = np.clip(self.stamina - drain + recovery, 0.0, STAMINA_MAX)

    def _match_rating(self, index: int) -> float:
        """This player's rating for the match just played, 0.0-10.0.

        Starts from a 6.0 "did their job" baseline and moves on what the
        player actually did. Keepers are scored on a different axis --
        saves and goals conceded rather than shots and passes -- since a
        keeper who never touches the ball has had a fine game.
        """
        stats = self.match_stats[index]
        team = 0 if index < 11 else 1
        is_keeper = index in (0, 11)

        # Deliberately NOT read off player.statistics: those are career
        # totals loaded from Firestore, so a veteran would start every match
        # on a 10.0.
        rating = 6.0
        rating += self._match_goals[index] * 1.2
        rating += self._match_assists[index] * 0.8

        if is_keeper:
            rating += stats["saves"] * 0.45
            rating -= stats["goals_conceded"] * 0.55
            if stats["goals_conceded"] == 0:
                rating += 0.6
        else:
            rating += stats["shots_on_target"] * 0.25
            rating += stats["tackles_won"] * 0.2
            rating -= (stats["tackles"] - stats["tackles_won"]) * 0.1
            passes = stats["passes"]
            if passes >= 5:
                accuracy = stats["passes_completed"] / passes
                rating += (accuracy - 0.6) * 2.0
            # Conceding as an outfielder still stings, just far less.
            rating -= self.scores[1 - team] * 0.08

        return float(np.clip(round(rating, 2), 0.0, 10.0))

    def match_summary(self) -> list[dict]:
        """Per-player stats for the match just played, index-aligned with
        all_players (team A 0-10, team B 11-21).
        """
        summary = []
        for index in range(22):
            entry = dict(self.match_stats[index])
            entry["goals"] = self._match_goals[index]
            entry["assists"] = self._match_assists[index]
            entry["rating"] = self._match_rating(index)
            summary.append(entry)
        return summary

    def _finalize_match_stats(self) -> None:
        """Folds this match's counters and ratings into every card's career
        totals. Called once, at full time."""
        for index in range(22):
            if index in (0, 11) and self.match_stats[index]["goals_conceded"] == 0:
                self.match_stats[index]["clean_sheets"] = 1
            self.all_players[index].record_match(self.match_stats[index], self._match_rating(index))

    def _attacking_team_now(self) -> int | None:
        """Which side is attacking right now, or None if the ball is dead."""
        if self.out_of_play or self.restart_type is not None:
            return None
        if self.ball_controller != -1:
            return 0 if self.ball_controller < 11 else 1
        # Nobody has it -- whoever touched it last is still the side attacking.
        return self.last_touch_team

    def _attack_is_live(self, attacker: int | None) -> bool:
        """True while `attacker`'s attack is still going.

        A referee doesn't end a half with the ball in the box. The attacking
        side is LATCHED when the whistle first comes due, rather than
        re-derived each frame -- otherwise possession simply ping-pongs
        between two teams who are each "attacking" in turn and the half never
        ends.

        The attack is over once the ball goes dead, the other team takes
        control, or it is cleared back out of the final third.
        """
        if attacker is None:
            return False

        current = self._attacking_team_now()
        if current is None:          # out of play
            return False
        if current != attacker:      # other team controls it
            return False

        ball_y = float(self.ball[1])
        # Team 0 attacks y=PITCH_HEIGHT, team 1 attacks y=0.
        if attacker == 0:
            return ball_y > DANGEROUS_ZONE_Y
        return ball_y < PITCH_HEIGHT - DANGEROUS_ZONE_Y

    def _compute_added_time(self) -> int:
        """Added time for the half that just ran out, in frames.

        Counts only what happened since the last call, so the second half is
        scored on its own stoppages rather than the whole match's. Jitter is
        drawn from self.rng, so a given seed always produces the same added
        time.
        """
        goals = sum(self.scores) - self._half_stoppage_mark["goals"]
        restarts = self.restart_count - self._half_stoppage_mark["restarts"]
        posts = self.post_hits - self._half_stoppage_mark["posts"]

        raw = (
            ADDED_TIME_BASE_FRAMES
            + goals * ADDED_TIME_PER_GOAL
            + restarts * ADDED_TIME_PER_RESTART
            + posts * ADDED_TIME_PER_POST
        )
        frames = int(raw * float(self.rng.uniform(0.8, 1.3)))

        self._half_stoppage_mark = {
            "goals": sum(self.scores),
            "restarts": self.restart_count,
            "posts": self.post_hits,
        }
        return max(0, min(ADDED_TIME_MAX_FRAMES, frames))

    def run_match(self, max_steps: int = 10800, fps: int = 60, render: bool = False, window_size=(700, 1000), title: str = "Packed Football"):
        """Plays a full match. `max_steps` is REGULATION length in clock
        frames (10800 == 90:00); added time is played on top of it.

        The loop is driven by match_clock_frames rather than by a raw
        iteration count. That is the fix for matches ending at 88:30: the
        180-frame halftime pause deliberately doesn't advance the clock, so
        counting iterations meant the pause ate 1:30 of football.
        """
        dt = 1.0 / fps

        if render:
            try:
                import pygame
            except ImportError as exc:
                raise RuntimeError("pygame is required for rendering. Install it with: pip install pygame") from exc

            pygame.init()
            screen = pygame.display.set_mode(window_size)
            pygame.display.set_caption(title)
            clock = pygame.time.Clock()
            running = True
        else:
            screen = None
            running = True

        regulation_half = max_steps // 2
        self.regulation_half_frames = regulation_half
        first_half_end = None   # regulation + added time for the 1st half
        second_half_end = None  # ditto for the 2nd
        halftime_done = False

        halftime_attacker = _UNSET
        fulltime_attacker = _UNSET

        # The loop below advances on match_clock_frames, which stalls while
        # the game is paused -- so it needs its own escape hatch rather than
        # trusting the clock to always move.
        iterations = 0
        iteration_limit = max_steps * 3

        while running:
            iterations += 1
            if iterations > iteration_limit:
                break

            # --- First half's regulation time is up: how long do we add?
            if first_half_end is None and self.match_clock_frames >= regulation_half:
                self.added_time_frames[0] = self._compute_added_time()
                first_half_end = regulation_half + self.added_time_frames[0]

            # --- Trigger Halftime (after the first half's added time)
            if not halftime_done and first_half_end is not None and self.match_clock_frames >= first_half_end:
                if halftime_attacker is _UNSET:
                    halftime_attacker = self._attacking_team_now()
                if (
                    self._attack_is_live(halftime_attacker)
                    and self.whistle_hold_frames[0] < MAX_WHISTLE_HOLD_FRAMES
                ):
                    self.whistle_hold_frames[0] += 1
                else:
                    self.goal_popup = {"text": "HALF TIME", "timer": 180, "team": None}
                    self.halftime_pause_timer = 180
                    self.reset_positions(restart_type="kickoff", team=1)
                    # Where the first half actually stopped, which is 45:00
                    # plus however much stoppage it ran. display_clock_frames
                    # needs it to restart the shown clock at 45:00.
                    self.halftime_clock_frames = self.match_clock_frames
                    if self.replay:
                        self.replay.event(self.match_clock_frames, ActionType.HALFTIME)
                        self.replay.event(self.match_clock_frames, ActionType.KICKOFF, team=1)
                    halftime_done = True

            # --- Second half's regulation time is up
            if (
                halftime_done
                and second_half_end is None
                and self.match_clock_frames >= max_steps + self.added_time_frames[0]
            ):
                self.added_time_frames[1] = self._compute_added_time()
                second_half_end = max_steps + self.added_time_frames[0] + self.added_time_frames[1]

            if second_half_end is not None and self.match_clock_frames >= second_half_end:
                # Same at full time: let a live attack finish rather than
                # blowing up with the ball in the box.
                if fulltime_attacker is _UNSET:
                    fulltime_attacker = self._attacking_team_now()
                if (
                    self._attack_is_live(fulltime_attacker)
                    and self.whistle_hold_frames[1] < MAX_WHISTLE_HOLD_FRAMES
                ):
                    self.whistle_hold_frames[1] += 1
                else:
                    break

            if render:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                        break
                    elif event.type == pygame.MOUSEBUTTONDOWN:
                        if event.button == 1:
                            btn_w, btn_h = 160, 45
                            btn_x, btn_y = window_size[0] - btn_w - 20, window_size[1] - btn_h - 20
                            if btn_x <= event.pos[0] <= btn_x + btn_w and btn_y <= event.pos[1] <= btn_y + btn_h:
                                self.camera_mode = "full" if getattr(self, "camera_mode", "zoom") == "zoom" else "zoom"

            if self.match_clock_frames % self.decision_interval == 0:
                self.step()
            self.tick(dt)

            if render:
                screen.fill((0, 0, 0))
                self.render(screen, window_size)
                pygame.display.flip()
                clock.tick(fps)

        if self.replay:
            # Force a final snapshot on the exact tick FULLTIME lands on.
            #
            # Playback clamps its cursor to the last sample's tick and only
            # fires events at or before it (MatchPlayback.gd), so an event
            # past the final sample is simply never processed -- the replay
            # would sit on its last frame forever and never leave the match
            # screen. Samples are normally only written every
            # sample_interval_ticks, and added time means the whistle no
            # longer falls on a multiple of that.
            self.replay.snapshot(
                self.match_clock_frames, self.positions, self.velocity, self.ball, self.ball_controller
            )
            self.replay.event(self.match_clock_frames, ActionType.FULLTIME)

        # --- Final Whistle Render Loop ---
        if render:
            self.goal_popup = {"text": "FULL TIME", "timer": final_whistle_delay, "team": None}
            
            while self.final_whistle_clock < final_whistle_delay and running:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                
                self.final_whistle_clock += 1
                if self.goal_popup["timer"] > 0:
                    self.goal_popup["timer"] -= 1

                screen.fill((0, 0, 0))
                self.render(screen, window_size)
                pygame.display.flip()
                clock.tick(fps)
                
            pygame.quit()

        for i in range(22):
            self.all_players[i].match_played()
        self._finalize_match_stats()
        return self

    def tick(self, dt:float = 1/60):
        if self.halftime_pause_timer > 0:
            self.halftime_pause_timer -= 1
            return

        self.match_clock_frames += 1
        if self.goal_popup["timer"] > 0:
            self.goal_popup["timer"] -= 1

        if self.goal_pause_timer > 0:
            self.goal_pause_timer -= 1
            if self.goal_pause_timer == 0:
                self.reset_positions(restart_type="kickoff") 
                self.kickoff_timer = 60
            return

        if self.restart_type is not None:
            self.restart_timer = max(0, self.restart_timer - 1)
            # Sampled THROUGH the stoppage. tick() returns early here, before
            # the snapshot below ever ran, so the replay had a 36-66 tick hole
            # where every stoppage was and the client could only jump-cut --
            # the viewer never saw what happened.
            if self.replay and self.match_clock_frames % self.replay.sample_interval_ticks == 0:
                self.replay.snapshot(
                    self.match_clock_frames, self.positions, self.velocity,
                    self.ball, self.ball_controller,
                )
            if self.restart_timer == 0:
                if self.restart_type == "penalty":
                    self._take_penalty()
                elif self.restart_type == "free_kick" and self.free_kick_kind == "shooting":
                    self._take_direct_free_kick()
                self.restart_type = None
                self.restart_team = None
                self.restart_player = None
                self.out_of_play = False
            return

        self._maybe_kickoff()
        self.positions += self.velocity * dt
        self._resolve_player_collisions()

        prev_ball_xy = np.array(self.ball[0:2], dtype=float)
        prev_ball_height = float(self.ball[4])

        if self.ball_controller == -1:
            self.ball[0] += self.ball[2] * dt
            self.ball[1] += self.ball[3] * dt
            self.ball_vz -= BALL_GRAVITY * dt
            self.ball[4] += self.ball_vz * dt
            if self.ball[4] <= 0.0:
                self.ball[4] = 0.0
                self.ball_vz = 0.0

            lofted = self.ball[4] > 0.0 and self.ball_event in LOFTED_EVENTS
            friction = (BALL_AIR_FRICTION if lofted else BALL_GROUND_FRICTION) ** dt
            self.ball[2] *= friction
            self.ball[3] *= friction
            
            if abs(self.ball[2]) < 0.1: self.ball[2] = 0.0
            if abs(self.ball[3]) < 0.1: self.ball[3] = 0.0
        else:
            self.ball[0:2] = self.positions[self.ball_controller]
            self.ball[2:4] = self.velocity[self.ball_controller]
            self.ball[4] = 0.0
            self.ball_vz = 0.0

        # Goal frame FIRST. A ball crossing the goal plane is a goal or a
        # rebound off the woodwork; either way the out-of-bounds branch below
        # must not get to claim it. This ordering is the fix for balls
        # disappearing into a scoreless kickoff.
        frame_result = self._resolve_goal_frame(prev_ball_xy, prev_ball_height)
        if frame_result == "goal":
            return

        if self.ball_controller == -1:
            self._body_check(prev_ball_xy)
        if frame_result == "rebound":
            # Ball is back in play just inside the line; skip the
            # out-of-bounds check this tick and let it run on.
            frame_rebounded = True
        else:
            frame_rebounded = False

        if not frame_rebounded and (
            self.ball[0] < 0.0 or self.ball[0] > PITCH_WIDTH or self.ball[1] < 0.0 or self.ball[1] > PITCH_HEIGHT
        ):
            out_x = self.ball[0]  # Store out-of-bounds X coordinate to determine which corner flag to use

            if self.ball[1] < 0.0 or self.ball[1] > PITCH_HEIGHT:
                # Anything reaching here crossed the endline WITHOUT being a
                # goal or hitting the frame (_resolve_goal_frame already
                # consumed those) -- so it is always a corner or a goal kick,
                # decided by who touched it last. There used to be a
                # "restart as a kickoff if it went through the goal mouth"
                # branch here; that was the scoreless-kickoff bug, and a ball
                # over the crossbar now correctly becomes a goal kick.
                if self.ball[1] < 0.0:  # Team A's endline (Y = 0)
                    if self.last_touch_team == 0:
                        restart_type = "corner"
                        restart_team = 1  # Team B attacks
                    else:
                        restart_type = "goal_kick"
                        restart_team = 0  # Team A restarts
                else:  # Team B's endline (Y = PITCH_HEIGHT)
                    if self.last_touch_team == 1:
                        restart_type = "corner"
                        restart_team = 0  # Team A attacks
                    else:
                        restart_type = "goal_kick"
                        restart_team = 1  # Team B restarts
            else:
                # Sideline out of bounds
                restart_type = "throw_in"
                restart_team = 1 - (self.last_touch_team if self.last_touch_team is not None else 0)

            # Pass the real out-of-play point to the restart method
            self._begin_restart(restart_type, restart_team, out_x, float(self.ball[1]))
            return

        self.ball[0] = np.clip(self.ball[0], 0.0, PITCH_WIDTH)
        self.ball[1] = np.clip(self.ball[1], 0.0, PITCH_HEIGHT)

        # Goal detection already happened above, before the out-of-bounds
        # branch -- see _resolve_goal_frame.

        if self.replay and self.match_clock_frames % self.replay.sample_interval_ticks == 0:
            self.replay.snapshot(self.match_clock_frames, self.positions, self.velocity, self.ball, self.ball_controller)

    def _capture_success_probability(self, rep_idx: int, ball_speed: float, ball_height: float) -> float:
        player_attr = self.all_players[rep_idx].attributes

        base = 0.90
        speed_penalty = min(0.75, ball_speed / 12.0)
        height_penalty = min(0.70, max(0.0, ball_height) / 3.0)
        pass_bonus = 0.0
        if self.ball_event in {"pass", "cross", "clearance", "throw_in"} and 2.5 <= ball_speed <= 12.0 and ball_height < 0.8:
            pass_bonus += 0.22
        if self.ball_event == "shot" and ball_speed > 15.0:
            pass_bonus -= 0.15
        if self.ball_event == "tackle" and ball_speed < 3.0:
            pass_bonus += 0.08
        agility_bonus = stat_ability(player_attr.agility) * 0.35
        control_bonus = stat_ability(player_attr.ballcontrol) * 0.25
        defending_bonus = stat_ability(player_attr.defending) * 0.20

        probability = base - speed_penalty - height_penalty + agility_bonus + control_bonus + defending_bonus + pass_bonus
        return float(np.clip(probability, 0.05, 0.95))

    def _body_check(self, prev_xy) -> None:
        """A ball cannot travel through a player.

        step() only resolves a loose ball every decision_interval frames, and a
        capture can be declined outright, so a ball could cross somebody clean
        and carry on -- which is the thing that looks most obviously wrong.
        Anyone the ball's path ACTUALLY crosses this frame gets a touch: they
        take it if they can, and it comes off them if they cannot.
        """
        if float(self.ball[4]) > HEAD_MIN_HEIGHT:
            return  # over him, not through him
        cur = np.array(self.ball[0:2], dtype=float)
        seg = cur - np.asarray(prev_xy, dtype=float)
        length = _norm2(seg)
        if length < 1e-6:
            return
        unit = seg / length
        rel = self.positions - np.asarray(prev_xy, dtype=float)
        along = np.clip(rel @ unit, 0.0, length)
        perp = np.linalg.norm(rel - np.outer(along, unit), axis=1)
        hits = np.flatnonzero(perp < BALL_TOUCH_RADIUS)
        if hits.size == 0:
            return

        for i in hits[np.argsort(along[hits])]:
            i = int(i)
            if self.player_stun_cooldown[i] > 0:
                continue
            if self.ball_release_player == i and self.ball_release_cooldown > 0:
                continue  # he just kicked it; it is leaving his own boot
            if float(np.dot(self.positions[i] - np.asarray(prev_xy, dtype=float), seg)) <= 0.0:
                continue  # he is behind the ball: it is leaving him, not hitting him
            if self._attempt_capture(i):
                return
            # He could not take it cleanly -- but it hit him, so it stops dead
            # at his feet instead of either ricocheting away or carrying on
            # through him. A heavy touch, which is what a miscontrol looks
            # like, and it leaves the ball there to be won.
            self.ball[2:4] = self.ball[2:4] * BODY_TOUCH_KEEP + self.rng.normal(0.0, 0.8, size=2)
            self.ball_capture_player = i
            self.ball_capture_cooldown = CAPTURE_RETRY_FRAMES
            return

    def _attempt_capture(self, index: int) -> bool:
        if self.ball_controller == index:
            return True

        # A beaten keeper is on the floor and can't quietly rescue the shot
        # they just missed via a block roll. Time-based, so a ball that clips
        # the post and trickles back still finds them down -- and one that
        # takes long enough to come back finds them up again.
        if self.player_stun_cooldown[index] > 0:
            return False

        if self.ball_capture_player == index and self.ball_capture_cooldown > 0:
            return False

        # The passer is frozen out of their own pass for the full cooldown;
        # their TEAMMATES only for TEAMMATE_RELEASE_BLOCK_FRAMES. Freezing the
        # whole side for the full cooldown left the ball untouchable for 3-6m,
        # so it phased through the man it was aimed at.
        if self.ball_release_player == index and self.ball_release_cooldown > 0:
            return False
        if self.ball_release_player >= 0 and self.ball_release_team_cooldown > 0:
            if (self.ball_release_player < 11) == (index < 11):
                return False

        dist_to_ball = _norm2(self.ball[0:2] - self.positions[index])
        if dist_to_ball > self.possession_radius + 0.5:
            return False

        ball_speed = float(_norm2(self.ball[2:4]))
        ball_height = max(0.0, float(self.ball[4]))
        current_team = 0 if index < 11 else 1
        pass_like_event = self.ball_event in {"pass", "cross", "clearance", "throw_in"}
        is_keeper = index in self._keeper_indices

        # Aerial ball: over their head, or headed -- before the moving-away
        # check, since a ball dropping onto you is yours whichever way it
        # travels. A keeper within hand reach takes the save/punch/catch
        # branches below instead.
        if ball_height >= HEAD_MIN_HEIGHT:
            if ball_height > self._reach[index]:
                return False
            if not is_keeper:
                return self._attempt_header(index)

        player_to_ball = self.ball[0:2] - self.positions[index]
        ball_motion = np.array(self.ball[2:4], dtype=float)
        if _norm2(ball_motion) > 0.0 and np.dot(player_to_ball, ball_motion) < -0.3:
            self.ball_capture_player = index
            self.ball_capture_cooldown = CAPTURE_RETRY_FRAMES
            return False

        if is_keeper and self.ball_event == "shot":
            unattempted = self.active_shot_id >= 0 and self.save_attempted_shot[index] != self.active_shot_id
            crossing = self.predict_goal_crossing(current_team) if unattempted else None
            if crossing is not None and crossing["on_target"]:
                return self._attempt_save(index)

        if pass_like_event and self.last_touch_team == current_team:
            # What makes a pass hard to take is its speed RELATIVE to the
            # receiver, and whether it is running with them or at them: one
            # taken in stride is easy however hard it was hit.
            my_vel = self.velocity[index]
            my_speed = float(_norm2(my_vel))
            rel_speed = float(_norm2(ball_motion - my_vel))
            align = 0.0
            if my_speed > 0.5 and ball_speed > 1e-6:
                align = float(np.dot(ball_motion / ball_speed, my_vel / my_speed))
            comfort = RECEIVE_COMFORT_SPEED * (1.0 + RECEIVE_ALIGN_BONUS * max(0.0, align))
            control_chance = (
                RECEIVE_BASE
                + stat_ability(self.all_players[index].attributes.composure) * 0.10
                + stat_ability(self.all_players[index].attributes.ballcontrol) * 0.20
                + max(0.0, 1.0 - rel_speed / comfort) * RECEIVE_STRIDE_WEIGHT
            )
            controlled = self.rng.random() < float(np.clip(control_chance, 0.35, 0.99))
            if not controlled and rel_speed > RECEIVE_STUN_SPEED and align < 0.2:
                # A hard ball taken facing the wrong way knocks them off
                # balance -- it does not sail through them untouched.
                self.player_stun_cooldown[index] = RECEIVE_STUN_FRAMES
                # It comes off them, it does not pass through: most of the pace
                # is killed, so a miscontrol is a heavy touch at their feet
                # rather than a ball that carries on into touch.
                self.ball[2:4] = (ball_motion * RECEIVE_DEFLECT_KEEP
                                  + self.rng.normal(0.0, 1.2, size=2))
                self.ball_capture_player = index
                self.ball_capture_cooldown = CAPTURE_RETRY_FRAMES
            if controlled:
                passer = self.last_pass_player
                if passer >= 0 and passer != index and (passer < 11) == (index < 11):
                    self.match_stats[passer]["passes_completed"] += 1
                self.last_pass_player = -1
                self.pass_receiver = -1

                self.ball_controller = index
                self.ball_capture_player = index
                self.ball_event = "neutral"
                self._register_touch(index)
                self.ball_capture_cooldown = CAPTURE_RETRY_FRAMES
                self.ball[0:2] = self.positions[index]
                self.ball[2:4] = self.velocity[index]
                self.ball[4] = 0.0
                self.ball_vz = 0.0
                self.visual_action[index] = "recieved_pass"
                self.visual_action_timer[index] = 15
                if self.replay:
                    self.replay.event(self.match_clock_frames, ActionType.RECEIVED_PASS, player_idx=index, team=0 if index < 11 else 1)
                return True
            return False
        

        block_threshold = 3.0
        can_block = not (is_keeper and self.ball_event == "shot")
        # A fast ball is only blocked by a body in its path, not one standing
        # two units to the side of it.
        if ball_speed >= BLOCK_FAST_SPEED and dist_to_ball > BLOCK_FAST_RADIUS:
            can_block = False
        if can_block and ((ball_speed >= block_threshold) or (ball_height >= 0.75)):
            deflection_bias = self._capture_success_probability(index, ball_speed, ball_height)
            pass_bias = 0.12 if self.ball_event in {"pass", "cross", "clearance", "throw_in"} else 0.04
            block_chance = np.clip(0.22 + (ball_speed * 0.10) + (ball_height * 0.28) + (self.all_players[index].attributes.agility / 100.0) * 0.30 - deflection_bias * 0.20 + pass_bias, 0.15, 0.98)
            if self.rng.random() < block_chance:
                return self._deflect_off(index, ball_speed, ball_height)

        success_chance = self._capture_success_probability(index, ball_speed, ball_height)
        success_chance = float(np.clip(success_chance + 0.15, 0.2, 0.98))

        if self.rng.random() < success_chance:
            # A teammate winning a pass through THIS path (a deflection, a
            # scrappy second ball) still completed it. Only the clean-control
            # branch above credited it, so passes_completed read ~15 points
            # below the side's real retention.
            passer = self.last_pass_player
            if (
                pass_like_event
                and passer >= 0
                and passer != index
                and (passer < 11) == (index < 11)
            ):
                self.match_stats[passer]["passes_completed"] += 1
                self.last_pass_player = -1

            self.ball_controller = index
            self.ball_capture_player = index
            self.ball_event = "neutral"
            self._register_touch(index)
            self.ball_capture_cooldown = int(8 + max(0.0, ball_height * 4.0))
            self.ball[0:2] = self.positions[index]
            self.ball[2:4] = self.velocity[index]
            self.ball[4] = 0.0
            self.ball_vz = 0.0
            if ball_height > 0.5:
                self.velocity[index] *= 0.65
            return True

        self.ball_capture_player = index
        self.ball_capture_cooldown = int(12 + max(0.0, ball_height * 8.0))
        if ball_height > 0.5:
            self.velocity[index] *= 0.5
            self.velocity[index] -= self.heading[index] * 0.6
        else:
            self.velocity[index] *= 0.85
        return False

    def _deflect_off(self, index: int, ball_speed: float, ball_height: float) -> bool:
        """The ball comes off this player uncontrolled -- a block, or a
        mistimed header. True if it drops dead enough for them to keep it."""
        current_heading = self.heading[index]
        if _norm2(current_heading) < 1e-8:
            current_heading = np.array([1.0, 0.0], dtype=float)
        ball_dir = np.array(self.ball[2:4], dtype=float)
        if _norm2(ball_dir) < 1e-8:
            ball_dir = np.array([1.0, 0.0], dtype=float)
        ball_dir = ball_dir / _norm2(ball_dir)

        normal = np.array([-ball_dir[1], ball_dir[0]], dtype=float)
        if np.dot(normal, current_heading) < 0.0:
            normal *= -1.0

        side_bias = self.rng.uniform(-1.0, 1.0)
        deflection = normal * side_bias + ball_dir * self.rng.uniform(0.35, 0.8)
        deflection = deflection / _norm2(deflection)

        self.ball_controller = -1
        self._register_touch(index)
        self.ball_capture_player = index
        self.ball_capture_cooldown = 12
        self.ball_release_player = index
        self.ball_release_cooldown = 8
        self.ball[0:2] = self.positions[index]
        self.ball[2:4] = deflection * max(3.0, ball_speed * self.rng.uniform(0.5, 0.9))
        self.ball[4] = max(0.0, ball_height * 0.5)
        self.ball_vz = 0.0
        self.velocity[index] *= 0.4

        if _norm2(self.ball[2:4]) <= max(2.0, self.all_players[index].attributes.speed * 0.12):
            self.ball_controller = index
            self.ball_capture_player = index
            self.ball_event = "neutral"
            self._register_touch(index)
            self.ball_capture_cooldown = 8
            self.ball[0:2] = self.positions[index]
            self.ball[2:4] = self.velocity[index]
            self.ball[4] = 0.0
            self.ball_vz = 0.0
            return True
        return False

    def _attempt_header(self, index: int) -> bool:
        """An outfield player meeting an aerial ball with their head. One
        roll to win it (a lost one glances off); a won one is a header at
        goal, a defensive header, or a flick-on, by where it happens.
        Always returns False: the ball is never held after a header."""
        attrs = self.all_players[index].attributes
        head_attr = float(getattr(attrs, "heading", 50))
        skill = head_attr / 100.0
        ball_speed = float(_norm2(self.ball[2:4]))
        ball_height = max(0.0, float(self.ball[4]))

        win_chance = float(np.clip(0.45 + 0.45 * skill - ball_speed / 100.0, 0.15, 0.95))
        if self.rng.random() >= win_chance:
            return self._deflect_off(index, ball_speed, ball_height)

        team = 0 if index < 11 else 1
        my_pos = np.array(self.positions[index], dtype=float)
        enemy_goal = self._goal_targets[index]
        own_goal = self._own_goals[index]
        forward = 1.0 if team == 0 else -1.0
        opponents = self.positions[11:22] if team == 0 else self.positions[0:11]

        if _norm2(enemy_goal - my_pos) <= HEADER_SHOT_RANGE and abs(my_pos[0] - PITCH_WIDTH / 2.0) < 21.0:
            # Header at goal: _calculate_shot's aim, spread from heading.
            pressure = int(np.sum(np.linalg.norm(opponents - my_pos, axis=1) < 3.0))
            composure = float(getattr(attrs, "composure", 50))
            # Floor low enough that heading still tells up to 100; at 0.9 every
            # header above 91 was identical.
            sigma = max(HEADER_SIGMA_FLOOR, max(0.0, 100.0 - head_attr) / 10.0 + pressure * max(0.0, 100.0 - composure) / 20.0)
            aim_x = (32.2 if self.rng.random() < 0.5 else 37.8) + self.rng.normal(0.0, sigma)
            aim_z = max(0.0, self.rng.uniform(0.2, 1.8) + self.rng.normal(0.0, sigma * 0.3))
            vec = np.array([aim_x, enemy_goal[1]]) - my_pos
            dist = _norm2(vec)
            unit = vec / max(dist, 1e-8)
            speed = HEADER_SHOT_SPEED[0] + (HEADER_SHOT_SPEED[1] - HEADER_SHOT_SPEED[0]) * skill
            self.match_stats[index]["shots"] += 1
            self.last_shot_player = index
            self._release_ball(index, unit, speed, aerial=True, event_type="shot")
            self.ball[4] = ball_height
            self.ball_vz = self._launch_vz(ball_height, aim_z, self._flight_time(dist, speed))
            crossing = self.predict_goal_crossing(1 - team)
            self.last_shot_on_target = bool(crossing and crossing["on_target"])
        elif _norm2(own_goal - my_pos) <= HEADER_CLEAR_RANGE:
            # Defensive header: away from goal, toward the nearer touchline.
            away = my_pos - own_goal
            unit = away / _norm2(away) if _norm2(away) > 1e-8 else np.array([0.0, forward])
            side = -1.0 if my_pos[0] < PITCH_WIDTH / 2.0 else 1.0
            unit = unit + np.array([side * 0.6, 0.0])
            unit = unit / _norm2(unit)
            angle = self.rng.normal(0.0, 0.1 + 0.35 * (1.0 - skill))
            c, s = math.cos(angle), math.sin(angle)
            unit = np.array([unit[0] * c - unit[1] * s, unit[0] * s + unit[1] * c])
            speed = HEADER_CLEAR_SPEED[0] + (HEADER_CLEAR_SPEED[1] - HEADER_CLEAR_SPEED[0]) * skill
            self._release_ball(index, unit, speed, aerial=True, event_type="clearance")
            self.ball[4] = ball_height
            self.ball_vz = self._launch_vz(ball_height, 0.0, 1.0 + 0.4 * skill)
        else:
            # Flick-on to the nearest teammate ahead, else straight on.
            teammates = self.positions[0:11] if team == 0 else self.positions[11:22]
            rel = teammates - my_pos
            ahead = rel[:, 1] * forward > 1.0
            if ahead.any():
                cand = rel[ahead]
                unit = cand[np.argmin(np.einsum("ij,ij->i", cand, cand))]
                unit = unit / _norm2(unit)
            else:
                unit = np.array([0.0, forward])
            self.match_stats[index]["passes"] += 1
            self._release_ball(index, unit, HEADER_FLICK_SPEED, aerial=True, event_type="pass")
            self.ball[4] = ball_height
            self.ball_vz = self._launch_vz(ball_height, 0.0, 0.5)

        self.velocity[index] *= 0.5
        self.visual_action[index] = "header"
        self.visual_action_timer[index] = 15
        if self.replay:
            self.replay.event(self.match_clock_frames, ActionType.HEADER, player_idx=index, team=team)
        return False

    def display_clock_frames(self) -> int:
        """The clock a VIEWER should see, which is not the same thing as
        match_clock_frames.

        match_clock_frames is one continuous timeline and has to stay that
        way -- every replay sample and event is ordered by it, so it can
        never go backwards. That means the second half simply carries on
        from wherever the first one stopped: play 2:12 of stoppage before
        the break and the second half kicks off at 47:12.

        Football doesn't work like that. The second half starts at 45:00
        however long the first half over-ran, and full time lands on 90:00
        plus only the second half's own stoppage. Shifting the shown clock
        back by exactly the first half's overrun is what makes the two
        agree, and it leaves the stored timeline untouched.

        The Godot client does the same arithmetic off the replay's HALFTIME
        event -- see ReplayReader.display_tick. Keep the two in step.
        """
        if self.halftime_clock_frames < 0 or self.match_clock_frames <= self.halftime_clock_frames:
            return self.match_clock_frames
        return self.match_clock_frames - (self.halftime_clock_frames - self.regulation_half_frames)

    def _goal_for_player(self, player_index: int) -> np.ndarray:
        return np.array([PITCH_WIDTH/2, 100.0]) if player_index < 11 else np.array([PITCH_WIDTH/2, 0.0])

    def goal_frame_bounds(self) -> tuple[float, float]:
        """Inside edges of the posts -- the x range a ball must cross to score."""
        post_min = PITCH_WIDTH / 2 - GOAL_WIDTH / 2.0
        post_max = PITCH_WIDTH / 2 + GOAL_WIDTH / 2.0
        return post_min + GOAL_POST_RADIUS, post_max - GOAL_POST_RADIUS

    def predict_goal_crossing(self, defending_team: int) -> dict | None:
        """Where the loose ball will cross `defending_team`'s goal line.

        Returns {"x", "z", "time", "on_target"} or None when the ball isn't
        travelling toward that goal at all.

        The single source of truth for "is this shot going in" -- the keeper's
        decision, the save roll and the shots-on-target stat all read it, so
        they can never disagree. Straight-line projection in the plane, with
        the same vertical arc tick() integrates (ball_vz under BALL_GRAVITY);
        the ball has no curve, so this is exact rather than an approximation.
        """
        goal_y = 0.0 if defending_team == 0 else PITCH_HEIGHT
        ball_y = float(self.ball[1])
        vel_y = float(self.ball[3])

        # Moving away from (or parallel to) that goal line.
        if abs(vel_y) < 1e-6:
            return None
        time_to_line = (goal_y - ball_y) / vel_y
        if time_to_line <= 0.0:
            return None

        cross_x = float(self.ball[0]) + float(self.ball[2]) * time_to_line
        cross_z = max(0.0, float(self.ball[4]) + self.ball_vz * time_to_line - 0.5 * BALL_GRAVITY * time_to_line ** 2)

        inner_min, inner_max = self.goal_frame_bounds()
        on_target = inner_min <= cross_x <= inner_max and cross_z < GOAL_HEIGHT
        return {"x": cross_x, "z": cross_z, "time": time_to_line, "on_target": on_target}

    def _fuzz_pass_direction(self, index: int, unit_vec: np.ndarray, pass_type: str) -> np.ndarray:
        """`unit_vec` rotated by this passer's execution error -- see
        PASS_AIM_ERROR_DEGREES. Seeded rng, so still deterministic."""
        accuracy = float(getattr(self.all_players[index].attributes, "accuracy", 50))
        sigma_deg = PASS_AIM_ERROR_DEGREES * (1.0 - stat_ability(accuracy))
        sigma_deg *= PASS_AIM_ERROR_BY_TYPE.get(pass_type, 1.0)
        if sigma_deg <= 0.0:
            return unit_vec
        angle = math.radians(self.rng.normal(0.0, sigma_deg))
        c, s = math.cos(angle), math.sin(angle)
        return np.array([unit_vec[0] * c - unit_vec[1] * s, unit_vec[0] * s + unit_vec[1] * c])

    def _flight_time(self, distance: float, speed: float, friction: float = BALL_GROUND_FRICTION) -> float:
        """Seconds for a loose ball launched at `speed` to cover `distance`,
        keeping `friction` of its speed per second (tick()'s rule). A ball
        that would stop short gets the frictionless estimate -- a shot that
        never reaches the line is a miss either way, and this just needs a
        finite number to aim by.
        """
        if speed <= 1e-6:
            return 0.0
        k = -math.log(friction)
        remaining = 1.0 - distance * k / speed
        if remaining <= 0.0:
            return distance / speed
        return -math.log(remaining) / k

    @staticmethod
    def _launch_vz(start_z: float, target_z: float, flight: float) -> float:
        """Vertical speed that takes a ball from start_z to target_z in
        `flight` seconds under BALL_GRAVITY."""
        flight = max(flight, 1e-3)
        return (target_z - start_z + 0.5 * BALL_GRAVITY * flight * flight) / flight

    def _resolve_goal_frame(self, prev_xy: np.ndarray, prev_height: float) -> str | None:
        """Resolves a ball that crossed a goal plane this tick.

        Returns "goal", "rebound", or None (didn't reach the frame -- the
        caller's normal out-of-bounds handling takes it from here).

        Height matters too: the crossing z is interpolated the same way, so a
        ball travelling over the bar is no longer a goal.
        """
        cur_x, cur_y = float(self.ball[0]), float(self.ball[1])
        prev_x, prev_y = float(prev_xy[0]), float(prev_xy[1])

        # Which plane, if either, did we pass through this tick?
        if prev_y > 0.0 >= cur_y:
            plane_y, scoring_team, inward = 0.0, 1, 1.0
        elif prev_y < PITCH_HEIGHT <= cur_y:
            plane_y, scoring_team, inward = PITCH_HEIGHT, 0, -1.0
        else:
            return None

        span = cur_y - prev_y
        t = 0.0 if abs(span) < 1e-9 else (plane_y - prev_y) / span
        t = min(1.0, max(0.0, t))
        cross_x = prev_x + t * (cur_x - prev_x)
        cross_z = max(0.0, prev_height + t * (float(self.ball[4]) - prev_height))

        post_centres = (PITCH_WIDTH / 2 - GOAL_WIDTH / 2.0, PITCH_WIDTH / 2 + GOAL_WIDTH / 2.0)
        inner_min = post_centres[0] + GOAL_POST_RADIUS
        inner_max = post_centres[1] - GOAL_POST_RADIUS

        if inner_min <= cross_x <= inner_max and cross_z < GOAL_HEIGHT:
            self._award_goal(scoring_team)
            return "goal"

        # Crossbar: inside the posts but at bar height. Comes down off the
        # frame rather than sailing on through.
        if inner_min <= cross_x <= inner_max and cross_z < GOAL_HEIGHT + GOAL_POST_RADIUS * 2.0:
            self._rebound_off_frame(np.array([cross_x, plane_y]), np.array([0.0, inward]), plane_y)
            self.ball_vz = -abs(self.ball_vz) * POST_REBOUND_DAMPING
            return "rebound"

        # Either post. A post is a vertical cylinder, so the normal runs from
        # its axis out to where the path meets its circle: the inside face
        # deflects goalward, the outside face away. Both are re-tested next
        # tick, which is how "in off the post" works without a special case.
        if cross_z < GOAL_HEIGHT:
            path = (np.asarray(prev_xy, dtype=float), np.array([cur_x, cur_y]))
            hit_t, hit_post = None, None
            for post_x in post_centres:
                t_hit = self._path_meets_post(path[0], path[1], np.array([post_x, plane_y]))
                if t_hit is not None and (hit_t is None or t_hit < hit_t):
                    hit_t, hit_post = t_hit, post_x
            if hit_post is not None:
                contact = path[0] + hit_t * (path[1] - path[0])
                normal = contact - np.array([hit_post, plane_y])
                if _norm2(normal) < 1e-8:
                    normal = np.array([0.0, inward], dtype=float)
                self._rebound_off_frame(contact, normal, plane_y)
                return "rebound"

        return None

    @staticmethod
    def _path_meets_post(start: np.ndarray, end: np.ndarray, centre: np.ndarray) -> float | None:
        """How far along start->end the ball first touches the post, as a
        fraction in [0, 1], or None if it misses. From above the post is a
        circle of GOAL_POST_RADIUS, so this is a segment against a circle."""
        d = end - start
        f = start - centre
        a = float(np.dot(d, d))
        if a < 1e-12:
            return None
        b = 2.0 * float(np.dot(f, d))
        c = float(np.dot(f, f)) - GOAL_POST_RADIUS * GOAL_POST_RADIUS
        disc = b * b - 4.0 * a * c
        if disc < 0.0:
            return None
        root = math.sqrt(disc)
        for t in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a)):
            if 0.0 <= t <= 1.0:
                return t
        return None

    def _rebound_off_frame(self, contact: np.ndarray, normal: np.ndarray, plane_y: float) -> None:
        """Bounces the ball off the woodwork at `plane_y`'s goal and leaves it
        in play. Which goal is passed in, never read off the contact point: a
        post is met short of the line, so a contact at the y=0 goal has a
        small POSITIVE y."""
        normal = np.asarray(normal, dtype=float)
        norm = _norm2(normal)
        normal = normal / norm if norm > 1e-8 else np.array([0.0, 1.0])

        velocity = np.array(self.ball[2:4], dtype=float)
        reflected = velocity - 2.0 * float(np.dot(velocity, normal)) * normal
        self.ball[2:4] = reflected * POST_REBOUND_DAMPING

        # Nudge the ball back inside along the pitch's long axis so the next
        # tick doesn't immediately re-detect the same crossing.
        inset = 0.35
        self.ball[0] = float(np.clip(contact[0], 0.0, PITCH_WIDTH))
        self.ball[1] = inset if plane_y <= 0.0 else PITCH_HEIGHT - inset

        self.post_hits += 1
        # The ball is loose and nobody has touched it since the shot -- leave
        # last_touch_* alone so a rebound that goes out still awards the right
        # corner/goal kick, exactly as a deflection would.
        self.ball_controller = -1

    def _award_goal(self, scoring_team: int) -> None:
        self.scores[scoring_team] += 1
        self.last_goal_team = scoring_team
        self.ball_controller = -1

        scorer_idx = -1
        if self.last_touch_player != -1:
            touch_team = 0 if self.last_touch_player < 11 else 1
            if touch_team == scoring_team:
                scorer_idx = self.last_touch_player
            elif (
                self.ball_event == "shot"
                and self.last_shot_player >= 0
                and (0 if self.last_shot_player < 11 else 1) == scoring_team
                and self.last_shot_on_target
            ):
                scorer_idx = self.last_shot_player
        own_goal = scorer_idx == -1

        # A goal is by definition on target, for whoever shot it; the
        # recording follows the same rule.
        if self.last_shot_player >= 0:
            self.match_stats[self.last_shot_player]["shots_on_target"] += 1
            if self.replay and not self.last_shot_on_target:
                self.replay.retype_last_shot_as_on_target(self.last_shot_player)
            self.last_shot_player = -1
        # Charged to the beaten keeper -- index 0 / 11 by formation contract.
        conceding_keeper = 11 if scoring_team == 0 else 0
        self.match_stats[conceding_keeper]["goals_conceded"] += 1

        # --- Evaluate Goal & Assist Statistics ---
        scorer_name = "Own Goal"
        if not own_goal:
            scorer = self.all_players[scorer_idx]
            scorer.scored()
            self._match_goals[scorer_idx] += 1
            scorer_name = scorer.lname

            # Only for a goal the scorer touched in themselves: a deflection
            # cleared the candidate when the defender's touch registered.
            if scorer_idx == self.last_touch_player and self.assist_candidate != -1:
                assister = self.all_players[self.assist_candidate]
                assister.assisted()
                self._match_assists[self.assist_candidate] += 1

        team_label = "A" if scoring_team == 0 else "B"
        self._trigger_goal_popup(f"{team_label}: {scorer_name}")

        self.goal_pause_timer = 90
        self.kickoff_team = 1 - scoring_team
        if self.replay:
            # player_idx is the credited scorer -- or, for an own goal, the
            # player who put it in, whose side then differs from `team`;
            # that mismatch is how the client tells the two apart
            # (MatchPlayback._process_events, MatchSession.scorers).
            self.replay.event(
                self.match_clock_frames,
                ActionType.GOAL,
                player_idx=self.last_touch_player if own_goal else scorer_idx,
                team=scoring_team,
            )
        self.last_touch_player = -1
        self.assist_candidate = -1

    def _turn_heading_toward(self, index: int, target_dir: np.ndarray) -> np.ndarray:
        # Runs ~100K times a match on 2-vectors: plain floats and math.*
        # here, not numpy -- np.linalg.norm/np.dot on a length-2 array cost
        # more in call overhead than the arithmetic. Same maths as before.
        tx, ty = float(target_dir[0]), float(target_dir[1])
        target_norm = math.hypot(tx, ty)
        if target_norm < 1e-8:
            return self.heading[index]
        tx, ty = tx / target_norm, ty / target_norm

        cx, cy = float(self.heading[index][0]), float(self.heading[index][1])
        current_norm = math.hypot(cx, cy)
        if current_norm < 1e-8:
            cx, cy = (0.0, 1.0) if index < 11 else (0.0, -1.0)
        else:
            cx, cy = cx / current_norm, cy / current_norm

        dot = min(1.0, max(-1.0, cx * tx + cy * ty))
        angle = math.acos(dot)

        agility = getattr(self.all_players[index].attributes, "agility", 50)
        max_turn = 0.18 + (agility / 100.0) * 0.9

        if angle <= max_turn:  # covers the old angle <= 1e-6 case too
            return np.array([tx, ty], dtype=float)

        cross = cx * ty - cy * tx
        theta = max_turn if cross >= 0.0 else -max_turn
        c, sn = math.cos(theta), math.sin(theta)
        rx, ry = c * cx - sn * cy, sn * cx + c * cy
        r = math.hypot(rx, ry)
        return np.array([rx / r, ry / r], dtype=float)

    def _release_ball(self, owner_index: int, direction: np.ndarray, launch_speed: float, aerial: bool = False, event_type: str = "neutral"):
        direction = np.asarray(direction, dtype=float)
        direction_norm = _norm2(direction)
        if direction_norm < 1e-8:
            direction = np.array([1.0, 0.0], dtype=float)
            direction_norm = 1.0
        direction = direction / direction_norm

        self.ball_event = event_type
        self.ball_controller = -1
        self.ball_release_player = owner_index
        self.intent[owner_index] = None
        self.last_pass_player = owner_index if event_type in ("pass", "cross", "throw_in") else -1

        # A new shot is a new save opportunity. Anything else ends the current
        # one, so a parried or cleared ball can't be "saved" a second time.
        if event_type == "shot":
            self._shot_counter += 1
            self.active_shot_id = self._shot_counter
        else:
            self.active_shot_id = -1

        self._register_touch(owner_index)
        
        if aerial:
            # Short enough that the kicker's side can still contest a cross on
            # its way down; a ball over their heads is kept off them by reach.
            self.ball_release_cooldown = 10 + int(min(15.0, launch_speed * 0.35))
            self.ball_release_team_cooldown = TEAMMATE_RELEASE_BLOCK_FRAMES
            # A hop off the ground; lofted kicks overwrite ball_vz after this.
            self.ball[4] = 0.0
            self.ball_vz = self._launch_vz(0.0, 0.0, 0.6)
        else:
            self.ball_release_cooldown = 8 + int(min(8.0, launch_speed * 0.08))
            self.ball_release_team_cooldown = TEAMMATE_RELEASE_BLOCK_FRAMES
            self.ball[4] = 0.0
            self.ball_vz = 0.0

        self.ball[0:2] = self.positions[owner_index]
        self.ball[2:4] = direction * launch_speed

    def _resolve_action(self, index: int, action: dict):
        if not action:
            return

        if self.player_stun_cooldown[index] > 0:
            return

        if self.ball_capture_player == index and self.ball_capture_cooldown > 0:
            return

        if self.ball_release_player == index and self.ball_release_cooldown > 0:
            return

        action_type = action["type"]

        if action_type == "move":
            target = np.array(action["target"], dtype=float)
            vec = target - self.positions[index]
            dist = math.hypot(float(vec[0]), float(vec[1]))

            if dist > 0.1:
                unit_vec = vec / dist
                self.heading[index] = self._turn_heading_toward(index, unit_vec)
                # A tired player is a slower player -- this is the only place
                # fatigue actually bites, so stamina changes how a match ends
                # rather than just being a number on a card.
                self.velocity[index] = self.heading[index] * (
                    base_speed * action["speed_mod"] * self._fatigue_factor(index)
                )
            else:
                self.velocity[index] = np.zeros(2, dtype=float)

        elif action_type == "pass":
            if self.ball_controller == index:
                target = np.array(action["target"], dtype=float)
                vec = target - self.positions[index]
                dist = _norm2(vec)
                if dist < 1e-8:
                    return

                # Who this ball is FOR. Nothing tracked this before, so the man
                # it was aimed at carried on with his own run and it rolled past
                # him -- the "passes go straight through players" problem.
                # Give and go: the man who played it pushes on instead of
                # standing admiring it.
                self.pass_and_move = index
                self.pass_and_move_timer = PASS_AND_MOVE_FRAMES
                mates = range(0, 11) if index < 11 else range(11, 22)
                self.pass_receiver = min(
                    (m for m in mates if m != index),
                    key=lambda m: _norm2(self.positions[m] - target),
                    default=-1,
                )

                if self.must_pass_next and self.must_pass_player == index:
                    self._clear_must_pass()
                elif self.kickoff_pass_required and self.kickoff_pass_player == index:
                    self._clear_must_pass()

                unit_vec = vec / dist
                pass_type = action.get("pass_type", "normal")

                # A throw-in is thrown, not kicked. The taker's own class has
                # no idea it's taking one (nothing ever emitted
                # pass_type="throw_in", which is why that branch below was
                # dead code), so the engine forces it here -- the same way a
                # restart taken from a pitch corner is forced into a cross
                # just below.
                if self.pending_restart_pass_type == "throw_in" and self.pending_restart_pass_player == index:
                    pass_type = "throw_in"
                    self.pending_restart_pass_type = None
                    self.pending_restart_pass_player = -1
                elif self.pending_restart_pass_type == "cross" and self.pending_restart_pass_player == index:
                    # A delivery, not a square ball: a crossable free kick, or a
                    # deep one hit long by a side chasing the game.
                    pass_type = "cross"
                    target = self._choose_restart_delivery(index)
                    vec = target - self.positions[index]
                    dist = _norm2(vec)
                    unit_vec = vec / dist if dist > 1e-8 else unit_vec
                    self.pending_restart_pass_type = None
                    self.pending_restart_pass_player = -1
                elif self.kickoff_pass_player == index:
                    px, py = self.positions[index]
                    if (px <= 5.0 or px >= PITCH_WIDTH - 5.0) and (py <= 5.0 or py >= PITCH_HEIGHT - 5.0):
                        pass_type = "cross"

                power = base_kick_pow * action["power"]
                aerial = False
                event_type = "pass"
                launch_vz = None
                if pass_type == "clearance":
                    aerial = True
                    power *= 1.2
                    launch_vz = self._launch_vz(0.0, 0.0, 1.6)
                elif pass_type == "cross":
                    # Flighted to drop to head height at the target: solve the
                    # launch speed from tick()'s friction for the wanted flight
                    # time, capped by the crosser's power (under-hit falls short).
                    aerial = True
                    event_type = "cross"
                    flight = min(CROSS_FLIGHT_MAX, max(CROSS_FLIGHT_MIN, dist / CROSS_FLIGHT_REF_SPEED))
                    needed = dist * -math.log(BALL_AIR_FRICTION) / (1.0 - BALL_AIR_FRICTION ** flight)
                    max_power = base_kick_pow * float(self.all_players[index].attributes.power) / 40.0
                    power = min(needed, max_power, CROSS_MAX_SPEED)
                    if power < needed:  # under-hit: drops short rather than looping higher
                        flight = min(CROSS_FLIGHT_MAX, self._flight_time(dist, power, BALL_AIR_FRICTION))
                    launch_vz = self._launch_vz(0.0, CROSS_ARRIVAL_HEIGHT, flight)
                elif pass_type == "throw_in":
                    aerial = False
                    power *= THROW_IN_POWER_FACTOR
                    event_type = "throw_in"

                self.match_stats[index]["passes"] += 1

                self.visual_action[index] = pass_type
                self.visual_action_timer[index] = 15
                if self.replay:
                    pass_event = {
                        "normal": ActionType.PASS,
                        "clearance": ActionType.CLEARANCE,
                        "cross": ActionType.CROSS,
                        # Not THROW_IN: that is the award, and the client
                        # banners it. This is the throw itself.
                        "throw_in": ActionType.THROW_TAKEN,
                    }.get(pass_type, ActionType.PASS)
                    self.replay.event(self.match_clock_frames, pass_event, player_idx=index, team=0 if index < 11 else 1)
                unit_vec = self._fuzz_pass_direction(index, unit_vec, pass_type)
                self._release_ball(index, unit_vec, power, aerial=aerial, event_type=event_type)
                if launch_vz is not None:
                    self.ball_vz = launch_vz

        elif action_type == "shoot":
            if self.ball_controller == index:
                target_3d = np.array(action["target_3d"], dtype=float)
                vec_xy = target_3d[:2] - self.ball[0:2]
                dist_xy = float(np.hypot(vec_xy[0], vec_xy[1]))
                if dist_xy < 1e-8:
                    return

                unit_xy = vec_xy / dist_xy
                shot_speed = base_kick_pow * action["power"]
                target_z = max(0.0, float(target_3d[2]))
                launch_vz = self._launch_vz(0.0, target_z, self._flight_time(dist_xy, shot_speed))
                aerial = launch_vz > 2.0

                self.match_stats[index]["shots"] += 1
                self.last_shot_player = index

                self.visual_action[index] = "shoot"
                self.visual_action_timer[index] = 15
                self._release_ball(index, unit_xy, shot_speed, aerial=aerial, event_type="shot")
                self.ball[2] = unit_xy[0] * shot_speed
                self.ball[3] = unit_xy[1] * shot_speed
                self.ball[4] = 0.0
                self.ball_vz = launch_vz
                crossing = self.predict_goal_crossing(1 if index < 11 else 0)
                self.last_shot_on_target = bool(crossing and crossing["on_target"])
                # The crossing above picks which of the two shot events this is.
                if self.replay:
                    self.replay.event(
                        self.match_clock_frames,
                        ActionType.SHOOT if self.last_shot_on_target else ActionType.SHOT_OFF_TARGET,
                        player_idx=index,
                        team=0 if index < 11 else 1,
                    )

        elif action_type == "tackle":
            if self.ball_controller == -1 or self.ball_controller == index:
                return

            holder_idx = self.ball_controller
            dist = _norm2(self.positions[index] - self.positions[holder_idx])
            
            if dist <= 2.0:
                defender_stat = action["stat"]
                attacker_stat = self.all_players[holder_idx].attributes.ballcontrol

                stat_diff = defender_stat - attacker_stat
                steal_chance = float(np.clip(0.40 + (stat_diff / 100.0), 0.10, 0.90))

                self.match_stats[index]["tackles"] += 1

                if self.rng.random() < steal_chance:
                    self.match_stats[index]["tackles_won"] += 1
                    self.visual_action[index] = "tackle"
                    self.visual_action_timer[index] = 15
                    if self.replay:
                        self.replay.event(self.match_clock_frames, ActionType.TACKLE, player_idx=index, team=0 if index < 11 else 1)
                    # Successful Tackle
                    tackle_vector = self.positions[index] - self.positions[holder_idx]
                    tackle_vector_norm = _norm2(tackle_vector)
                    if tackle_vector_norm < 1e-8:
                        tackle_vector = self.heading[index]
                        tackle_vector_norm = _norm2(tackle_vector)
                    if tackle_vector_norm < 1e-8:
                        tackle_vector = np.array([1.0, 0.0])
                        tackle_vector_norm = 1.0

                    unit_vec = tackle_vector / tackle_vector_norm
                    launch_power = base_kick_pow * (0.25 + (defender_stat / 100.0) * 0.75)

                    self._release_ball(holder_idx, unit_vec, launch_power, aerial=(launch_power > 15.0 or abs(unit_vec[1]) > 0.7), event_type="tackle")
                    self.velocity[index] = np.zeros(2, dtype=float)
                    self.velocity[holder_idx] = np.zeros(2, dtype=float)
                    self.player_stun_cooldown[index] = 20
                    self.player_stun_cooldown[holder_idx] = 20
                elif self._is_foul(index, holder_idx, stat_diff):
                    # Mistimed lunge rather than a clean beating.
                    self._award_foul(index, holder_idx)
                    return
                else:
                    # Failed Tackle: Defender gets ankle-broken
                    self.visual_action[index] = "anklebreaker"
                    self.visual_action_timer[index] = 60
                    if self.replay:
                        self.replay.event(self.match_clock_frames, ActionType.ANKLEBREAKER, player_idx=index, team=0 if index < 11 else 1)
                    self.velocity[index] = np.zeros(2, dtype=float)
                    self.player_stun_cooldown[index] = 60  # Stun the defender so the attacker can pass them

        elif action_type == "capture":
            if self.ball_release_player == index and self.ball_release_cooldown > 0:
                return
            self._attempt_capture(index)

        elif action_type == "save":
            self._attempt_save(index)

    def _choose_restart_delivery(self, index: int) -> np.ndarray:
        """Where a set-piece delivery is aimed: the box, at whoever is in it.
        Falls back to the penalty spot so a cross with nobody home still goes
        somewhere sensible rather than out of play."""
        team = 0 if index < 11 else 1
        goal_y = PITCH_HEIGHT if team == 0 else 0.0
        box_y = goal_y - 11.0 if team == 0 else 11.0
        mates = [
            i for i in self._fk_outfield(team, exclude={index})
            if abs(float(self.positions[i][1]) - box_y) < 12.0
        ]
        if not mates:
            return np.array([PITCH_WIDTH / 2.0, box_y])
        pick = min(mates, key=lambda i: abs(float(self.positions[i][0]) - PITCH_WIDTH / 2.0))
        return np.asarray(self.positions[pick], dtype=float)

    def _arm_restart_pass(self, kind: str, player: int):
        """Tag the restart's first touch.

        Keeps its OWN player reference: restart_player is wiped the moment the
        whistle goes, so the `restart_player == index` guard this used to rely
        on could never be true by the time anyone actually played the ball --
        which is why throw-ins were being released as ordinary passes.
        """
        self.pending_restart_pass_type = kind
        self.pending_restart_pass_player = int(player)

    def _clear_free_kick_ring(self, spot, attacking_team: int, exclude) -> None:
        """Push the defending side out of the ten-yard ring."""
        defending = 1 - attacking_team
        goal_y = PITCH_HEIGHT if attacking_team == 0 else 0.0
        away = np.array([0.0, 1.0 if goal_y < float(spot[1]) else -1.0])
        spot = np.asarray(spot, dtype=float)
        for i in self._fk_outfield(defending, exclude=exclude):
            delta = np.asarray(self.positions[i], dtype=float) - spot
            dist = _norm2(delta)
            if dist >= WALL_DISTANCE:
                continue
            unit = delta / dist if dist > 1e-6 else away
            self.positions[i] = spot + unit * WALL_DISTANCE

    def _deficit(self, team: int) -> int:
        """Goals this side is behind by, 0 if level or ahead. Every free kick
        setup reads this: a team chasing the game commits more bodies."""
        return max(0, int(self.scores[1 - team]) - int(self.scores[team]))

    def _free_kick_kind(self, spot, team: int) -> str:
        goal = np.array([PITCH_WIDTH / 2.0, PITCH_HEIGHT if team == 0 else 0.0])
        dist = _norm2(goal - np.asarray(spot, dtype=float))
        off_centre = abs(float(spot[0]) - PITCH_WIDTH / 2.0)
        if dist <= FK_SHOOTING_RANGE and off_centre <= FK_SHOOTING_HALF_WIDTH:
            return "shooting"
        if dist <= FK_CROSS_RANGE:
            return "crossable"
        return "defensive"

    def _fk_outfield(self, team: int, exclude=()) -> list:
        return [
            i for i in (range(0, 11) if team == 0 else range(11, 22))
            if i not in self._keeper_indices and i not in exclude
        ]

    def _setup_defensive_free_kick(self, spot, team: int) -> int:
        """Deep in their own half: a restart of play, not a chance.

        A centre-half or holder takes it, the side in front of him pushes up to
        meet it, and the defending side drops back into its shape. No wall --
        nobody is shooting from here. A team chasing the game pushes further up
        and launches it instead of playing out.
        """
        chase = min(self._deficit(team), FK_CHASE_BONUS_MAX)
        taker = self._pick_role_slot(team, ("CB", "CDM", "LB", "RB"), 2)
        forward = 1.0 if team == 0 else -1.0
        self.positions[taker] = np.asarray(spot, dtype=float) - np.array([0.0, forward * 1.5])

        others = self._fk_outfield(team, exclude={taker})
        if chase:
            # Behind, so this is a chance, not a restart: put bodies in the box
            # for the ball he is about to launch. Pushing everyone up a few
            # units left nobody to aim at.
            box_y = 85.0 if team == 0 else 15.0
            others.sort(key=lambda i: -float(self.positions[i][1]) * forward)
            for i in others[: 2 + chase]:
                self.positions[i] = np.array([
                    PITCH_WIDTH / 2.0 + self.rng.uniform(-11.0, 11.0),
                    box_y + self.rng.uniform(-4.0, 4.0),
                ])
            others = others[2 + chase:]
        # Everyone else ahead of the ball pushes on.
        push = 6.0 + chase * 4.0
        for i in others:
            y = float(self.positions[i][1]) + forward * push
            self.positions[i][1] = float(np.clip(y, 2.0, PITCH_HEIGHT - 2.0))

        # The defending side drops into its own shape rather than pressing a
        # dead ball it cannot win.
        for i in self._fk_outfield(1 - team):
            slot = np.asarray(self.formation[i]["pos"], dtype=float)
            self.positions[i] = 0.5 * self.positions[i] + 0.5 * slot

        # Behind: hit it long. Level or ahead: play out.
        self._arm_restart_pass("cross" if chase else "free_kick", taker)
        return taker

    def _setup_crossable_free_kick(self, spot, team: int) -> int:
        """Wide, or too far out to shoot: a delivery into the box.

        Set up like a corner -- bodies into the area, markers with them, a rest
        line behind. How many go in scales with the deficit.
        """
        chase = min(self._deficit(team), FK_CHASE_BONUS_MAX)
        taker = self._pick_role_slot(team, ("LM", "RM", "LW", "RW", "CM"), 7)
        forward = 1.0 if team == 0 else -1.0
        self.positions[taker] = np.asarray(spot, dtype=float) - np.array([0.0, forward * 1.5])

        box_y = 85.0 if team == 0 else 15.0
        runners = self._fk_outfield(team, exclude={taker})
        runners.sort(key=lambda i: -float(self.positions[i][1]) * forward)
        going_in = runners[: 3 + chase]
        for i in going_in:
            self.positions[i] = np.array([
                PITCH_WIDTH / 2.0 + self.rng.uniform(-11.0, 11.0),
                box_y + self.rng.uniform(-4.0, 4.0),
            ])
        # The rest hold a line behind the ball for the clearance.
        for i in runners[3 + chase:]:
            self.positions[i][1] = float(spot[1]) - forward * 8.0

        markers = self._fk_outfield(1 - team)
        markers.sort(key=lambda i: float(self.positions[i][1]) * forward, reverse=True)
        for n, i in enumerate(markers[: len(going_in) + 1]):
            self.positions[i] = np.array([
                PITCH_WIDTH / 2.0 + self.rng.uniform(-10.0, 10.0),
                box_y + forward * 3.0 + self.rng.uniform(-3.0, 3.0),
            ])

        self._arm_restart_pass("cross", taker)
        return taker

    def _setup_shooting_free_kick(self, spot, team: int) -> int:
        """Close and central: the best striker of a ball has a go, over a wall.

        Resolved by its own check at the whistle (_resolve_free_kick), not as
        an open-play shot -- the keeper is set and the wall is in the way, which
        the open-play save curve knows nothing about.
        """
        candidates = self._fk_outfield(team)
        taker = max(
            candidates,
            key=lambda i: self.all_players[i].attributes.shooting * 0.7
            + self.all_players[i].attributes.accuracy * 0.3,
        )
        forward = 1.0 if team == 0 else -1.0
        self.positions[taker] = np.asarray(spot, dtype=float) - np.array([0.0, forward * 2.0])

        self._place_wall(spot, team)
        keeper = self._keeper_indices[1] if team == 0 else self._keeper_indices[0]
        goal_y = PITCH_HEIGHT if team == 0 else 0.0
        self.positions[keeper] = np.array([PITCH_WIDTH / 2.0, goal_y - forward * 0.5])
        return taker

    def _resolve_free_kick(self, taker: int, keeper: int):
        """Beat the wall and hit the target, then beat a set keeper."""
        attrs = self.all_players[taker].attributes
        gk = self.all_players[keeper].attributes
        placement = FK_PLACEMENT_MIN + FK_PLACEMENT_SPAN * stat_ability(
            attrs.shooting * 0.7 + attrs.accuracy * 0.3
        )
        save = FK_SAVE_MIN + FK_SAVE_SPAN * stat_ability(
            (gk.agility * 0.6 + gk.vision * 0.4 + gk.ballcontrol * 0.3) / 1.3
        )
        on_target = self.rng.random() < placement
        blocked = self.rng.random() < FK_WALL_BLOCK
        saved = self.rng.random() < save
        return (on_target and not blocked and not saved), on_target, blocked

    def _place_wall(self, spot, attacking_team: int) -> set:
        """Stands three defenders across the ball-to-goal line, a legal distance
        off it, picked by who is already nearest. Returns who was used."""
        defending = 1 - attacking_team
        goal_y = PITCH_HEIGHT if attacking_team == 0 else 0.0
        to_goal = np.array([PITCH_WIDTH / 2.0, goal_y]) - spot
        dist = _norm2(to_goal)
        if dist < 1e-6:
            return set()
        unit = to_goal / dist
        wall_centre = spot + unit * min(WALL_DISTANCE, dist * 0.5)
        across = np.array([-unit[1], unit[0]])

        outfield = [
            i for i in (range(0, 11) if defending == 0 else range(11, 22))
            if i not in self._keeper_indices
        ]
        outfield.sort(key=lambda i: _norm2(self.positions[i] - wall_centre))
        used = set()
        for n, i in enumerate(outfield[:WALL_PLAYERS]):
            offset = (n - (WALL_PLAYERS - 1) / 2.0) * 1.0
            self.positions[i] = wall_centre + across * offset
            used.add(i)
        return used

    def _take_direct_free_kick(self):
        """Strike it at the whistle. Unlike open play the keeper is set and a
        wall is in the way, so this goes through _resolve_free_kick rather than
        the open-play save curve, which knows about neither."""
        taker = self.restart_player
        if taker is None:
            return
        attacking = self.restart_team
        keeper = self._keeper_indices[1] if attacking == 0 else self._keeper_indices[0]
        scored, on_target, blocked = self._resolve_free_kick(taker, keeper)

        goal_y = PITCH_HEIGHT if attacking == 0 else 0.0
        side = 1.0 if self.rng.random() < 0.5 else -1.0
        target_x = PITCH_WIDTH / 2.0 + side * (GOAL_WIDTH / 2.0 - 0.7)
        if not on_target:
            target_x += side * GOAL_WIDTH * 0.7

        self.match_stats[taker]["shots"] += 1
        self.last_shot_player = taker
        self.last_shot_on_target = on_target
        if on_target:
            self.match_stats[taker]["shots_on_target"] += 1

        vec = np.array([target_x, goal_y]) - self.positions[taker]
        unit = vec / max(_norm2(vec), 1e-6)
        self._release_ball(taker, unit, FREE_KICK_SHOT_SPEED, aerial=True, event_type="shot")
        # Aim it FLAT. _flight_time defaulted to ground friction while the ball
        # flies under air friction, so the estimate was far too long and
        # _launch_vz answered with a lob: from 25 units it peaked at 5m against
        # a 2.5m bar, and every free kick outside ~18 units sailed over.
        flight = self._flight_time(_norm2(vec), FREE_KICK_SHOT_SPEED, friction=BALL_AIR_FRICTION)
        self.ball_vz = min(
            self._launch_vz(0.0, FREE_KICK_TARGET_HEIGHT, flight), FREE_KICK_MAX_VZ
        )

        if blocked and on_target:
            # Into the wall: it comes straight back off them.
            self.ball[2:4] = -self.ball[2:4] * 0.3
        elif not scored and on_target:
            self.match_stats[keeper]["saves"] += 1
            self.ball[0:2] = self.positions[keeper]
            self.ball[2:4] = np.zeros(2)
            self.ball_controller = keeper
            if self.replay:
                self.replay.event(
                    self.match_clock_frames, ActionType.SAVE,
                    player_idx=keeper, team=0 if keeper < 11 else 1,
                )

    def _take_penalty(self):
        """Resolve the spot kick, then leave the ball live for the rebound."""
        taker = self.restart_player
        if taker is None:
            return
        attacking = self.restart_team
        keeper = self._keeper_indices[1] if attacking == 0 else self._keeper_indices[0]
        scored, aim, dive, on_target = self._resolve_penalty(taker, keeper)

        goal_y = PITCH_HEIGHT if attacking == 0 else 0.0
        target_x = PITCH_WIDTH / 2.0 + aim * (GOAL_WIDTH / 2.0 - 0.6)
        if not on_target:
            target_x += (GOAL_WIDTH * 0.8) * (1 if aim >= 0 else -1)

        self.match_stats[taker]["shots"] += 1
        self.last_shot_player = taker
        self.last_shot_on_target = on_target
        vec = np.array([target_x, goal_y]) - self.positions[taker]
        unit = vec / max(_norm2(vec), 1e-6)
        self._release_ball(taker, unit, PENALTY_SHOT_SPEED, aerial=False, event_type="shot")
        if on_target:
            self.match_stats[taker]["shots_on_target"] += 1

        self.positions[keeper] = np.array(
            [PITCH_WIDTH / 2.0 + dive * KEEPER_REACH * 0.7, goal_y], dtype=float
        )
        if not scored and on_target:
            # He read it: the ball dies at his hands rather than crossing.
            self.match_stats[keeper]["saves"] += 1
            self.ball[0:2] = self.positions[keeper]
            self.ball[2:4] = np.zeros(2)
            self.ball_controller = keeper
            if self.replay:
                self.replay.event(
                    self.match_clock_frames, ActionType.SAVE,
                    player_idx=keeper, team=0 if keeper < 11 else 1,
                )

    def _in_own_box(self, index: int, spot) -> bool:
        """Is `spot` inside the penalty area index DEFENDS? The attacking-box
        test at the state build is the mirror of this one."""
        x, y = float(spot[0]), float(spot[1])
        if not (14.0 < x < 56.0):
            return False
        return y < 18.0 if index < 11 else y > 82.0

    def _is_foul(self, defender: int, holder: int, stat_diff: float) -> bool:
        """Did a missed tackle take the man instead of the ball?

        Rolled only on a FAILED tackle, so a clean challenge is never a foul.
        Rises with aggression, with how badly the defender was outmatched (a
        beaten man lunges), and with coming from behind -- headings pointing
        the same way means he is chasing, not facing.
        """
        attrs = self.all_players[defender].attributes
        from_behind = float(np.dot(self.heading[defender], self.heading[holder]))
        chance = (
            FOUL_BASE
            + stat_ability(getattr(attrs, "aggression", 40)) * FOUL_AGGRESSION_WEIGHT
            + max(0.0, -stat_diff / 100.0) * FOUL_OUTPACED_WEIGHT
            + max(0.0, from_behind) * FOUL_FROM_BEHIND_WEIGHT
        )
        return self.rng.random() < float(np.clip(chance, 0.0, FOUL_MAX))

    def _award_foul(self, offender: int, victim: int):
        """Whistle. A foul in the offender's own box is a penalty, anything
        else a free kick from the spot the victim was standing."""
        spot = np.array(self.positions[victim], dtype=float)
        self.match_stats[offender]["fouls"] += 1
        self.velocity[offender] = np.zeros(2, dtype=float)
        if self.replay:
            self.replay.event(
                self.match_clock_frames, ActionType.FOUL,
                player_idx=offender, team=0 if offender < 11 else 1,
            )
        attacking_team = 0 if victim < 11 else 1
        kind = "penalty" if self._in_own_box(offender, spot) else "free_kick"
        self._begin_restart(kind, attacking_team, float(spot[0]), float(spot[1]))

    def _attempt_save(self, index: int) -> bool:
        """The one and only way a keeper stops a shot.

        Both the "save" and "dive" decisions route here, and each shot gets
        exactly ONE attempt: the ball is either kept out or the keeper is
        beaten.
        """
        if self.ball_controller != -1:
            return False
        if self.player_stun_cooldown[index] > 0:
            return False  # already beaten and on the floor

        shot_id = self.active_shot_id
        if shot_id >= 0 and self.save_attempted_shot[index] == shot_id:
            return False  # one attempt per shot, already used

        defending_team = 0 if index < 11 else 1
        crossing = self.predict_goal_crossing(defending_team)
        if crossing is None:
            return False

        # Wait until the ball is actually on them. Checked BEFORE the attempt
        # is recorded, so a keeper starting to dive early doesn't burn the
        # shot's single save on a ball still halfway across the box.
        dist_to_ball = float(_norm2(self.ball[0:2] - self.positions[index]))
        if dist_to_ball > SAVE_ENGAGE_DISTANCE and crossing["time"] > SAVE_ENGAGE_TIME:
            return False

        # Don't dive at a ball that isn't going in. A small margin keeps the
        # keeper reacting to one whistling just past the post.
        inner_min, inner_max = self.goal_frame_bounds()
        if not (
            inner_min - SAVE_COMMIT_MARGIN <= crossing["x"] <= inner_max + SAVE_COMMIT_MARGIN
            and crossing["z"] < GOAL_HEIGHT + SAVE_COMMIT_MARGIN
        ):
            return False

        if shot_id >= 0:
            self.save_attempted_shot[index] = shot_id

        ball_speed = float(_norm2(self.ball[2:4]))
        lateral = abs(crossing["x"] - float(self.positions[index][0]))
        gk_attrs = self.all_players[index].attributes

        # Throw themselves at where the ball is going, so a save reads as a
        # dive in the replay rather than a keeper standing still.
        if lateral > 0.3:
            direction = 1.0 if crossing["x"] > self.positions[index][0] else -1.0
            dive_speed = max(4.0, (gk_attrs.agility / 100.0) * base_speed * 1.6)
            self.velocity[index] = np.array([direction * dive_speed, 0.0], dtype=float)

        save_chance = self._save_chance(gk_attrs, ball_speed, lateral)

        if self.rng.random() >= save_chance: #beaten
            self.velocity[index] = np.zeros(2, dtype=float)
            self.player_stun_cooldown[index] = KEEPER_BEATEN_FRAMES
            self.visual_action[index] = "beaten"
            self.visual_action_timer[index] = KEEPER_BEATEN_FRAMES
            if self.replay:
                self.replay.event(
                    self.match_clock_frames, ActionType.SAVE_FAILED,
                    player_idx=index, team=0 if index < 11 else 1,
                )
            return False

        self.match_stats[index]["saves"] += 1
        if crossing["on_target"] and self.last_shot_player >= 0:
            self.match_stats[self.last_shot_player]["shots_on_target"] += 1
            self.last_shot_player = -1

        self.visual_action[index] = "save"
        self.visual_action_timer[index] = 20
        if self.replay:
            self.replay.event(self.match_clock_frames, ActionType.SAVE, player_idx=index, team=defending_team)

        handling_stat = (gk_attrs.composure * 0.6) + (gk_attrs.ballcontrol * 0.4)
        gather_chance = float(np.clip((handling_stat / 100.0) * 0.85 - (ball_speed / 40.0), 0.05, 0.85))

        if self.rng.random() < gather_chance:
            # --- SUCCESSFUL GATHER (CATCH) ---
            self.ball_controller = index
            self.ball_capture_player = index
            self.ball_event = "neutral"
            self._register_touch(index)
            self.ball_capture_cooldown = 8

            self.ball[0:2] = self.positions[index]
            self.ball[2:4] = self.velocity[index]
            self.ball[4] = 0.0
            self.ball_vz = 0.0

            self.velocity[index] = np.zeros(2, dtype=float)
            self.player_stun_cooldown[index] = 6  # Faster recovery for catching safely
        else:
            # --- DEFLECTION (PARRY) ---
            if self.rng.random() < 0.7:  # sideways
                side_dir = -2.0 if self.positions[index][0] < 35.0 else 2.0
                deflect_x = side_dir * self.rng.uniform(0.8, 1.2)
                deflect_y = -0.5 if self.positions[index][1] < 50.0 else 0.5
            else:  # punch out
                deflect_x = self.rng.uniform(-1.0, 1.0)
                deflect_y = 1.0 if self.positions[index][1] < 50.0 else -1.0

            deflect_dir = np.array([deflect_x, deflect_y])
            deflect_dir = deflect_dir / _norm2(deflect_dir)

            self.ball_controller = -1
            self.last_touch_team = defending_team
            self.ball_capture_player = index
            self.ball_capture_cooldown = 20
            self.ball_release_player = index
            self.ball_release_cooldown = 10

            self.ball[0:2] = self.positions[index]
            self.ball[2:4] = deflect_dir * max(6.0, ball_speed * 0.7)
            self.ball[4] = max(0.5, float(self.ball[4]))
            self.ball_vz = self.rng.uniform(2.0, 6.0)

            self.velocity[index] = np.zeros(2, dtype=float)
            self.player_stun_cooldown[index] = 30  # Longer recovery for diving
        return True

    def _save_chance(self, gk_attrs, ball_speed: float, lateral: float) -> float:
        """How likely this keeper is to stop THIS shot.

        Quality scales with the keeper; difficulty comes from the shot -- how
        fast it is, and how far they have to move to reach where it will
        cross the line. Anchored so a keeper at STAT_CEILING is near-certain on a
        slow ball straight at them and about even money on a fast one at full
        stretch.
        """
        save_stat = ((gk_attrs.agility * 0.6) + (gk_attrs.vision * 0.4) + (gk_attrs.ballcontrol * 0.3)) / 1.3
        quality = KEEPER_QUALITY_BASE + (1.0 - KEEPER_QUALITY_BASE) * min(1.0, save_stat / STAT_CEILING)

        speed_term = min(1.0, max(0.0, ball_speed / HARD_SHOT_SPEED))
        reach_term = min(1.0, max(0.0, lateral / KEEPER_REACH))
        difficulty = (
            SAVE_DIFFICULTY_SPEED_WEIGHT * speed_term + SAVE_DIFFICULTY_REACH_WEIGHT * reach_term
        )

        return float(np.clip(quality * (1.0 - MAX_DIFFICULTY_PENALTY * difficulty), 0.02, 0.99))

    def _resolve_penalty(self, taker_index: int, keeper_index: int):
        """A penalty is a guessing game, not a shot.

        Deliberately NOT routed through _save_chance: that is calibrated for
        open play and rates a slow central shot as the easiest possible save,
        which is exactly what a penalty is -- so penalties would be saved far
        too often. Here the taker picks a corner and the keeper independently
        picks one, and the keeper only gets a save roll if he guessed right.

        Both scales start at 0.80, so even a hopeless taker mostly hits his
        spot and even a poor keeper saves the ones he reads. That keeps
        conversion in the 60-70% band while still rewarding the good ones.

        Returns (scored, aim, dive, on_target); aim/dive are -1 left, 0 middle,
        1 right, from the taker's point of view.
        """
        attrs = self.all_players[taker_index].attributes
        gk = self.all_players[keeper_index].attributes

        # Capped: MIN + SPAN already lands at 0.99, and stat_ability keeps
        # rising past 100, so an item-fed taker would never miss.
        placement = min(PENALTY_CERTAINTY_CAP, PENALTY_PLACEMENT_MIN + PENALTY_PLACEMENT_SPAN * stat_ability(
            attrs.shooting * 0.8 + attrs.accuracy * 0.2
        ))
        save = min(PENALTY_CERTAINTY_CAP, PENALTY_SAVE_MIN + PENALTY_SAVE_SPAN * stat_ability(
            (gk.agility * 0.6 + gk.vision * 0.4 + gk.ballcontrol * 0.3) / 1.3
        ))

        aim = int(self.rng.choice(PENALTY_SIDES))
        dive = int(self.rng.choice(PENALTY_SIDES))
        on_target = self.rng.random() < placement
        read_it = dive == aim and self.rng.random() < save
        return (on_target and not read_it), aim, dive, on_target

    def _players_deciding(self, dist_to_ball: np.ndarray) -> np.ndarray:
        """Boolean per player: does this round get a fresh decision from
        them? See the ADAPTIVE_* constants for the rules. Vectorised --
        this runs every round and must cost far less than one decision.
        """
        rounds = np.full(22, ADAPTIVE_FAR_ROUNDS, dtype=int)
        rounds[dist_to_ball < ADAPTIVE_MID_RADIUS] = ADAPTIVE_MID_ROUNDS
        rounds[dist_to_ball < ADAPTIVE_NEAR_RADIUS] = ADAPTIVE_NEAR_ROUNDS

        # Anyone the ball is heading toward: closest approach to the segment
        # the ball will travel in the lookahead window (velocity is units/s).
        if self.ball_controller == -1:
            ball_vel = self.ball[2:4]
            speed = float(np.hypot(ball_vel[0], ball_vel[1]))
            if speed > 0.5:
                direction = ball_vel / speed
                rel = self.positions - self.ball[0:2]
                along = np.clip(rel @ direction, 0.0, speed * ADAPTIVE_PATH_LOOKAHEAD)
                closest = rel - along[:, None] * direction
                path_dist = np.sqrt(np.einsum("ij,ij->i", closest, closest))
                rounds[path_dist < ADAPTIVE_PATH_RADIUS] = ADAPTIVE_NEAR_ROUNDS
        else:
            rounds[self.ball_controller] = ADAPTIVE_NEAR_ROUNDS

        # Keepers: by which half the ball is in, not by distance.
        ball_y = float(self.ball[1])
        for gk in self._keeper_indices:
            in_own_half = ball_y < 50.0 if gk < 11 else ball_y > 50.0
            if in_own_half:
                rounds[gk] = min(rounds[gk], ADAPTIVE_KEEPER_OWN_HALF_ROUNDS)
            elif rounds[gk] == ADAPTIVE_MID_ROUNDS:
                rounds[gk] = ADAPTIVE_FAR_ROUNDS

        # A change of phase wakes everyone: possession turning over, a
        # restart, a shot. A fullback on a 6-round cadence must not learn
        # about a turnover a fifth of a second late.
        phase = (self.ball_controller, self.ball_event, self.last_touch_team, self.restart_timer > 0)
        woken = phase != self._prev_phase
        self._prev_phase = phase
        if woken:
            return np.ones(22, dtype=bool)

        self._decision_rounds = rounds
        # Staggered by index so the far players don't all land on one round.
        return (self.step_count + np.arange(22)) % rounds == 0

    def step(self):
        self.step_count += 1
        if self.pass_and_move_timer > 0:
            self.pass_and_move_timer -= 1
        if self.ball_release_team_cooldown > 0:
            self.ball_release_team_cooldown -= 1
        if self.ball_release_cooldown > 0:
            self.ball_release_cooldown -= 1
        if self.ball_release_cooldown == 0:
            self.ball_release_player = -1

        if self.ball_capture_cooldown > 0:
            self.ball_capture_cooldown -= 1
        if self.ball_capture_cooldown == 0:
            self.ball_capture_player = -1

        if np.any(self.player_stun_cooldown > 0):
            self.player_stun_cooldown = np.maximum(self.player_stun_cooldown - 1, 0)

        if np.any(self.visual_action_timer > 0):
            self.visual_action_timer = np.maximum(self.visual_action_timer - 1, 0)

        if self.ball_release_player >= 0 and self.ball_release_cooldown > 0 and self.ball_controller == self.ball_release_player:
            self.ball_controller = -1

        # Only ANOTHER player taking the ball clears this, never a loose one.
        # A set piece leaves the ball on the deck with ball_controller == -1, and
        # this ran before the restart guard below -- so must_pass was wiped on
        # the first step and the taker was free to shoot instead of playing it.
        if self.ball_controller >= 0:
            if self.must_pass_next and self.ball_controller != self.must_pass_player:
                self._clear_must_pass()
            elif self.kickoff_pass_required and self.ball_controller != self.kickoff_pass_player:
                self._clear_must_pass()

        if self.kickoff_timer > 0:
            self._maybe_kickoff()
            return
        
        if self.restart_timer > 0:
            return
        
        ball_pos = self.ball[0:2]

        direction_vectors = ball_pos - self.positions
        distances = np.linalg.norm(direction_vectors, axis=1)
        # Which players re-decide this round. `distances` gets masked with
        # inf below for the capture logic, so the gate reads it now.
        deciding = self._players_deciding(distances) if self.adaptive_decisions else None

        possesion: int = 0
        if self.ball_controller == -1:
            if self.ball_release_player >= 0:
                release_team = 0 if self.ball_release_player < 11 else 1
                distances[self.ball_release_player] = np.inf
                if release_team == 0:
                    distances[:11] = np.inf
                else:
                    distances[11:] = np.inf
                if self.ball_release_cooldown > 0:
                    release_pos = self.positions[self.ball_release_player]
                    nearby_release_zone = np.linalg.norm(self.positions - release_pos, axis=1) < 4.0
                    distances[nearby_release_zone] = np.inf

            ball_h = max(0.0, float(self.ball[4]))
            if ball_h >= HEAD_MIN_HEIGHT:
                # Aerial: whoever can reach it contests it, best header wins.
                near = np.flatnonzero((distances < HEAD_RADIUS) & (self._reach >= ball_h))
                if near.size:
                    gk_near = [int(i) for i in near if i in self._keeper_indices]
                    if gk_near and distances[gk_near[0]] <= float(distances[near].min()):
                        self._attempt_capture(gk_near[0])
                    else:
                        outfield = np.array([i for i in near if i not in self._keeper_indices])
                        if outfield.size:
                            score = np.array([
                                0.6 * getattr(self.all_players[i].attributes, "heading", 50)
                                + 0.2 * self.all_players[i].attributes.agility
                                + 0.5 * (getattr(self.all_players[i].attributes, "height", 180) - 170)
                                - 6.0 * distances[i]
                                for i in outfield
                            ]) + self.rng.normal(0.0, 8.0, size=outfield.size)
                            self._attempt_capture(int(outfield[int(np.argmax(score))]))
            else:
                # Offer it down the queue, not just to the nearest man. He may
                # be inside his own capture lockout from a touch he just missed,
                # and asking only him meant the ball rolled through a crowd
                # untouched -- a third of all offers were refused this way, and
                # in a third of those somebody else was stood in range.
                order = np.argsort(distances)
                for cand in order[:LOOSE_BALL_OFFERS]:
                    cand = int(cand)
                    if distances[cand] >= self.possession_radius + 1.5:
                        break
                    if self.ball_capture_player == cand and self.ball_capture_cooldown > 0:
                        continue
                    if self._attempt_capture(cand):
                        break

            if self.ball_event in {"pass", "cross", "shot", "throw_in"}:
                possesion = 1 if self.last_touch_team == 0 else -1

        else:
            if self.ball_controller >= 11:
                possesion = -1
            else:
                possesion = 1

        # Per-round, for every player at once, rather than rebuilt inside the
        # loop below for each deciding player: the numbers each state dict
        # needs that don't depend on anyone's decision.
        ball_velocity = np.array(self.ball[2:4], dtype=float)
        ball_height = float(self.ball[4])
        goal_vecs = self._goal_targets - self.positions
        dists_to_goal = np.sqrt(np.einsum("ij,ij->i", goal_vecs, goal_vecs))
        goal_dirs = goal_vecs / (dists_to_goal[:, None] + 1e-8)
        # "Pressure": opponents within 3 units and ahead of the player, in
        # the direction of their goal. One 22x11 pass instead of 22 small ones.
        pressure_counts = np.zeros(22, dtype=int)
        for team_slice, opp_slice in ((slice(0, 11), slice(11, 22)), (slice(11, 22), slice(0, 11))):
            rel = self.positions[opp_slice][None, :, :] - self.positions[team_slice][:, None, :]  # 11x11x2
            forward = np.einsum("ijk,ik->ij", rel, goal_dirs[team_slice])
            near = np.einsum("ijk,ijk->ij", rel, rel) < 9.0  # 3.0 ** 2
            pressure_counts[team_slice] = np.sum((forward > 0.0) & near, axis=1)
        ys = self.positions[:, 1]
        xs = self.positions[:, 0]
        past_halfspaces = np.where(np.arange(22) < 11, ys > 50.0, ys < 50.0)
        in_boxes = (14.0 < xs) & (xs < 56.0) & np.where(np.arange(22) < 11, ys > 82.0, ys < 18.0)
        # Is a centre-back home for each side? See CB_HOME_DEPTH.
        cb_home = [False, False]
        for team, (team_slice, goal_y) in enumerate(((slice(0, 11), 0.0), (slice(11, 22), PITCH_HEIGHT))):
            cbs = self._cb_mask[team_slice]
            if cbs.any():
                pos = self.positions[team_slice][cbs]
                cb_home[team] = bool(np.any(
                    (np.abs(pos[:, 1] - goal_y) < CB_HOME_DEPTH) & (np.abs(pos[:, 0] - PITCH_WIDTH / 2.0) < CB_HOME_HALF_WIDTH)
                ))
        # The keeper's loose-ball read is per TEAM, not per player -- computed
        # at most twice a round, not 22 times.
        goal_crossings = (
            [self.predict_goal_crossing(0), self.predict_goal_crossing(1)]
            if self.ball_controller == -1 else [None, None]
        )

        actions = []
        for i in range(22):
            if i == self.ball_capture_player and self.ball_capture_cooldown > 0:
                actions.append(None)
                continue

            if deciding is not None and not deciding[i]:
                # Not this player's round: carry on with their last movement.
                # Anything else they last did was one-shot and already
                # happened -- repeating a pass or a shot would be a new one.
                last = self._last_actions[i]
                actions.append(last if last is not None and last.get("type") == "move" else None)
                continue

            home = i < 11
            enemy_goal = self._goal_targets[i]

            state = {
                "has_ball": (self.ball_controller == i),
                "ball_pos": ball_pos,
                "ball_velocity": ball_velocity,
                "ball_height": ball_height,
                "ball_vz": self.ball_vz,
                "my_pos": self.positions[i],
                "my_velocity": self.velocity[i],
                "my_heading": self.heading[i],
                "dist_to_ball": distances[i],
                "dist_to_goal": dists_to_goal[i],
                "vec_to_goal": goal_vecs[i],
                "enemy_goal": enemy_goal,
                "goal_target": enemy_goal,
                "a_direction": 1 if home else -1,
                "in_penalty_box": bool(in_boxes[i]),
                "in_attacking_box": bool(in_boxes[i]),
                "pressure_count": int(pressure_counts[i]),
                "teammates": self.positions[0:11] if home else self.positions[11:22],
                "teammate_vel": self.velocity[0:11] if home else self.velocity[11:22],
                "opponent_vel": self.velocity[11:22] if home else self.velocity[0:11],
                "teammate_pace": self._pace[0:11] if home else self._pace[11:22],
                "opponent_pace": self._pace[11:22] if home else self._pace[0:11],
                "opponents": self.positions[11:22] if home else self.positions[0:11],
                "formation_pos": self.formation[i]["pos"],
                "my_role": self.formation[i]["role"],
                # Whether one of my centre-backs is holding the middle. A
                # full-back reads this to decide between its flank and the
                # centre -- see defender.py's "cover".
                "cb_home": cb_home[0 if home else 1],
                "team_possession": possesion if home else -possesion,
                "past_halfspace": bool(past_halfspaces[i]),
                "own_goal": self._own_goals[i],
                "must_pass_next": self.must_pass_next and self.must_pass_player == i and self.ball_controller == i,
                "is_loose": (self.ball_controller == -1),
                # 0-100. Available for player classes that want to pace
                # themselves; fatigue already slows movement regardless (see
                # _fatigue_factor).
                "stamina": float(self.stamina[i]),
                # Where the loose ball will cross this player's own goal line,
                # or null. Only the keeper reads it (see goalkeeper.py) -- it
                # is what lets them tell a shot that's going in from one
                # drifting wide, instead of diving at everything.
                "goal_crossing": goal_crossings[0 if home else 1],
                # The plan this player latched onto last round ("wingplay")
                # or None; a decision keeps it by returning it on its action.
                "intent": self.intent[i],
                "rng": self.rng,
            }
            intended_action = self.all_players[i].step(state)
            # The intended receiver goes to meet the ball instead of running his
            # own route past it. _chase_target keeps the meeting point in play.
            if (
                i == self.pass_and_move
                and self.pass_and_move_timer > 0
                and self.ball_controller != i
            ):
                fwd = 1.0 if i < 11 else -1.0
                ahead = np.array([
                    float(np.clip(self.positions[i][0] * 0.7 + (PITCH_WIDTH / 2.0) * 0.3, 2.0, PITCH_WIDTH - 2.0)),
                    float(np.clip(self.positions[i][1] + fwd * PASS_AND_MOVE_PUSH, 2.0, PITCH_HEIGHT - 2.0)),
                ])
                intended_action = {
                    "type": "move",
                    "target": ahead,
                    "speed_mod": pace_ability(self.all_players[i].attributes.speed) * 1.1,
                }
            if (
                i == self.pass_receiver
                and self.ball_controller == -1
                and self.ball_event in {"pass", "cross", "throw_in"}
            ):
                intended_action = {
                    "type": "move",
                    "target": self.all_players[i]._chase_target(state),
                    "speed_mod": pace_ability(self.all_players[i].attributes.speed) * 1.15,
                }
            actions.append(intended_action)
            self._last_actions[i] = intended_action
            self.intent[i] = intended_action.get("intent") if intended_action else None
            self._decisions_made += 1

        resolve_order = np.argsort(distances)

        for i in resolve_order:
            self._resolve_action(int(i), actions[int(i)])

        # Charged after the actions land, so this step's cost reflects the
        # velocities those actions just set.
        self._drain_stamina()


def run_match(teamA, teamB, max_steps: int = 10800, fps: int = 60, render: bool = False, window_size=(1280, 800), title: str = "Packed Football", formation_home="4-4-2", formation_away="4-4-2"):
    match = game(teamA, teamB, formation_home=formation_home, formation_away=formation_away)
    return match.run_match(max_steps=max_steps, fps=fps, render=render, window_size=window_size, title=title)


  