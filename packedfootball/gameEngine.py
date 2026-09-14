import copy
from dataclasses import asdict

import numpy as np
from typing import Final

from replay import ActionType, ReplayRecorder

# Bump whenever match behaviour changes. 
# Stamped onto every games/{id} doc so a reported match can be read against the engine
# that actually produced it -- seed + ENGINE_VERSION together reproduce a
# game exactly. 
# 
# v2: goal frame with posts/crossbar, throw-ins from the real
# out point, real stoppage time, match stats + ratings, keeper can leave its
# line, stamina, height.
ENGINE_VERSION: Final[int] = 2

PITCH_WIDTH: Final[float] = 70.0
PITCH_HEIGHT: Final[float] = 100.0
GOAL_WIDTH: Final = 7.5
GOAL_HEIGHT: Final = 2.5
GOAL_POST_RADIUS: Final = 0.25
POST_REBOUND_DAMPING: Final = 0.55 # how much goalpost eats the velocity
THROW_IN_POWER_FACTOR: Final = 2.0 / 3.0 # touch power idk random

FRAMES_PER_CLOCK_SECOND: Final = 2 # match_clock_frames / 2 = seconds, so 90:00 == 10800

# Stoppage time, in frames. Weighted heavy per event on purpose: this engine
# keeps the ball in play far more than real football (~5 restarts a match,
# not ~60), so light weights would give every match a 0:10 of added time.
ADDED_TIME_BASE_FRAMES: Final = 60   # 30s
ADDED_TIME_PER_GOAL: Final = 60      # 30s, celebration + restart
ADDED_TIME_PER_RESTART: Final = 20   # 10s per throw-in/corner/goal kick
ADDED_TIME_PER_POST: Final = 10      # 5s scramble
ADDED_TIME_MAX_FRAMES: Final = 840   # cap at 8:00
# A half doesn't end while an attack is live (see _attack_is_live). This caps
# how long the whistle can be held so a team knocking it around up there
# can't stall the match. 200 frames == 1:40 of clock.
MAX_WHISTLE_HOLD_FRAMES: Final = 200
# How deep into the opponent's half counts as a live attack. The final third,
# not the halfway line: measured over 30 matches, "past halfway" held the
# whistle on 14 of 20 occasions and hit the cap in half of them (teams just
# pass it around the opponent's half). The final third holds 5 of 20, averages
# 40 seconds, and never hits the cap.
DANGEROUS_ZONE_Y: Final = PITCH_HEIGHT * 2.0 / 3.0

# Sentinel for "not latched yet", since None legitimately means "ball dead".
_UNSET = object()

# Stamina. Everyone starts a match on STAMINA_MAX regardless of their card;
# the `stamina` ATTRIBUTE is !resistance! to losing it, so two players doing
# identical work tire at different rates.
STAMINA_MAX: Final = 100.0
STAMINA_DRAIN_PER_STEP: Final = 0.014    # full sprint, at reference stamina
STAMINA_REFERENCE: Final = 60            # attribute that drains at exactly 1.0x
STAMINA_RECOVERY_PER_STEP: Final = 0.010 # paid back only while barely moving
# Effort below this counts as walking/standing and earns recovery. Set low on
# purpose: at a generous threshold, recovery outpaced drain at ordinary match
# effort and nobody ever got tired.
STAMINA_RECOVERY_EFFORT: Final = 0.25
STAMINA_MIN_SPEED_FACTOR: Final = 0.65   # pace kept when completely empty

base_kick_pow:Final = 20
base_speed:Final = 10.0
possession_radius: Final = 2.0
final_whistle_delay: Final = 600
OUT_OF_POSITION_PENALTY: Final = 0.9

# formations.py imports PITCH_WIDTH/PITCH_HEIGHT from this module, so this
# import must come after they're defined above to avoid a circular-import
# failure (formations.py is mid-import of a still-partial gameEngine module).
from formations import get_formation, is_similar_position


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
    from player.player import Attributes, TENDENCY_FIELDS

    original_fields = asdict(p.attributes)
    scaled_fields = {
        field: (value if field in TENDENCY_FIELDS else round(value * OUT_OF_POSITION_PENALTY))
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
    def __init__(self, teamA, teamB, seed=None, record_replay=False, formation_home="4-4-2", formation_away="4-4-2"):

        self.teamA = teamA # name, short_name, players
        self.teamB = teamB
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.replay = ReplayRecorder() if record_replay else None

        self.formation_home = formation_home
        self.formation_away = formation_away
        self.formation = _combine_formations(formation_home, formation_away)

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

        self.positions = np.zeros((22,2),float) # (x,y) pairs
        self.velocity = np.zeros((22,2),float) # (vx,vy) pairs

        self.heading = np.zeros((22,2),float) # (hx,hy) pairs
        self.heading[0:11] = [0.0, 1.0] 
        self.heading[11:22] = [0.0, -1.0] 

        self.ball = np.array([35.0, 50.0, 0.0, 0.0, 0.0,],float) # (x,y,vx,vy,vz)
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
        self.last_pass_player = -1
        self._match_goals = [0] * 22
        self._match_assists = [0] * 22
        self.stamina = np.full(22, STAMINA_MAX, dtype=float)
       
        self.ball_controller = -1  # -1 indicates a loose ball. 0-21 corresponds to the player index currently in possession.
        self.ball_event = "neutral"
        
        self.possession_radius = possession_radius
        self.player_radius = 1
        self.step_count = 0
        self.match_clock_frames = 0
        self.ball_release_cooldown = 0
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
        self.restart_timer = 0  
        self.pending_restart_pass_type = None # Outlives restart_type (which is cleared the moment restart_timer runs out) so the restart's first pass still knows it's a throw-in.
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
        for i in range(len(self.positions)):
            for j in range(i + 1, len(self.positions)):
                delta = self.positions[i] - self.positions[j]
                dist = np.linalg.norm(delta)
                min_dist = self.player_radius 

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
        return min(candidates, key=lambda idx: float(np.linalg.norm(self.positions[idx] - point)))

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
        teammates.sort(key=lambda idx: float(np.linalg.norm(self.positions[idx] - point)))
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
            distance = float(np.linalg.norm(offset))
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
            self.ball_controller = kickoff_player
            self._set_must_pass_for_player(kickoff_player)
            if self.kickoff_timer == 0:
                self.out_of_play = False
                self.ball_release_player = -1
                self.ball_release_cooldown = 0

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
        for i in range(22):
            self.positions[i] = np.array(self.formation[i]["pos"], dtype=float)
        self.velocity[:] = 0.0
        self.heading[0:11] = [0.0, 1.0]
        self.heading[11:22] = [0.0, -1.0]

        if restart_type == "kickoff":
            kickoff_player = self._kickoff_player_for_team(team)
            self.positions[kickoff_player] = np.array([35.0, 50.0], dtype=float)
            self.ball[:] = [35.0, 50.0, 0.0, 0.0, 0.0]
            self.ball_controller = kickoff_player
            self._set_must_pass_for_player(kickoff_player)
            return

        if restart_type == "throw_in":
            self.ball[:] = [35.0, 50.0, 0.0, 0.0, 0.0]
            self.ball_controller = -1
            return

        if restart_type == "corner":
            attacking_y = 85.0 if team == 0 else 15.0
            defending_y = 92.0 if team == 0 else 8.0
            
            a_box = [2, 3, 6, 7, 9, 10] if team == 0 else [13, 14, 17, 18, 20, 21]
            d_box = [12, 13, 14, 15, 16, 17, 18, 19] if team == 0 else [1, 2, 3, 4, 5, 6, 7, 8]

            for p in a_box:
                self.positions[p] = [35.0 + self.rng.uniform(-10, 10), attacking_y + self.rng.uniform(-4, 4)]

            for p in d_box:
                self.positions[p] = [35.0 + self.rng.uniform(-12, 12), defending_y + self.rng.uniform(-3, 3)]

            self.ball[:] = [35.0, 50.0, 0.0, 0.0, 0.0]
            self.ball_controller = -1
            return
        if restart_type == "goal_kick":
            self.ball[:] = [35.0, 50.0, 0.0, 0.0, 0.0]
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
        self.pending_restart_pass_type = None
        if restart_type in ("throw_in", "corner", "goal_kick"):
            self.restart_count += 1
        self.reset_positions(restart_type=restart_type, team=self.restart_team)

        if restart_type == "kickoff":
            self.kickoff_team = self.restart_team
            kickoff_player = self._kickoff_player_for_team(self.kickoff_team)
            self.positions[kickoff_player] = np.array([35.0, 50.0], dtype=float)
            self.ball[:] = [35.0, 50.0, 0.0, 0.0, 0.0]
            self.ball_controller = kickoff_player
            self._set_must_pass_for_player(kickoff_player)
            self.kickoff_timer = 30
        elif restart_type == "corner":
            corner_player = self._pick_role_slot(self.restart_team, ("RW", "LW", "RM", "LM", "WB"), 8)
            self.restart_player = corner_player
            
            # Snap player to the left or right corner flag depending on out_x
            corner_x = 0.0 if out_x < 35.0 else PITCH_WIDTH
            corner_y = PITCH_HEIGHT if self.restart_team == 0 else 0.0
            
            self.positions[corner_player] = [corner_x, corner_y]
            self.ball[:] = [corner_x, corner_y, 0.0, 0.0, 0.0]
            self.ball_controller = corner_player
            self._set_must_pass_for_player(corner_player)
            
        elif restart_type == "goal_kick":
            keeper = 0 if self.restart_team == 0 else 11
            self.restart_player = keeper
            self.ball[:] = [self.positions[keeper][0], self.positions[keeper][1], 0.0, 0.0, 0.0]
            self.ball_controller = keeper
            self._set_must_pass_for_player(keeper)
        elif restart_type == "throw_in":
            throw_x = 0.0 if out_x < PITCH_WIDTH / 2.0 else PITCH_WIDTH
            throw_y = float(np.clip(35.0 if out_y is None else out_y, 1.0, PITCH_HEIGHT - 1.0))
            throw_point = np.array([throw_x, throw_y], dtype=float)

            # Full-backs and wide players take throw-ins, nearest one first --
            # see _pick_nearest_eligible for why proximity matters here.
            throw_player = self._pick_nearest_eligible(
                self.restart_team, throw_point, ("LB", "RB", "WB", "LM", "RM", "LW", "RW")
            )
            self.restart_player = throw_player

            self._shift_shape_toward(throw_point, self.restart_team)
            self.positions[throw_player] = throw_point.copy()
            self.ball[:] = [throw_x, throw_y, 0.0, 0.0, 0.0]
            self.ball_controller = throw_player
            self._set_must_pass_for_player(throw_player)
            # Survives restart_timer expiring (which clears restart_type), so
            # the throw itself is still thrown rather than kicked -- see
            # _resolve_action's pass branch.
            self.pending_restart_pass_type = "throw_in"

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
                else: color = (200, 200, 200)
            else:
                color = base_color
            
            radius = max(9, int(18 * (scale / (width / 40.0)))) # Scale player radius dynamically
            if self.ball_controller == idx:
                pygame.draw.circle(screen, (255, 255, 255), (sx, sy), radius + 4, 3)
            pygame.draw.circle(screen, color, (sx, sy), radius)

            # Heading Indicator
            heading = self.heading[idx]
            if np.linalg.norm(heading) > 0:
                heading = heading / np.linalg.norm(heading)
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
        clock_total_seconds = int(self.match_clock_frames / 2.0)
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
        first_half_end = None   # regulation + added time for the 1st half
        second_half_end = None  # ditto for the 2nd
        halftime_done = False

        # Who was attacking when each whistle came due, latched once (None is
        # a real value here -- "ball was dead" -- hence the sentinel).
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

            if self.match_clock_frames % 2 == 0:
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
            if self.restart_timer == 0:
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
            self.ball[4] -= 9.8 * dt
            
            friction = 0.5 ** dt
            self.ball[2] *= friction
            self.ball[3] *= friction
            
            if abs(self.ball[2]) < 0.1: self.ball[2] = 0.0
            if abs(self.ball[3]) < 0.1: self.ball[3] = 0.0
        else:
            self.ball[0:2] = self.positions[self.ball_controller]
            self.ball[2:4] = self.velocity[self.ball_controller]
            self.ball[4] = 0.0 

        # Goal frame FIRST. A ball crossing the goal plane is a goal or a
        # rebound off the woodwork; either way the out-of-bounds branch below
        # must not get to claim it. This ordering is the fix for balls
        # disappearing into a scoreless kickoff.
        frame_result = self._resolve_goal_frame(prev_ball_xy, prev_ball_height)
        if frame_result == "goal":
            return
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
        agility_bonus = (player_attr.agility / 100.0) * 0.35
        control_bonus = (player_attr.ballcontrol / 100.0) * 0.25
        defending_bonus = (player_attr.defending / 100.0) * 0.20

        probability = base - speed_penalty - height_penalty + agility_bonus + control_bonus + defending_bonus + pass_bonus
        return float(np.clip(probability, 0.05, 0.95))

    def _attempt_capture(self, index: int) -> bool:
        if self.ball_controller == index:
            return True

        if self.ball_capture_player == index and self.ball_capture_cooldown > 0:
            return False

        if self.ball_release_player >= 0 and self.ball_release_cooldown > 0:
            release_team = 0 if self.ball_release_player < 11 else 1
            current_team = 0 if index < 11 else 1
            if release_team == current_team:
                return False

        dist_to_ball = np.linalg.norm(self.ball[0:2] - self.positions[index])
        if dist_to_ball > self.possession_radius + 0.5:
            return False

        ball_speed = float(np.linalg.norm(self.ball[2:4]))
        ball_height = max(0.0, float(self.ball[4]))
        current_team = 0 if index < 11 else 1
        pass_like_event = self.ball_event in {"pass", "cross", "clearance", "throw_in"}

        player_to_ball = self.ball[0:2] - self.positions[index]
        ball_motion = np.array(self.ball[2:4], dtype=float)
        if np.linalg.norm(ball_motion) > 0.0 and np.dot(player_to_ball, ball_motion) < -0.3:
            self.ball_capture_player = index
            self.ball_capture_cooldown = 8
            return False

        if pass_like_event and self.last_touch_team == current_team:
            control_chance = (
                0.8
                + (self.all_players[index].attributes.composure / 100.0) * 0.10
                + (self.all_players[index].attributes.ballcontrol / 100.0) * 0.20
                + max(0.0, 1.0 - ball_speed / 18.0) * 0.15
            )
            if self.rng.random() < float(np.clip(control_chance, 0.60, 0.99)):
                passer = self.last_pass_player
                if passer >= 0 and passer != index and (passer < 11) == (index < 11):
                    self.match_stats[passer]["passes_completed"] += 1
                self.last_pass_player = -1

                self.ball_controller = index
                self.ball_capture_player = index
                self.ball_event = "neutral"
                self._register_touch(index)
                self.ball_capture_cooldown = 8
                self.ball[0:2] = self.positions[index]
                self.ball[2:4] = self.velocity[index]
                self.ball[4] = 0.0
                self.visual_action[index] = "recieved_pass"
                self.visual_action_timer[index] = 15
                if self.replay:
                    self.replay.event(self.match_clock_frames, ActionType.RECEIVED_PASS, player_idx=index, team=0 if index < 11 else 1)
                return True
            return False
        

        block_threshold = 3.0
        if (ball_speed >= block_threshold) or (ball_height >= 0.75):
            deflection_bias = self._capture_success_probability(index, ball_speed, ball_height)
            pass_bias = 0.12 if self.ball_event in {"pass", "cross", "clearance", "throw_in"} else 0.04
            block_chance = np.clip(0.22 + (ball_speed * 0.10) + (ball_height * 0.28) + (self.all_players[index].attributes.agility / 100.0) * 0.30 - deflection_bias * 0.20 + pass_bias, 0.15, 0.98)
            if self.rng.random() < block_chance:
                current_heading = self.heading[index]
                if np.linalg.norm(current_heading) < 1e-8:
                    current_heading = np.array([1.0, 0.0], dtype=float)
                ball_dir = np.array(self.ball[2:4], dtype=float)
                if np.linalg.norm(ball_dir) < 1e-8:
                    ball_dir = np.array([1.0, 0.0], dtype=float)
                ball_dir = ball_dir / np.linalg.norm(ball_dir)

                normal = np.array([-ball_dir[1], ball_dir[0]], dtype=float)
                if np.dot(normal, current_heading) < 0.0:
                    normal *= -1.0

                side_bias = self.rng.uniform(-1.0, 1.0)
                deflection = normal * side_bias + ball_dir * self.rng.uniform(0.35, 0.8)
                deflection = deflection / np.linalg.norm(deflection)

                self.ball_controller = -1
                self._register_touch(index)
                self.ball_capture_player = index
                self.ball_capture_cooldown = 12
                self.ball_release_player = index
                self.ball_release_cooldown = 8
                self.ball[0:2] = self.positions[index]
                self.ball[2:4] = deflection * max(3.0, ball_speed * self.rng.uniform(0.5, 0.9))
                self.ball[4] = max(0.0, ball_height * 0.5)
                self.velocity[index] *= 0.4         

                if np.linalg.norm(self.ball[2:4]) <= max(2.0, self.all_players[index].attributes.speed * 0.12):
                    self.ball_controller = index
                    self.ball_capture_player = index
                    self.ball_event = "neutral"
                    self._register_touch(index)
                    self.ball_capture_cooldown = 8
                    self.ball[0:2] = self.positions[index]
                    self.ball[2:4] = self.velocity[index]
                    self.ball[4] = 0.0
                    return True
                return False

        success_chance = self._capture_success_probability(index, ball_speed, ball_height)
        success_chance = float(np.clip(success_chance + 0.15, 0.2, 0.98))

        if self.rng.random() < success_chance:
            self.ball_controller = index
            self.ball_capture_player = index
            self.ball_event = "neutral"
            self._register_touch(index)
            self.ball_capture_cooldown = int(8 + max(0.0, ball_height * 4.0))
            self.ball[0:2] = self.positions[index]
            self.ball[2:4] = self.velocity[index]
            self.ball[4] = 0.0
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

    def _goal_for_player(self, player_index: int) -> np.ndarray:
        return np.array([PITCH_WIDTH/2, 100.0]) if player_index < 11 else np.array([PITCH_WIDTH/2, 0.0])

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
            self._rebound_off_frame(np.array([cross_x, plane_y]), np.array([0.0, inward]))
            return "rebound"

        # Either post. Reflect about the outward normal from the post centre,
        # so a ball clipping the inside face deflects goalward and one
        # clipping the outside face deflects away -- both are then re-tested
        # next tick by this same function, which is how "in off the post"
        # works without being special-cased.
        for post_x in post_centres:
            if abs(cross_x - post_x) <= GOAL_POST_RADIUS and cross_z < GOAL_HEIGHT:
                normal = np.array([cross_x - post_x, 0.0], dtype=float)
                if np.linalg.norm(normal) < 1e-8:
                    normal = np.array([0.0, inward], dtype=float)
                self._rebound_off_frame(np.array([cross_x, plane_y]), normal)
                return "rebound"

        return None

    def _rebound_off_frame(self, contact: np.ndarray, normal: np.ndarray) -> None:
        """Bounces the ball off the woodwork and leaves it in play."""
        normal = np.asarray(normal, dtype=float)
        norm = np.linalg.norm(normal)
        normal = normal / norm if norm > 1e-8 else np.array([0.0, 1.0])

        velocity = np.array(self.ball[2:4], dtype=float)
        reflected = velocity - 2.0 * float(np.dot(velocity, normal)) * normal
        self.ball[2:4] = reflected * POST_REBOUND_DAMPING

        # Nudge the ball back inside along the pitch's long axis so the next
        # tick doesn't immediately re-detect the same crossing.
        inset = 0.35
        contact_y = float(contact[1])
        self.ball[0] = float(np.clip(contact[0], 0.0, PITCH_WIDTH))
        self.ball[1] = inset if contact_y <= 0.0 else PITCH_HEIGHT - inset

        self.post_hits += 1
        # The ball is loose and nobody has touched it since the shot -- leave
        # last_touch_* alone so a rebound that goes out still awards the right
        # corner/goal kick, exactly as a deflection would.
        self.ball_controller = -1

    def _award_goal(self, scoring_team: int) -> None:
        self.scores[scoring_team] += 1
        self.last_goal_team = scoring_team
        self.ball_controller = -1

        # A goal is by definition on target, for whoever shot it.
        if self.last_shot_player >= 0:
            self.match_stats[self.last_shot_player]["shots_on_target"] += 1
            self.last_shot_player = -1
        # Charged to the beaten keeper -- index 0 / 11 by formation contract.
        conceding_keeper = 11 if scoring_team == 0 else 0
        self.match_stats[conceding_keeper]["goals_conceded"] += 1

        # --- Evaluate Goal & Assist Statistics ---
        scorer_name = "Own Goal"
        if self.last_touch_player != -1:
            touch_team = 0 if self.last_touch_player < 11 else 1
            if touch_team == scoring_team:
                scorer = self.all_players[self.last_touch_player]
                scorer.scored()
                self._match_goals[self.last_touch_player] += 1
                scorer_name = scorer.lname

                if self.assist_candidate != -1:
                    assister = self.all_players[self.assist_candidate]
                    assister.assisted()
                    self._match_assists[self.assist_candidate] += 1
            else:
                self.assist_candidate = -1

        team_label = "A" if scoring_team == 0 else "B"
        self._trigger_goal_popup(f"{team_label}: {scorer_name}")

        self.goal_pause_timer = 90
        self.kickoff_team = 1 - scoring_team
        if self.replay:
            self.replay.event(self.match_clock_frames, ActionType.GOAL, player_idx=self.last_touch_player, team=scoring_team)
        self.last_touch_player = -1
        self.assist_candidate = -1

    def _turn_heading_toward(self, index: int, target_dir: np.ndarray) -> np.ndarray:
        target_dir = np.asarray(target_dir, dtype=float)
        target_norm = np.linalg.norm(target_dir)
        if target_norm < 1e-8:
            return self.heading[index]
        target_dir = target_dir / target_norm

        current = self.heading[index]
        current_norm = np.linalg.norm(current)
        if current_norm < 1e-8:
            current = np.array([0.0, 1.0]) if index < 11 else np.array([0.0, -1.0])
            current_norm = 1.0
        current = current / current_norm

        dot = float(np.clip(np.dot(current, target_dir), -1.0, 1.0))
        angle = np.arccos(dot)

        agility = getattr(self.all_players[index].attributes, "agility", 50)
        max_turn = 0.18 + (agility / 100.0) * 0.9

        if angle <= 1e-6:
            return target_dir
        if angle <= max_turn:
            return target_dir

        cross = current[0] * target_dir[1] - current[1] * target_dir[0]
        sign = 1.0 if cross >= 0.0 else -1.0
        theta = sign * max_turn
        c, s = np.cos(theta), np.sin(theta)
        rotated = np.array([
            c * current[0] - s * current[1],
            s * current[0] + c * current[1],
        ], dtype=float)
        return rotated / np.linalg.norm(rotated)

    def _release_ball(self, owner_index: int, direction: np.ndarray, launch_speed: float, aerial: bool = False, event_type: str = "neutral"):
        direction = np.asarray(direction, dtype=float)
        direction_norm = np.linalg.norm(direction)
        if direction_norm < 1e-8:
            direction = np.array([1.0, 0.0], dtype=float)
            direction_norm = 1.0
        direction = direction / direction_norm

        self.ball_event = event_type
        self.ball_controller = -1
        self.ball_release_player = owner_index
        self.last_pass_player = owner_index if event_type in ("pass", "throw_in") else -1
        self._register_touch(owner_index)
        
        if aerial:
            self.ball_release_cooldown = 40 + int(min(25.0, launch_speed * 1.2))
            self.ball[4] = 0.8 + min(1.2, launch_speed / 18.0)
        else:
            self.ball_release_cooldown = 8 + int(min(8.0, launch_speed * 0.08))
            self.ball[4] = 0.0

        self.ball[0:2] = self.positions[owner_index]
        self.ball[2:4] = direction * launch_speed
        self.ball[4] = max(0.0, self.ball[4])

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
            dist = np.linalg.norm(vec)

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
                dist = np.linalg.norm(vec)
                if dist < 1e-8:
                    return

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
                if self.pending_restart_pass_type == "throw_in" and self.restart_player == index:
                    pass_type = "throw_in"
                    self.pending_restart_pass_type = None
                elif self.kickoff_pass_player == index:
                    px, py = self.positions[index]
                    if (px <= 5.0 or px >= PITCH_WIDTH - 5.0) and (py <= 5.0 or py >= PITCH_HEIGHT - 5.0):
                        pass_type = "cross"

                power = base_kick_pow * action["power"]
                aerial = False
                event_type = "pass"
                if pass_type == "clearance":
                    aerial = True
                    power *= 1.2
                elif pass_type == "cross":
                    aerial = True
                    power *= 1.15
                elif pass_type == "throw_in":
                    # Two thirds of the player's normal passing power -- an
                    # arm throw, not a leg. Grounded, so a teammate can
                    # actually control it.
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
                        "throw_in": ActionType.THROW_IN,
                    }.get(pass_type, ActionType.PASS)
                    self.replay.event(self.match_clock_frames, pass_event, player_idx=index, team=0 if index < 11 else 1)
                # event_type (not pass_type) is what _capture_success_probability
                # and _attempt_capture branch on -- both already special-case
                # "throw_in" alongside pass/cross/clearance.
                self._release_ball(index, unit_vec, power, aerial=aerial, event_type=event_type)

        elif action_type == "shoot":
            if self.ball_controller == index:
                target_3d = np.array(action["target_3d"], dtype=float)
                ball_pos_3d = np.array([self.ball[0], self.ball[1], 0.0], dtype=float)
                vec_3d = target_3d - ball_pos_3d
                dist_3d = np.linalg.norm(vec_3d)
                if dist_3d < 1e-8:
                    return

                unit_vec_3d = vec_3d / dist_3d
                shot_speed = base_kick_pow * action["power"]
                aerial = bool(np.abs(unit_vec_3d[2]) > 0.1 or target_3d[2] > 0.2)

                self.match_stats[index]["shots"] += 1
                # On-target is credited later, when the ball actually reaches
                # the frame (a goal) or is saved -- the real definition, and
                # better than trusting where the shooter aimed.
                self.last_shot_player = index

                self.visual_action[index] = "shoot"
                self.visual_action_timer[index] = 15
                if self.replay:
                    self.replay.event(self.match_clock_frames, ActionType.SHOOT, player_idx=index, team=0 if index < 11 else 1)
                self._release_ball(index, unit_vec_3d[:2], shot_speed, aerial=aerial, event_type="shot")
                self.ball[2] = unit_vec_3d[0] * shot_speed
                self.ball[3] = unit_vec_3d[1] * shot_speed
                self.ball[4] = abs(unit_vec_3d[2]) * shot_speed

        elif action_type == "tackle":
            if self.ball_controller == -1 or self.ball_controller == index:
                return

            holder_idx = self.ball_controller
            dist = np.linalg.norm(self.positions[index] - self.positions[holder_idx])
            
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
                    tackle_vector_norm = np.linalg.norm(tackle_vector)
                    if tackle_vector_norm < 1e-8:
                        tackle_vector = self.heading[index]
                        tackle_vector_norm = np.linalg.norm(tackle_vector)
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
            if self.ball_controller != -1:
                return
                
            dist = np.linalg.norm(self.ball[0:2] - self.positions[index])
            
            if dist <= 4.0:
                ball_speed = np.linalg.norm(self.ball[2:4])
                gk_attrs = self.all_players[index].attributes
                
                save_stat = (gk_attrs.agility * 0.6) + (gk_attrs.vision * 0.4) + (gk_attrs.ballcontroll)*0.3
                save_chance = float(np.clip((save_stat / 100.0) * 0.80, 0.10, 0.95))
                
                if self.rng.random() < save_chance:
                    self.match_stats[index]["saves"] += 1
                    # A shot that had to be saved was on target. Credited to
                    # whoever struck it, not to the keeper.
                    if self.last_shot_player >= 0:
                        self.match_stats[self.last_shot_player]["shots_on_target"] += 1
                        self.last_shot_player = -1

                    self.visual_action[index] = "save"
                    self.visual_action_timer[index] = 20
                    if self.replay:
                        self.replay.event(self.match_clock_frames, ActionType.SAVE, player_idx=index, team=0 if index < 11 else 1)


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
                        
                        self.velocity[index] = np.zeros(2, dtype=float)
                        self.player_stun_cooldown[index] = 6 # Faster recovery for catching safely
                    else:
                        # --- DEFLECTION (PARRY) ---
                        if self.rng.random() < 0.7: #sideways
                            side_dir = -2.0 if self.positions[index][0] < 35.0 else 2.0
                            deflect_x = side_dir * self.rng.uniform(0.8, 1.2)
                            deflect_y = -0.5 if self.positions[index][1] < 50.0 else 0.5
                        else: # punch out
                            deflect_x = self.rng.uniform(-1.0, 1.0)
                            deflect_y = 1.0 if self.positions[index][1] < 50.0 else -1.0 
                            
                        deflect_dir = np.array([deflect_x, deflect_y])
                        deflect_dir = deflect_dir / np.linalg.norm(deflect_dir)
                        
                        self.ball_controller = -1
                        self.last_touch_team = 0 if index < 11 else 1
                        self.ball_capture_player = index
                        self.ball_capture_cooldown = 20
                        self.ball_release_player = index
                        self.ball_release_cooldown = 10
                        
                        self.ball[0:2] = self.positions[index]
                        self.ball[2:4] = deflect_dir * max(6.0, ball_speed * 0.7)
                        self.ball[4] = self.rng.uniform(1.0, 4.0)
                        
                        self.velocity[index] = np.zeros(2, dtype=float)
                        self.player_stun_cooldown[index] = 30 # Longer recovery for diving
                else:
                    # Goal...
                    self.velocity[index] = np.zeros(2, dtype=float)
                    self.player_stun_cooldown[index] = 45

    def step(self):
        self.step_count += 1
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

            closest_idx = int(np.argmin(distances))
            if distances[closest_idx] < self.possession_radius + 1.5:
                self._attempt_capture(closest_idx)

            if self.ball_event in {"pass", "cross", "shot", "throw_in"}:
                possesion = 1 if self.last_touch_team == 0 else -1

        else:
            if self.ball_controller >= 11:
                possesion = -1
            else:
                possesion = 1

        actions = []
        for i in range(22):
            if i == self.ball_capture_player and self.ball_capture_cooldown > 0:
                actions.append(None)
                continue

            j = 1
            if i >= 11:
                j = -1

            enemy_goal = self._goal_for_player(i)
            vec_to_goal = enemy_goal - self.positions[i]
            dist_to_goal = np.linalg.norm(vec_to_goal)
            past_halfspace = False
            if i < 11 and self.positions[i][1] > 50.0:
                past_halfspace = True
            elif i >= 11 and self.positions[i][1] < 50.0:
                past_halfspace = True

            opponents = self.positions[11:22] if i < 11 else self.positions[0:11]
            goal_vec = self._goal_for_player(i) - self.positions[i]
            goal_dir = goal_vec / (np.linalg.norm(goal_vec) + 1e-8)
            rel_vectors = opponents - self.positions[i]
            forward_scores = np.dot(rel_vectors, goal_dir)
            pressure_mask = (forward_scores > 0.0) & (np.linalg.norm(rel_vectors, axis=1) < 3.0)
            pressure_count = int(np.sum(pressure_mask))

            in_penalty_box = False
            if i < 11 and self.positions[i][1] > 82.0 and 14.0 < self.positions[i][0] < 56.0:
                in_penalty_box = True
            elif i >= 11 and self.positions[i][1] < 18.0 and 14.0 < self.positions[i][0] < 56.0:
                in_penalty_box = True

            state = {
                "has_ball": (self.ball_controller == i),
                "ball_pos": ball_pos,
                "ball_velocity": np.array(self.ball[2:4], dtype=float),
                "ball_height": float(self.ball[4]),
                "my_pos": self.positions[i],
                "my_velocity": self.velocity[i],
                "my_heading": self.heading[i],
                "dist_to_ball": distances[i],
                "dist_to_goal": dist_to_goal,
                "vec_to_goal": vec_to_goal,
                "enemy_goal": enemy_goal,
                "goal_target": enemy_goal,
                "a_direction": 1 if i < 11 else -1,
                "in_penalty_box": in_penalty_box,
                "in_attacking_box": in_penalty_box,
                "pressure_count": pressure_count,
                "teammates": self.positions[0:11] if i < 11 else self.positions[11:22],
                "opponents": opponents,
                "formation_pos": self.formation[i]["pos"],
                "team_possession": possesion * j,
                "past_halfspace": past_halfspace,
                "own_goal": np.array([35.0, 0.0]) if i < 11 else np.array([35.0, 100.0]),
                "must_pass_next": self.must_pass_next and self.must_pass_player == i and self.ball_controller == i,
                "is_loose": (self.ball_controller == -1),
                # 0-100. Available for player classes that want to pace
                # themselves; fatigue already slows movement regardless (see
                # _fatigue_factor).
                "stamina": float(self.stamina[i]),
                "rng": self.rng,
            }
            intended_action = self.all_players[i].step(state)
            actions.append(intended_action)

        resolve_order = np.argsort(distances)

        for i in resolve_order:
            self._resolve_action(int(i), actions[int(i)])

        # Charged after the actions land, so this step's cost reflects the
        # velocities those actions just set.
        self._drain_stamina()


def run_match(teamA, teamB, max_steps: int = 10800, fps: int = 60, render: bool = False, window_size=(1280, 800), title: str = "Packed Football", formation_home="4-4-2", formation_away="4-4-2"):
    match = game(teamA, teamB, formation_home=formation_home, formation_away=formation_away)
    return match.run_match(max_steps=max_steps, fps=fps, render=render, window_size=window_size, title=title)


  