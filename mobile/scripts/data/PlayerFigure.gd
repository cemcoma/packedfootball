class_name PlayerFigure
extends RefCounted

## One blocky player, drawn from primitives. The only place a player's body
## is drawn anywhere in the game.
##
## Called from two places at very different sizes -- the match pitch
## (MatchPlayback._draw, ~48px tall) and the card portrait
## (PlayerModelView._draw, ~90px) -- so all geometry is written in a
## normalised box and scaled to whatever `height_px` the caller asks for.
##
## EVERY NUMBER THAT SHAPES THE FIGURE IS A CONSTANT BELOW. The drawing
## functions contain no bare fractions at all: to make the torso wider or
## the head smaller, change one constant at the top and never open a
## function. The layout block explains what the numbers mean.
##
## THE SPRITE SEAM. When this becomes real pixel art, draw_into() is the
## function that changes and nothing else moves: every caller already passes
## appearance + kit + facing + pose + build and gets back "a player, this
## tall, standing here". A sprite version would swap the draw_rect calls for
## draw_texture_rect_region against an atlas, keep the same 8 facings (5
## drawn, 3 mirrored) and the same tinting.
##
## Anchored at the FEET, not the centre. A character stands on its position
## rather than being centred on it -- that is what lets the drawn figure be
## much taller than the 1.3-unit physical radius the simulation uses,
## without anything in gameEngine.py changing.

### SUPER IMPORTANT ###

# ===========================================================================
# PROPORTIONS
# ===========================================================================
#
# Every number below is a FRACTION, never a pixel count, so the same figure
# works at 17px on the tactical camera and 90px on a card.
#
#   *_W, *_SPREAD, *_X   fractions of the figure's WIDTH
#   *_Y                  height above the FEET: 0.0 = ground, 1.0 = top
#   *_H                  fractions of the figure's HEIGHT
#
# The body is one stack of bands. They have to tile without gaps and without
# hiding each other, so each band's bottom edge is the one below it plus its
# height:
#
#            1.00  +-------+
#                  | head  |   HEAD_Y  .. HEAD_Y + HEAD_H
#   HEAD_Y  0.76   +-------+
#                  | torso |   TORSO_Y .. TORSO_Y + TORSO_H   (arms overlay)
#   TORSO_Y 0.42   +-------+
#                  |shorts |   SHORTS_Y .. SHORTS_Y + SHORTS_H
#   SHORTS_Y 0.28  +-------+
#                  | legs  |   LEG_Y   .. LEG_Y + LEG_H
#   LEG_Y   0.07   +-------+
#                  | boots |   BOOT_Y  .. BOOT_Y + BOOT_H
#   BOOT_Y  0.00   +-------+  <- feet, the position the sim actually tracks
#
# If you move one band, move its neighbour to match or you get a gap.

## Width of the figure as a fraction of its height. The single biggest knob:
## raise it and everyone gets chunkier, lower it and everyone gets lanky.
const ASPECT := 0.62

# -- band positions and heights ---------------------------------------------
const BOOT_Y := 0.00
const BOOT_H := 0.07
const LEG_Y := 0.07
const LEG_H := 0.30
const SHORTS_Y := 0.28
const SHORTS_H := 0.2
const TORSO_Y := 0.42
const TORSO_H := 0.34
const HEAD_Y := 0.76
const HEAD_H := 0.32

# -- widths -----------------------------------------------------------------
const LEG_W := 0.30         # each leg
const LEG_SPREAD := 0.35    # centre line to each leg's inner edge
const SHORTS_W := 0.70
const TORSO_W := 0.70
const ARM_W := 0.25
const HEAD_W := 0.6

## Arms hang off the SIDES of the torso, so where they sit is DERIVED from
## TORSO_W (see arm_spread()) rather than being its own constant. Widen the
## torso and the arms move out with it -- they can never end up buried in
## it, which is what used to happen when the two were set independently.
##
## This is the only nudge: 0.0 puts the inner edge of each arm flush against
## the torso. Positive tucks them into it (a hunched, narrow-shouldered
## look), negative floats them off it.
const ARM_INSET := 0.0

# -- torso detail -----------------------------------------------------------
# How many CONTRAST stripes show on a striped shirt -- 3 means you count
# three stripes, not three bars of which half are the shirt colour. They are
# laid out symmetrically about the centre line with the primary colour
# showing between them and down both edges, so the shirt always starts and
# ends the same way round.
#
# Each stripe plus its gaps needs room: the torso is split into
# STRIPE_COUNT * 2 + 1 bands. On the pitch the torso is only ~17px wide, so
# 3 gives ~2.4px bands and 6 gives ~1.3px -- past that they stop reading as
# stripes and STRIPE_MIN_PX drops them.
const STRIPE_COUNT := 3
const STRIPE_MIN_PX := 1.0        # below this a stripe is mush; draw solid
const COLLAR_X := 0.30            # fraction across the torso where it starts
const COLLAR_W := 0.40            # fraction of the torso's width
const COLLAR_H := 0.035
const TORSO_LUNGE_TILT := 0.04    # how far the body rides up in a lunge

# -- arms and hands ---------------------------------------------------------
const ARM_Y := 0.43
const ARM_H := 0.30
const HAND_H := 0.10
const ARM_SWING := 0.60           # how much of the leg swing the arms mirror

# -- head detail ------------------------------------------------------------
const EYE_W := 0.16               # fraction of the head's width
const EYE_Y := 0.42               # fraction up the head
const EYE_X_LEFT := 0.20          # fractions across the head
const EYE_X_RIGHT := 0.80
const EYE_COLOR := Color(0.1, 0.1, 0.1)

# -- hair ------------------------------------------------------------------
# The SHAPES live in PlayerAppearance.HAIR_STYLES, as data -- that is where
# you add or edit a hairstyle. What is left here is only what applies to
# every style regardless of its shape.
const HAIR_CAP_H := 0.34          # the plain cap every style collapses to at DETAIL_LOW
const HAIR_BACK_Y := 0.35         # back of the head, seen when running away
const HAIR_BACK_H := 0.65

# -- shirt number -----------------------------------------------------------
const NUMBER_Y := 0.50
const NUMBER_SIZE := 0.17
const NUMBER_MIN_PX := 7.0

# -- ground shadow ----------------------------------------------------------
const SHADOW_W := 0.80
const SHADOW_H := 0.10
const SHADOW_W_FLASH := 0.8      # wider when an action colour is on it
const SHADOW_H_FLASH := 0.10      # wider when an action colour is on it
const SHADOW_COLOR := Color(0, 0, 0, 0.20)

# -- motion -----------------------------------------------------------------
const RUN_SWING := 0.055          # how far the legs travel in a stride
const LEAN := 0.10                # 3/4 body shift toward the facing
const LEG_LEAN := 0.40            # how much of that the legs take
const HEAD_LEAN := 1.40           # ... and the head, which leads the turn

const LIFT_KICK := 0.12           # striking leg, other one planted
const LIFT_LUNGE_FRONT := 0.14
const LIFT_LUNGE_BACK := 0.05
const LIFT_REACH := 0.06

# -- side view (FACING_E / FACING_W) ------------------------------------------
# The body seen edge-on, drawn by _draw_profile instead of the front view
# shifted sideways: no second arm facing the viewer, legs that scissor fore
# and aft, one eye. "Forward" below means toward the facing; widths are
# fractions of the figure's width like everything else.
const PROFILE_TORSO_W := 0.46
const PROFILE_SHORTS_W := 0.50
const PROFILE_LEG_W := 0.26
const PROFILE_LEG_OFFSET := 0.07  # the far leg stands this far behind the near one
const PROFILE_BOOT_TOE := 0.10    # boots stick out forward by this much
const PROFILE_STRIDE := 0.15      # how far each leg travels fore/aft at full swing
const PROFILE_TRAIL_LIFT := 0.05  # the trailing leg's heel comes up this much
const PROFILE_KICK_REACH := 1.3   # striking leg, as a multiple of PROFILE_STRIDE
const PROFILE_LUNGE_REACH := 1.7
const PROFILE_ARM_W := 0.22
const PROFILE_ARM_SWING := 0.13   # how far the arms swing fore/aft at full stride
const PROFILE_FAR_SHADE := 0.30   # how much darker the far arm and leg are
const PROFILE_HEAD_W := 0.54
const PROFILE_EYE_X := 0.72       # fraction across the head, from the back
const PROFILE_HAIR_BACK_X := 0.45 # the back of the head is hair up to here
const PROFILE_RIDGE_X := 0.12     # a mohawk runs front to back between these
const PROFILE_RIDGE_W := 0.76

# Keeper at full stretch. Absolute, NOT derived from the torso -- the point
# of a dive is that the arms are thrown well clear of the body. Keep it
# above arm_spread() or a diving keeper looks like a standing one.
const REACH_SPREAD := 0.62
const REACH_Y := 0.66
const REACH_H := 0.10
const REACH_SPAN := 1.60          # multiple of ARM_W
const REACH_GLOVE := 0.45         # fraction of the arm that is glove

# -- celebrations -----------------------------------------------------------
# WHICH celebration a player does is data (PlayerAppearance.CELEBRATIONS, a
# recipe of the named parts below); these numbers shape the parts.
#
# A celebration is a TIMELINE, not a single pose: for POSE_CELEBRATE the
# `phase` draw_into gets is SECONDS since the goal, and celebration_state()
# turns that into which stage the player is in -- a run-up, an optional
# leap, an optional slide, then the final pose held. The caller moves the
# player along the ground by the `travel` it returns; this file only draws
# the body. The whole thing is written to fit CELEBRATE_DURATION, the
# real-time hold MatchPlayback puts on a goal.
const CELEBRATE_DURATION := 5.0
# Radians per second for the sways and waves of the held pose.
const CELEBRATE_PHASE_RATE := 6.0
# The run-up: leg cycle in radians per second.
const CELEBRATE_RUN_CYCLE := 12.0
# A leap: how high (fraction of height) and how fast the player keeps
# moving while airborne (fraction of run speed). One full turn in the air.
const CELEBRATE_JUMP_HEIGHT := 0.45
const CELEBRATE_JUMP_SPEED := 0.5
# A slide: starts at this fraction of run speed and brakes to a stop.
const CELEBRATE_SLIDE_SPEED := 0.8

const STAGE_RUN := "run"
const STAGE_JUMP := "jump"
const STAGE_SLIDE := "slide"
const STAGE_POSE := "pose"

# "up": both arms raised, swaying.
const CELEBRATE_FLARE := 0.02     # how far raised arms sit OUTSIDE arm_spread()
const CELEBRATE_ARM_Y := 0.62
const CELEBRATE_ARM_H := 0.26
const CELEBRATE_HAND_H := 0.06
const CELEBRATE_WAVE_W := 0.14    # how far the arms sway
const CELEBRATE_WAVE_SPEED := 2.20

# "pump": one raised arm pumping up and down by this much (fraction of height).
const CELEBRATE_PUMP_H := 0.08

# "wide": arms straight out, aeroplane. Lower than a keeper's reach (which
# is level with the head) -- shoulder height, so it reads as balance, not
# a save.
const CELEBRATE_WIDE_Y := 0.58
const CELEBRATE_WIDE_HAND := 0.30 # fraction of the arm that is hand

# "shush": the near arm bends up so a finger lands on the mouth.
const CELEBRATE_SHUSH_MOUTH_Y := 0.22   # fraction up the head, PlayerAppearance's mouth band
const CELEBRATE_SHUSH_FOREARM_H := 0.07

# "back": arms swept down and behind, wider than the body, chest out.
const CELEBRATE_BACK_FLARE := 0.14
const CELEBRATE_BACK_Y := 0.30
const CELEBRATE_BACK_H := 0.24

# "cradle": both forearms across the front at waist height.
const CELEBRATE_CRADLE_Y := 0.50
const CELEBRATE_CRADLE_H := 0.08
const CELEBRATE_CRADLE_OVERHANG := 0.06 # how far the arms stick out past the torso

# Whole-body motion.
const CELEBRATE_BOUNCE_SPEED := 1.10    # hops per phase unit, roughly (abs(sin) doubles it)
const CELEBRATE_SPIN_SPEED := 0.90      # facings per phase unit: one turn every ~1.5s
const CELEBRATE_ROCK_W := 0.10          # side-to-side sway, fraction of width
const CELEBRATE_ROCK_SPEED := 1.10
const CELEBRATE_STEP_SPEED := 2.20      # running on the spot
const CELEBRATE_KNEEL_DROP := 0.14      # how much shorter a kneeling figure is (fraction of height)
const CELEBRATE_WIDE_STANCE := 0.12     # extra spread per leg for a wide stance

const LEGS_STAND := "stand"
const LEGS_WIDE := "wide"
const LEGS_KNEEL := "kneel"
const LEGS_STEP := "step"

const SOCK_DARKEN := 0.55         # how much darker the sock is than the boot

# -- actions ------------------------------------------------------------------
# What a player does when the replay says they shot, passed, cleared, tackled
# or saved: a short timeline, one recipe each. draw_into gets the recipe's
# name as the pose and seconds into it as the phase; MatchPlayback arms the
# action `lead` seconds BEFORE the event's tick, so a kick winds up before
# the ball leaves and the strike lands on the event.
#
#   kind    kick    lead: backswing   strike: back -> through   recover: -> stand
#           tackle  lead: lunge out   hold                        recover
#           throw   lead: arms up     strike: arms come over      recover
#           dive    lead: go down     hold: on the ground         recover: up
#   leg     how high the kicking / lunging foot comes (fraction of height)
#   reach   how far it goes fore/aft, side on (multiple of PROFILE_STRIDE)
#   arm     how far the arms counter-swing (fraction of height)
#   drop    how far the body crouches (fraction of height)
#   angle   a dive's tilt from upright, degrees, toward the ball
#   lift    how far a dive leaves the ground (fraction of height)
const ACTIONS := {
	"shoot":  {"kind": "kick", "lead": 1.5, "strike": 0.20, "recover": 1.20, "leg": 0.30, "reach": 2.0, "arm": 0.10},
	"pass":   {"kind": "kick", "lead": 0.50, "strike": 0.06, "recover": 0.20, "leg": 0.09, "reach": 1.0, "arm": 0.05},
	"clear":  {"kind": "kick", "lead": 1.00, "strike": 0.9, "recover": 0.35, "leg": 0.22, "reach": 1.7, "arm": 0.12},
	"trap":   {"kind": "kick", "lead": 0.00, "strike": 0.06, "recover": 0.14, "leg": 0.06, "reach": 0.6, "arm": 0.00},
	"throw":  {"kind": "throw", "lead": 0.20, "strike": 0.50, "recover": 0.20},
	"tackle": {"kind": "tackle", "lead": 0.10, "hold": 0.15, "recover": 0.25, "leg": 0.14, "reach": 1.8, "drop": 0.20, "arm": 0.08},
	"dive":   {"kind": "dive", "lead": 0.12, "hold": 0.30, "recover": 0.35, "angle": 75.0, "lift": 0.10, "drop": 0.06},
	"header": {"kind": "jump", "lead": 0.15, "hold": 0.12, "recover": 0.25, "lift": 0.22},
}

# ===========================================================================
# BUILD -- per-player variation
# ===========================================================================
#
# Two multipliers so 22 figures aren't 22 identical blocks. They come from
# the card's OWN attributes rather than a random roll, so the variation
# means something: a 198cm keeper towers, a powerful striker is broad.
#
#   build.y  height multiplier, from `height` (centimetres)
#   build.x  width multiplier,  from `power` (not used rn)
#
# Widen these ranges for more obvious variety; set both ends to 1.0 to turn
# variation off entirely.
const BUILD_CM_MIN := 160.0       # packEngine.HEIGHT_MIN
const BUILD_CM_MAX := 205.0       # packEngine.HEIGHT_MAX
const BUILD_SHORTEST := 0.90
const BUILD_TALLEST := 1.10
const BUILD_NARROWEST := 1.00
const BUILD_WIDEST := 1.00

# ===========================================================================

# Screen-space facings. atan2(vy, vx) with +y DOWN, so "south" is toward the
# bottom of the screen, which reads as toward the viewer.
const FACING_E := 0
const FACING_SE := 1
const FACING_S := 2
const FACING_SW := 3
const FACING_W := 4
const FACING_NW := 5
const FACING_N := 6
const FACING_NE := 7

## Running toward the viewer -- the face is visible.
const FACINGS_TOWARD := [FACING_SE, FACING_S, FACING_SW]
## Running away -- you see their back, so the shirt number shows instead.
const FACINGS_AWAY := [FACING_NW, FACING_N, FACING_NE]

const DETAIL_LOW := 0   # full-pitch camera: a readable blob, no face/number
const DETAIL_FULL := 1  # zoom camera and card portraits

const POSE_IDLE := "idle"
const POSE_RUN := "run"
const POSE_KICK := "kick"
const POSE_LUNGE := "lunge"
const POSE_REACH := "reach"
const POSE_CELEBRATE := "celebrate"

## Keeper gloves. Not from the appearance palette on purpose -- gloves are
## equipment, not a look you rolled, and white is what reads as "that one is
## the goalkeeper" at 48px.
const GLOVE_COLOR := Color(0.96, 0.96, 0.98)

# How far past a sector's midpoint the heading has to go before the facing
# actually switches. Without it a player running almost exactly NE flickers
# between N and E every frame.
const FACING_HYSTERESIS := 0.18


## Centre line to each arm's OUTER edge, derived so the arm's INNER edge
## lands exactly on the side of the torso:
##
##     torso    -TORSO_W/2 .............. +TORSO_W/2
##     left arm  -spread .. -TORSO_W/2
##     right arm             +TORSO_W/2 .. +spread
##
## Change TORSO_W and the arms follow. Nothing else needs touching.
static func arm_spread() -> float:
	return TORSO_W / 2.0 + ARM_W - ARM_INSET


## Height and width multipliers for one card, from its own attributes.
## Returns Vector2(width, height); Vector2.ONE for a card with no attributes
## (the bundled demo replay's roster sidecar carries names only).
static func build_from(attributes: Dictionary) -> Vector2:
	if attributes.is_empty():
		return Vector2.ONE

	var cm := float(attributes.get("height", 180))
	var tall := clampf((cm - BUILD_CM_MIN) / (BUILD_CM_MAX - BUILD_CM_MIN), 0.0, 1.0)

	var power := clampf(float(attributes.get("power", 50)) / 100.0, 0.0, 1.0)

	return Vector2(
		lerpf(BUILD_NARROWEST, BUILD_WIDEST, power),
		lerpf(BUILD_SHORTEST, BUILD_TALLEST, tall)
	)


## Which of the 8 facings this velocity means, or `previous` when the player
## is too slow to have a meaningful heading (standing still must not spin).
static func facing_from_velocity(vel: Vector2, previous: int, min_speed: float = 0.6) -> int:
	if vel.length() < min_speed:
		return previous

	var sector := atan2(vel.y, vel.x) / (PI / 4.0)  # -4..4, one unit per facing
	var nearest := int(round(sector)) % 8
	if nearest < 0:
		nearest += 8
	if nearest == previous:
		return previous

	# Hysteresis, but only against the ONE-STEP change, which is the only
	# one that flickers: a player running almost exactly NE sits on the
	# N/NE boundary and would otherwise swap every frame. A bigger turn --
	# someone actually changing direction -- commits immediately, so a
	# player who spins round doesn't keep facing the old way.
	var steps: int = abs(nearest - previous)
	if steps > 4:
		steps = 8 - steps
	# absf(...) is how far from the sector's centre we are: 0 dead centre,
	# 0.5 right on the boundary.
	if steps == 1 and absf(sector - round(sector)) > 0.5 - FACING_HYSTERESIS:
		return previous
	return nearest


## The facing nearest a direction, no hysteresis -- for a direction that
## is chosen rather than measured, like a celebration run-off.
static func facing_from_direction(dir: Vector2) -> int:
	if dir.is_zero_approx():
		return FACING_S
	return posmod(int(round(atan2(dir.y, dir.x) / (PI / 4.0))), 8)


static func faces_viewer(facing: int) -> bool:
	return facing in FACINGS_TOWARD


static func faces_away(facing: int) -> bool:
	return facing in FACINGS_AWAY


## Where a celebration recipe is `t` seconds after the goal:
##
##   stage   STAGE_RUN / STAGE_JUMP / STAGE_SLIDE / STAGE_POSE
##   travel  ground covered so far, in SECONDS OF RUNNING -- the caller
##           multiplies by its own run speed to get pitch units
##   lift    how far off the ground (fraction of height), the leap's arc
##   turn    0..1 through the leap's one full spin
##
## The stages come from the recipe's "run", "jump" and "slide" seconds,
## each 0 when absent; a recipe with none of them is just its pose from
## the first frame.
static func celebration_state(recipe: Dictionary, t: float) -> Dictionary:
	var run: float = recipe.get("run", 0.0)
	var jump: float = recipe.get("jump", 0.0)
	var slide: float = recipe.get("slide", 0.0)
	var state := {"stage": STAGE_POSE, "travel": 0.0, "lift": 0.0, "turn": 0.0}

	if t < run:
		state.stage = STAGE_RUN
		state.travel = t
		return state
	state.travel = run
	t -= run

	if t < jump:
		var u := t / jump
		state.stage = STAGE_JUMP
		state.travel += t * CELEBRATE_JUMP_SPEED
		state.lift = sin(u * PI) * CELEBRATE_JUMP_HEIGHT
		state.turn = u
		return state
	state.travel += jump * CELEBRATE_JUMP_SPEED
	t -= jump

	if t < slide:
		# Speed falls linearly to zero over the slide, so the distance is
		# the integral: u - u^2/2 of the full-speed distance.
		var u := t / slide
		state.stage = STAGE_SLIDE
		state.travel += CELEBRATE_SLIDE_SPEED * slide * (u - u * u / 2.0)
		return state
	state.travel += CELEBRATE_SLIDE_SPEED * slide / 2.0
	return state


## Draws one player standing at `feet`, `height_px` tall before `build`.
##
## `build` is Vector2(width, height) multipliers -- see build_from(). `phase`
## drives the run cycle (pass the playback tick plus something per-player so
## 22 figures don't march in lockstep) -- except for POSE_CELEBRATE, where
## it is SECONDS since the goal and drives the whole celebration timeline
## (see celebration_state); `flash` is the action colour from the replay
## event stream, drawn as a ground marker so the legend still means what it
## says without repainting the whole shirt.
## Whether `pose` names one of the ACTIONS timelines.
static func is_action(pose: String) -> bool:
	return ACTIONS.has(pose)


## How long an action runs, in seconds -- its lead plus the rest of it.
static func action_duration(name: String) -> float:
	var act: Dictionary = ACTIONS.get(name, {})
	return float(act.get("lead", 0.0)) + float(act.get("strike", 0.0)) + float(act.get("hold", 0.0)) + float(act.get("recover", 0.0))


## Seconds before the event's tick the action has to start so its strike
## lands on the event.
static func action_lead(name: String) -> float:
	return float(ACTIONS.get(name, {}).get("lead", 0.0))


## Where an action is `t` seconds in, as one number:
##   kick    -1 at the top of the backswing, +1 at full follow-through, 0 standing
##   tackle  0 standing .. 1 fully out
##   throw   0 .. 1 arms overhead, back to 0 as the ball goes
##   dive    0 upright .. 1 flat out
## Before the start (t < 0) and after the end it is 0 -- the figure stands.
static func action_amount(name: String, t: float) -> float:
	var act: Dictionary = ACTIONS.get(name, {})
	if act.is_empty() or t < 0.0:
		return 0.0
	var lead: float = act.get("lead", 0.0)
	var strike: float = act.get("strike", 0.0)
	var hold: float = act.get("hold", 0.0)
	var recover: float = act.get("recover", 0.0)
	if act.get("kind", "kick") == "kick":
		var back := -1.0 if lead > 0.0 else 0.0  # no lead, no backswing to come through from
		if t < lead:
			return -_ease_out(t / lead)
		if t < lead + strike:
			return lerpf(back, 1.0, (t - lead) / strike)
		if t < lead + strike + recover:
			return 1.0 - _ease_out((t - lead - strike) / recover)
		return 0.0
	# tackle / throw / dive: out, hold, back.
	if t < lead:
		return _ease_out(t / lead) if lead > 0.0 else 1.0
	if t < lead + strike + hold:
		return 1.0
	if t < lead + strike + hold + recover:
		return 1.0 - _ease_out((t - lead - strike - hold) / recover)
	return 0.0


static func _ease_out(x: float) -> float:
	x = clampf(x, 0.0, 1.0)
	return 1.0 - (1.0 - x) * (1.0 - x)


static func draw_into(
	canvas: CanvasItem,
	feet: Vector2,
	height_px: float,
	appearance: Dictionary,
	kit: KitDesign,
	facing: int,
	pose: String,
	detail: int,
	phase: float = 0.0,
	number: int = 0,
	flash: Color = Color(0, 0, 0, 0),
	font: Font = null,
	is_keeper: bool = false,
	build: Vector2 = Vector2.ONE,
	aim: float = 0.0
) -> void:
	if height_px <= 1.0:
		return

	# A taller player is proportionally wider too (w derives from h), and
	# build.x is the extra breadth on top of that.
	var h := height_px * build.y
	var w := h * ASPECT * build.x

	var skin := _slot_color(appearance, "skin_tone", PlayerAppearance.SKIN_TONES, Color(0.87, 0.65, 0.45))
	var hair := _slot_color(appearance, "hair_color", PlayerAppearance.HAIR_COLORS, Color(0.09, 0.07, 0.06))
	var boots := _slot_color(appearance, "shoe_color", PlayerAppearance.SHOE_COLORS, Color(0.1, 0.1, 0.1))
	var shirt := kit.primary_color() if kit != null else Color(0.2, 0.5, 1.0)
	var trim := kit.secondary_color() if kit != null else Color.WHITE
	var pattern: String = kit.pattern if kit != null else KitDesign.PATTERN_SOLID

	# Ground marker first -- everything else sits on top of it.
	var marker := flash if flash.a > 0.0 else SHADOW_COLOR
	var marker_w := w * (SHADOW_W_FLASH if flash.a > 0.0 else SHADOW_W)
	var marker_h := h * (SHADOW_H_FLASH if flash.a > 0.0 else SHADOW_H)

	_ellipse(canvas, feet, marker_w, marker_h , marker)

	# A celebration is the one pose that moves the WHOLE figure: it can hop
	# (the body leaves `feet`, the shadow stays), spin (the facing turns on
	# its own, whatever the velocity says) or drop to its knees. Everything
	# below draws from `body` rather than `feet` for that reason. It's also
	# a timeline: the run-up stage is drawn as an ordinary run, the leap as
	# a body in the air, and only the slide and the held pose use the
	# recipe's arm and leg parts.
	var body := feet
	var arms := ""
	var legs := LEGS_STAND
	var rock := 0.0
	var swing := 0.0
	if pose == POSE_RUN:
		swing = sin(phase) * RUN_SWING
	elif pose == POSE_CELEBRATE:
		var recipe := PlayerAppearance.celebration(int(appearance.get("celebration", 0)))
		var state := celebration_state(recipe, phase)
		var clock := phase * CELEBRATE_PHASE_RATE
		match state.stage:
			STAGE_RUN:
				pose = POSE_RUN
				swing = sin(phase * CELEBRATE_RUN_CYCLE) * RUN_SWING
			STAGE_JUMP:
				body.y -= h * state.lift
				facing = posmod(facing + int(floor(state.turn * 8.0)), 8)
				arms = "up"
			_:
				arms = recipe.get("arms", "up")
				legs = recipe.get("legs", LEGS_STAND)
				if recipe.get("spin", false):
					facing = posmod(int(floor(clock * CELEBRATE_SPIN_SPEED)), 8)
				if recipe.get("rock", false):
					rock = sin(clock * CELEBRATE_ROCK_SPEED) * w * CELEBRATE_ROCK_W
				var bounce: float = recipe.get("bounce", 0.0)
				if bounce > 0.0:
					body.y -= h * bounce * absf(sin(clock * CELEBRATE_BOUNCE_SPEED))
				if legs == LEGS_STEP:
					swing = sin(clock * CELEBRATE_STEP_SPEED) * RUN_SWING
		# The held pose's sways run off the faster clock.
		phase = clock

	# An action (pose names an ACTIONS recipe, phase is seconds into it)
	# becomes limb amplitudes, and the pose itself a plain stand. The old
	# single-frame poses are the same amplitudes held at full.
	var act: Dictionary = ACTIONS.get(pose, {})
	var amount := action_amount(pose, phase) if not act.is_empty() else 0.0
	var kick := 0.0      # -1 back .. +1 through
	var lunge := 0.0     # 0 .. 1 out
	var drop := 0.0      # crouch, fraction of height
	var tilt := 0.0      # dive: radians about the feet, signed toward the ball
	var motion := act    # which recipe's amplitudes the limbs read
	match act.get("kind", ""):
		"kick":
			kick = amount
		"tackle":
			lunge = amount
			drop = amount * float(act.get("drop", 0.0))
		"throw":
			arms = "up" if amount > 0.0 else arms
		"dive":
			var toward := signf(aim)
			tilt = toward * deg_to_rad(float(act.get("angle", 75.0))) * amount
			drop = amount * float(act.get("drop", 0.0)) if toward == 0.0 else 0.0
			body.y -= h * float(act.get("lift", 0.0)) * sin(PI * amount)
			arms = "up" if amount > 0.0 else arms
			facing = FACING_S
		"jump":
			# A header: straight up off the ground and back, arms up for balance.
			body.y -= h * float(act.get("lift", 0.0)) * sin(PI * amount)
			arms = "up" if amount > 0.0 else arms
	if pose == POSE_KICK:
		kick = 1.0
		motion = ACTIONS["shoot"]
	elif pose == POSE_LUNGE:
		lunge = 1.0
		motion = ACTIONS["tackle"]
	if not act.is_empty() or pose in [POSE_KICK, POSE_LUNGE]:
		pose = POSE_IDLE

	# A dive: the whole figure pivots about the feet toward the ball, the
	# shadow staying where it was. Everything below draws in that frame.
	if tilt != 0.0:
		canvas.draw_set_transform(body, tilt, Vector2.ONE)
		body = Vector2.ZERO

	# Side on: its own drawing, not the front view shifted. A dive stays
	# front-on -- both arms thrown out along the dive is the picture.
	var side := _side_for(facing)
	if side != 0.0 and pose != POSE_REACH:
		_draw_profile(
			canvas, body + Vector2(rock, 0.0), w, h, side, pose, swing, arms, legs, phase,
			skin, hair, boots, shirt, trim, pattern, appearance, detail, is_keeper,
			kick, lunge, drop, motion
		)
		return

	# 3/4 lean: shift the upper body toward where they're looking, which is
	# most of what sells a direction on a figure this blocky.
	var lean := _lean_for(facing) * w * LEAN + rock

	var kick_lift := maxf(0.0, kick) * float(motion.get("leg", LIFT_KICK))
	var lunge_lift := lunge * float(motion.get("leg", LIFT_LUNGE_FRONT))
	_draw_legs(canvas, body, w, h, boots, trim, pose, swing, lean, legs, kick_lift, lunge_lift, drop)
	# Kneeling folds the legs under, so everything above them sits lower.
	if legs == LEGS_KNEEL:
		body.y += h * CELEBRATE_KNEEL_DROP
	body.y += h * drop
	_draw_torso(canvas, body, w, h, shirt, trim, pattern, lunge * TORSO_LUNGE_TILT, lean, detail)
	# Arms under the head, except when the hand is ON the face.
	var arm_lift := (kick + lunge) * float(motion.get("arm", 0.0))
	if arms == "shush":
		_draw_head(canvas, body, w, h, skin, hair, appearance, facing, lean, detail)
		_draw_arms(canvas, body, w, h, trim, skin, pose, swing, lean, phase, is_keeper, arms, arm_lift)
	else:
		_draw_arms(canvas, body, w, h, trim, skin, pose, swing, lean, phase, is_keeper, arms, arm_lift)
		_draw_head(canvas, body, w, h, skin, hair, appearance, facing, lean, detail)

	if detail == DETAIL_FULL and number > 0 and faces_away(facing) and font != null:
		_draw_number(canvas, body, w, h, number, trim, shirt, font, lean)

	if tilt != 0.0:
		canvas.draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)


# ------------------------------------------------------------------ layers

## Boots, legs and shorts. A `lift` raises that leg -- toward the viewer is
## "forward" in this pseudo-top-down view, so a raised leg reads as a stride
## or a kick. Lifts are fractions of height, like every other Y here.
static func _draw_legs(
	canvas: CanvasItem, feet: Vector2, w: float, h: float,
	boots: Color, shorts: Color, pose: String, swing: float, lean: float,
	legs: String = LEGS_STAND, kick_lift: float = 0.0, lunge_lift: float = 0.0, drop: float = 0.0
) -> void:
	var leg_w := w * LEG_W
	var spread := LEG_SPREAD + (CELEBRATE_WIDE_STANCE if legs == LEGS_WIDE else 0.0)
	var left_x := -w * spread
	var right_x := w * spread - leg_w
	# Kneeling folds the legs under and a crouch bends them: the band is
	# shorter and the shorts (and everything draw_into stacks above them)
	# come down with it.
	var fold := (CELEBRATE_KNEEL_DROP if legs == LEGS_KNEEL else 0.0) + drop
	var leg_h := LEG_H - fold
	var shorts_y := SHORTS_Y - fold

	var left_lift := kick_lift + lunge_lift
	var right_lift := lunge_lift * LIFT_LUNGE_BACK / LIFT_LUNGE_FRONT
	match pose:
		POSE_RUN:
			left_lift = swing
			right_lift = -swing
		POSE_CELEBRATE:
			if legs == LEGS_STEP:
				left_lift = swing
				right_lift = -swing
		POSE_REACH:
			left_lift = LIFT_REACH
			right_lift = LIFT_REACH

	for side in [[left_x, left_lift], [right_x, right_lift]]:
		var x: float = side[0] + lean * LEG_LEAN
		var lift: float = side[1]
		_rect(canvas, feet, w, h, x, BOOT_Y + lift, leg_w, h * BOOT_H, boots)
		_rect(canvas, feet, w, h, x, LEG_Y + lift, leg_w, h * leg_h, boots.lerp(Color.BLACK, SOCK_DARKEN))

	# Shorts last: they overlap the top of both legs, which is what hides
	# the seam when one leg is lifted.
	_rect(canvas, feet, w, h, -w * SHORTS_W / 2.0, shorts_y, w * SHORTS_W, h * SHORTS_H, shorts)


static func _draw_torso(
	canvas: CanvasItem, feet: Vector2, w: float, h: float,
	shirt: Color, trim: Color, pattern: String, tilt: float, lean: float, detail: int,
	torso_w_frac: float = TORSO_W
) -> void:
	var torso_w := w * torso_w_frac
	var torso_h := h * TORSO_H
	var x := -torso_w / 2.0 + lean
	var base_y := TORSO_Y + tilt

	# The shirt is always painted solid first and the stripes go ON it. That
	# is what makes the layout symmetric: the torso is divided into
	# STRIPE_COUNT stripes and STRIPE_COUNT + 1 gaps, so a stripe can never
	# sit flush against one edge with a gap at the other. It also means no
	# rounding gap can ever show grass through the shirt, which the old
	# alternating-bars version needed a special case for.
	#
	#   STRIPE_COUNT = 3   |  gap  |###|  gap  |###|  gap  |###|  gap  |
	#                      ^ both edges are the primary colour ^
	_rect(canvas, feet, w, h, x, base_y, torso_w, torso_h, shirt)

	if pattern == KitDesign.PATTERN_STRIPES and detail == DETAIL_FULL:
		var band_w := torso_w / float(STRIPE_COUNT * 2 + 1)
		if band_w >= STRIPE_MIN_PX:
			for i in range(STRIPE_COUNT):
				# Odd bands are the stripes, even ones the gaps either side.
				_rect(canvas, feet, w, h, x + band_w * (i * 2 + 1), base_y, band_w, torso_h, trim)
	elif pattern == KitDesign.PATTERN_QUARTERS and detail == DETAIL_FULL and h > 0.0:
		var rect_w := torso_w / 2.0
		var rect_h := torso_h / 2.0
		_rect(canvas, feet, w, h, x, base_y, rect_w, rect_h, trim)
		_rect(canvas, feet, w, h, x + rect_w, base_y + rect_h / h, rect_w, rect_h, trim)

	# Collar, sitting just inside the top of the torso -- it is what makes a
	# SOLID kit still read as two colours rather than one flat block.
	if detail == DETAIL_FULL and pattern != KitDesign.PATTERN_QUARTERS:
		_rect(
			canvas, feet, w, h,
			x + torso_w * COLLAR_X, base_y + TORSO_H - COLLAR_H,
			torso_w * COLLAR_W, h * COLLAR_H, trim
		)


## Arms, and the hands on the end of them. A keeper's hands are gloves, which
## at this size is the whole of "that one is the goalkeeper" -- there is no
## separate keeper shirt, so without it the two are indistinguishable.
static func _draw_arms(
	canvas: CanvasItem, feet: Vector2, w: float, h: float,
	sleeve: Color, skin: Color, pose: String, swing: float, lean: float,
	phase: float = 0.0, is_keeper: bool = false, celebration_arms: String = "",
	arm_lift: float = 0.0
) -> void:
	var arm_w := w * ARM_W
	var hand := GLOVE_COLOR if is_keeper else skin

	if pose == POSE_REACH:
		# Keeper at full stretch: both arms out sideways, level with the
		# head, gloves on the ends.
		var span := arm_w * REACH_SPAN
		var left_x := -w * REACH_SPREAD + lean
		var right_x := w * REACH_SPREAD - span + lean
		_rect(canvas, feet, w, h, left_x, REACH_Y, span, h * REACH_H, sleeve)
		_rect(canvas, feet, w, h, right_x, REACH_Y, span, h * REACH_H, sleeve)
		_rect(canvas, feet, w, h, left_x, REACH_Y, span * REACH_GLOVE, h * REACH_H, hand)
		_rect(canvas, feet, w, h, right_x + span * (1.0 - REACH_GLOVE), REACH_Y, span * REACH_GLOVE, h * REACH_H, hand)
		return

	# "swing" is the ordinary run-cycle arms, driven by the leg swing
	# draw_into computed for a LEGS_STEP celebration; every other arm pose
	# is its own gesture. A throw or a dive borrows the raised arms.
	if (pose == POSE_CELEBRATE and celebration_arms != "swing") or celebration_arms == "up":
		_draw_celebrating_arms(canvas, feet, w, h, sleeve, hand, celebration_arms, lean, phase if pose == POSE_CELEBRATE else 0.0)
		return

	var lift := swing * ARM_SWING + arm_lift
	var spread := arm_spread()
	for side in [[-w * spread + lean, -lift], [w * spread - arm_w + lean, lift]]:
		var x: float = side[0]
		var dy: float = side[1]
		_rect(canvas, feet, w, h, x, ARM_Y + dy, arm_w, h * ARM_H, sleeve)
		_rect(canvas, feet, w, h, x, ARM_Y + dy - HAND_H, arm_w, h * HAND_H, hand)


## The arm poses a celebration recipe can name (PlayerAppearance.CELEBRATIONS'
## "arms"). Each is a gesture on its own; the sway/pump is the only thing
## moving, since the player is standing still -- that is what makes any of
## them read as celebrating rather than running. An unknown name draws the
## arms-up wave, so a recipe from a newer build still shows something.
static func _draw_celebrating_arms(
	canvas: CanvasItem, feet: Vector2, w: float, h: float,
	sleeve: Color, hand: Color, arms: String, lean: float, phase: float
) -> void:
	var arm_w := w * ARM_W
	var spread := arm_spread()
	var wave := sin(phase * CELEBRATE_WAVE_SPEED) * w * CELEBRATE_WAVE_W
	# Screen-space: "left" is the viewer's left, hanging arms are drawn
	# from ARM_Y up (hand below), raised arms from CELEBRATE_ARM_Y up
	# (hand on top).
	var left_x := -w * spread + lean
	var right_x := w * spread - arm_w + lean

	match arms:
		"wide":
			# Straight out to both sides -- the keeper's reach geometry at
			# shoulder height, hands on the ends.
			var span := arm_w * REACH_SPAN
			var lx := -w * REACH_SPREAD + lean
			var rx := w * REACH_SPREAD - span + lean
			_rect(canvas, feet, w, h, lx, CELEBRATE_WIDE_Y, span, h * REACH_H, sleeve)
			_rect(canvas, feet, w, h, rx, CELEBRATE_WIDE_Y, span, h * REACH_H, sleeve)
			_rect(canvas, feet, w, h, lx, CELEBRATE_WIDE_Y, span * CELEBRATE_WIDE_HAND, h * REACH_H, hand)
			_rect(canvas, feet, w, h, rx + span * (1.0 - CELEBRATE_WIDE_HAND), CELEBRATE_WIDE_Y, span * CELEBRATE_WIDE_HAND, h * REACH_H, hand)
		"pump":
			# Right fist punching the air, left arm hanging.
			var pump := (0.5 + 0.5 * sin(phase * CELEBRATE_WAVE_SPEED)) * CELEBRATE_PUMP_H
			_draw_raised_arm(canvas, feet, w, h, right_x + w * CELEBRATE_FLARE, CELEBRATE_ARM_Y + pump, sleeve, hand)
			_draw_hanging_arm(canvas, feet, w, h, left_x, sleeve, hand)
		"shush":
			# Right upper arm raised, forearm across to the mouth, finger
			# on the lips. Left arm hanging.
			var mouth_y := HEAD_Y + HEAD_H * CELEBRATE_SHUSH_MOUTH_Y
			_rect(canvas, feet, w, h, right_x, ARM_Y + ARM_H * 0.5, arm_w, h * (mouth_y - ARM_Y - ARM_H * 0.5), sleeve)
			_rect(canvas, feet, w, h, lean, mouth_y, right_x + arm_w - lean, h * CELEBRATE_SHUSH_FOREARM_H, sleeve)
			_rect(canvas, feet, w, h, lean - arm_w * 0.5, mouth_y, arm_w * 0.5, h * CELEBRATE_SHUSH_FOREARM_H, hand)
			_draw_hanging_arm(canvas, feet, w, h, left_x, sleeve, hand)
		"back":
			# Both arms down and swept out behind: lower than a hanging arm
			# and flared past the shoulders, chest out.
			var flare := w * CELEBRATE_BACK_FLARE
			for ax in [left_x - flare, right_x + flare]:
				_rect(canvas, feet, w, h, ax, CELEBRATE_BACK_Y, arm_w, h * CELEBRATE_BACK_H, sleeve)
				_rect(canvas, feet, w, h, ax, CELEBRATE_BACK_Y - HAND_H, arm_w, h * HAND_H, hand)
		"cradle":
			# Forearms stacked across the front at waist height, one a
			# little above the other, hands on opposite ends. The rocking
			# comes from draw_into's `rock` lean, not from here.
			var overhang := w * CELEBRATE_CRADLE_OVERHANG
			var span := w * TORSO_W + overhang * 2.0
			var x := -w * TORSO_W / 2.0 - overhang + lean
			for i in range(2):
				var y := CELEBRATE_CRADLE_Y + CELEBRATE_CRADLE_H * float(i)
				_rect(canvas, feet, w, h, x, y, span, h * CELEBRATE_CRADLE_H, sleeve)
				var hand_x := x if i == 0 else x + span - arm_w
				_rect(canvas, feet, w, h, hand_x, y, arm_w, h * CELEBRATE_CRADLE_H, hand)
		_:
			# "up", and anything this build doesn't know: both arms raised,
			# swaying together.
			var celebrate_spread := spread + CELEBRATE_FLARE
			for ax in [-w * celebrate_spread + lean + wave, w * celebrate_spread - arm_w + lean + wave]:
				_draw_raised_arm(canvas, feet, w, h, ax, CELEBRATE_ARM_Y, sleeve, hand)


## One arm straight up from `y`, hand on top.
static func _draw_raised_arm(
	canvas: CanvasItem, feet: Vector2, w: float, h: float, x: float, y: float, sleeve: Color, hand: Color
) -> void:
	var arm_w := w * ARM_W
	_rect(canvas, feet, w, h, x, y, arm_w, h * CELEBRATE_ARM_H, sleeve)
	_rect(canvas, feet, w, h, x, y + CELEBRATE_ARM_H, arm_w, h * CELEBRATE_HAND_H, hand)


## One arm hanging at the side, hand below -- the idle arm.
static func _draw_hanging_arm(
	canvas: CanvasItem, feet: Vector2, w: float, h: float, x: float, sleeve: Color, hand: Color
) -> void:
	var arm_w := w * ARM_W
	_rect(canvas, feet, w, h, x, ARM_Y, arm_w, h * ARM_H, sleeve)
	_rect(canvas, feet, w, h, x, ARM_Y - HAND_H, arm_w, h * HAND_H, hand)


## The side view. `side` is +1 facing east (screen right), -1 west, and
## multiplies everything that has a forward, so west is east mirrored.
## Painter's order back to front: far leg, far arm, near leg, shorts, torso,
## near arm, head -- the far limbs are shaded and only ever peek out.
static func _draw_profile(
	canvas: CanvasItem, body: Vector2, w: float, h: float, side: float,
	pose: String, swing: float, arms: String, legs: String, phase: float,
	skin: Color, hair: Color, boots: Color, shirt: Color, trim: Color, pattern: String,
	appearance: Dictionary, detail: int, is_keeper: bool,
	kick: float = 0.0, lunge: float = 0.0, drop: float = 0.0, motion: Dictionary = {}
) -> void:
	var hand := GLOVE_COLOR if is_keeper else skin
	var sock := boots.lerp(Color.BLACK, SOCK_DARKEN)
	var far := Color.BLACK

	# Stride -1..1: the run cycle's vertical swing becomes fore/aft travel,
	# the near leg forward at +1 and the arms swinging against the legs.
	var stride := clampf(swing / RUN_SWING, -1.0, 1.0)
	var near_fwd := 0.0
	var far_fwd := 0.0
	var near_lift := 0.0
	var far_lift := 0.0
	var arm_swing := 0.0
	var stepping := pose == POSE_RUN or (pose == POSE_CELEBRATE and legs == LEGS_STEP)
	if stepping:
		near_fwd = stride * PROFILE_STRIDE
		far_fwd = -stride * PROFILE_STRIDE
		near_lift = maxf(0.0, -stride) * PROFILE_TRAIL_LIFT
		far_lift = maxf(0.0, stride) * PROFILE_TRAIL_LIFT
		arm_swing = -stride * PROFILE_ARM_SWING
	elif kick != 0.0:
		# Back through the backswing, forward and up through the strike.
		near_fwd = kick * PROFILE_STRIDE * float(motion.get("reach", PROFILE_KICK_REACH))
		near_lift = maxf(0.0, kick) * float(motion.get("leg", LIFT_KICK))
		far_fwd = -PROFILE_STRIDE * 0.4 * absf(kick)
		arm_swing = -kick * PROFILE_ARM_SWING * 0.6
	elif lunge > 0.0:
		near_fwd = lunge * PROFILE_STRIDE * float(motion.get("reach", PROFILE_LUNGE_REACH))
		far_fwd = -lunge * PROFILE_STRIDE * 0.6
		far_lift = lunge * LIFT_LUNGE_BACK
		arm_swing = lunge * PROFILE_ARM_SWING
	elif pose == POSE_CELEBRATE and legs == LEGS_WIDE:
		near_fwd = PROFILE_STRIDE * 0.8
		far_fwd = -PROFILE_STRIDE * 0.8

	var kneel := legs == LEGS_KNEEL
	var fold := (CELEBRATE_KNEEL_DROP if kneel else 0.0) + drop
	var leg_h := LEG_H - fold
	var shorts_y := SHORTS_Y - fold
	var leg_w := w * PROFILE_LEG_W
	var toe := w * PROFILE_BOOT_TOE
	var arm_w := w * PROFILE_ARM_W

	# Far leg, then far arm: both behind the body.
	_profile_leg(canvas, body, w, h, side, far_fwd - PROFILE_LEG_OFFSET, far_lift, leg_w, leg_h, toe,
		boots.lerp(far, PROFILE_FAR_SHADE), sock.lerp(far, PROFILE_FAR_SHADE))
	var gesture := arms if (pose == POSE_CELEBRATE or arms == "up") else "hang"
	_profile_arm(canvas, body, w, h, side, -side * arm_swing * w - arm_w / 2.0, arm_w, gesture,
		trim.lerp(far, PROFILE_FAR_SHADE), hand.lerp(far, PROFILE_FAR_SHADE), phase, false)

	_profile_leg(canvas, body, w, h, side, near_fwd, near_lift, leg_w, leg_h, toe, boots, sock)
	_rect(canvas, body, w, h, -w * PROFILE_SHORTS_W / 2.0, shorts_y, w * PROFILE_SHORTS_W, h * SHORTS_H, trim)
	body.y += h * fold

	_draw_torso(canvas, body, w, h, shirt, trim, pattern, lunge * TORSO_LUNGE_TILT, 0.0, detail, PROFILE_TORSO_W)
	_profile_arm(canvas, body, w, h, side, side * arm_swing * w - arm_w / 2.0, arm_w, gesture,
		trim, hand, phase, true)
	_profile_head(canvas, body, w, h, side, skin, hair, appearance, detail)


## One leg seen from the side, boot toe forward. `fwd` is fore/aft travel as
## a fraction of width, `lift` height off the ground as a fraction of height.
static func _profile_leg(
	canvas: CanvasItem, body: Vector2, w: float, h: float, side: float,
	fwd: float, lift: float, leg_w: float, leg_h: float, toe: float, boot: Color, sock: Color
) -> void:
	var x := side * fwd * w - leg_w / 2.0
	var boot_x := x - (toe if side < 0.0 else 0.0)
	_rect(canvas, body, w, h, boot_x, BOOT_Y + lift, leg_w + toe, h * BOOT_H, boot)
	_rect(canvas, body, w, h, x, LEG_Y + lift, leg_w, h * leg_h, sock)


## One arm seen from the side. "hang" is the idle/run arm; a celebration's
## gesture collapses to "up" (both arms raised, the near one in front) or
## "wide" (near arm forward, far arm back -- the aeroplane, side on).
static func _profile_arm(
	canvas: CanvasItem, body: Vector2, w: float, h: float, side: float,
	x: float, arm_w: float, gesture: String, sleeve: Color, hand: Color, phase: float, near: bool
) -> void:
	match gesture:
		"wide":
			var span := arm_w * REACH_SPAN
			var out := side if near else -side
			var ax := x + arm_w / 2.0 if out > 0.0 else x + arm_w / 2.0 - span
			_rect(canvas, body, w, h, ax, CELEBRATE_WIDE_Y, span, h * REACH_H, sleeve)
			var hand_x := ax + span * (1.0 - CELEBRATE_WIDE_HAND) if out > 0.0 else ax
			_rect(canvas, body, w, h, hand_x, CELEBRATE_WIDE_Y, span * CELEBRATE_WIDE_HAND, h * REACH_H, hand)
		"hang", "swing":
			_rect(canvas, body, w, h, x, ARM_Y, arm_w, h * ARM_H, sleeve)
			_rect(canvas, body, w, h, x, ARM_Y - HAND_H, arm_w, h * HAND_H, hand)
		_:
			# "up" and every other gesture: raised, swaying, the far arm a
			# touch behind so it shows past the near one.
			var wave := sin(phase * CELEBRATE_WAVE_SPEED) * w * CELEBRATE_WAVE_W * 0.5
			var back := 0.0 if near else -side * arm_w * 0.5
			_draw_raised_arm(canvas, body, w, h, x + wave + back, CELEBRATE_ARM_Y, sleeve, hand)


## The head side on: narrower, one eye toward the front, hair as the style's
## cap with the back of the head filled in (a mohawk becomes a ridge running
## front to back). Strands hanging in front of the face are left out.
static func _profile_head(
	canvas: CanvasItem, body: Vector2, w: float, h: float, side: float,
	skin: Color, hair: Color, appearance: Dictionary, detail: int
) -> void:
	var head_w := w * PROFILE_HEAD_W
	var head_h := h * HEAD_H
	var x := -head_w / 2.0
	_rect(canvas, body, w, h, x, HEAD_Y, head_w, head_h, skin)

	var style := PlayerAppearance.hair_style(int(appearance.get("hair_style", 1)))
	var has_hair: bool = not style["parts"].is_empty()
	if detail == DETAIL_LOW:
		if has_hair:
			_rect(canvas, body, w, h, x, HEAD_Y + HEAD_H - HEAD_H * HAIR_CAP_H, head_w, head_h * HAIR_CAP_H, hair)
		return

	if has_hair and not style.get("covers_back", true):
		# A ridge: the style's height, run the length of the head.
		for part in style["parts"]:
			_rect(canvas, body, w, h, x + head_w * PROFILE_RIDGE_X, HEAD_Y + HEAD_H * float(part[1]),
				head_w * PROFILE_RIDGE_W, head_h * float(part[3]), hair)
	elif has_hair:
		for part in style["parts"]:
			var px := float(part[0])
			var pw := float(part[2])
			# A part entirely past the front of the head is the strand that
			# would hang over the face: skip it. Past the back, it hangs down
			# the back of the neck, which is right.
			if (side > 0.0 and px >= 1.0) or (side < 0.0 and px + pw <= 0.0):
				continue
			_rect(canvas, body, w, h, x + head_w * px, HEAD_Y + HEAD_H * float(part[1]),
				head_w * pw, head_h * float(part[3]), hair)
		var back_x := x if side > 0.0 else x + head_w * (1.0 - PROFILE_HAIR_BACK_X)
		_rect(canvas, body, w, h, back_x, HEAD_Y + HEAD_H * HAIR_BACK_Y, head_w * PROFILE_HAIR_BACK_X, head_h * HAIR_BACK_H, hair)

	var eye_w := maxf(1.0, head_w * EYE_W)
	var eye_frac := PROFILE_EYE_X if side > 0.0 else 1.0 - PROFILE_EYE_X
	_rect(canvas, body, w, h, x + head_w * eye_frac - eye_w / 2.0, HEAD_Y + HEAD_H * EYE_Y, eye_w, eye_w, EYE_COLOR)


static func _draw_head(
	canvas: CanvasItem, feet: Vector2, w: float, h: float,
	skin: Color, hair: Color, appearance: Dictionary, facing: int, lean: float, detail: int
) -> void:
	var head_w := w * HEAD_W
	var head_h := h * HEAD_H
	var x := -head_w / 2.0 + lean * HEAD_LEAN

	_rect(canvas, feet, w, h, x, HEAD_Y, head_w, head_h, skin)

	_draw_hair(canvas, feet, w, h, x, head_w, head_h, hair, int(appearance.get("hair_style", 1)), facing, detail)

	# The face only exists when they're looking at you. Running away shows
	# the back of their head, which _draw_hair has already filled in.
	if detail != DETAIL_FULL or not faces_viewer(facing):
		return

	var eye_w := maxf(1.0, head_w * EYE_W)
	var eye_y := HEAD_Y + HEAD_H * EYE_Y
	_rect(canvas, feet, w, h, x + head_w * EYE_X_LEFT - eye_w / 2.0, eye_y, eye_w, eye_w, EYE_COLOR)
	_rect(canvas, feet, w, h, x + head_w * EYE_X_RIGHT - eye_w / 2.0, eye_y, eye_w, eye_w, EYE_COLOR)

	_draw_shape(
		canvas, feet, w, h, x, head_w, head_h,
		PlayerAppearance.face_style(int(appearance.get("face", 0))),
		PlayerAppearance.MOUTH_COLOR
	)


## Hair, whatever shape PlayerAppearance says it is. This function knows
## nothing about any particular style -- adding one is an entry in
## PlayerAppearance.HAIR_STYLES and nothing here changes.
static func _draw_hair(
	canvas: CanvasItem, feet: Vector2, w: float, h: float,
	x: float, head_w: float, head_h: float,
	hair: Color, style_index: int, facing: int, detail: int
) -> void:
	var style := PlayerAppearance.hair_style(style_index)

	if detail == DETAIL_LOW:
		# Too small for a shape to read: every style that has any hair at all
		# collapses to the same skull cap.
		if not style["parts"].is_empty():
			var cap_h := head_h * HAIR_CAP_H
			_rect(canvas, feet, w, h, x, HEAD_Y + HEAD_H - HEAD_H * HAIR_CAP_H, head_w, cap_h, hair)
		return

	_draw_shape(canvas, feet, w, h, x, head_w, head_h, style, hair)

	# Running away: what you'd actually see is the back of their head, not a
	# bald patch under the cap. A mohawk (or a bald head) says no.
	if faces_away(facing) and style.get("covers_back", true):
		_rect(canvas, feet, w, h, x, HEAD_Y + HEAD_H * HAIR_BACK_Y, head_w, head_h * HAIR_BACK_H, hair)


## Draws a PlayerAppearance shape -- a list of [x, y, w, h] parts in
## head-box fractions -- in one flat colour. Shared by hair and faces, and
## the one place that understands the format.
static func _draw_shape(
	canvas: CanvasItem, feet: Vector2, w: float, h: float,
	x: float, head_w: float, head_h: float,
	style: Dictionary, color: Color
) -> void:
	for part in style.get("parts", []):
		_rect(
			canvas, feet, w, h,
			x + head_w * float(part[0]),
			HEAD_Y + HEAD_H * float(part[1]),
			head_w * float(part[2]),
			head_h * float(part[3]),
			color
		)


static func _draw_number(
	canvas: CanvasItem, feet: Vector2, w: float, h: float,
	number: int, trim: Color, shirt: Color, font: Font, lean: float
) -> void:
	# The number sits on the shirt, so it has to contrast with the SHIRT.
	# Prefer the kit's own second colour (that's what a real shirt does),
	# and only fall back to plain black/white when the two kit colours are
	# too close to each other to read.
	var ink := trim
	if absf(trim.get_luminance() - shirt.get_luminance()) < 0.25:
		ink = Color.BLACK if shirt.get_luminance() > 0.5 else Color.WHITE

	var size_px := int(maxf(NUMBER_MIN_PX, h * NUMBER_SIZE))
	var pos := Vector2(feet.x - w * 0.5 + lean, feet.y - h * NUMBER_Y)
	canvas.draw_string(font, pos, str(number), HORIZONTAL_ALIGNMENT_CENTER, w, size_px, ink)


# ----------------------------------------------------------------- helpers

## Normalised -> screen. `nx` is an offset from the figure's centre line in
## PIXELS (already multiplied by w by the caller); `ny` is a fraction of the
## height above the feet, 0 = ground.
static func _rect(
	canvas: CanvasItem, feet: Vector2, w: float, h: float,
	nx: float, ny: float, rw: float, rh: float, color: Color
) -> void:
	canvas.draw_rect(Rect2(Vector2(feet.x + nx, feet.y - ny * h - rh), Vector2(rw, rh)), color)


static func _ellipse(canvas: CanvasItem, center: Vector2, width: float, height: float, color: Color) -> void:
	var points := PackedVector2Array()
	for i in range(12):
		var a := TAU * float(i) / 12.0
		points.append(center + Vector2(cos(a) * width * 0.5, sin(a) * height * 0.5))
	canvas.draw_colored_polygon(points, color)


## How far, and which way, the upper body leans for a given facing: -1 fully
## left (W), +1 fully right (E), 0 straight toward or away from the viewer.
## +1 for east, -1 for west, 0 for every facing that keeps the front view.
static func _side_for(facing: int) -> float:
	match facing:
		FACING_E:
			return 1.0
		FACING_W:
			return -1.0
	return 0.0


static func _lean_for(facing: int) -> float:
	match facing:
		FACING_E:
			return 1.0
		FACING_SE, FACING_NE:
			return 0.6
		FACING_W:
			return -1.0
		FACING_SW, FACING_NW:
			return -0.6
	return 0.0


static func _slot_color(appearance: Dictionary, key: String, palette: Array, fallback: Color) -> Color:
	# int(), not a bare lookup: appearance can come from a real Firestore
	# doc, and a float Variant used as an Array index is a hard runtime
	# error rather than a silent conversion.
	if not appearance.has(key):
		return fallback
	var index := int(appearance[key])
	if index < 0 or index >= palette.size():
		return fallback
	return palette[index]
