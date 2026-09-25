class_name KitSwatch
extends Control

## A team's kit as a small block: the pattern, not just the primary colour.
##
## The scoreboard used to be two flat ColorRects, so a striped kit and a solid
## one in the same colour were indistinguishable. Layout mirrors
## PlayerFigure._draw_torso so a swatch and the shirts on the pitch agree.

## Matches PlayerFigure.STRIPE_COUNT -- the torso splits into
## STRIPE_COUNT * 2 + 1 bands, odd ones the contrast stripe.
const STRIPE_COUNT := PlayerFigure.STRIPE_COUNT

## Below this a stripe stops reading as one, same rule the pitch uses.
const STRIPE_MIN_PX := 1.5

var _design: KitDesign = null
var _border: Color = Color(0, 0, 0, 0.55)


func set_design(design: KitDesign) -> void:
	_design = design
	queue_redraw()


func set_border(color: Color) -> void:
	_border = color
	queue_redraw()


func _draw() -> void:
	if size.x <= 0.0 or size.y <= 0.0:
		return

	var primary := _design.primary_color() if _design != null else Color(0.2, 0.5, 1.0)
	var trim := _design.secondary_color() if _design != null else Color.WHITE
	var pattern: String = _design.pattern if _design != null else KitDesign.PATTERN_SOLID

	draw_rect(Rect2(Vector2.ZERO, size), primary)

	if pattern == KitDesign.PATTERN_STRIPES:
		var band := size.x / float(STRIPE_COUNT * 2 + 1)
		if band >= STRIPE_MIN_PX:
			for i in range(STRIPE_COUNT):
				draw_rect(Rect2(band * (i * 2 + 1), 0.0, band, size.y), trim)
	elif pattern == KitDesign.PATTERN_QUARTERS:
		var half := size * 0.5
		draw_rect(Rect2(0.0, 0.0, half.x, half.y), trim)
		draw_rect(Rect2(half.x, half.y, half.x, half.y), trim)
	else:
		# A solid kit still reads as two colours on the pitch because of the
		# collar; this is that, as a band along the top.
		draw_rect(Rect2(0.0, 0.0, size.x, maxf(2.0, size.y * 0.22)), trim)

	draw_rect(Rect2(Vector2.ZERO, size), _border, false, 2.0)
