from dataclasses import dataclass, asdict
import numpy as np

position = ["GK","CD","LB","RB","CDM","CM","CAM","LM","RM","CF","LW","RW"]

@dataclass
class Attributes: #out of 100, can be over

    #Physical attributes
    stamina: int = 60 ##kullanmıcam poc için
    speed: int = 60
    agility: int = 50
    passing: int = 50
    ballcontrol: int = 50
    defending: int = 50
    tackling: int = 70
    dribbiling: int = 30
    shooting: int = 50
    power: int = 80
    accuracy: int = 80
    vision:int = 60

    #Tendencies
    pass_tendency: int = 50
    shoot_tendency: int = 90
    drible_tendency: int = 60
    aggression: int = 40
    composure: int = 70
    clear_tendency:int = 10


class player:
    def __init__(self, fname, lname, position, attributes:Attributes = None):

        #cosmetic
        self.fname = fname
        self.lname = lname
        self.statistics = {"goals": 0,"assists":0,"matches_played": 0}

        #functional
        self.position = position
        if attributes is None:
            self.attributes = Attributes()
        else:
            self.attributes = attributes


    def getAttributes(self):
        return self.attributes

    #statistic updaters
    def scored(self):
        self.statistics["goals"]+=1
    def assisted(self):
        self.statistics["assists"]+=1
    def matchPlayed(self):
         self.statistics["matches_played"]+=1


    def _choose_pass_target(self, state: dict) -> np.ndarray:
        teammates = state["teammates"]
        opponents = state["opponents"]
        my_pos = state["my_pos"]
        
        pass_options = []
        
        for tm in teammates:
            if np.array_equal(tm, my_pos):
                continue
                
            vec_to_tm = tm - my_pos
            dist_to_tm = np.linalg.norm(vec_to_tm)      
            opp_dists_to_tm = np.linalg.norm(opponents - tm, axis=1)
            nearest_opp_dist = np.min(opp_dists_to_tm)
            
            raw_score = (nearest_opp_dist * 5.0) - (dist_to_tm * 0.5)
            
            if np.linalg.norm(state["enemy_goal"] - tm) < np.linalg.norm(state["enemy_goal"] - my_pos):
                raw_score += 15.0
                
            pressure_penalty = state["pressure_count"] * (100 - self.attributes.composure) / 10.0
            effective_vision = max(1.0, self.attributes.vision - pressure_penalty)
            error_variance = 200.0 / effective_vision 
            
            perceived_score = raw_score + np.random.normal(loc=0.0, scale=error_variance)
            pass_options.append((perceived_score, tm))
            
        pass_options.sort(key=lambda x: x[0], reverse=True)
        return pass_options[0][1]

    def _calculate_shot(self, state: dict) -> dict:
        goal_center_x = 35.0
        goal_y = 100.0 if state["a_direction"] == 1 else 0.0 
        
        aim_left = np.random.choice([True, False])
        target_x = 31.5 if aim_left else 38.5
        target_z = np.random.uniform(0.5, 2.0)
        
        intended_target = np.array([target_x, goal_y, target_z])
        base_error = (100.0 - self.attributes.shooting) / 15.0

        pressure_penalty = state["pressure_count"] * ((100.0 - self.attributes.composure) / 20.0)
        
        my_pos = state["my_pos"]
        vec_to_center = np.array([goal_center_x, goal_y]) - my_pos
        dist = np.linalg.norm(vec_to_center)
        unit_to_goal = vec_to_center / (dist + 0.001)
        facing_dot = np.dot(state["my_heading"], unit_to_goal)
        
        heading_penalty = max(0.0, (0.8 - facing_dot) * 5.0) 
        
        total_variance = base_error + pressure_penalty + heading_penalty
        
        actual_x = intended_target[0] + np.random.normal(0, total_variance)
        actual_z = intended_target[2] + np.random.normal(0, total_variance * 0.5) 
        actual_z = max(0.0, actual_z)
        
        final_target_3d = [actual_x, goal_y, actual_z]

        required_power = min(1.0, dist / 25.0)
        actual_power = required_power * (self.attributes.power / 100.0)
        
        return {
            "type": "shoot",
            "target_3d": final_target_3d,
            "power": actual_power
        }


    #action calculations
    def step(self, state: dict) -> dict:
        """
        state = {
            "has_ball": bool,
            "ball_pos": (x,y),
            "my_pos": (x,y),
            "my_velocity": (vx,vy),
            "my_heading": (hx,hy),
            "dist_to_ball": float,
            "dist_to_goal": float,
            "vec_to_goal": vec_to_goal,
            "in_penalty_box": bool
            "pressure_count": int
            "teammates": list(x,y)
            "opponents": list(x,y)
            "formation_pos": (x,y),
            "team_possession": -1,0,1; opp, noone, us
            "past_halfspace": bool
        }
        """
        
        if state["has_ball"]:
            if state["past_halfspace"]: # Enemy halfspace 
                actions = ["pass", "shoot", "dribble", "stop"]

                t_pass = self.attributes.pass_tendency
                t_shoot = self.attributes.shoot_tendency
                t_dribble = self.attributes.drible_tendency
                t_stop = 10

                dist_to_goal = state["dist_to_goal"]
                vec_to_goal = state["vec_to_goal"]
                unit_vec_to_goal = vec_to_goal / (dist_to_goal if dist_to_goal > 0 else 1.0)
                facing_goal = np.dot(state["my_heading"], unit_vec_to_goal)

                if state["in_attacking_box"]:
                    t_shoot *= 2.5 
                else:
                    t_shoot -= (dist_to_goal * 2.0) 
                
                if facing_goal < 0.0:
                    t_shoot *= 0.1 
                elif facing_goal > 0.8:
                    t_shoot *= 1.5

                if state["pressure_count"] > 1:
                    t_dribble -= (state["pressure_count"] * 25)
                    t_pass += (state["pressure_count"] * 20)
                    t_stop = 0 
                elif state["pressure_count"] == 0:
                    t_dribble += (self.attributes.speed * 0.5)
                    t_stop += 10
                    
                t_pass = max(5.0, t_pass)
                t_shoot = max(0.0, t_shoot) 
                t_dribble = max(1.0, t_dribble)
                t_stop = max(0.0, t_stop)

                total = t_pass + t_shoot + t_dribble + t_stop
                probs = [t_pass/total, t_shoot/total, t_dribble/total, t_stop/total]
                decision = np.random.choice(actions, p=probs)

                if decision == "shoot":
                    return self._calculate_shot()
                elif decision == "pass":
                    best_target = self._choose_pass_target(state)                
                    dist = np.linalg.norm(best_target - state["my_pos"])
                    required_power = min(1.0, dist / 4.0) 
                    actual_power = required_power * (self.attributes.passing / 100.0)
                    return {"type": "pass", "target": best_target, "power": actual_power}
                elif decision == "dribble":
                    return {"type": "move", "target": state["goal_target"], "speed_mod": self.attributes.dribbiling / 100.0}
                else: #stop
                    return None


            else: # Own halfspace
                actions = ["pass", "dribble", "stop", "clear"]

                t_pass = self.attributes.pass_tendency
                t_dribble = self.attributes.drible_tendency
                t_stop = 15.0
                t_clear = self.attributes.clear_tendency

                own_goal_y = 0.0 if state.get("a_direction", 1) == 1 else 100.0
                dist_to_own_goal = np.linalg.norm(np.array([35.0, own_goal_y]) - state["my_pos"])

                if dist_to_own_goal < 25.0:
                    t_clear *= 2.5
                    t_dribble *= 0.3 
                    
                if state.get("pressure_count", 0) > 1:
                    t_clear += (state["pressure_count"] * 40)
                    t_pass -= 20
                    t_dribble = 0
                    t_stop = 0
                elif state.get("pressure_count", 0) == 0:
                    t_clear *= 0.1
                    t_dribble += (self.attributes.speed * 0.5)
                    t_stop += 15

                t_pass = max(5.0, t_pass)
                t_dribble = max(1.0, t_dribble)
                t_clear = max(0.0, t_clear)
                t_stop = max(0.0, t_stop)

                total = t_pass + t_dribble + t_clear + t_stop
                probs = [t_pass/total, t_dribble/total, t_stop/total, t_clear/total]
                decision = np.random.choice(actions, p=probs)

                if decision == "clear":
                    forward_y = 100.0 if state.get("a_direction", 1) == 1 else 0.0
                    wide_x = np.random.choice([0.0, 70.0]) 
                    
                    target = np.array([wide_x + np.random.uniform(-15, 15), forward_y])
                    
                    actual_power = min(1.0, self.attributes.power / 80.0)
                    
                    return {"type": "pass", "target": target, "power": actual_power}
                        
                elif decision == "pass":
                    best_target = self._choose_pass_target(state)
                    dist = np.linalg.norm(best_target - state["my_pos"])
                    required_power = min(1.0, dist / 40.0) 
                    actual_power = required_power * (self.attributes.passing / 100.0)
                    return {"type": "pass", "target": best_target, "power": actual_power}
                    
                elif decision == "dribble":
                    enemy_goal_y = 100.0 if state.get("a_direction", 1) == 1 else 0.0
                    return {"type": "move", "target": np.array([35.0, enemy_goal_y]), "speed_mod": self.attributes.dribbiling / 100.0}
                    
                else: # stop
                    return None
                    
        elif state.get("team_possession") == 1:
            actions = ["forward_run", "support", "hold"]
            
            t_forward = self.attributes.shoot_tendency + (self.attributes.speed * 0.5)
            t_support = self.attributes.pass_tendency + 20.0
            t_hold = self.attributes.defending + 30.0

            forward_shift = 15.0 if state.get("a_direction", 1) == 1 else -15.0
            tactical_pos = np.array([state["formation_pos"][0], state["formation_pos"][1] + forward_shift])

            dist_to_ball = np.linalg.norm(state["ball_pos"] - state["my_pos"])
            dist_to_goal = state["dist_to_goal"]
            
            own_goal_y = 0.0 if state.get("a_direction", 1) == 1 else 100.0
            dist_to_own_goal = abs(state["formation_pos"][1] - own_goal_y)

            if dist_to_ball < 20.0:
                t_support *= 2.0 
                
            if dist_to_goal < 35.0:
                t_forward *= 1.5 
                
            if dist_to_own_goal < 30.0:
                t_hold *= 5.0 
                t_forward *= 0.1

            t_forward = max(0.0, t_forward)
            t_support = max(0.0, t_support)
            t_hold = max(1.0, t_hold)

            total = t_forward + t_support + t_hold
            probs = [t_forward/total, t_support/total, t_hold/total]
            decision = np.random.choice(actions, p=probs)

            if decision == "forward_run":
                enemy_goal_y = 100.0 if state.get("a_direction", 1) == 1 else 0.0
                run_target = np.array([state["my_pos"][0], enemy_goal_y])
                return {"type": "move", "target": run_target, "speed_mod": (self.attributes.speed * 0.9) / 100.0}
                
            elif decision == "support":
                vec_to_ball = state["ball_pos"] - state["my_pos"]
                support_target = state["my_pos"] + (vec_to_ball * 0.5)
                return {"type": "move", "target": support_target, "speed_mod": (self.attributes.speed * 0.7) / 100.0}
                
            else:
                return {"type": "move", "target": tactical_pos, "speed_mod": (self.attributes.speed * 0.5) / 100.0}
                
        elif state.get("team_possession") == -1:
            # Defending / Loose Ball (team_possession == -1 or 0)
            dist_to_ball = np.linalg.norm(state["ball_pos"] - state["my_pos"])
            press_chance = getattr(self.attributes, "aggression", 40)
            
            # The whole formation drops back slightly when defending
            backward_shift = -10.0 if state.get("a_direction", 1) == 1 else 10.0
            defensive_pos = np.array([state["formation_pos"][0], state["formation_pos"][1] + backward_shift])
            
            if dist_to_ball < 15.0 and np.random.randint(0, 100) < press_chance:
                # Sprint to close down the ball carrier
                return {"type": "move", "target": state["ball_pos"], "speed_mod": (self.attributes.speed * 0.9) / 100.0}
            else:
                # Drift back into defensive shape
                return {"type": "move", "target": defensive_pos, "speed_mod": (self.attributes.speed * 0.6) / 100.0}




    ##visual stuff
    def __str__(self):
        attributes_str = ""
        for aname,aval in asdict(self.attributes).items():
            attributes_str += f"{aname}: {aval}\n"  

        return f"""*** {self.fname} {self.lname} *** 
        Matches Played = {self.statistics.get("matches_played")}
        Goals = {self.statistics.get("goals")}
        Assists = {self.statistics.get("assists")}
        
        *** Attributes ***
        {attributes_str}
        ------------------------
        """

    def __repr__(self):
        return f"Player({self.fname} {self.lname}, {self.position})"


class goalkeeper(player):
    pass