class_name KitPreview
extends Control

## The Customize Kit screen's preview: a player wearing the kit you're
## editing.
##
## It used to draw a floating shirt on its own. It shows the whole figure
## now for one reason -- this is the screen where customization is sold, so
## it has to show what you are actually buying: the thing other managers see
## running around during a match, drawn by the very same renderer
## (PlayerFigure.gd) the pitch uses. A shirt on its own can look great and
## still read as nothing at player size.
##
## The body underneath is deliberately a FIXED, neutral look rather than one
## of your cards: the subject here is the kit, and having the model's hair
## change between visits would be a distraction (and there is no single
## "your player" to pick -- a manager owns a squad, not an avatar).

## Neutral model. Indices into PlayerAppearance's palettes.
const PREVIEW_APPEARANCE := {
	"skin_tone": 1,
	"hair_style": 1,
	"hair_color": 0,
	"face": 1,
	"shoe_color": 0,
}

var design: KitDesign = KitDesign.new()

var _outline: Color = Color(0.5, 0.5, 0.55)


func _ready() -> void:
	ThemeManager.theme_changed.connect(_refresh_outline)
	_refresh_outline()


func set_design(new_design: KitDesign) -> void:
	design = new_design if new_design != null else KitDesign.new()
	queue_redraw()


## A white kit on a light background (or a black one on the dark backdrop)
## would otherwise be a player-shaped hole -- the ground shadow and this
## outline are what keep it a figure.
func _refresh_outline() -> void:
	_outline = ThemeManager.color("surface_border")
	queue_redraw()


func _draw() -> void:
	if size.x <= 0.0 or size.y <= 0.0:
		return

	# Leave room under the feet for the ground shadow PlayerFigure draws.
	var height: float = minf(size.y * 0.92, size.x / PlayerFigure.ASPECT)
	var feet := Vector2(size.x / 2.0, (size.y + height) / 2.0)

	PlayerFigure.draw_into(
		self,
		feet,
		height,
		PREVIEW_APPEARANCE,
		design,
		PlayerFigure.FACING_S,
		PlayerFigure.POSE_IDLE,
		PlayerFigure.DETAIL_FULL
	)

	# A floor line, so the figure reads as standing rather than hanging.
	draw_line(
		Vector2(feet.x - height * PlayerFigure.ASPECT * 0.7, feet.y + height * 0.06),
		Vector2(feet.x + height * PlayerFigure.ASPECT * 0.7, feet.y + height * 0.06),
		Color(_outline, 0.5),
		1.0
	)
