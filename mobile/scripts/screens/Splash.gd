extends Control

const MENU_SCENE := "res://scenes/Menu.tscn"
const AUTH_SCENE := "res://scenes/Auth.tscn"
const AuthScreen := preload("res://scripts/screens/Auth.gd")

# Shared with tools/make_splash.py.
const IMAGE_SIZE := Vector2(2400, 1100)
const LOGO_WIDTH_FRAC := 0.43
const LOGO_CENTER_Y_FRAC := 0.46
const LOGO_PAD := 90.0  # transparent px around the logo inside splash_logo.png

## Shortest time the splash stays up, so the logo never just flashes past.
const MIN_DISPLAY_SEC := 1.4
const FADE_SEC := 0.35

@onready var _logo: TextureRect = %Logo
@onready var _bar: LoadingBar = %LoadingBar
@onready var _status: Label = %StatusLabel

func _ready() -> void:
	_layout()
	resized.connect(_layout)
	_bar.modulate.a = 0.0
	_status.modulate.a = 0.0
	_play_intro()
	_boot()

func _layout() -> void:
	var view := size
	var cover := maxf(view.x / IMAGE_SIZE.x, view.y / IMAGE_SIZE.y)
	var origin := (view - IMAGE_SIZE * cover) / 2.0

	var tex_size := _logo.texture.get_size()
	var logo_scale := IMAGE_SIZE.x * LOGO_WIDTH_FRAC / (tex_size.x - 2.0 * LOGO_PAD) * cover
	_logo.size = tex_size * logo_scale
	_logo.pivot_offset = _logo.size / 2.0
	var center := origin + Vector2(IMAGE_SIZE.x / 2.0, IMAGE_SIZE.y * LOGO_CENTER_Y_FRAC) * cover
	_logo.position = center - _logo.size / 2.0

	# Bar and status hang below the visible logo, laid out against the
	# screen rather than the image so they never fall off a narrow crop.
	var logo_bottom := center.y + (tex_size.y / 2.0 - LOGO_PAD) * logo_scale
	var bar_size := Vector2(clampf(view.x * 0.34, 240.0, 420.0), 18.0)
	_bar.size = bar_size
	_bar.position = Vector2((view.x - bar_size.x) / 2.0, logo_bottom + view.y * 0.07)
	_status.size = Vector2(view.x, 24.0)
	_status.position = Vector2(0.0, _bar.position.y + bar_size.y + 8.0)

func _play_intro() -> void:
	var tw := create_tween()
	tw.tween_interval(0.15)
	tw.tween_property(_logo, "scale", Vector2(1.06, 0.94), 0.10).set_trans(Tween.TRANS_SINE)
	tw.tween_property(_logo, "scale", Vector2(0.97, 1.04), 0.12).set_trans(Tween.TRANS_SINE)
	tw.tween_property(_logo, "scale", Vector2.ONE, 0.2).set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	tw.tween_property(_bar, "modulate:a", 1.0, 0.3)
	tw.parallel().tween_property(_status, "modulate:a", 1.0, 0.3)

func _boot() -> void:
	var min_display := get_tree().create_timer(MIN_DISPLAY_SEC)
	_set_progress(0.2, tr("Checking for a saved session..."))
	var target := AUTH_SCENE
	var resumed: bool = await FirebaseAuth.try_resume_session()
	if resumed:
		_set_progress(0.55, tr("Loading your squad..."))
		var loaded: bool = await GameProfile.load_all()
		if loaded:
			IapClient.initialize_for_signed_in_user(FirebaseAuth.uid)
			target = MENU_SCENE
		else:
			AuthScreen.startup_notice = tr("Could not load your squad. Check your connection and sign in again.")
	_set_progress(1.0, tr("Kick-off!"))

	if min_display.time_left > 0.0:
		await min_display.timeout
	await get_tree().create_timer(0.25).timeout  # let the bar visibly fill
	_transition_to(target)


func _set_progress(fraction: float, status: String) -> void:
	_bar.target = fraction
	_status.text = status

func _transition_to(scene_path: String) -> void:
	var layer := CanvasLayer.new()
	layer.layer = 100
	var cover := ColorRect.new()
	cover.color = Color(0, 0, 0, 0)
	cover.mouse_filter = Control.MOUSE_FILTER_IGNORE
	layer.add_child(cover)
	get_tree().root.add_child(layer)
	cover.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)  # after add_child: needs the viewport rect

	var tw := cover.create_tween()
	tw.tween_property(cover, "color:a", 1.0, FADE_SEC)
	tw.tween_callback(get_tree().change_scene_to_file.bind(scene_path))
	tw.tween_interval(0.1)
	tw.tween_property(cover, "color:a", 0.0, FADE_SEC)
	tw.tween_callback(layer.queue_free)
