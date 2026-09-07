import numpy as np
from typing import Final

import packedfootball.player as player


PITCH_WIDTH: Final[float] = 70.0
PITCH_HEIGHT: Final[float] = 100.0
GOAL_WIDTH: Final = 7.5
GOAL_HEIGHT: Final = 2.5
base_kick_pow:Final = 40
base_speed:Final = 10.0
ball_capture_cooldown:Final = 10.0

formation = { ##442 için fix sadece 
        0:[35.0, 5.0],   # GK

        1:[12.0, 20.0],  # LB
        2:[27.0, 15.0],  # LCB
        3:[43.0, 15.0],  # RCB
        4:[58.0, 20.0],  # RB

        5:[12.0, 40.0],  # LM
        6:[27.0, 35.0],  # LCM
        7:[43.0, 35.0],  # RCM
        8:[58.0, 40.0],  # RM

        9:[27.0, 52.0],  # LS
        10:[43.0, 52.0], # RS

        11:[35.0, 95.0], # GK

        12:[58.0, 80.0], # LB 
        13:[43.0, 85.0], # LCB
        14:[27.0, 85.0], # RCB
        15:[12.0, 80.0], # RB

        16:[58.0, 60.0], # LM
        17:[43.0, 65.0], # LCM
        18:[27.0, 65.0], # RCM
        19:[12.0, 60.0], # RM

        20:[43.0, 48.0], # LS
        21:[27.0, 48.0] # RS
}

class game:
    def __init__(self, teamA, teamB):

        self.teamA = teamA # name, players
        self.teamB = teamB

        self.all_players = self.teamA.players + self.teamB.players

        self.positions = np.zeros((22,2),float) # (x,y) pairs
        self.velocity = np.zeros((22,2),float) # (vx,vy) pairs

        self.heading = np.zeros((22,2),float) # (hx,hy) pairs
        self.heading[0:11] = [0.0, 1.0] 
        self.heading[11:22] = [0.0, -1.0] 

        self.ball = np.array([35.0, 50.0, 0.0, 5.0, 0.0,],float) # (x,y,vx,vy,vz)
        self.scores = [0, 0]
        self.last_goal_team = None
       
        self.ball_controller = -1  # -1 indicates a loose ball. 0-21 corresponds to the player index currently in possession.
        
        self.possession_radius = 1
        self.player_radius = 1.25
        self.step_count = 0
        self.debug_decisions = []
        self.ball_release_cooldown = 0
        self.ball_release_player = -1
        self.ball_capture_cooldown = 0
        self.ball_capture_player = -1
        self.player_stun_cooldown = np.zeros(22, dtype=int)

        #### ILLEGAL SHIT JUST POC 442 formation for both, future will have customizable formations (strategy dp) TODO

        self.positions[0] = [35,00]

        self.positions[1] = [15,30]
        self.positions[2] = [30,30]
        self.positions[3] = [40,30]
        self.positions[4] = [55,30]
        self.positions[5] = [15,40]

        self.positions[6] = [30,40]
        self.positions[7] = [40,40]
        self.positions[8] = [55,40]

        self.positions[9] = [35,43]
        self.positions[10] = [35,46]


        self.positions[11] = [35, 100]

        self.positions[12] = [15, 70]
        self.positions[13] = [30, 70]
        self.positions[14] = [40, 70]
        self.positions[15] = [55, 70]

        self.positions[16] = [15, 60]
        self.positions[17] = [30, 60]
        self.positions[18] = [40, 60]
        self.positions[19] = [55, 60]

        self.positions[20] = [32, 55]
        self.positions[21] = [38, 55]

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

    def render(self, screen, window_size=(700, 1000)):
        try:
            import pygame
        except ImportError as exc: 
            raise RuntimeError("pygame is required for rendering. Install it with: pip install pygame") from exc

        width, height = window_size
        scale_x = width / PITCH_WIDTH
        scale_y = height / PITCH_HEIGHT

        # Grass Background
        pygame.draw.rect(screen, (22, 120, 55), (0, 0, width, height))

        # Pitch Outlines
        pygame.draw.rect(screen, (255, 255, 255), (0, 0, width, height), 2)
        
        # Halfway Line
        pygame.draw.line(screen, (255, 255, 255), (0, height / 2), (width, height / 2), 2)
        
        # Center Circle and Center Spot
        pygame.draw.circle(screen, (255, 255, 255), (int(width / 2), int(height / 2)), int(9.15 * scale_x), 2)
        pygame.draw.circle(screen, (255, 255, 255), (int(width / 2), int(height / 2)), 3)

        # Top Penalty Box (Engine expects X: 14 to 56, Y: 0 to 18)
        pygame.draw.rect(screen, (255, 255, 255), (14 * scale_x, 0, 42 * scale_x, 18 * scale_y), 2)
        # Top 6-Yard Box
        pygame.draw.rect(screen, (255, 255, 255), (26 * scale_x, 0, 18 * scale_x, 5.5 * scale_y), 2)
        # Top Goal (X: 31.25 to 38.75)
        pygame.draw.rect(screen, (200, 200, 200), (31.25 * scale_x, 0, 7.5 * scale_x, 2 * scale_y))

        # Bottom Penalty Box (Engine expects X: 14 to 56, Y: 82 to 100)
        pygame.draw.rect(screen, (255, 255, 255), (14 * scale_x, 82 * scale_y, 42 * scale_x, 18 * scale_y), 2)
        # Bottom 6-Yard Box
        pygame.draw.rect(screen, (255, 255, 255), (26 * scale_x, 94.5 * scale_y, 18 * scale_x, 5.5 * scale_y), 2)
        # Bottom Goal
        pygame.draw.rect(screen, (200, 200, 200), (31.25 * scale_x, height - (2 * scale_y), 7.5 * scale_x, 2 * scale_y))

        # Players
        for idx, pos in enumerate(self.positions):
            x = int(pos[0] * scale_x)
            y = int(pos[1] * scale_y)
            color = (50, 130, 255) if idx < 11 else (255, 90, 90)
            
            radius = 6
            if self.ball_controller == idx:
                radius = 8
                pygame.draw.circle(screen, (255, 255, 255), (x, y), radius + 2, 2)
            pygame.draw.circle(screen, color, (x, y), radius)

            # Heading Indicator
            heading = self.heading[idx]
            if np.linalg.norm(heading) > 0:
                heading = heading / np.linalg.norm(heading)
                end_x = int((pos[0] + heading[0] * 1.5) * scale_x)
                end_y = int((pos[1] + heading[1] * 1.5) * scale_y)
                pygame.draw.line(screen, (255, 255, 255), (x, y), (end_x, end_y), 2)

            # Player Numbers
            font = pygame.font.SysFont(None, 14)
            label = font.render(str(idx), True, (0, 0, 0))
            screen.blit(label, (x - 5, y - 4))

        # Ball (White with black outline for visibility)
        bx = int(self.ball[0] * scale_x)
        by = int(self.ball[1] * scale_y)
        
        # Simulate height (Z-axis) by expanding the ball slightly when in the air
        z_bonus = max(0, int(self.ball[4] * 0.5))
        pygame.draw.circle(screen, (255, 255, 255), (bx, by), 4 + z_bonus)
        pygame.draw.circle(screen, (0, 0, 0), (bx, by), 4 + z_bonus, 1)

    def run_match(self, max_steps: int = 3000, fps: int = 60, render: bool = False, window_size=(700, 1000), title: str = "Packed Football"):
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
            if render:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                        break

            self.step()
            self.tick(dt)

            if render:
                screen.fill((0, 0, 0))
                self.render(screen, window_size)
                pygame.display.flip()
                clock.tick(fps)

            steps += 1

        if render:
            pygame.quit()

        return self

    def tick(self, dt:float = 1/60):
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

        self.ball[0] = np.clip(self.ball[0], 0.0, PITCH_WIDTH)
        if self.ball[1] < -1.0 or self.ball[1] > PITCH_HEIGHT + 1.0:
            self.ball[1] = np.clip(self.ball[1], 0.0, PITCH_HEIGHT)
        else:
            self.ball[1] = np.clip(self.ball[1], 0.0, PITCH_HEIGHT)

        self._check_goal()

    def _capture_success_probability(self, rep_idx: int, ball_speed: float, ball_height: float) -> float:
        player_attr = self.all_players[rep_idx].attributes

        base = 0.90
        speed_penalty = min(0.75, ball_speed / 12.0)
        height_penalty = min(0.70, max(0.0, ball_height) / 3.0)
        agility_bonus = (player_attr.agility / 100.0) * 0.35
        control_bonus = (player_attr.ballcontrol / 100.0) * 0.25
        defending_bonus = (player_attr.defending / 100.0) * 0.20

        probability = base - speed_penalty - height_penalty + agility_bonus + control_bonus + defending_bonus
        return float(np.clip(probability, 0.05, 0.95))

    def _attempt_capture(self, index: int) -> bool:
        if self.ball_controller == index:
            return True

        if self.ball_release_player >= 0 and self.ball_release_cooldown > 0:
            release_team = 0 if self.ball_release_player < 11 else 1
            current_team = 0 if index < 11 else 1
            if release_team == current_team:
                return False

        dist_to_ball = np.linalg.norm(self.ball[0:2] - self.positions[index])
        if dist_to_ball > self.possession_radius + 1.5:
            return False

        ball_speed = float(np.linalg.norm(self.ball[2:4]))
        ball_height = max(0.0, float(self.ball[4]))
        success_chance = self._capture_success_probability(index, ball_speed, ball_height)

        if np.random.random() < success_chance:
            self.ball_controller = index
            self.ball_capture_player = index
            self.ball_capture_cooldown = int(10 + max(0.0, ball_height * 6.0))
            self.ball[0:2] = self.positions[index]
            self.ball[2:4] = self.velocity[index]
            self.ball[4] = 0.0
            if ball_height > 0.5:
                self.velocity[index] *= 0.65
            return True

        self.ball_capture_player = index
        self.ball_capture_cooldown = int(18 + max(0.0, ball_height * 12.0))
        if ball_height > 0.5:
            self.velocity[index] *= 0.5
            self.velocity[index] -= self.heading[index] * 0.6
        else:
            self.velocity[index] *= 0.85
        return False

    def _goal_for_player(self, player_index: int) -> np.ndarray:
        return np.array([35.0, 100.0]) if player_index < 11 else np.array([35.0, 0.0])

    def _check_goal(self):
        goal_top_y = 0.0
        goal_bottom_y = PITCH_HEIGHT
        goal_x_min = 35.0 - GOAL_WIDTH / 2.0
        goal_x_max = 35.0 + GOAL_WIDTH / 2.0
        ball_x = self.ball[0]
        ball_y = self.ball[1]

        if ball_x >= goal_x_min and ball_x <= goal_x_max:
            if ball_y <= goal_top_y + 0.8:
                self.scores[1] += 1
                self.last_goal_team = 1
                self.ball_controller = -1
                self.ball[:] = [35.0, 50.0, 0.0, 0.0, 0.0]
                return True
            if ball_y >= goal_bottom_y - 0.8:
                self.scores[0] += 1
                self.last_goal_team = 0
                self.ball_controller = -1
                self.ball[:] = [35.0, 50.0, 0.0, 0.0, 0.0]
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

    def _release_ball(self, owner_index: int, direction: np.ndarray, launch_speed: float, aerial: bool = False):
        direction = np.asarray(direction, dtype=float)
        direction_norm = np.linalg.norm(direction)
        if direction_norm < 1e-8:
            direction = np.array([1.0, 0.0], dtype=float)
            direction_norm = 1.0
        direction = direction / direction_norm

        self.ball_controller = -1
        self.ball_release_player = owner_index

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

                unit_vec = vec / dist
                self._release_ball(index, unit_vec, base_kick_pow * action["power"], aerial=False)

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
                self._release_ball(index, unit_vec_3d[:2], shot_speed, aerial=aerial)
                self.ball[2] = unit_vec_3d[0] * shot_speed
                self.ball[3] = unit_vec_3d[1] * shot_speed
                self.ball[4] = abs(unit_vec_3d[2]) * shot_speed

        elif action_type == "tackle":
            if self.ball_controller == -1 or self.ball_controller == index:
                return

            holder_idx = self.ball_controller
            dist = np.linalg.norm(self.positions[index] - self.positions[holder_idx])
            if dist <= 2.0:
                steal_chance = min(1.0, max(0.0, action["stat"] / 100.0))
                if np.random.random() < steal_chance:
                    tackle_vector = self.positions[index] - self.positions[holder_idx]
                    tackle_vector_norm = np.linalg.norm(tackle_vector)
                    if tackle_vector_norm < 1e-8:
                        tackle_vector = self.heading[index]
                        tackle_vector_norm = np.linalg.norm(tackle_vector)
                    if tackle_vector_norm < 1e-8:
                        tackle_vector = np.array([1.0, 0.0])
                        tackle_vector_norm = 1.0

                    unit_vec = tackle_vector / tackle_vector_norm
                    launch_power = base_kick_pow * (0.25 + (action["stat"] / 100.0) * 0.75)

                    self._release_ball(holder_idx, unit_vec, launch_power, aerial=(launch_power > 15.0 or abs(unit_vec[1]) > 0.7))
                    self.velocity[index] = np.zeros(2, dtype=float)
                    self.velocity[holder_idx] = np.zeros(2, dtype=float)
                    self.player_stun_cooldown[index] = 20
                    self.player_stun_cooldown[holder_idx] = 20

        elif action_type == "capture":
            if self.ball_release_player == index and self.ball_release_cooldown > 0:
                return
            self._attempt_capture(index)

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

        if self.ball_release_player >= 0 and self.ball_release_cooldown > 0 and self.ball_controller == self.ball_release_player:
            self.ball_controller = -1

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
        else:
            if self.ball_controller > 11:
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
                "formation_pos": formation[i],
                "team_possession": possesion * j,
                "past_halfspace": past_halfspace,
                "own_goal": np.array([35.0, 0.0]) if i < 11 else np.array([35.0, 100.0]),
            }
            intended_action = self.all_players[i].step(state)
            actions.append(intended_action)

        controller_action = None
        if 0 <= self.ball_controller < len(actions):
            controller_action = actions[self.ball_controller]
            self.debug_decisions.append({
                "step": self.step_count,
                "ball_controller": self.ball_controller,
                "decision": controller_action,
            })
            print(f"[STEP {self.step_count}] ball_controller={self.ball_controller} -> {controller_action}")
        else:
            self.debug_decisions.append({
                "step": self.step_count,
                "ball_controller": self.ball_controller,
                "decision": None,
            })
            print(f"[STEP {self.step_count}] ball_controller={self.ball_controller} -> no controller action")

        for i, action in enumerate(actions):
            self._resolve_action(i, action)

        if self.ball_controller == -1:
            candidate_distances = np.linalg.norm(self.ball[0:2] - self.positions, axis=1)
            if self.ball_release_player >= 0 and self.ball_release_cooldown > 0:
                candidate_distances[self.ball_release_player] = np.inf
                release_zone = np.linalg.norm(self.positions - self.positions[self.ball_release_player], axis=1) < 5.0
                candidate_distances[release_zone] = np.inf

            closest_idx = int(np.argmin(candidate_distances))
            if candidate_distances[closest_idx] < self.possession_radius + 1.5:
                self._attempt_capture(closest_idx)
        elif self.ball_controller >= 0:
            self.ball[0:2] = self.positions[self.ball_controller]
            self.ball[2:4] = self.velocity[self.ball_controller]
            self.ball[4] = 0.0


def run_match(teamA, teamB, max_steps: int = 3000, fps: int = 60, render: bool = False, window_size=(1000, 700), title: str = "Packed Football"):
    match = game(teamA, teamB)
    return match.run_match(max_steps=max_steps, fps=fps, render=render, window_size=window_size, title=title)


  