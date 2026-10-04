class_name PitchDraw
extends RefCounted

## The pitch itself: grass, markings, goals and the pitch-space -> pixel
## camera. Static, and drawn into whatever CanvasItem the caller passes, so
## the match replay and the penalty shootout draw the SAME pitch rather than
## two that drift apart.
##
## Extracted from MatchPlayback, which still owns everything that moves --
## players, ball, trails, banners. This is only the ground they stand on.
##
## Dimensions are gameEngine.py's, ported 1:1: a 70x100 pitch, an 18-deep
## penalty area 42 wide, a 5.5-deep six-yard box, and a goal 7.5 wide and 2
## deep centred on x = 35 (game_config.GOAL_WIDTH).

const PITCH_WIDTH := 70.0
const PITCH_HEIGHT := 100.0

const GOAL_HALF_WIDTH_UNITS := 3.75
const GOAL_DEPTH_UNITS := 2.0
const GOAL_CENTRE_X := 35.0

## How far past each goal line the camera may show. Has to cover the goal
## itself (2 units deep, drawn at y -2..0 and 100..102) plus a figure's worth
## of overhang, since a keeper on their line is drawn upward from it.
const CAMERA_MARGIN_UNITS := 4.5
## ...and past each touchline, so a ball rolling out for a throw-in stays in
## frame instead of stopping at the screen's edge.
const CAMERA_SIDE_MARGIN_UNITS := 2.0
## Tightened from 45 when players became figures rather than dots: at 45 a
## character is 38px and the customization nobody can see isn't worth selling.
## 36 puts it at ~48px while still showing most of the pitch's width.
const ZOOM_VISIBLE_Y_SPAN := 36.0

const GRASS_COLOR := Color(0.09, 0.47, 0.22)
const LINE_COLOR := Color(1.0, 1.0, 1.0, 0.9)
const LINE_WIDTH := 1.5

## Below this a box has no useful area to map into.
const MIN_DRAW := 8.0


## The camera for a box of `box` pixels looking at `ball_pos`.
##
## "full" fits the whole pitch plus the margin behind each goal line, so both
## goals and both keepers are in frame rather than cropped at y=0/100.
## "zoom" follows the ball at a fixed vertical span.
## `flip` turns the view 180 degrees (the second half's change of ends).
static func compute_camera(
	box: Vector2, ball_pos: Vector2, mode: String = "zoom", flip: bool = false
) -> Dictionary:
	var cam := _compute_camera_unflipped(box, flip_point(ball_pos) if flip else ball_pos, mode)
	cam["flip"] = flip
	return cam


## Pitch point turned 180 degrees about the centre spot.
static func flip_point(p: Vector2) -> Vector2:
	return Vector2(PITCH_WIDTH - p.x, PITCH_HEIGHT - p.y)


static func _compute_camera_unflipped(box: Vector2, ball_pos: Vector2, mode: String) -> Dictionary:
	var w := box.x
	var h := box.y
	if w < MIN_DRAW or h < MIN_DRAW:
		return {"scale": 1.0, "cam_x": 0.0, "cam_y": 0.0}

	if mode == "full":
		var full_height := PITCH_HEIGHT + CAMERA_MARGIN_UNITS * 2.0
		var fit := minf(w / PITCH_WIDTH, h / full_height)
		var offset_x := (w - PITCH_WIDTH * fit) / 2.0
		var offset_y := (h - full_height * fit) / 2.0
		return {
			"scale": fit,
			"cam_x": -offset_x / fit,
			"cam_y": -offset_y / fit - CAMERA_MARGIN_UNITS,
		}

	var visible_y_span := ZOOM_VISIBLE_Y_SPAN
	var visible_x_span := visible_y_span * (w / h)
	var scale := h / visible_y_span

	var cam_x: float
	if visible_x_span >= PITCH_WIDTH:
		# Wider than the pitch, so there is nothing to pan: centre on the
		# midline. Clamping a span wider than its own bounds gives a negative
		# upper bound, which collapses to 0 and pins the pitch flush left with
		# all the spare width bunched on the right.
		cam_x = (PITCH_WIDTH - visible_x_span) / 2.0
	else:
		cam_x = clampf(
			ball_pos.x - visible_x_span / 2.0,
			-CAMERA_SIDE_MARGIN_UNITS,
			PITCH_WIDTH + CAMERA_SIDE_MARGIN_UNITS - visible_x_span
		)
	# The vertical clamp runs CAMERA_MARGIN_UNITS past each end, which is what
	# puts the keeper, the goal and a ball in the net on screen.
	var cam_y := clampf(
		ball_pos.y - visible_y_span / 2.0,
		-CAMERA_MARGIN_UNITS,
		maxf(-CAMERA_MARGIN_UNITS, PITCH_HEIGHT + CAMERA_MARGIN_UNITS - visible_y_span)
	)
	return {"scale": scale, "cam_x": cam_x, "cam_y": cam_y}


## A camera showing `y_span` units of pitch down the screen, starting at
## `top_y`, centred on `centre_x`.
##
## What a set piece wants, and why it is not compute_camera: a penalty has no
## ball to follow and a fixed region worth seeing. Fitting by HEIGHT is what
## keeps the figures a readable size on a tall phone -- fitting the penalty
## area by width instead put the whole scene in the top fifth of the screen
## with the rest empty grass. The sides of the box fall outside the view on a
## narrow screen, which costs nothing: nothing happens out there.
static func camera_for_span(
	box: Vector2, centre_x: float, y_span: float, top_y: float
) -> Dictionary:
	if box.x < MIN_DRAW or box.y < MIN_DRAW or y_span <= 0.0:
		return {"scale": 1.0, "cam_x": 0.0, "cam_y": 0.0}

	var scale := box.y / y_span
	var visible_x_span := box.x / scale
	var cam_x: float
	if visible_x_span >= PITCH_WIDTH:
		# Wider than the pitch: centre on the midline rather than clamp, which
		# would pin it flush to one edge (see compute_camera).
		cam_x = (PITCH_WIDTH - visible_x_span) / 2.0
	else:
		cam_x = clampf(
			centre_x - visible_x_span / 2.0,
			-CAMERA_SIDE_MARGIN_UNITS,
			PITCH_WIDTH + CAMERA_SIDE_MARGIN_UNITS - visible_x_span
		)
	return {"scale": scale, "cam_x": cam_x, "cam_y": top_y}


## Pitch units -> the canvas's own local pixels. (0, 0) is the drawing box's
## top-left, not the screen's, so a caller wanting nothing outside its bounds
## sets clip_contents on the node it draws into.
static func to_screen(p: Vector2, cam: Dictionary) -> Vector2:
	# cam's values come back typed as Variant (Dictionary access), which
	# GDScript's type inference can't resolve through an operator like `*`.
	var scale: float = cam.scale
	var cam_x: float = cam.cam_x
	var cam_y: float = cam.cam_y
	if cam.get("flip", false):
		p = flip_point(p)
	return Vector2((p.x - cam_x) * scale, (p.y - cam_y) * scale)


## Grass, markings, both goals and the corner arcs -- the whole ground, in the
## order it has to be drawn. `box` is the canvas's size, for the grass fill.
static func draw_pitch(canvas: CanvasItem, cam: Dictionary, box: Vector2) -> void:
	canvas.draw_rect(Rect2(Vector2.ZERO, box), GRASS_COLOR)
	draw_lines(canvas, cam)
	draw_goal(canvas, cam, 0.0, -1.0)
	draw_goal(canvas, cam, PITCH_HEIGHT, 1.0)
	draw_corner_quarter(canvas, cam, Vector2(0, 0), 0.0, PI / 2.0)
	draw_corner_quarter(canvas, cam, Vector2(PITCH_WIDTH, 0), PI / 2.0, PI)
	draw_corner_quarter(canvas, cam, Vector2(PITCH_WIDTH, PITCH_HEIGHT), PI, 3.0 * PI / 2.0)
	draw_corner_quarter(canvas, cam, Vector2(0, PITCH_HEIGHT), -PI / 2.0, 0.0)


## Outline of a pitch-space rect, matching gameEngine.py's render() helper.
## Both corners are transformed rather than one plus a size, so the rect is
## right whichever way the camera reads the axes.
static func draw_rect_outline(
	canvas: CanvasItem, cam: Dictionary, px: float, py: float, pw: float, ph: float,
	color: Color, width: float
) -> void:
	var a := to_screen(Vector2(px, py), cam)
	var b := to_screen(Vector2(px + pw, py + ph), cam)
	canvas.draw_rect(Rect2(a.min(b), (b - a).abs()), color, false, width)


static func draw_lines(canvas: CanvasItem, cam: Dictionary) -> void:
	var scale: float = cam.scale

	draw_rect_outline(canvas, cam, 0.0, 0.0, PITCH_WIDTH, PITCH_HEIGHT, LINE_COLOR, LINE_WIDTH)

	canvas.draw_line(
		to_screen(Vector2(0.0, PITCH_HEIGHT / 2.0), cam),
		to_screen(Vector2(PITCH_WIDTH, PITCH_HEIGHT / 2.0), cam),
		LINE_COLOR,
		LINE_WIDTH
	)

	var center := to_screen(Vector2(PITCH_WIDTH / 2.0, PITCH_HEIGHT / 2.0), cam)
	canvas.draw_arc(center, 9.15 * scale, 0.0, TAU, 48, LINE_COLOR, LINE_WIDTH)
	canvas.draw_circle(center, 2.0, LINE_COLOR)

	# Penalty boxes + six-yard boxes, top and bottom.
	draw_rect_outline(canvas, cam, 14.0, 0.0, 42.0, 18.0, LINE_COLOR, LINE_WIDTH)
	draw_rect_outline(canvas, cam, 26.0, 0.0, 18.0, 5.5, LINE_COLOR, LINE_WIDTH)
	draw_rect_outline(canvas, cam, 14.0, 82.0, 42.0, 18.0, LINE_COLOR, LINE_WIDTH)
	draw_rect_outline(canvas, cam, 26.0, 94.5, 18.0, 5.5, LINE_COLOR, LINE_WIDTH)


## Goal frame + netting. `goal_y` is 0 (top) or PITCH_HEIGHT (bottom);
## `depth_dir` is which way it extends beyond the boundary (-1 top, +1 bottom).
static func draw_goal(canvas: CanvasItem, cam: Dictionary, goal_y: float, depth_dir: float) -> void:
	var left_x := GOAL_CENTRE_X - GOAL_HALF_WIDTH_UNITS
	var right_x := GOAL_CENTRE_X + GOAL_HALF_WIDTH_UNITS
	var back_y := goal_y + depth_dir * GOAL_DEPTH_UNITS

	var top_left := to_screen(Vector2(left_x, goal_y), cam)
	var top_right := to_screen(Vector2(right_x, goal_y), cam)
	var back_left := to_screen(Vector2(left_x, back_y), cam)
	var back_right := to_screen(Vector2(right_x, back_y), cam)

	# Dark backing inside the goal mouth. Without it the goal is a white
	# wireframe on green and a white ball sitting in the net disappears into
	# the crosshatch -- this is what makes a goal read as a goal.
	canvas.draw_colored_polygon(
		PackedVector2Array([top_left, top_right, back_right, back_left]),
		Color(0.05, 0.16, 0.10, 0.55)
	)

	var net_color := Color(1.0, 1.0, 1.0, 0.35)
	var net_divisions := 5
	for i in range(net_divisions + 1):
		var t := float(i) / net_divisions
		canvas.draw_line(top_left.lerp(top_right, t), back_left.lerp(back_right, t), net_color, 1.0)
		canvas.draw_line(top_left.lerp(back_left, t), top_right.lerp(back_right, t), net_color, 1.0)

	var post_color := Color.WHITE
	canvas.draw_line(top_left, back_left, post_color, 3.0)
	canvas.draw_line(top_right, back_right, post_color, 3.0)
	canvas.draw_line(back_left, back_right, post_color, 3.0)
	canvas.draw_line(top_left, top_right, post_color, 4.0)


static func draw_corner_quarter(
	canvas: CanvasItem, cam: Dictionary, corner: Vector2, start_angle: float, end_angle: float
) -> void:
	var scale: float = cam.scale
	var base := to_screen(corner, cam)
	if cam.get("flip", false):
		start_angle += PI
		end_angle += PI
	# White and antialiased, unlike the markings -- a 2-unit arc is short
	# enough that the line colour's alpha would lose it against the grass.
	canvas.draw_arc(base, 2.0 * scale, start_angle, end_angle, 16, Color.WHITE, 2.0, true)
