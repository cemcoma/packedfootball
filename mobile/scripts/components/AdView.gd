extends PanelContainer
class_name ShopAdView

signal watch_pressed

const CURRENCY_AMOUNT_SCENE := preload("res://scenes/components/CurrencyAmount.tscn")

@onready var _name_label: Label = %NameLabel
@onready var _description_label: Label = %DescriptionLabel
@onready var _reward_row: HBoxContainer = %RewardRow
@onready var _tag_label: Label = %TagLabel
@onready var _watch_button: Button = %WatchButton

func _ready() -> void:
	_watch_button.pressed.connect(func(): watch_pressed.emit())

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

	set_affordable(ad.available)
	
	if not ad.available:
		_tag_label.text = ad.unavailable_reason
		_tag_label.visible = true
	else:
		_tag_label.visible = false

func _add_reward_amount(currency: String, amount: int) -> void:
	var view: CurrencyAmount = CURRENCY_AMOUNT_SCENE.instantiate()
	_reward_row.add_child(view)
	view.set_amount(currency, amount)
	view.set_sizes(16, 12)

func set_affordable(is_affordable: bool) -> void:
	_watch_button.disabled = not is_affordable
