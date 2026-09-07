import numpy as np
import player
from typing import Final

PITCH_WIDTH: Final[float] = 70.0
PITCH_HEIGHT: Final[float] = 100.0
GOAL_WIDTH: Final = 7.5
GOAL_HEIGHT: Final = 2.5
base_kick_pow:Final = 20
base_speed:Final = 5.0

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

        self.ball = np.array([35.0, 50.0, 0.0, 0.0, 0.0,],float) # (x,y,vx,vy,vz)
       
        self.ball_controller = -1  # -1 indicates a loose ball. 0-21 corresponds to the player index currently in possession.
        
        self.possession_radius = 0.5 #how close a player needs to be to claim a loose ball


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

        self.positions[9] = [35,45]
        self.positions[10] = [35,50]


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

    def tick(self, dt:float = 1/60):
        self.positions += self.velocity * dt

        self.positions[:, 0] = np.clip(self.positions[:, 0], 0.0, PITCH_WIDTH) 
        self.positions[:, 1] = np.clip(self.positions[:, 1], 0.0, PITCH_HEIGHT)

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
        self.ball[1] = np.clip(self.ball[1], 0.0, PITCH_HEIGHT)
        

    def step(self):
        ball_pos = self.ball[0:2]
        
        direction_vectors = ball_pos - self.positions
        distances = np.linalg.norm(direction_vectors, axis=1)

        possesion:int = 0
        if self.ball_controller == -1:
            closest_idx = np.argmin(distances)
            if distances[closest_idx] < self.possession_radius:
                self.ball_controller = closest_idx
        else:
            if self.ball_controller > 11 :
                possesion = -1
            else:
                possesion = 1

       
        actions = []
        for i in range(22):
            j = 1
            if i > 11:
                j = -1
        
            enemy_goal = np.array([35.0, 100.0] if i < 11 else [35.0, 0.0])
            vec_to_goal = enemy_goal - self.positions[i]
            dist_to_goal = np.linalg.norm(vec_to_goal)
            past_halfspace = False
            if i < 11 and self.positions[i][1] > 50.0: # Team A attacking North
                past_halfspace = True
            elif i >= 11 and self.positions[i][1] < 50.0: # Team B attacking South
                past_halfspace = True

            opponents = self.positions[11:22] if i < 11 else self.positions[0:11]
            pressure_dists = np.linalg.norm(opponents - self.positions[i], axis=1)
            pressure_count = np.sum(pressure_dists < 3.0) 

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
                "in_penalty_box": in_penalty_box,
                "pressure_count": pressure_count, # Int: 0 means open, 2+ means heavily marked
                "teammates": self.positions[0:11] if i < 11 else self.positions[11:22],
                "opponents": opponents,
                "formation_pos": formation[i],
                "team_possession": possesion * j,
                "past_halfspace":past_halfspace
            }
            intended_action = self.all_players[i].step(state)
            actions.append(intended_action)



        for i, action in enumerate(actions):
            if not action: 
                continue
                
            if action["type"] == "move":
                target = np.array(action["target"])
                vec = target - self.positions[i]
                dist = np.linalg.norm(vec)
                
                if dist > 0.1: # Prevent division by zero
                    unit_vec = vec / dist
                    # Base speed is 5.0 m/s, modified by player's speed attribute
                    self.velocity[i] = unit_vec * (5.0 * action["speed_mod"]) 
                else:
                    self.velocity[i] = [0.0, 0.0]
                    
            elif action["type"] == "pass":
                # Ensure the player actually has the ball before letting them shoot/pass
                if self.ball_controller == i:
                    target = np.array(action["target"])
                    vec = target - self.positions[i]
                    unit_vec = vec / np.linalg.norm(vec)
                    
                    # Release the ball and apply power
                    self.ball_controller = -1
                   
                    self.ball[2:4] = unit_vec * (base_kick_pow * action["power"])
            elif action["type"] == "shoot":
                if self.ball_controller == i:
                    target_3d = np.array(action["target_3d"])
                    
                    # Current ball position in 3D
                    ball_pos_3d = np.array([self.ball[0], self.ball[1], 0.0])
                    
                    # Calculate 3D unit vector
                    vec_3d = target_3d - ball_pos_3d
                    dist_3d = np.linalg.norm(vec_3d)
                    unit_vec_3d = vec_3d / dist_3d
                    
                    self.ball_controller = -1
                    
                    shot_speed = base_kick_pow * action["power"]
                    
                    self.ball[2] = unit_vec_3d[0] * shot_speed
                    self.ball[3] = unit_vec_3d[1] * shot_speed
                    self.ball[4] = unit_vec_3d[2] * shot_speed

       
  