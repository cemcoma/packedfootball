import numpy as np
import scipy as sp
from typing import Final

PITCH_WIDTH: Final[float] = 70.0
PITCH_HEIGHT: Final[float] = 100.0



class game:
    def __init__(self, teamA, teamB):

        self.teamA = teamA # name, players
        self.teamB = teamB

        self.positions = np.zeros((22,2),float) # (x,y) pairs
        self.velocity = np.zeros((22,2),float) # (vx,vy) pairs

        self.heading = np.zeros((22,2),float) # (hx,hy) pairs
        self.heading[0:11] = [0.0, 1.0] 
        self.heading[11:22] = [0.0, -1.0] 

        self.ball = np.array([35.0, 50.0, 0.0, 0.0, 0.0],float) # (x,y,vx,vy,vz)


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
        # 1. Update all 22 player positions simultaneously
        self.positions += self.velocity * dt

        # 2. Keep players strictly inside the pitch boundaries
        self.positions[:, 0] = np.clip(self.positions[:, 0], 0.0, PITCH_WIDTH)
        self.positions[:, 1] = np.clip(self.positions[:, 1], 0.0, PITCH_HEIGHT)

        # 3. Update ball position (x, y) using its velocity (vx, vy)
        self.ball[0] += self.ball[2] * dt
        self.ball[1] += self.ball[3] * dt

        # 4. Apply ground friction to the ball (e.g., velocity decays over time)
        # 0.5 decay means it loses half its speed per second
        friction = 0.5 ** dt
        self.ball[2] *= friction
        self.ball[3] *= friction

        # 5. Stop the ball completely if moving infinitesimally slow (prevents floating-point sliding)
        if abs(self.ball[2]) < 0.1: self.ball[2] = 0.0
        if abs(self.ball[3]) < 0.1: self.ball[3] = 0.0

        # 6. Clamp ball boundaries (For a real engine, you'd trigger a Throw-In/Goal Kick event here instead of clipping)
        self.ball[0] = np.clip(self.ball[0], 0.0, PITCH_WIDTH)
        self.ball[1] = np.clip(self.ball[1], 0.0, PITCH_HEIGHT)
        

    def step(self):
        ball_pos = self.ball[0:2]

        direction_vectors = ball_pos - self.positions
        distances = np.linalg.norm(direction_vectors, axis=1, keepdims=True)
        safe_distances = np.where(distances == 0, 1.0, distances)
        unit_directions = direction_vectors / safe_distances

       
  