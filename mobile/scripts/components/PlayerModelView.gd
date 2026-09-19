class_name PlayerModelView
extends Control

## The card portrait: one player, standing still, facing you.
##
## This is now a thin wrapper -- it decides WHICH player and at what size,
## and PlayerFigure.gd does the drawing. It used to own a copy of that
## geometry, from back when the pitch drew coloured discs and the models
## were "ONLY to cards, not the pitch slot markers or match playback". The
## pitch draws real figures now, so both ends share one renderer instead of
## two that drift.
##
## Appearance is real data: packEngine.PackManager rolls one per card at
## creation time (pack open / starter roster), it's persisted on
## players/{id}, and PlayerCard.appearance reads it back. The
## PlayerAppearance.mock_from_id() fallback is only a safety net for a doc
## with the field missing -- every live card has been backfilled, so it
## should never be what a player actually sees.

var _appearance: Dictionary = {}
# Idle by default -- a portrait. CustomizePlayer switches this to
# POSE_CELEBRATE to preview the celebration being picked, and then the
# figure animates: _process runs the same seconds-since-the-goal clock the
# pitch feeds PlayerFigure, looping every CELEBRATE_DURATION, so what you
# see here is what plays after a goal -- minus the ground covered, since
# a portrait runs on the spot.
var _pose: String = PlayerFigure.POSE_IDLE
var _phase: float = 0.0
# The kit this player is drawn wearing. Null means "ask GameProfile at draw
# time" -- every card shown in this client belongs to the signed-in manager,
# so their own kit is the right shirt for it.
var _kit: KitDesign = null
# Width/height multipliers from this card's own height and power -- see
# PlayerFigure.build_from. Vector2.ONE until a card is set.
var _build: Vector2 = Vector2.ONE

## How much of the frame a celebrating figure gets -- enough headroom for
## the tallest hop (Jump's bounce) and the widest arms (the aeroplane).
const CELEBRATE_FIT := 0.8


func set_card(card: PlayerCard) -> void:
	# Build before appearance: set_appearance is what triggers the redraw.
	_build = PlayerFigure.build_from(card.attributes)
	if card.appearance.is_empty():
		set_appearance(PlayerAppearance.mock_from_id(card.player_id))
	else:
		set_appearance(card.appearance)


func set_appearance(appearance: Dictionary) -> void:
	_appearance = appearance
	queue_redraw()


## Which pose the portrait stands in. POSE_CELEBRATE plays the card's
## celebration on a loop; anything else is a still.
func set_pose(pose: String) -> void:
	_pose = pose
	_phase = 0.0
	set_process(pose == PlayerFigure.POSE_CELEBRATE)
	queue_redraw()


func _ready() -> void:
	set_process(false)


func _process(delta: float) -> void:
	_phase = fmod(_phase + delta, PlayerFigure.CELEBRATE_DURATION)
	queue_redraw()


## Overrides the shirt. Only needed where the card being shown isn't the
## signed-in manager's (an opponent's squad, say) -- otherwise leave it.
func set_kit(kit: KitDesign) -> void:
	_kit = kit
	queue_redraw()


func _draw() -> void:
	if _appearance.is_empty() or size.x <= 0.0 or size.y <= 0.0:
		return

	# All the actual drawing lives in PlayerFigure now -- the same renderer
	# the match pitch uses, so a card portrait and the player running around
	# on the pitch can never drift apart, and the eventual sprite backend
	# lands in both places at once.
	#
	# This is also where the portrait gained a SHIRT: the torso used to be
	# drawn in skin colour, because kits didn't exist when this was written.
	var kit: KitDesign = _kit
	if kit == null:
		kit = GameProfile.kit_design()

	# Fit to whichever dimension runs out first, and leave room for the
	# build: a tall card would otherwise grow straight out of the frame.
	# A celebration can reach past the standing figure (arms out wide, a
	# hop), so it's drawn a little smaller to keep the whole gesture in.
	var celebrating := _pose == PlayerFigure.POSE_CELEBRATE
	var height: float = minf(
		size.y / PlayerFigure.BUILD_TALLEST,
		size.x / (PlayerFigure.ASPECT * PlayerFigure.BUILD_WIDEST)
	) * (CELEBRATE_FIT if celebrating else 1.0)
	PlayerFigure.draw_into(
		self,
		Vector2(size.x / 2.0, (size.y + height * _build.y) / 2.0),  # feet, vertically centred
		height,
		_appearance,
		kit,
		PlayerFigure.FACING_S,   # facing the viewer: it's a portrait
		_pose,
		PlayerFigure.DETAIL_FULL,
		_phase,
		0,
		Color(0, 0, 0, 0),
		null,
		false,
		_build
	)
