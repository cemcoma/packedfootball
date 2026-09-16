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
const LEG_H := 0.23
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
const SHADOW_W_FLASH := 1.6      # wider when an action colour is on it
const SHADOW_H_FLASH := 0.3      # wider when an action colour is on it
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

# Keeper at full stretch. Absolute, NOT derived from the torso -- the point
# of a dive is that the arms are thrown well clear of the body. Keep it
# above arm_spread() or a diving keeper looks like a standing one.
const REACH_SPREAD := 0.62
const REACH_Y := 0.66
const REACH_H := 0.10
const REACH_SPAN := 1.60          # multiple of ARM_W
const REACH_GLOVE := 0.45         # fraction of the arm that is glove

const CELEBRATE_FLARE := 0.02     # how far raised arms sit OUTSIDE arm_spread()
const CELEBRATE_ARM_Y := 0.62
const CELEBRATE_ARM_H := 0.26
const CELEBRATE_HAND_H := 0.06
const CELEBRATE_WAVE_W := 0.14    # how far the arms sway
const CELEBRATE_WAVE_SPEED := 2.20

const SOCK_DARKEN := 0.55         # how much darker the sock is than the boot

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
const BUILD_SHORTEST := 0.88
const BUILD_TALLEST := 1.14
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


static func faces_viewer(facing: int) -> bool:
	return facing in FACINGS_TOWARD


static func faces_away(facing: int) -> bool:
	return facing in FACINGS_AWAY


## Draws one player standing at `feet`, `height_px` tall before `build`.
##
## `build` is Vector2(width, height) multipliers -- see build_from(). `phase`
## drives the run cycle (pass the playback tick plus something per-player so
## 22 figures don't march in lockstep); `flash` is the action colour from the
## replay event stream, drawn as a ground marker so the legend still means
## what it says without repainting the whole shirt.
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
	build: Vector2 = Vector2.ONE
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

	# 3/4 lean: shift the upper body toward where they're looking, which is
	# most of what sells a direction on a figure this blocky.
	var lean := _lean_for(facing) * w * LEAN

	var swing := 0.0
	if pose == POSE_RUN:
		swing = sin(phase) * RUN_SWING

	_draw_legs(canvas, feet, w, h, boots, trim, pose, swing, lean)
	_draw_torso(canvas, feet, w, h, shirt, trim, pattern, pose, lean, detail)
	_draw_arms(canvas, feet, w, h, trim, skin, pose, swing, lean, phase, is_keeper)
	_draw_head(canvas, feet, w, h, skin, hair, appearance, facing, lean, detail)

	if detail == DETAIL_FULL and number > 0 and faces_away(facing) and font != null:
		_draw_number(canvas, feet, w, h, number, trim, shirt, font, lean)


# ------------------------------------------------------------------ layers

## Boots, legs and shorts. A `lift` raises that leg -- toward the viewer is
## "forward" in this pseudo-top-down view, so a raised leg reads as a stride
## or a kick. Lifts are fractions of height, like every other Y here.
static func _draw_legs(
	canvas: CanvasItem, feet: Vector2, w: float, h: float,
	boots: Color, shorts: Color, pose: String, swing: float, lean: float
) -> void:
	var leg_w := w * LEG_W
	var left_x := -w * LEG_SPREAD
	var right_x := w * LEG_SPREAD - leg_w

	var left_lift := 0.0
	var right_lift := 0.0
	match pose:
		POSE_RUN:
			left_lift = swing
			right_lift = -swing
		POSE_KICK:
			left_lift = LIFT_KICK
		POSE_LUNGE:
			left_lift = LIFT_LUNGE_FRONT
			right_lift = LIFT_LUNGE_BACK
		POSE_REACH:
			left_lift = LIFT_REACH
			right_lift = LIFT_REACH

	for side in [[left_x, left_lift], [right_x, right_lift]]:
		var x: float = side[0] + lean * LEG_LEAN
		var lift: float = side[1]
		_rect(canvas, feet, w, h, x, BOOT_Y + lift, leg_w, h * BOOT_H, boots)
		_rect(canvas, feet, w, h, x, LEG_Y + lift, leg_w, h * LEG_H, boots.lerp(Color.BLACK, SOCK_DARKEN))

	# Shorts last: they overlap the top of both legs, which is what hides
	# the seam when one leg is lifted.
	_rect(canvas, feet, w, h, -w * SHORTS_W / 2.0, SHORTS_Y, w * SHORTS_W, h * SHORTS_H, shorts)


static func _draw_torso(
	canvas: CanvasItem, feet: Vector2, w: float, h: float,
	shirt: Color, trim: Color, pattern: String, pose: String, lean: float, detail: int
) -> void:
	var torso_w := w * TORSO_W
	var torso_h := h * TORSO_H
	var x := -torso_w / 2.0 + lean
	var base_y := TORSO_Y + (TORSO_LUNGE_TILT if pose == POSE_LUNGE else 0.0)

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

	# Collar, sitting just inside the top of the torso -- it is what makes a
	# SOLID kit still read as two colours rather than one flat block.
	if detail == DETAIL_FULL:
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
	phase: float = 0.0, is_keeper: bool = false
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

	if pose == POSE_CELEBRATE:
		# Both arms up, waving. The sway is the only thing moving -- the
		# player is stationary, which is what makes it read as celebrating
		# rather than running.
		var wave := sin(phase * CELEBRATE_WAVE_SPEED) * w * CELEBRATE_WAVE_W
		var celebrate_spread := arm_spread() + CELEBRATE_FLARE
		for ax in [-w * celebrate_spread + lean + wave, w * celebrate_spread - arm_w + lean + wave]:
			_rect(canvas, feet, w, h, ax, CELEBRATE_ARM_Y, arm_w, h * CELEBRATE_ARM_H, sleeve)
			_rect(
				canvas, feet, w, h, ax, CELEBRATE_ARM_Y + CELEBRATE_ARM_H,
				arm_w, h * CELEBRATE_HAND_H, hand
			)
		return

	var lift := swing * ARM_SWING
	var spread := arm_spread()
	for side in [[-w * spread + lean, -lift], [w * spread - arm_w + lean, lift]]:
		var x: float = side[0]
		var dy: float = side[1]
		_rect(canvas, feet, w, h, x, ARM_Y + dy, arm_w, h * ARM_H, sleeve)
		_rect(canvas, feet, w, h, x, ARM_Y + dy - HAND_H, arm_w, h * HAND_H, hand)


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
