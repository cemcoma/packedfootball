class_name KitSwatch
extends Control

## A team's kit as a small block: the pattern, not just the primary colour.
##
## The scoreboard used to be two flat ColorRects, so a striped kit and a solid
## one in the same colour were indistinguishable. Painted by
## PlayerFigure.paint_shirt, so a swatch and the shirts on the pitch agree.

## Sleeves as side strips, the fraction of the width each takes.
const SLEEVE_W := 0.18

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

	PlayerFigure.paint_shirt(self, Rect2(Vector2.ZERO, size), pattern, primary, trim)
	if pattern == KitDesign.PATTERN_SLEEVES:
		draw_rect(Rect2(0.0, 0.0, size.x * SLEEVE_W, size.y), trim)
		draw_rect(Rect2(size.x * (1.0 - SLEEVE_W), 0.0, size.x * SLEEVE_W, size.y), trim)
	elif not (pattern in KitDesign.PATTERNS) or pattern == KitDesign.PATTERN_SOLID:
		# A solid kit still reads as two colours on the pitch because of the
		# collar; this is that, as a band along the top.
		draw_rect(Rect2(0.0, 0.0, size.x, maxf(2.0, size.y * 0.22)), trim)

	draw_rect(Rect2(Vector2.ZERO, size), _border, false, 2.0)
