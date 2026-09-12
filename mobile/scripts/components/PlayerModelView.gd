class_name PlayerModelView
extends Control

## Placeholder "pixelated character" portrait -- a blocky, layered avatar
## built from _draw() primitives, the same custom-draw idiom PitchView.gd
## already uses for its grass/lines (this is inherently a drawn graphic,
## not something Control nodes model well, unlike the surrounding card
## layout which stays real Controls). Embedded only in PlayerCardView.tscn
## (replacing its old empty Spacer) -- "player models ONLY to cards", not
## the pitch slot markers or match playback.
##
## Appearance is now real: packEngine.PackManager rolls one per card at
## creation time (pack open / starter roster) and it's persisted on
## players/{id}, read back via PlayerCard.appearance. The PlayerAppearance.
## mock_from_id() fallback only still matters for a card whose doc predates
## that -- run backend/scripts/sync_player_appearance.py to backfill those
## with a real (if not random) tier-based look instead of relying on this.

var _appearance: Dictionary = {}


func set_card(card: PlayerCard) -> void:
	if card.appearance.is_empty():
		set_appearance(PlayerAppearance.mock_from_id(card.player_id))
	else:
		set_appearance(card.appearance)


func set_appearance(appearance: Dictionary) -> void:
	_appearance = appearance
	queue_redraw()


func _draw() -> void:
	if _appearance.is_empty() or size.x <= 0.0 or size.y <= 0.0:
		return

	var w: float = size.x
	var h: float = size.y
	var cx: float = w / 2.0

	# int(), not a bare Dictionary lookup -- appearance can now come from a
	# real Firestore doc (via PlayerCard.appearance) rather than only ever
	# PlayerAppearance.mock_from_id()'s guaranteed-int output, and assigning
	# a float Variant into an int-typed slot (a statically-typed var, or --
	# same rule -- an Array's integer index) is a hard runtime error, not a
	# silent conversion (see PackData.gd's _int() for the same concern
	# applied to a typed var instead of an index).
	var skin: Color = PlayerAppearance.SKIN_TONES[int(_appearance["skin_tone"])]
	var hair_color: Color = PlayerAppearance.HAIR_COLORS[int(_appearance["hair_color"])]
	var shoe_color: Color = PlayerAppearance.SHOE_COLORS[int(_appearance["shoe_color"])]

	var head_size := Vector2(w * 0.5, h * 0.32)
	var head_pos := Vector2(cx - head_size.x / 2.0, h * 0.06)

	var torso_size := Vector2(w * 0.62, h * 0.40)
	var torso_pos := Vector2(cx - torso_size.x / 2.0, head_pos.y + head_size.y - h * 0.02)

	var foot_size := Vector2(w * 0.16, h * 0.10)
	var foot_y: float = torso_pos.y + torso_size.y - h * 0.02
	var left_foot_pos := Vector2(cx - torso_size.x * 0.32, foot_y)
	var right_foot_pos := Vector2(cx + torso_size.x * 0.32 - foot_size.x, foot_y)

	draw_rect(Rect2(left_foot_pos, foot_size), shoe_color)
	draw_rect(Rect2(right_foot_pos, foot_size), shoe_color)
	draw_rect(Rect2(torso_pos, torso_size), skin)
	draw_rect(Rect2(head_pos, head_size), skin)

	_draw_hair(head_pos, head_size, cx, hair_color)
	_draw_face(head_pos, head_size, cx, w)


## Hair only ever draws in the top ~55% of the head -- however wide a given
## style bulges sideways, it never dips low enough to cover the eyes/mouth
## _draw_face() puts in the bottom half, so no style/face combination can
## visually clash regardless of which 2 of the 5x5 options land together.
func _draw_hair(head_pos: Vector2, head_size: Vector2, cx: float, hair_color: Color) -> void:
	var style: int = int(_appearance["hair_style"])
	if style == 0:
		return  # bald

	var part_y: float = head_pos.y + head_size.y * 0.55
	if style == 1:  # short cap
		draw_rect(Rect2(head_pos, Vector2(head_size.x, head_size.y * 0.3)), hair_color)
	elif style == 2:  # long -- cap plus sides down to the part line
		draw_rect(Rect2(head_pos, Vector2(head_size.x, head_size.y * 0.3)), hair_color)
		var side_w: float = head_size.x * 0.22
		var side_h: float = part_y - head_pos.y
		draw_rect(Rect2(head_pos, Vector2(side_w, side_h)), hair_color)
		draw_rect(Rect2(Vector2(head_pos.x + head_size.x - side_w, head_pos.y), Vector2(side_w, side_h)), hair_color)
	elif style == 3:  # mohawk
		var strip_w: float = head_size.x * 0.22
		var strip_h: float = head_size.y * 0.5
		draw_rect(Rect2(Vector2(cx - strip_w / 2.0, head_pos.y - strip_h * 0.35), Vector2(strip_w, strip_h)), hair_color)
	elif style == 4:  # full
		var pad: float = head_size.x * 0.2
		var full_size := Vector2(head_size.x + pad * 2.0, part_y - head_pos.y + pad * 0.5)
		draw_rect(Rect2(Vector2(head_pos.x - pad, head_pos.y - pad * 0.5), full_size), hair_color)


func _draw_face(head_pos: Vector2, head_size: Vector2, cx: float, w: float) -> void:
	var eye_color := Color(0.1, 0.1, 0.1)
	var eye_y: float = head_pos.y + head_size.y * 0.58
	var eye_dx: float = head_size.x * 0.18
	var eye_size := Vector2(head_size.x * 0.09, head_size.x * 0.09)
	draw_rect(Rect2(Vector2(cx - eye_dx - eye_size.x / 2.0, eye_y), eye_size), eye_color)
	draw_rect(Rect2(Vector2(cx + eye_dx - eye_size.x / 2.0, eye_y), eye_size), eye_color)

	var mouth_color := Color(0.25, 0.15, 0.12)
	var mouth_y: float = head_pos.y + head_size.y * 0.93
	var mouth_half_w: float = head_size.x * 0.16
	var mouth_left := Vector2(cx - mouth_half_w, mouth_y)
	var mouth_right := Vector2(cx + mouth_half_w, mouth_y)
	var lw: float = maxf(1.0, w * 0.025)

	var face: int = int(_appearance["face"])
	if face == 0:  # neutral
		draw_line(mouth_left, mouth_right, mouth_color, lw)
	elif face == 1:  # smile
		var mid := Vector2(cx, mouth_y + head_size.y * 0.06)
		draw_line(mouth_left, mid, mouth_color, lw)
		draw_line(mid, mouth_right, mouth_color, lw)
	elif face == 2:  # frown
		var mid := Vector2(cx, mouth_y - head_size.y * 0.06)
		draw_line(mouth_left, mid, mouth_color, lw)
		draw_line(mid, mouth_right, mouth_color, lw)
	elif face == 3:  # surprised
		var s: float = head_size.x * 0.1
		draw_rect(Rect2(Vector2(cx - s / 2.0, mouth_y - s / 2.0), Vector2(s, s)), mouth_color)
	elif face == 4:  # smirk
		var tip := Vector2(cx + mouth_half_w, mouth_y - head_size.y * 0.05)
		draw_line(Vector2(cx - mouth_half_w * 0.3, mouth_y), tip, mouth_color, lw)
