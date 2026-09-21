class_name PackWalkoutStage
extends Control

## The EA-style pack open: the pack shakes while a tier-coloured aura leaks
## out of it, bursts, and the player himself WALKS OUT of the light -- a
## silhouette at first, lit up as he arrives, running his own goal
## celebration (the very one the match plays, PlayerAppearance.CELEBRATIONS)
## -- before turning into his card.
##
## The aura colour IS the hint at the best card in the pack -- purple for a
## special, a cycling holo for an icon -- so setup() is always given the
## BEST pull's tier, never the card currently on screen.
##
## Art hook: every effect looks for sprites/effects/<slot>_<tier>.png, then
## <slot>_<family>.png, then <slot>.png, and falls back to a procedural
## shape when none of them exist. Slots: aura, rays, beam, spark.

const EFFECT_DIR := "res://sprites/effects"
const FALLBACK_PACK := "res://sprites/packs/StandardPack1.png"

## Per tier FAMILY: how long the buildup runs, how hard the pack shakes at
## the end of it, how strong the god-rays are (0 = none) and how many
## sparks leak out. A rarer pull gets a longer, louder hint.
const FLARE := {
	"bronze":   {"charge": 0.8, "shake": 2.0, "rays": 0.0, "sparks": 10, "holo": false},
	"silver":   {"charge": 0.9, "shake": 3.0, "rays": 0.2, "sparks": 16, "holo": false},
	"gold":     {"charge": 1.2, "shake": 4.0, "rays": 0.45, "sparks": 26, "holo": false},
	"platinum": {"charge": 1.5, "shake": 5.5, "rays": 0.6, "sparks": 34, "holo": false},
	"diamond":  {"charge": 1.8, "shake": 7.0, "rays": 0.75, "sparks": 44, "holo": false},
	"special":  {"charge": 2.1, "shake": 9.0, "rays": 0.9, "sparks": 58, "holo": false},
	"icon":     {"charge": 2.5, "shake": 11.0, "rays": 1.0, "sparks": 72, "holo": true},
}

const AURA_MIN_SCALE := 0.45
const AURA_MAX_SCALE := 1.25
const AURA_MAX_ALPHA := 0.85
const RAYS_MAX_ALPHA := 0.5
const BEAM_MAX_ALPHA := 0.75
const RAY_COUNT := 14
const RAY_SPIN := 0.5  # radians/sec at rest, faster as the charge builds
const PULSE_SPEED := 6.0
const HOLO_HUE_SPEED := 0.5
const HOLO_SAT := 0.55

## How lit the stage stays after the burst, so a walkout card doesn't rise
## out of a dead black screen.
const BLOOM_AFTER_BURST := 0.55

const WALK_SECONDS := 0.65
const WALK_FROM_Y := 150.0  # how far below its resting place a card starts
const PUNCH_SCALE := 1.06

# -- the player who walks out --------------------------------------------------
## How tall he stands in pixels: coming out of the light, and arrived.
const FIGURE_MIN_HEIGHT := 55.0
const FIGURE_MAX_HEIGHT := 200.0
## Where his feet are, measured up from the bottom of the Figure rect.
const FIGURE_FOOT_MARGIN := 60.0
const FIGURE_RUN_CYCLE := 9.0  # leg cycle of the walk out, radians/sec
## A celebration that runs/slides covers ground; this is how many pixels a
## second of that travel is worth on this stage (the pitch has its own).
const FIGURE_TRAVEL_PX := 26.0

const APPROACH_SECONDS := 0.85
const REVEAL_SECONDS := 0.3
const CELEBRATE_SECONDS := 2.6

@onready var _center: Control = %Center
@onready var _rays: TextureRect = %Rays
@onready var _aura: TextureRect = %Aura
@onready var _beam: TextureRect = %Beam
@onready var _sparks: CPUParticles2D = %Sparks
@onready var _pack: TextureRect = %PackSprite
@onready var _burst: CPUParticles2D = %Burst
@onready var _figure: Control = %Figure
@onready var _card_holder: Control = %CardHolder
@onready var _flash: ColorRect = %Flash

var _flare_color: Color = Color.WHITE
var _charge_seconds: float = 1.0
var _shake_max: float = 4.0
var _rays_strength: float = 0.0
var _holo: bool = false

# Tweened scalars; _process turns them into the actual visuals, so a
# fast-forward only ever has one property per phase to jump to the end of.
var _charge: float = 0.0
var _bloom: float = 0.0
var _beam_t: float = 0.0

# The walking-out player. Everything PlayerFigure.draw_into needs, plus
# how far along his timeline he is -- _figure_t is tweened in real time, so
# a fast-forward lands him on the held pose exactly as waiting would.
var _figure_appearance: Dictionary = {}
var _figure_recipe: Dictionary = {}
var _figure_build: Vector2 = Vector2.ONE
var _figure_kit: KitDesign = null
var _figure_pose: String = PlayerFigure.POSE_IDLE
var _figure_t: float = 0.0
var _figure_grow: float = 0.0  # 0 = far back in the light, 1 = arrived

var _time: float = 0.0
var _pack_home: Vector2 = Vector2.ZERO
var _active_tween: Tween = null
## Set by a tap: the walkout runs in several stages, and "get on with it"
## has to mean all of them, not just the one on screen.
var _rushed: bool = false


func _ready() -> void:
	_rays.draw.connect(_on_rays_draw)
	_figure.draw.connect(_on_figure_draw)
	_pack_home = _pack.position
	set_process(false)


## `tier` is the best card in the pack -- everything on this stage is
## coloured from it. Call before play_charge().
func setup(pack_texture: Texture2D, tier: String) -> void:
	var flare: Dictionary = FLARE.get(PlayerCard.tier_family(tier), FLARE["bronze"])
	_charge_seconds = flare["charge"]
	_shake_max = flare["shake"]
	_rays_strength = flare["rays"]
	_holo = flare["holo"]
	_flare_color = PlayerCard.tier_color(tier)

	_pack.texture = pack_texture if pack_texture != null else load(FALLBACK_PACK)
	_pack.visible = _pack.texture != null
	_pack.modulate = Color.WHITE
	_pack.scale = Vector2.ONE

	var glow := _radial_texture()
	_aura.texture = _effect_texture("aura", tier)
	if _aura.texture == null:
		_aura.texture = glow
	_beam.texture = _effect_texture("beam", tier)
	if _beam.texture == null:
		_beam.texture = glow
	_rays.texture = _effect_texture("rays", tier)  # null -> _on_rays_draw() draws them

	var spark: Texture2D = _effect_texture("spark", tier)
	if spark == null:
		spark = _radial_texture(16)
	_configure_particles(spark, int(flare["sparks"]))

	_flash.color = Color(_flare_color.lightened(0.65), 1.0)
	_flash.modulate.a = 0.0
	set_process(true)


## Puts a card on the stage HIDDEN, for walk_out() to bring up later. It
## has to be in the tree before PlayerCardView.set_card() can fill it in,
## which is long before it should be seen -- the player walks out first.
func add_card(view: Control) -> void:
	view.modulate.a = 0.0
	_card_holder.add_child(view)


# -- phases --------------------------------------------------------------------

## The pack drops in, then the buildup: shake + aura + sparks, ramping to
## the burst. One Tween for both so a tap fast-forwards the lot.
func play_charge() -> void:
	_pack.modulate.a = 0.0
	_pack.scale = Vector2.ONE * 0.7

	var tween := create_tween()
	_active_tween = tween
	tween.tween_property(_pack, "modulate:a", 1.0, 0.18)
	tween.parallel().tween_property(_pack, "scale", Vector2.ONE, 0.3) \
		.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	tween.tween_callback(func() -> void: _sparks.emitting = true)
	tween.tween_property(self, "_charge", 1.0, _charge_seconds) \
		.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_IN)
	await tween.finished
	_active_tween = null


## The pack blows apart into a tier-coloured flash, leaving the stage lit
## (BLOOM_AFTER_BURST) for whatever walks out of it.
func play_burst() -> void:
	_sparks.emitting = false
	_burst.restart()
	_burst.emitting = true

	var tween := create_tween()
	_active_tween = tween
	tween.tween_property(_flash, "modulate:a", 1.0, 0.09)
	tween.parallel().tween_property(_pack, "scale", Vector2.ONE * 1.6, 0.16) \
		.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_IN)
	tween.parallel().tween_property(_pack, "modulate:a", 0.0, 0.16)
	tween.tween_callback(_on_pack_gone)
	tween.tween_property(_flash, "modulate:a", 0.0, 0.4)
	await tween.finished
	_active_tween = null


func _on_pack_gone() -> void:
	_pack.visible = false
	_charge = 0.0
	_bloom = BLOOM_AFTER_BURST


## The walkout: the player comes up the beam as a silhouette, the light
## catches him, and he plays his own goal celebration -- the same recipe,
## off the same card, that the match uses when he scores.
func player_walkout(card: PlayerCard) -> void:
	_figure_appearance = card.resolved_appearance()
	_figure_recipe = PlayerAppearance.celebration(int(_figure_appearance.get("celebration", 0)))
	_figure_build = PlayerFigure.build_from(card.attributes)
	_figure_kit = GameProfile.kit_design()
	_figure_pose = PlayerFigure.POSE_RUN
	_figure_t = 0.0
	_figure_grow = 0.0
	_figure.modulate = Color(0.0, 0.0, 0.0, 0.0)  # black: a shape in the light, not a man yet
	_figure.visible = true
	_rushed = false

	var walk := create_tween()
	_active_tween = walk
	walk.set_parallel(true)
	walk.tween_property(self, "_beam_t", 1.0, 0.3)
	walk.tween_property(_figure, "modulate:a", 1.0, 0.3)
	walk.tween_property(self, "_figure_grow", 1.0, APPROACH_SECONDS) \
		.set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_OUT)
	walk.tween_property(self, "_figure_t", APPROACH_SECONDS, APPROACH_SECONDS)
	await walk.finished

	if not _rushed:
		var reveal := create_tween()
		_active_tween = reveal
		reveal.tween_property(_figure, "modulate", Color.WHITE, REVEAL_SECONDS)
		await reveal.finished
	_figure.modulate = Color.WHITE
	_figure_grow = 1.0

	# POSE_CELEBRATE reads `phase` as seconds since the goal and runs the
	# whole timeline off it (run-up, leap, slide, held pose), so tweening
	# the clock in real time IS the celebration.
	_figure_pose = PlayerFigure.POSE_CELEBRATE
	_figure_t = 0.0
	if _rushed:
		_figure_t = CELEBRATE_SECONDS  # straight to the held pose
		_active_tween = null
		return

	var celebrate := create_tween()
	_active_tween = celebrate
	celebrate.tween_property(self, "_figure_t", CELEBRATE_SECONDS, CELEBRATE_SECONDS)
	await celebrate.finished
	_active_tween = null


## The card forms where the player stood -- he dissolves into it as it
## rises, overshoots and lands. `view` must already be on the stage (see
## add_card).
func walk_out(view: Control, target_scale: Vector2) -> void:
	var home: Vector2 = -view.custom_minimum_size / 2.0
	view.pivot_offset = view.custom_minimum_size / 2.0
	view.position = home + Vector2(0.0, WALK_FROM_Y)
	view.scale = target_scale * 0.35
	view.modulate.a = 0.0

	var tween := create_tween()
	_active_tween = tween
	tween.set_parallel(true)
	tween.tween_property(self, "_beam_t", 1.0, 0.3)
	tween.tween_property(view, "position", home, WALK_SECONDS) \
		.set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	tween.tween_property(view, "scale", target_scale, WALK_SECONDS) \
		.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	tween.tween_property(view, "modulate:a", 1.0, 0.25)
	tween.tween_property(_figure, "modulate:a", 0.0, 0.35)
	await tween.finished
	_figure.visible = false

	var punch := create_tween()
	_active_tween = punch
	punch.tween_property(view, "scale", target_scale * PUNCH_SCALE, 0.09)
	punch.tween_property(view, "scale", target_scale, 0.16)
	await punch.finished
	_active_tween = null


## Clears a card off the stage to make room for the next walkout.
func put_away(view: Control) -> void:
	var tween := create_tween()
	_active_tween = tween
	tween.set_parallel(true)
	tween.tween_property(view, "modulate:a", 0.0, 0.22)
	tween.tween_property(view, "scale", view.scale * 0.7, 0.22)
	tween.tween_property(view, "position", view.position - Vector2(0.0, 40.0), 0.22)
	tween.tween_property(self, "_beam_t", 0.0, 0.22)
	await tween.finished
	_active_tween = null


## A tap means "get on with it": the running phase jumps to its end. A
## killed Tween never fires `finished`, so this steps it to completion
## instead -- whatever is awaiting it still resumes.
func fast_forward() -> void:
	_rushed = true
	if _active_tween != null and _active_tween.is_valid():
		_active_tween.custom_step(9999.0)


func dismiss() -> void:
	set_process(false)
	_figure.visible = false
	_sparks.emitting = false
	_burst.emitting = false
	visible = false


# -- drawing -------------------------------------------------------------------

func _process(delta: float) -> void:
	_time += delta
	if _holo:
		_flare_color = Color.from_hsv(fposmod(_time * HOLO_HUE_SPEED, 1.0), HOLO_SAT, 1.0)
		_sparks.color = _flare_color
		_burst.color = _flare_color

	var glow: float = maxf(_charge, _bloom)
	var pulse: float = 1.0 + sin(_time * PULSE_SPEED) * 0.05

	_aura.modulate = Color(_flare_color, glow * AURA_MAX_ALPHA)
	_aura.scale = Vector2.ONE * (lerpf(AURA_MIN_SCALE, AURA_MAX_SCALE, glow) * pulse)

	_rays.visible = _rays_strength > 0.0 and glow > 0.0
	if _rays.visible:
		_rays.rotation += delta * RAY_SPIN * (0.4 + glow)
		_rays.modulate = Color(_flare_color, glow * _rays_strength * RAYS_MAX_ALPHA)
		if _holo:
			_rays.queue_redraw()

	_beam.visible = _beam_t > 0.0
	if _beam.visible:
		_beam.modulate = Color(_flare_color, _beam_t * BEAM_MAX_ALPHA)
		_beam.scale = Vector2(lerpf(0.5, 1.0, _beam_t), _beam_t)

	if _figure.visible:
		_figure.queue_redraw()  # every frame: the pose is animating

	if _pack.visible:
		# Squared so the shake stays still at first and only rattles hard
		# right before the burst.
		var amount: float = _charge * _charge * _shake_max
		_pack.position = _pack_home + Vector2(randf_range(-1.0, 1.0), randf_range(-1.0, 1.0)) * amount


## The walking-out player, drawn by the same renderer as the match pitch
## and the card portraits -- so his build, kit, face and celebration are
## the card's own, not a stand-in.
func _on_figure_draw() -> void:
	if _figure_appearance.is_empty():
		return

	var travel: float = 0.0
	if _figure_pose == PlayerFigure.POSE_CELEBRATE:
		travel = PlayerFigure.celebration_state(_figure_recipe, _figure_t).travel
	var feet := Vector2(
		_figure.size.x / 2.0,
		minf(_figure.size.y, _figure.size.y - FIGURE_FOOT_MARGIN + travel * FIGURE_TRAVEL_PX)
	)
	# POSE_RUN wants a leg-cycle angle, POSE_CELEBRATE wants seconds.
	var phase: float = _figure_t
	if _figure_pose != PlayerFigure.POSE_CELEBRATE:
		phase *= FIGURE_RUN_CYCLE

	PlayerFigure.draw_into(
		_figure,
		feet,
		lerpf(FIGURE_MIN_HEIGHT, FIGURE_MAX_HEIGHT, _figure_grow),
		_figure_appearance,
		_figure_kit,
		PlayerFigure.FACING_S,  # facing the player who opened the pack
		_figure_pose,
		PlayerFigure.DETAIL_FULL,
		phase,
		0,
		Color(0, 0, 0, 0),
		null,
		false,
		_figure_build
	)


## Only runs when no rays_*.png was found -- a spinning pinwheel of flat
## wedges, which is all the sprite would be anyway.
func _on_rays_draw() -> void:
	if _rays.texture != null:
		return
	var center: Vector2 = _rays.size / 2.0
	var radius: float = minf(center.x, center.y)
	var half: float = TAU / float(RAY_COUNT) * 0.3
	for i in RAY_COUNT:
		var angle: float = TAU * float(i) / float(RAY_COUNT)
		_rays.draw_colored_polygon(PackedVector2Array([
			center,
			center + Vector2(radius, 0.0).rotated(angle - half),
			center + Vector2(radius, 0.0).rotated(angle + half),
		]), Color.WHITE)


func _configure_particles(spark: Texture2D, amount: int) -> void:
	_sparks.texture = spark
	_sparks.amount = amount
	_sparks.color = _flare_color
	_sparks.emission_shape = CPUParticles2D.EMISSION_SHAPE_RECTANGLE
	_sparks.emission_rect_extents = _pack.size / 2.0

	_burst.texture = spark
	_burst.amount = amount * 2
	_burst.color = _flare_color


# -- art lookup ----------------------------------------------------------------

## Most specific wins: aura_special_champ.png, then aura_special.png, then
## aura.png. null means "nothing supplied -- draw it procedurally".
static func _effect_texture(slot: String, tier: String) -> Texture2D:
	for name in [
		"%s_%s" % [slot, tier],
		"%s_%s" % [slot, PlayerCard.tier_family(tier)],
		slot,
	]:
		var path := "%s/%s.png" % [EFFECT_DIR, name]
		if ResourceLoader.exists(path):
			return load(path)
	return null


## White in the middle fading to nothing at the edge -- the stand-in for
## every soft glow on this stage, tinted by whatever draws it.
static func _radial_texture(size: int = 256) -> GradientTexture2D:
	var gradient := Gradient.new()
	gradient.offsets = PackedFloat32Array([0.0, 0.35, 1.0])
	gradient.colors = PackedColorArray([
		Color(1, 1, 1, 1), Color(1, 1, 1, 0.5), Color(1, 1, 1, 0)
	])

	var texture := GradientTexture2D.new()
	texture.gradient = gradient
	texture.fill = GradientTexture2D.FILL_RADIAL
	texture.fill_from = Vector2(0.5, 0.5)
	texture.fill_to = Vector2(1.0, 0.5)
	texture.width = size
	texture.height = size
	return texture
