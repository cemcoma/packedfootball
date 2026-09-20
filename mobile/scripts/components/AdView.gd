extends PanelContainer
class_name ShopAdView

signal watch_pressed

const CURRENCY_AMOUNT_SCENE := preload("res://scenes/components/CurrencyAmount.tscn")

@onready var _name_label: Label = %NameLabel
@onready var _description_label: Label = %DescriptionLabel
@onready var _reward_row: HBoxContainer = %RewardRow
@onready var _tag_label: Label = %TagLabel
@onready var _watch_button: Button = %WatchButton
@onready var _progress_bar: ProgressBar = %ProgressBar
@onready var _progress_label: Label = %ProgressLabel
@onready var _steps_flow: HFlowContainer = %StepsFlow

# Which currency the bar is tinted with -- the first one the track pays.
var _accent_currency: String = "credits"

func _ready() -> void:
	_watch_button.pressed.connect(func(): watch_pressed.emit())
	ThemeManager.theme_changed.connect(_restyle)
	_restyle()

func set_ad_data(ad: AdData) -> void:
	_name_label.text = ad.title
	_description_label.text = ad.description
	
	# Clear old rewards
	for child in _reward_row.get_children():
		_reward_row.remove_child(child)
		child.queue_free()
		
	# Build reward row
	if ad.reward_credits > 0:
		_add_reward_amount("credits", ad.reward_credits)
	if ad.reward_bucks > 0:
		_add_reward_amount("bucks", ad.reward_bucks)
	if ad.reward_energy > 0:
		_add_reward_amount("energy", ad.reward_energy)

	_refresh_progress(ad)
	set_affordable(ad.available)
	
	if not ad.available:
		_tag_label.text = ad.unavailable_reason
		_tag_label.visible = true
	else:
		_tag_label.visible = false

## How far along today's track this account is, and -- when the steps
## actually differ -- what each one along it pays.
func _refresh_progress(ad: AdData) -> void:
	var total := maxi(ad.step_max, 1)
	var done := clampi(ad.step_current, 0, total)
	_progress_bar.max_value = total
	_progress_bar.value = done
	_progress_label.text = "%d / %d" % [done, total]

	for child in _steps_flow.get_children():
		_steps_flow.remove_child(child)
		child.queue_free()

	_accent_currency = _track_currency(ad.steps)
	_steps_flow.visible = _steps_vary(ad.steps)
	if _steps_flow.visible:
		for i in ad.steps.size():
			if i > 0:
				_steps_flow.add_child(_glyph("→"))
			var chip := _step_chip(ad.steps[i])
			# Spent steps read as history; the ones still to come stay lit.
			chip.modulate.a = 0.35 if i < done else 1.0
			_steps_flow.add_child(chip)
	_restyle()


func _step_chip(step) -> Control:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 1)
	var fields: Dictionary = step if step is Dictionary else {}
	for key in ["credits", "bucks", "energy"]:
		var amount := int(fields.get(key, 0))
		if amount <= 0:
			continue
		# A step paying two currencies needs the "+", or "500 1" reads as one
		# number followed by another rather than as a single payout.
		if row.get_child_count() > 0:
			row.add_child(_glyph("+"))
		var view: CurrencyAmount = CURRENCY_AMOUNT_SCENE.instantiate()
		row.add_child(view)
		view.set_amount(key, amount)
		view.set_sizes(11, 10)
	return row


func _glyph(text: String) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", 10)
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	return label


## A step reduced to its payout, so two can be compared without relying on
## Dictionary equality.
static func _step_key(step) -> String:
	var fields: Dictionary = step if step is Dictionary else {}
	return "%d/%d/%d" % [
		int(fields.get("credits", 0)), int(fields.get("bucks", 0)), int(fields.get("energy", 0))
	]


static func _steps_vary(steps: Array) -> bool:
	if steps.size() < 2:
		return false
	var first := _step_key(steps[0])
	for step in steps:
		if _step_key(step) != first:
			return true
	return false


static func _track_currency(steps: Array) -> String:
	for step in steps:
		var fields: Dictionary = step if step is Dictionary else {}
		for key in ["energy", "bucks", "credits"]:
			if int(fields.get(key, 0)) > 0:
				return key
	return "credits"


## The bar carries the track's colour; the labels take the Theme's, the way
## EnergyBar settled it.
func _restyle() -> void:
	if _progress_bar == null:
		return
	var accent := CurrencyDisplay.color_for(_accent_currency)

	var fill := StyleBoxFlat.new()
	fill.bg_color = accent
	fill.set_corner_radius_all(3)
	_progress_bar.add_theme_stylebox_override("fill", fill)

	var track := StyleBoxFlat.new()
	track.bg_color = Color(accent.r, accent.g, accent.b, 0.18)
	track.set_corner_radius_all(3)
	_progress_bar.add_theme_stylebox_override("background", track)


func _add_reward_amount(currency: String, amount: int) -> void:
	var view: CurrencyAmount = CURRENCY_AMOUNT_SCENE.instantiate()
	_reward_row.add_child(view)
	view.set_amount(currency, amount)
	view.set_sizes(16, 12)

func set_affordable(is_affordable: bool) -> void:
	_watch_button.disabled = not is_affordable
