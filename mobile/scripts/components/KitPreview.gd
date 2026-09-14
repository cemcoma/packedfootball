class_name KitPreview
extends Control

## Draws a shirt for a KitDesign. Pure _draw(), like PitchView -- a shirt is
## a shape, not something Control nodes model.
##
## Geometry is written in a normalised 0..1 box and scaled to whatever size
## this control is given, so the same code draws the big preview on the
## Customize Kit screen and (later) a thumbnail anywhere else.
##
## Patterns live in one place, _draw_torso(): add a branch there and a name
## to KitDesign.PATTERNS and the new pattern is pickable everywhere, with no
## other file touched.

const STRIPE_COUNT := 7  # vertical bars across the torso, odd so it's symmetric

# Normalised shirt, y downward. The torso is a rect so patterns can be drawn
# as plain clipped rects; the sleeves are polygons.
const TORSO := Rect2(0.28, 0.12, 0.44, 0.80)
const SLEEVE_LEFT := [
	Vector2(0.28, 0.12), Vector2(0.09, 0.30), Vector2(0.09, 0.52), Vector2(0.28, 0.44),
]
const SLEEVE_RIGHT := [
	Vector2(0.72, 0.12), Vector2(0.91, 0.30), Vector2(0.91, 0.52), Vector2(0.72, 0.44),
]
const COLLAR := [
	Vector2(0.42, 0.12), Vector2(0.50, 0.24), Vector2(0.58, 0.12),
]

var design: KitDesign = KitDesign.new()

var _outline: Color = Color(0.5, 0.5, 0.55)


func _ready() -> void:
	ThemeManager.theme_changed.connect(_refresh_outline)
	_refresh_outline()


func set_design(new_design: KitDesign) -> void:
	design = new_design if new_design != null else KitDesign.new()
	queue_redraw()


## A white kit on a light background (or a black one on the dark backdrop)
## is otherwise a shirt-shaped hole -- the outline is what keeps it a shirt.
func _refresh_outline() -> void:
	_outline = ThemeManager.color("surface_border")
	queue_redraw()


func _scaled(point: Vector2) -> Vector2:
	return Vector2(point.x * size.x, point.y * size.y)


func _scaled_polygon(points: Array) -> PackedVector2Array:
	var out := PackedVector2Array()
	for point in points:
		out.append(_scaled(point))
	return out


func _scaled_rect(rect: Rect2) -> Rect2:
	return Rect2(_scaled(rect.position), Vector2(rect.size.x * size.x, rect.size.y * size.y))


func _draw() -> void:
	var primary := design.primary_color()
	var secondary := design.secondary_color()

	# Sleeves and collar always take the secondary color, which is what
	# makes a two-color kit read as two-color even on the solid pattern.
	for sleeve in [SLEEVE_LEFT, SLEEVE_RIGHT]:
		var points := _scaled_polygon(sleeve)
		draw_colored_polygon(points, secondary)
		_draw_outline(points)

	_draw_torso(primary, secondary)

	var collar := _scaled_polygon(COLLAR)
	draw_colored_polygon(collar, secondary)
	_draw_outline(collar)


func _draw_torso(primary: Color, secondary: Color) -> void:
	var torso := _scaled_rect(TORSO)

	match design.pattern:
		KitDesign.PATTERN_STRIPES:
			var stripe_width := torso.size.x / float(STRIPE_COUNT)
			for i in range(STRIPE_COUNT):
				# The last stripe takes whatever width is left over, so
				# rounding can't leave a sliver of background showing.
				var width := stripe_width
				if i == STRIPE_COUNT - 1:
					width = torso.position.x + torso.size.x - (torso.position.x + stripe_width * i)
				var bar := Rect2(
					Vector2(torso.position.x + stripe_width * i, torso.position.y),
					Vector2(width, torso.size.y)
				)
				draw_rect(bar, secondary if i % 2 == 1 else primary)
		_:
			# Solid, and the fallback for a pattern this build doesn't know.
			draw_rect(torso, primary)

	draw_rect(torso, _outline, false, 1.5)


func _draw_outline(points: PackedVector2Array) -> void:
	var closed := points.duplicate()
	closed.append(points[0])
	draw_polyline(closed, _outline, 1.5)
