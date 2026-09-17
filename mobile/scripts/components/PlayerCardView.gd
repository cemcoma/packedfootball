class_name PlayerCardView
extends Control

## Reusable "card" visual for a PlayerCard: a tier-colored rectangle showing
## overall/position/name/tier. The actual template lives in the companion
## PlayerCardView.tscn (open it in the editor to restyle) -- this script
## only fills in the fields and forwards taps. Used everywhere a card needs
## to be shown (Team's bench grid and selected-slot detail panel,
## PackReveal's reveal animation/browse grid/stats popup) so there is
## exactly one template to redesign when real card art/a real character
## portrait exists, instead of every screen that shows a card needing its
## own update.
##
## Styling today is handled by applying a pre-loaded texture to the 
## BackgroundTexture node based on the player's tier.
##
## The "Model" child (see PlayerModelView.gd) is the placeholder layered
## character portrait -- a real appearance rolled server-side per card (see
## PlayerAppearance.gd's docstring), falling back to a mock look derived
## from player_id alone only for a card that predates that.

signal pressed

const OUT_OF_POSITION_COLOR := Color(1.0, 0.7, 0.3)  # same amber Team.gd uses for "unsaved changes"

# -- highlight ----------------------------------------------------------------
#
# The ring is TWO-TONE and that is not decoration. A card's background is a
# flat TIER colour, so any single-colour ring vanishes on some tier -- gold
# on a gold card, white on an icon card. A dark outer edge under a bright
# inner one reads against all seven.
## How round the card itself is. Everything else that traces the card's
## edge derives from this, so the corners stay concentric instead of drifting
## apart the moment one of them is nudged: a rounded rect inset by N needs a
## radius of CARD_CORNER - N to sit parallel to it, and outset by N needs
## CARD_CORNER + N.
const CARD_CORNER := 8

const RING_OUTER_WIDTH := 3
const RING_INNER_WIDTH := 2
## RingOuter sits flush with the edge; RingInner is inset 2px in the scene.
const RING_OUTER_CORNER := CARD_CORNER
const RING_INNER_CORNER := CARD_CORNER - 2
const RING_SHADE := Color(0, 0, 0, 0.55)  # the dark half of the two-tone edge

## Passed as the badge colour to mean "whatever the theme's accent is right
## now" -- a real Color can't express "unset", and a caller shouldn't have to
## re-pass a colour every time the theme flips.
const BADGE_THEME_ACCENT := Color(0, 0, 0, 0)

# The celebration glow: how far past the card's edge it sits, how hard it
# breathes, and how long one breath takes.
const GLOW_WIDTH := 4
## Must match the Glow node's negative offsets in PlayerCardView.tscn.
const GLOW_OUTSET := 5
const GLOW_MIN_ALPHA := 0.25
const GLOW_MAX_ALPHA := 0.9
const GLOW_MAX_SCALE := 1.05
const GLOW_PERIOD := 1.2

@onready var _background_texture: TextureRect = %BackgroundTexture
@onready var _overall_label: Label = %OverallLabel
@onready var _position_label: Label = %PositionLabel
@onready var _name_label: Label = %NameLabel
@onready var _tier_label: Label = %TierLabel
@onready var _tap_button: Button = %TapButton
@onready var _model_view: PlayerModelView = %Model
@onready var _highlight: Control = %Highlight
@onready var _ring_outer: Panel = %RingOuter
@onready var _ring_inner: Panel = %RingInner
@onready var _badge: Panel = %Badge
@onready var _badge_label: Label = %BadgeLabel
@onready var _glow: Panel = %Glow

var _card: PlayerCard = null

var _badge_text: String = ""
var _badge_color: Color = BADGE_THEME_ACCENT
var _glow_tween: Tween = null


func _ready() -> void:
	_tap_button.pressed.connect(_on_tap_button_pressed)
	# The ring/badge colours are baked into StyleBoxFlats here, so a
	# dark/light swap has to rebuild them -- same as CurrencyChip. A widget
	# that only uses themed Panel styles gets restyled for free; these don't.
	ThemeManager.theme_changed.connect(_restyle_highlight)
	# Scaling the glow about its middle rather than its top-left corner.
	_glow.resized.connect(func() -> void: _glow.pivot_offset = _glow.size / 2.0)


func _on_tap_button_pressed() -> void:
	pressed.emit()


func set_card(card: PlayerCard) -> void:
	_card = card
	
	if card.background_texture:
		_background_texture.texture = card.background_texture
	else:
		print("No background... %s" % _card.tier)
		_background_texture.texture = null
		
	_overall_label.text = str(card.overall())
	_position_label.text = card.position
	_name_label.text = card.display_name()
	_tier_label.text = tr(card.tier.capitalize())
	_model_view.set_card(card)
	# All three are per-CONTEXT, not per-card, and this view gets recycled
	# (PackReveal reuses instances). Clear them so a card never inherits the
	# last one's state; callers re-apply whichever apply to them.
	set_out_of_position(false)
	set_badge("")
	set_celebrating(false)


## Tints the position label amber -- used by Team.gd wherever this card is
## shown assigned to (or being considered for) a slot whose role differs
## from card.position (a "similar position" substitution -- see
## Formations.is_similar_position -- since anything else is never allowed
## to reach this screen at all). Purely a display hint; the actual 0.9x
## attribute penalty only ever applies inside gameEngine.py's match
## simulation, never to what's shown here.
func set_out_of_position(is_out_of_position: bool) -> void:
	if is_out_of_position:
		_position_label.add_theme_color_override("font_color", OUT_OF_POSITION_COLOR)
	else:
		_position_label.remove_theme_color_override("font_color")


## Marks the card with a small corner badge and a ring around its edge --
## "XI" for a player in the starting lineup, and whatever else later needs
## to be readable at a glance in a grid of near-identical cards. "" clears
## it.
##
## Replaces a modulate tint, which was wrong twice over: a tint recolours
## the tier art, the kit and the player's own skin along with it, and with
## eleven cards wearing it at once the whole grid went gold. It also fought
## PackReveal, which tweens modulate for its fade-in and resets it to white
## on a recycled card. This owns its own nodes and never touches modulate.
##
## The badge carries its own solid background rather than borrowing the
## card's, which is what keeps it legible on every tier.
func set_badge(text: String, color: Color = BADGE_THEME_ACCENT) -> void:
	_badge_text = text
	_badge_color = color
	_restyle_highlight()


## The pack-reveal flourish for the best card in a pack: a glow just outside
## the edge that breathes until it's turned off.
##
## Separate from set_badge because the two jobs are opposites -- this is
## transient and loud, that is persistent and quiet -- and they used to
## share one hook, which is how a permanent status ended up wearing a
## celebration. Runs on its own node, so PackReveal can go on tweening the
## card's own scale and modulate underneath without the two colliding.
func set_celebrating(is_celebrating: bool) -> void:
	if _glow == null:
		return  # called before _ready(); set_card() re-clears it after
	if _glow_tween != null:
		_glow_tween.kill()
		_glow_tween = null
	_glow.visible = is_celebrating
	if not is_celebrating:
		return

	_glow.add_theme_stylebox_override(
		"panel", _ring_style(GLOW_WIDTH, CARD_CORNER + GLOW_OUTSET, _highlight_color())
	)
	_glow.pivot_offset = _glow.size / 2.0
	_glow.scale = Vector2.ONE
	_glow.modulate.a = GLOW_MIN_ALPHA

	# Bound to this node, so it dies with a recycled or freed card rather
	# than ticking on against a dangling reference.
	_glow_tween = create_tween().set_loops()
	_glow_tween.set_trans(Tween.TRANS_SINE)
	_glow_tween.tween_property(_glow, "modulate:a", GLOW_MAX_ALPHA, GLOW_PERIOD * 0.5)
	_glow_tween.parallel().tween_property(_glow, "scale", Vector2.ONE * GLOW_MAX_SCALE, GLOW_PERIOD * 0.5)
	_glow_tween.tween_property(_glow, "modulate:a", GLOW_MIN_ALPHA, GLOW_PERIOD * 0.5)
	_glow_tween.parallel().tween_property(_glow, "scale", Vector2.ONE, GLOW_PERIOD * 0.5)


func _highlight_color() -> Color:
	return ThemeManager.color("accent") if _badge_color == BADGE_THEME_ACCENT else _badge_color


func _restyle_highlight() -> void:
	if _highlight == null:
		return  # set_badge() ran before _ready(); _ready() calls back here
	_highlight.visible = _badge_text != ""
	if not _highlight.visible:
		return

	var accent := _highlight_color()
	_ring_outer.add_theme_stylebox_override(
		"panel", _ring_style(RING_OUTER_WIDTH, RING_OUTER_CORNER, RING_SHADE)
	)
	_ring_inner.add_theme_stylebox_override(
		"panel", _ring_style(RING_INNER_WIDTH, RING_INNER_CORNER, accent)
	)

	var badge_style := StyleBoxFlat.new()
	badge_style.bg_color = accent
	badge_style.set_corner_radius_all(5)
	badge_style.set_border_width_all(1)
	badge_style.border_color = RING_SHADE
	_badge.add_theme_stylebox_override("panel", badge_style)

	_badge_label.text = _badge_text
	# Black or white lettering, whichever the badge's own colour can carry --
	# the accent is a pale gold in dark mode and a deep one in light, and a
	# fixed text colour is unreadable on one of them.
	_badge_label.add_theme_color_override(
		"font_color", Color.BLACK if accent.get_luminance() > 0.5 else Color.WHITE
	)


## A border with no fill -- the shape both rings and the glow are made of.
static func _ring_style(width: int, corner: int, color: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.draw_center = false
	style.set_border_width_all(width)
	style.border_color = color
	style.set_corner_radius_all(corner)
	return style
