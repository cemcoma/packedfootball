from player.player import _clamp, _ball_pressure, _count_within, _dists, _pick, _norm2, player, ActionProfile, OFFSIDE_MARGIN, GOAL_SIDE_PRESS, GOAL_SIDE_CONTAIN
from game_config import PRESS_FROM_DEFENDING, RECOVERY_CB_LANE, RECOVERY_MIN_DEPTH, RECOVERY_PRESS_RANGE, RECOVERY_RANGE, pass_power, PITCH_HEIGHT, PITCH_WIDTH, pace_ability, stat_ability
import numpy as np

# Where a full-back stands in to cover the middle when no centre-back is
# home (state["cb_home"] is False): this far off their own goal line, this
# far either side of the centre, on the side their flank is. Deep enough
# to be between a lone striker and the goal, not so deep the whole side
# collapses onto the six-yard box.
# How far ahead of his man a marker positions himself.
MARK_LEAD_SECONDS = 0.35

COVER_DEPTH = 22.0
COVER_HALF_GAP = 7.0
COVER_ROLES = ("LB", "RB", "LWB", "RWB")

# A full-back off the ball holds the back line (_back_line_target): level with the
# centre-backs, tucking in toward the far post -- a third CB -- as the ball nears his goal.
FB_ROLES = ("LB", "RB")
FB_LINE_BALL_GAP = 10.0     # with no centre-backs to hold a line with, this far goal-side of the ball
FB_WIDTH_FAR = 19.0         # off the middle with the ball upfield...
FB_WIDTH_NEAR = 11.0        # ...and fully tucked in with it near his goal
FB_TUCK_FROM = 60.0         # ball depth where the tuck starts
FB_TUCK_TO = 30.0           # ...and where it is complete
FB_BALL_SHIFT = 0.35        # the line slides this much toward the ball's side
FB_FLANK_X = 8.0            # the ball is on his flank past this, off the middle
FB_ENGAGE_RANGE = 6.0       # off his flank, he only goes at a ball this close

# The ball-side full-back overlaps once a teammate has it on his flank OVERLAP_FROM off our
# goal: OVERLAP_LEAD ahead of the ball, outside the carrier -- or inside him (the underlap)
# when the carrier is on the line. The far full-back stays home.
OVERLAP_FROM = 40.0
OVERLAP_LEAD = 8.0
OVERLAP_ROOM = 8.0          # carrier closer than this to the touchline: go inside him
OVERLAP_INSIDE_X = 12.0     # the underlap channel, this far in from the touchline
OVERLAP_CHANCE = 0.15       # per decision while it is on; latched once he goes
OVERLAP_SPRINT = 1.3        # it is a sprint: he has to get past the ball
FB_ATTACK_TRAIL = 12.0      # with the ball on his side he holds this far behind it...
FB_ATTACK_LIMIT = 35.0      # ...up to this far up from his slot

# Off the ball, the back line holds at DEF_LINE_SHARE of the ball's depth, not on its formation
# slot (half a pitch behind play with the ball upfield) -- never past DEF_LINE_MAX, beyond which
# a centre-back no longer counts as home (gameEngine.CB_HOME_DEPTH) and the full-backs tuck in.
DEF_LINE_SHARE = 0.5
DEF_LINE_MAX = 38.0

# A centre-back on the man with the ball holds at the edge of his box, CB_STAND_DEPTH off goal:
# he does not back off into it, and steps out of it to meet a man still outside -- a foul there
# is a free kick, not a penalty. Beaten, the recovery run takes over.
CB_STAND_DEPTH = 22.0

class CenterBackActionProfile(ActionProfile):
    role_name = "center_back"
    allowed_actions = {
        "stop", "pass", "clear", "dribble", "forward_run",
        "support", "hold_attack", "hold_defense", "press",
        "contain", "recover", "recover_slow", "tackle", "capture",
        "man_mark"
    }
    action_biases = {
        "pass": 0.8, "clear": 0.8, "dribble": 0.2, "cross": 0.1,
        "forward_run": 0.2, "support": 0.5, "hold_attack": 0.3,
        "hold_defense": 1.8, "press": 1.0, "contain": 1.5,
        "recover": 1.3, "tackle": 1.5, "capture": 1.0, "man_mark": 1.8
    }

class FullbackActionProfile(ActionProfile):
    role_name = "fullback"
    allowed_actions = {
        "stop", "pass", "clear", "dribble", "forward_run", "cross",
        "support", "hold_attack", "hold_defense", "press",
        "contain", "recover", "recover_slow", "tackle", "capture",
        "man_mark", "cover"
    }
    action_biases = {
        "pass": 2.0, "clear": 0.2, "dribble": 0.8, "cross": 1.6,
        "forward_run": 1.2, "support": 1.0, "hold_attack": 1.0,
        "hold_defense": 1.2, "press": 1.2, "contain": 1.2,
        "recover": 1.4, "tackle": 1.2, "capture": 1.0, "man_mark": 1.0,
        "cover": 1.0,
    }


class WingbackActionProfile(ActionProfile):
    role_name = "wingback"
    allowed_actions = {
        "stop", "pass", "clear", "dribble", "forward_run", "cross",
        "support", "hold_attack", "hold_defense", "press",
        "contain", "recover", "recover_slow", "tackle", "capture",
        "man_mark", "overlap", "cover"
    }
    action_biases = {
        "pass": 1.8, "clear": 0.15, "dribble": 1.0, "cross": 2.0,
        "forward_run": 1.8, "support": 1.3, "hold_attack": 1.4,
        "hold_defense": 0.9, "press": 1.1, "contain": 1.0,
        "recover": 1.2, "tackle": 1.0, "capture": 0.9, "man_mark": 0.8,
        "overlap": 1.6, "cover": 1.0,
    }


class Defender(player):
    def _build_action(self, decision: str, state: dict) -> dict | None:
        if decision == "stop":
            return None
            
        elif decision == "shoot":
            return self._calculate_shot(state)
            
        elif decision == "pass":
            if self._tactic(state).long_ball and not state.get("past_halfspace"):
                long_target = self._long_ball_target(state)
                if long_target is not None:
                    return {"type": "pass", "target": long_target, "power": 1.0, "pass_type": "long"}
            best_target = self._choose_pass_target(state)
            dist = _norm2(best_target - state["my_pos"])
            required_power = pass_power(dist, self.attributes.power, 1.0, 60.0)
            actual_power = required_power
            return {"type": "pass", "target": best_target, "power": actual_power}
            
        elif decision == "clear":
            if self._tactic(state).long_ball and not state.get("past_halfspace"):
                long_target = self._long_ball_target(state)
                if long_target is not None:
                    return {"type": "pass", "target": long_target, "power": 1.0, "pass_type": "long"}
            target = self._clearance_target(state)
            return {"type": "pass", "target": target, "power": min(1.0, self.attributes.power / 50.0), "pass_type": "clearance"}

        elif decision == "cross":
            return self._cross_action(state)
            
        elif decision == "dribble":
            enemy_goal_y = 100.0 if state.get("a_direction", 1) == 1 else 0.0
            dribble_speed = max(1.0, stat_ability(self.attributes.dribbling) * 1.25)
            # A full-back carries it up his flank, not across the middle.
            x = _clamp(float(state["my_pos"][0]), 5.0, PITCH_WIDTH - 5.0) if state.get("my_role") in FB_ROLES else 35.0
            return {"type": "move", "target": np.array([x, enemy_goal_y]), "speed_mod": dribble_speed}

        elif decision in ("wing_run", "wide_run", "attack_box", "take_on", "carry_across"):
            return self._build_wing_action(decision, state)
            
        elif decision == "forward_run":
            enemy_goal_y = 100.0 if state.get("a_direction", 1) == 1 else 0.0
            # A centre-back steps into midfield, never past halfway; a full-back goes all the way.
            run_y = PITCH_HEIGHT / 2.0 if state.get("my_role") == "CB" else enemy_goal_y
            run_target = np.array([state["my_pos"][0], run_y])
            return {"type": "move", "target": run_target, "speed_mod": pace_ability(self.attributes.speed) * 0.9}

        elif decision == "overlap" and state.get("my_role") in FB_ROLES:
            return {"type": "move", "target": self._overlap_target(state),
                    "speed_mod": pace_ability(self.attributes.speed) * OVERLAP_SPRINT, "intent": "overlap"}

        elif decision == "overlap":
            # Hugs whichever touchline this wingback's own formation slot sits
            # on, and pushes ahead of the ball rather than straight at goal --
            # the classic overlapping run, distinct from forward_run's
            # straight dash and support's ball-landing intercept.
            touchline_x = 2.0 if state["formation_pos"][0] < PITCH_WIDTH / 2.0 else PITCH_WIDTH - 2.0
            lead = 10.0 if state.get("a_direction", 1) == 1 else -10.0
            ahead_y = _clamp(state["ball_pos"][1] + lead, 0.0, PITCH_HEIGHT)
            overlap_target = np.array([touchline_x, ahead_y])
            return {"type": "move", "target": overlap_target, "speed_mod": pace_ability(self.attributes.speed) * 1.0}

        elif decision == "support":
            target = self._predict_ball_landing_target(state)
            vec_to_target = target - state["my_pos"]
            intercept_weight = 0.55 + pace_ability(self.attributes.speed) * 0.35
            support_target = self._support_target(state, state["my_pos"] + (vec_to_target * intercept_weight))
            return {"type": "move", "target": support_target, "speed_mod": pace_ability(self.attributes.speed) * 0.7}
            
        elif decision == "hold_attack":
            forward = 1.0 if state.get("a_direction", 1) == 1 else -1.0
            push, pace = 15.0, 0.5
            if state.get("my_role") in FB_ROLES and not self._ball_far_side(state):
                # The ball-side full-back keeps up with the play, FB_ATTACK_TRAIL behind it.
                ball_ahead = (float(state["ball_pos"][1]) - float(state["formation_pos"][1])) * forward
                push, pace = _clamp(ball_ahead - FB_ATTACK_TRAIL, push, FB_ATTACK_LIMIT), 0.7
            push -= self._tactic(state).line_depth
            tactical_pos = np.array([state["formation_pos"][0], state["formation_pos"][1] + push * forward])
            return {"type": "move", "target": tactical_pos, "speed_mod": pace_ability(self.attributes.speed) * pace}
            
        elif decision == "cover" or (decision in {"hold_defense", "hold_attack", "recover", "recover_slow"} and self._should_cover(state)):
            return {"type": "move", "target": self._cover_target(state), "speed_mod": pace_ability(self.attributes.speed) * 0.8}

        elif decision == "hold_defense":
            # A high line (line_depth < 0) holds up the pitch; a deep one is home already.
            drop = 10.0 + min(0.0, self._tactic(state).line_depth)
            backward_shift = -drop if state.get("a_direction", 1) == 1 else drop
            target = np.array([state["formation_pos"][0], self._hold_line_y(state, state["formation_pos"][1] + backward_shift)])
            return {"type": "move", "target": target, "speed_mod": pace_ability(self.attributes.speed) * 0.6}
            
        elif decision == "man_mark":
            opponents = np.asarray(state.get("opponents", []))
            if opponents.size == 0:
                return {"type": "move", "target": state["formation_pos"], "speed_mod": pace_ability(self.attributes.speed) * 0.6}
            
            own_goal = np.array([35.0, 0.0 if state.get("a_direction", 1) == 1 else 100.0])
            dists = np.linalg.norm(opponents - state["my_pos"], axis=1)

            # Pick the man who is actually dangerous, not merely the closest:
            # the one with the ball in my area outranks a spare body stood
            # nearer me, which is how a winger used to run off unattended.
            ball_pos = np.asarray(state["ball_pos"], dtype=float)
            threat = np.linalg.norm(opponents - ball_pos, axis=1)
            pick = int(np.argmin(dists + np.clip(threat - 4.0, 0.0, None) * 0.6))
            target_opp = opponents[pick]

            # Mark where he is GOING. Sitting on where he stands means always
            # arriving a step late.
            opp_vels = state.get("opponent_vel")
            if opp_vels is not None:
                target_opp = target_opp + np.asarray(opp_vels[pick], dtype=float) * MARK_LEAD_SECONDS

            vec_to_goal = own_goal - target_opp
            mark_pos = target_opp + (vec_to_goal / (_norm2(vec_to_goal) + 1e-5)) * 1.5
            # Full pace: marking at 0.8 meant the marker was slower than his man
            # by construction and simply got left behind.
            return {"type": "move", "target": mark_pos, "speed_mod": pace_ability(self.attributes.speed) * 1.0}

        elif decision == "press":
            if self._carrier_to_stop(state):
                press_target = self._stand_ground(state, self._goal_side_target(state, GOAL_SIDE_PRESS))
            else:
                target = self._predict_ball_landing_target(state)
                vec_to_target = target - state["my_pos"]
                press_weight = 0.7 + pace_ability(self.attributes.speed) * 0.25
                press_target = state["my_pos"] + (vec_to_target * press_weight)
            return {"type": "move", "target": press_target, "speed_mod": pace_ability(self.attributes.speed) * 0.9}

        elif decision == "contain":
            if self._carrier_to_stop(state):
                contain_target = self._stand_ground(state, self._goal_side_target(state, GOAL_SIDE_CONTAIN))
            else:
                target = self._predict_ball_landing_target(state)
                vec_to_target = target - state["my_pos"]
                contain_weight = 0.5 + pace_ability(self.attributes.speed) * 0.2
                contain_target = state["my_pos"] + (vec_to_target * contain_weight)
            return {"type": "move", "target": contain_target, "speed_mod": pace_ability(self.attributes.speed) * 0.8}
            
        elif decision in {"recover", "recover_slow"}:
            x = _clamp(float(state["formation_pos"][0]) + (float(state["ball_pos"][0]) - 35.0) * 0.35, 0.0, PITCH_WIDTH)
            slot_y = _clamp(float(state["formation_pos"][1]) + (float(state["ball_pos"][1]) - 50.0) * 0.10, 0.0, PITCH_HEIGHT)
            speed_mult = 0.7 if decision == "recover" else 0.4
            return {"type": "move", "target": np.array([x, self._hold_line_y(state, slot_y)]), "speed_mod": pace_ability(self.attributes.speed) * speed_mult}
            
        elif decision == "tackle":
            return {"type": "tackle", "stat": self.attributes.tackling}
            
        elif decision == "capture":
            return {"type": "capture", "stat": self.attributes.ballcontrol}
        
        elif decision == "chase":
            return {"type": "move", "target": self._chase_target(state), "speed_mod": pace_ability(self.attributes.speed) * 1.0}

        elif decision == "recovery_run":
            return self._recovery_run(state)

        elif decision == "hold_line":
            # Into his lane, dropping to the line if it is deeper -- never stepping up to it.
            target = self._line_target(state)
            own_goal_y = float(state["own_goal"][1])
            forward = 1.0 if own_goal_y == 0.0 else -1.0
            my_depth = (float(state["my_pos"][1]) - own_goal_y) * forward
            target[1] = own_goal_y + forward * min(my_depth, (float(target[1]) - own_goal_y) * forward)
            return {"type": "move", "target": target, "speed_mod": pace_ability(self.attributes.speed) * 0.9}

        elif decision == "back_line":
            return {"type": "move", "target": self._back_line_target(state), "speed_mod": pace_ability(self.attributes.speed) * 0.8}

        return None

    def _decide_on_ball_attack(self, state: dict) -> str:
        if state.get("must_pass_next", False):
            px, py = state["my_pos"]
            if (px <= 5.0 or px >= PITCH_WIDTH ) and (py <= 5.0 or py >= PITCH_HEIGHT):
                return "cross"
            return "pass"

        latched_move = self._latched_attack_move(state)
        if latched_move is not None:
            return latched_move

        fullback = state.get("my_role") in FB_ROLES
        if fullback:
            latched = self._decide_wingplay(state)
            if latched is not None:
                return latched

        actions = ["pass", "shoot", "dribble", "cross", "stop", "wing_run"]
        progressive_pass = self._best_progressive_pass_target(state) is not None
        pressure = state.get("pressure_count", 0)

        t_pass = self.attributes.pass_tendency * 0.4 * self.get_action_bias("pass")
        t_shoot = self.attributes.shoot_tendency * self.get_action_bias("shoot", 0.5)
        t_dribble = self.attributes.drible_tendency * self.get_action_bias("dribble")
        # Only with someone in the box to find (_box_runners), like any cross.
        t_cross = self.get_action_bias("cross") * 25.0 if self._box_runners(state) > 0 else 0.0
        t_stop = 10.0
        # A full-back up the flank runs the line to the crossing zone, as a winger does.
        t_wing = 0.0
        if fullback and self._is_wide(state) and not self._in_crossing_zone(state) and not self._beat_marker(state):
            t_wing = (self.attributes.speed + self.attributes.dribbling) * 0.5 + (60.0 if pressure == 0 else 0.0)
            t_dribble *= 0.3
            t_cross = 0.0

        if not progressive_pass: t_pass *= 0.08
        elif pressure > 0: t_pass *= 1.35

        # Wing positioning increases cross tendency
        my_x = state["my_pos"][0]
        if my_x < 15.0 or my_x > 55.0:
            t_cross *= 3.5
            t_dribble *= 1.5

        if pressure > 1:
            t_dribble -= (pressure * 25)
            t_pass += (pressure * 18)
            t_stop = 0
            t_cross *= 0.5

        moves, t_dribble = self._carve_attack_moves(state, t_dribble)

        tac = self._tactic(state)
        t_pass += self._wall_pass_pull(state)
        t_pass *= tac.pass_bias
        t_dribble *= tac.dribble_bias
        t_cross *= tac.cross_bias
        t_wing *= tac.cross_bias

        t_pass = max(0.0, t_pass)
        t_shoot = max(0.0, t_shoot)
        t_dribble = max(1.0, t_dribble)
        t_cross = max(0.0, t_cross)
        t_stop = max(0.0, t_stop)

        total = t_pass + t_shoot + t_dribble + t_cross + t_stop + t_wing + sum(moves.values())
        if total <= 0: return "dribble"
        
        probs = [t_pass/total, t_shoot/total, t_dribble/total, t_cross/total, t_stop/total, t_wing/total] + [weight / total for weight in moves.values()]
        actions = actions + list(moves)
        return _pick(state["rng"], actions, probs)

    def _decide_on_ball_defense(self, state: dict) -> str:
        actions = ["pass", "dribble", "stop", "clear"]
        progressive_pass = self._best_progressive_pass_target(state) is not None
        pressure = state.get("pressure_count", 0)

        t_pass = self.attributes.pass_tendency * 0.45 * self.get_action_bias("pass")
        t_dribble = self.attributes.drible_tendency * self.get_action_bias("dribble")
        t_clear = self.attributes.clear_tendency * self.get_action_bias("clear")
        t_stop = 15.0

        # A long-ball side always has a pass on: the front man.
        long_ready = self._tactic(state).long_ball and self._long_ball_target(state) is not None
        if not progressive_pass and not long_ready: t_pass *= 0.1 * self._tactic(state).recycle_bias
        elif pressure > 0: t_pass *= 1.3

        own_goal_y = 0.0 if state.get("a_direction", 1) == 1 else 100.0
        dist_to_own_goal = _norm2(np.array([35.0, own_goal_y]) - state["my_pos"])

        if dist_to_own_goal < 25.0:
            t_clear *= 2.5
            t_dribble *= 0.3

        if pressure > 1:
            t_clear += (pressure * 40)
            t_pass += (pressure * 12)
        elif pressure == 0:
            # Nobody within 3 units in front, so there is nothing to clear FROM.
            # A clearance here just concedes possession, and since 3.0.0 it flies
            # where the player FACES -- which on a touchline is straight out for
            # a throw-in. Play it instead; _choose_pass_target will take a
            # sideways or backward ball when no progressive one exists, so the
            # progressive-pass starve above must not apply either.
            t_clear = 0.0
            t_pass = self.attributes.pass_tendency * 0.45 * self.get_action_bias("pass")

        tac = self._tactic(state)
        t_pass += self._wall_pass_pull(state)
        t_pass *= tac.pass_bias
        t_dribble *= tac.dribble_bias
        t_clear *= tac.clear_bias

        t_pass = max(0.0, t_pass)
        t_dribble = max(1.0, t_dribble)
        t_clear = max(0.0, t_clear)
        t_stop = max(0.0, t_stop)

        total = t_pass + t_dribble + t_clear + t_stop
        if total <= 0: return "clear"
        
        probs = [t_pass/total, t_dribble/total, t_stop/total, t_clear/total]
        return _pick(state["rng"], actions, probs)

    def _holds_the_middle(self, state: dict) -> bool:
        """A centre-back does not follow a winger out: while the ball is wide of
        his lane and not yet on him, he keeps his place in the line."""
        if state.get("my_role") != "CB" or state.get("is_loose", False):
            return False
        ball_pos = np.asarray(state["ball_pos"], dtype=float)
        wide = abs(float(ball_pos[0]) - PITCH_WIDTH / 2.0) > RECOVERY_CB_LANE
        dist = _norm2(ball_pos - state["my_pos"])
        return wide and RECOVERY_PRESS_RANGE < dist < RECOVERY_RANGE

    def _should_cover(self, state: dict) -> bool:
        """A full-back with no centre-back home holds the middle instead of
        its flank -- own corners, or both CBs caught upfield. Checked after
        the loose-ball chase so a ball only they can reach is still theirs."""
        return state.get("my_role") in COVER_ROLES and not state.get("cb_home", True)

    def _decide_off_ball_attack(self, state: dict) -> str:
        if state.get("is_loose", False):
            landing_target = self._predict_ball_landing_target(state)
            my_dist = _norm2(landing_target - state["my_pos"])
            
            teammates = np.asarray(state.get("teammates", []))
            closer_teammates = 0
            if teammates.size > 0:
                closer_teammates = _count_within(teammates, landing_target, my_dist - 0.1)

            if closer_teammates == 0 or self._high_ball_mine(state, my_dist, closer_teammates):
                return "chase"

        if self._should_cover(state):
            return "cover"

        if self._overlap_on(state):
            if state.get("intent") == "overlap" or state["rng"].random() < OVERLAP_CHANCE * self._tactic(state).defender_push:
                return "overlap"
        
        actions = ["forward_run", "support", "hold_attack", "overlap"]
        t_forward = (self.attributes.shoot_tendency + (self.attributes.speed * 0.5)) * self.get_action_bias("forward_run")
        t_support = (self.attributes.pass_tendency + 20.0) * self.get_action_bias("support")
        t_hold = (self.attributes.defending + 30.0) * self.get_action_bias("hold_attack")
        t_overlap = (self.attributes.speed + 20.0) * self.get_action_bias("overlap", 0.0)

        dist_to_ball = _norm2(state["ball_pos"] - state["my_pos"])
        if dist_to_ball > 12.0:
            t_support *= 0.4
            t_hold *= 2.5
            t_overlap *= 0.5

        tac = self._tactic(state)
        t_forward *= tac.defender_push
        t_overlap *= tac.defender_push
        t_support *= tac.support_bias

        t_forward = max(0.0, t_forward)
        t_support = max(0.0, t_support)
        t_hold = max(1.0, t_hold)
        t_overlap = max(0.0, t_overlap)

        total = t_forward + t_support + t_hold + t_overlap
        probs = [t_forward/total, t_support/total, t_hold/total, t_overlap/total]
        return _pick(state["rng"], actions, probs)

    def _decide_off_ball_defense(self, state: dict) -> str:
        if state.get("is_loose", False):
            landing_target = self._predict_ball_landing_target(state)
            my_dist = _norm2(landing_target - state["my_pos"])
            
            teammates = np.asarray(state.get("teammates", []))
            closer_teammates = 0
            if teammates.size > 0:
                closer_teammates = _count_within(teammates, landing_target, my_dist - 0.1)

            if closer_teammates == 0 or self._high_ball_mine(state, my_dist, closer_teammates):
                return "chase"

        if self._is_beaten(state):
            return "recovery_run"

        dist_to_ball = _norm2(state["ball_pos"] - state["my_pos"])
        ball_pressure_count = _ball_pressure(state)

        if self._holds_the_middle(state):
            return "hold_line"

        # Close enough to matter, the ball wins; otherwise an uncovered
        # middle does.
        if dist_to_ball >= 15.0 and self._should_cover(state):
            return "cover"

        if dist_to_ball < 2.0:
            actions = ["tackle", "contain"]
            # Aggression alone, so the better side gets better challenges and
            # not more of them. The 160 holds the overall rate at the ~33% it
            # was when defending sat in t_contain -- 50% sampled the quality
            # gap half again as often and cost the underdog badly.
            t_tackle = max(1.0, self.attributes.aggression * 1.5)
            t_contain = max(1.0, 160.0 - self.attributes.aggression)
            probs = [t_tackle / (t_tackle + t_contain), t_contain / (t_tackle + t_contain)]
            return _pick(state["rng"], actions, probs)

        if dist_to_ball < 15.0:
            if dist_to_ball >= FB_ENGAGE_RANGE and self._holds_back_line(state):
                return "back_line"
            if ball_pressure_count >= 2: return "contain"
            return "press" if state["rng"].integers(0, 100) < min(100, getattr(self.attributes, "defending", 50) * PRESS_FROM_DEFENDING * self._tactic(state).press_bias) else "contain"

        if self._holds_back_line(state):
            return "back_line"
        actions = ["back_line" if state.get("my_role") in FB_ROLES else "hold_defense", "man_mark"]
        t_hold = 50.0 * self.get_action_bias("hold_defense")
        t_mark = 50.0 * self.get_action_bias("man_mark")
        probs = [t_hold / (t_hold + t_mark), t_mark / (t_hold + t_mark)]
        return _pick(state["rng"], actions, probs)

    def _flank(self, state: dict) -> float:
        return -1.0 if state["formation_pos"][0] < PITCH_WIDTH / 2.0 else 1.0

    def _holds_back_line(self, state: dict) -> bool:
        """A full-back leaves a ball in the middle or on the far flank to the centre-backs."""
        if state.get("my_role") not in FB_ROLES:
            return False
        return (float(state["ball_pos"][0]) - PITCH_WIDTH / 2.0) * self._flank(state) <= FB_FLANK_X

    def _hold_line_y(self, state: dict, drop_y: float) -> float:
        """The back line's y: DEF_LINE_SHARE of the ball's depth, moved by the tactic's line_depth,
        never deeper than `drop_y` (the old target) -- and `drop_y` itself for a loose ball coming
        at our goal, which the line turns and drops for."""
        own_goal_y = float(state["own_goal"][1])
        forward = 1.0 if own_goal_y == 0.0 else -1.0
        drop_depth = (float(drop_y) - own_goal_y) * forward
        if self._ball_coming(state):
            return float(drop_y)
        ball_depth = (float(state["ball_pos"][1]) - own_goal_y) * forward
        depth = _clamp(ball_depth * DEF_LINE_SHARE - self._tactic(state).line_depth, RECOVERY_MIN_DEPTH, DEF_LINE_MAX)
        return own_goal_y + forward * max(depth, drop_depth)

    def _stand_ground(self, state: dict, target: np.ndarray) -> np.ndarray:
        """A centre-back's goal-side `target`, but no deeper than CB_STAND_DEPTH while the man is
        still outside it: on his line to goal, at the edge of the box."""
        if state.get("my_role") != "CB":
            return target
        own_goal = np.asarray(state["own_goal"], dtype=float)
        forward = 1.0 if own_goal[1] == 0.0 else -1.0
        carrier = np.asarray(state["ball_pos"], dtype=float)
        carrier_depth = (carrier[1] - own_goal[1]) * forward
        if carrier_depth <= CB_STAND_DEPTH + GOAL_SIDE_PRESS or (target[1] - own_goal[1]) * forward >= CB_STAND_DEPTH:
            return target
        to_goal = (own_goal - carrier) / (_norm2(own_goal - carrier) + 1e-8)
        along = (CB_STAND_DEPTH - carrier_depth) / min(to_goal[1] * forward, -1e-3)
        return carrier + to_goal * along

    def _ball_far_side(self, state: dict) -> bool:
        return (float(state["ball_pos"][0]) - PITCH_WIDTH / 2.0) * self._flank(state) < -FB_FLANK_X

    def _overlap_on(self, state: dict) -> bool:
        """A teammate has it on my flank past OVERLAP_FROM, with a centre-back home behind me."""
        if state.get("my_role") not in FB_ROLES or state.get("is_loose", False) or not state.get("cb_home", True):
            return False
        own_goal_y = float(state["own_goal"][1])
        ball_x, ball_y = float(state["ball_pos"][0]), float(state["ball_pos"][1])
        return (
            (ball_x - PITCH_WIDTH / 2.0) * self._flank(state) > FB_FLANK_X
            and abs(ball_y - own_goal_y) >= OVERLAP_FROM
        )

    def _overlap_target(self, state: dict) -> np.ndarray:
        """OVERLAP_LEAD ahead of the ball, never offside: outside the carrier, or inside a
        carrier who is on the touchline."""
        touch = self._touchline_x(state)
        ball_x, ball_y = float(state["ball_pos"][0]), float(state["ball_pos"][1])
        x = touch if abs(ball_x - touch) > OVERLAP_ROOM else touch - self._flank(state) * OVERLAP_INSIDE_X
        forward = 1.0 if state.get("a_direction", 1) == 1 else -1.0
        enemy_goal_y = PITCH_HEIGHT if forward > 0 else 0.0
        depth = max((enemy_goal_y - ball_y) * forward - OVERLAP_LEAD, self._offside_line(state) + OFFSIDE_MARGIN)
        return np.array([x, enemy_goal_y - depth * forward])

    def _back_line_target(self, state: dict) -> np.ndarray:
        """Level with the centre-backs -- whose line already carries the tactic's depth -- so he
        never plays a man onside behind them; level with the ball once it is past them. Narrows
        from FB_WIDTH_FAR to FB_WIDTH_NEAR as the ball nears goal, sliding with it."""
        own_goal_y = float(state["own_goal"][1])
        forward = 1.0 if own_goal_y == 0.0 else -1.0
        ball_x = float(state["ball_pos"][0])
        ball_depth = (float(state["ball_pos"][1]) - own_goal_y) * forward
        if state.get("cb_line") is not None:
            depth = min((state["cb_line"] - own_goal_y) * forward, ball_depth)
        else:
            depth = ball_depth - FB_LINE_BALL_GAP - self._tactic(state).line_depth
        depth = max(RECOVERY_MIN_DEPTH, depth)
        tuck = _clamp((FB_TUCK_FROM - ball_depth) / (FB_TUCK_FROM - FB_TUCK_TO), 0.0, 1.0)
        width = FB_WIDTH_FAR + (FB_WIDTH_NEAR - FB_WIDTH_FAR) * tuck
        x = PITCH_WIDTH / 2.0 + self._flank(state) * width + (ball_x - PITCH_WIDTH / 2.0) * FB_BALL_SHIFT
        return np.array([_clamp(x, 3.0, PITCH_WIDTH - 3.0), own_goal_y + forward * depth])

    def _cover_target(self, state: dict) -> np.ndarray:
        """The spot a covering full-back holds: COVER_DEPTH off its own goal
        line, COVER_HALF_GAP to the side of centre its flank is on."""
        own_goal_y = 0.0 if state.get("a_direction", 1) == 1 else PITCH_HEIGHT
        toward_pitch = 1.0 if own_goal_y == 0.0 else -1.0
        side = -1.0 if state["formation_pos"][0] < PITCH_WIDTH / 2.0 else 1.0
        return np.array([PITCH_WIDTH / 2.0 + side * COVER_HALF_GAP, own_goal_y + toward_pitch * COVER_DEPTH])

    def _decide_loose_ball(self, state: dict) -> str:
            dist_to_ball = _norm2(state["ball_pos"] - state["my_pos"])
            
            # Calculate distances of all teammates to the ball
            teammates = np.asarray(state.get("teammates", []))
            if teammates.size > 0:
                teammate_dists = _dists(teammates, state["ball_pos"])
                # Count exactly how many teammates are closer to the ball than I am
                # We subtract 0.1 to avoid tie-breaking bugs with our own distance
                closer_teammates = int(np.sum(teammate_dists < dist_to_ball - 0.1))
            else:
                closer_teammates = 0

            # Absolute priority: grab the ball if it is at our feet
            if dist_to_ball < 2.5: 
                return "capture"

            # 1. The single closest player to the ball goes directly to the landing spot
            if closer_teammates == 0:
                return "chase"
                
            # 2. The second closest player provides secondary support if nearby
            if closer_teammates == 1 and dist_to_ball < 15.0:
                return "contain"

            # 3. Everyone else actively runs away from the ball back to their tactical zone
            return "recover"


class CenterBack(Defender):
    primary_stats = ("defending", "tackling", "heading")

    def __init__(self, fname, lname, tier, position, attributes=None, country=None, hometown=None, appearance=None):
        super().__init__(fname, lname, tier, position, attributes, country, hometown, appearance)
        self.action_profile = CenterBackActionProfile()
        self.allowed_actions = set(self.action_profile.get_allowed_actions())
        self.action_biases = dict(self.action_profile.get_action_biases())

class Fullback(Defender):
    primary_stats = ("defending", "tackling", "speed","passing")

    def __init__(self, fname, lname, tier, position, attributes=None, country=None, hometown=None, appearance=None):
        super().__init__(fname, lname, tier, position, attributes, country, hometown, appearance)
        self.action_profile = FullbackActionProfile()
        self.allowed_actions = set(self.action_profile.get_allowed_actions())
        self.action_biases = dict(self.action_profile.get_action_biases())


class Wingback(Defender):
    """3-5-2's flank role: more attacking than a Fullback, still a recognized
    defender for tackling/positioning purposes. Signature move is "overlap"
    """
    primary_stats = ("speed", "passing", "defending")

    def __init__(self, fname, lname, tier, position, attributes=None, country=None, hometown=None, appearance=None):
        super().__init__(fname, lname, tier, position, attributes, country, hometown, appearance)
        self.action_profile = WingbackActionProfile()
        self.allowed_actions = set(self.action_profile.get_allowed_actions())
        self.action_biases = dict(self.action_profile.get_action_biases())