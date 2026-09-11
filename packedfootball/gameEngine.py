import numpy as np
from typing import Final

from replay import ActionType, ReplayRecorder

PITCH_WIDTH: Final[float] = 70.0
PITCH_HEIGHT: Final[float] = 100.0
GOAL_WIDTH: Final = 7.5
GOAL_HEIGHT: Final = 2.5
base_kick_pow:Final = 20
base_speed:Final = 10.0
possession_radius: Final = 2.0
final_whistle_delay: Final = 600

# formations.py imports PITCH_WIDTH/PITCH_HEIGHT from this module, so this
# import must come after they're defined above to avoid a circular-import
# failure (formations.py is mid-import of a still-partial gameEngine module).
from formations import get_formation


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

        self.all_players = self.teamA.players + self.teamB.players

        self.positions = np.zeros((22,2),float) # (x,y) pairs
        self.velocity = np.zeros((22,2),float) # (vx,vy) pairs

        self.heading = np.zeros((22,2),float) # (hx,hy) pairs
        self.heading[0:11] = [0.0, 1.0] 
        self.heading[11:22] = [0.0, -1.0] 

        self.ball = np.array([35.0, 50.0, 0.0, 0.0, 0.0,],float) # (x,y,vx,vy,vz)
        self.scores = [0, 0]
        self.last_goal_team = None
       
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
        self.camera_mode = "zoom" 
        self.visual_action = [""] * 22
        self.visual_action_timer = np.zeros(22, dtype=int)
        self.final_whistle_clock = 0
        self.halftime_pause_timer = 0
        # self.camera_flipped = False TODO
        
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

    def _begin_restart(self, restart_type: str, team: int | None = None, out_x: float = 35.0):
        self.out_of_play = True
        self.restart_type = restart_type
        self.restart_team = team if team is not None else (0 if self.last_touch_team is None else 1 - self.last_touch_team)
        self.restart_timer = 30
        self.ball_controller = -1
        self.ball_release_player = -1
        self.ball_release_cooldown = 0
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
            throw_player = self._pick_role_slot(self.restart_team, ("LM", "RM", "LW", "RW", "WB", "CDM"), 5)
            self.restart_player = throw_player
            self.ball[:] = [self.positions[throw_player][0], self.positions[throw_player][1], 0.0, 0.0, 0.0]
            self.ball_controller = throw_player
            self._set_must_pass_for_player(throw_player)

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
        

    def run_match(self, max_steps: int = 10800, fps: int = 60, render: bool = False, window_size=(700, 1000), title: str = "Packed Football"):
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

        steps = 0
        while running and steps < max_steps:
            # --- Trigger Halftime ---
            if steps == max_steps // 2:
                self.goal_popup = {"text": "HALF TIME", "timer": 180, "team": None}
                self.halftime_pause_timer = 180
                self.reset_positions(restart_type="kickoff", team=1)
                if self.replay:
                    self.replay.event(self.match_clock_frames, ActionType.HALFTIME)
                    self.replay.event(self.match_clock_frames, ActionType.KICKOFF, team=1)
                # self.camera_flipped = True TODO

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

            steps += 1

        if self.replay:
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

        if self.ball[0] < 0.0 or self.ball[0] > PITCH_WIDTH or self.ball[1] < 0.0 or self.ball[1] > PITCH_HEIGHT:
            out_x = self.ball[0]  # Store out-of-bounds X coordinate to determine which corner flag to use
            
            if self.ball[1] < 0.0 or self.ball[1] > PITCH_HEIGHT:
                # Goal bounds check
                if 35.0 - GOAL_WIDTH / 2.0 <= self.ball[0] <= 35.0 + GOAL_WIDTH / 2.0:
                    restart_type = "kickoff"
                    restart_team = 1 - (self.last_touch_team if self.last_touch_team is not None else 0)
                else:
                    # Endline bounds check (Corner vs Goal Kick based on last touch)
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

            # Pass out_x to the restart method
            self._begin_restart(restart_type, restart_team, out_x)
            return

        self.ball[0] = np.clip(self.ball[0], 0.0, PITCH_WIDTH)
        self.ball[1] = np.clip(self.ball[1], 0.0, PITCH_HEIGHT)

        self._check_goal()

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

    def _check_goal(self):
        goal_top_y = 0.0
        goal_bottom_y = PITCH_HEIGHT
        goal_x_min = PITCH_WIDTH/2 - GOAL_WIDTH / 2.0
        goal_x_max = PITCH_WIDTH/2 + GOAL_WIDTH / 2.0
        ball_x = self.ball[0]
        ball_y = self.ball[1]

        if ball_x >= goal_x_min and ball_x <= goal_x_max:
            if ball_y <= goal_top_y + 0.8:
                scoring_team = 1 
            elif ball_y >= goal_bottom_y - 0.8:
                scoring_team = 0 
            else:
                return False

            self.scores[scoring_team] += 1
            self.last_goal_team = scoring_team
            self.ball_controller = -1
            
            # --- Evaluate Goal & Assist Statistics ---
            scorer_name = "Own Goal"
            if self.last_touch_player != -1:
                touch_team = 0 if self.last_touch_player < 11 else 1
                if touch_team == scoring_team:
                    scorer = self.all_players[self.last_touch_player]
                    scorer.scored()
                    scorer_name = scorer.lname
                    
                    if self.assist_candidate != -1:
                        assister = self.all_players[self.assist_candidate]
                        assister.assisted()
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

            return True
            
        return False

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
                self.velocity[index] = self.heading[index] * (base_speed * action["speed_mod"])
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

                if self.kickoff_pass_player == index:
                    px, py = self.positions[index]
                    if (px <= 5.0 or px >= PITCH_WIDTH - 5.0) and (py <= 5.0 or py >= PITCH_HEIGHT - 5.0):
                        pass_type = "cross"

                power = base_kick_pow * action["power"]
                aerial = False
                if pass_type == "clearance":
                    aerial = True
                    power *= 1.2
                elif pass_type == "cross":
                    aerial = True
                    power *= 1.15
                elif pass_type == "throw_in":
                    aerial = False
                    power *= 0.8

                self.visual_action[index] = pass_type
                self.visual_action_timer[index] = 15
                if self.replay:
                    pass_event = {"normal": ActionType.PASS, "clearance": ActionType.CLEARANCE, "cross": ActionType.CROSS}.get(
                        pass_type, ActionType.PASS
                    )
                    self.replay.event(self.match_clock_frames, pass_event, player_idx=index, team=0 if index < 11 else 1)
                self._release_ball(index, unit_vec, power, aerial=aerial, event_type="pass")

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

                if self.rng.random() < steal_chance:
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
                
                save_stat = (gk_attrs.agility * 0.6) + (gk_attrs.vision * 0.4)
                save_chance = float(np.clip(0.20 + (save_stat / 100.0) * 0.60, 0.10, 0.95))
                
                if self.rng.random() < save_chance:
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
                "rng": self.rng,
            }
            intended_action = self.all_players[i].step(state)
            actions.append(intended_action)

        resolve_order = np.argsort(distances)

        for i in resolve_order:
            self._resolve_action(int(i), actions[int(i)])


def run_match(teamA, teamB, max_steps: int = 10800, fps: int = 60, render: bool = False, window_size=(1280, 800), title: str = "Packed Football", formation_home="4-4-2", formation_away="4-4-2"):
    match = game(teamA, teamB, formation_home=formation_home, formation_away=formation_away)
    return match.run_match(max_steps=max_steps, fps=fps, render=render, window_size=window_size, title=title)


  