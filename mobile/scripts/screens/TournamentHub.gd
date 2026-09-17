extends Control

## Tournament hub: pick a format. Daily is real; the rest are declared but
## disabled, so the shape of what's coming is visible without pretending it
## exists.


## Formats that don't exist yet. Shown greyed out with a reason, because a
## silent absence reads as a missing feature and a disabled button with a
## label reads as a roadmap.
const COMING_SOON := [
	{"name": "Weekly League", "hint": "Seven days, bigger groups, bigger prizes."},
	{"name": "Monthly Cup", "hint": "A knockout bracket across the whole month."},
	{"name": "Seasonal", "hint": "Long-form competition with its own ranking."},
]

@onready var _daily_button: Button = %DailyButton
@onready var _daily_hint: Label = %DailyHint
@onready var _coming_soon_box: VBoxContainer = %ComingSoonBox
@onready var _back_button: Button = %BackButton


func _ready() -> void:
	_daily_button.pressed.connect(_on_daily_pressed)
	_back_button.pressed.connect(_on_back_pressed)

	_build_coming_soon()
	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()


func _build_coming_soon() -> void:
	for entry in COMING_SOON:
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 12)

		var button := Button.new()
		button.text = tr(entry["name"])
		button.custom_minimum_size = Vector2(300, 50)
		button.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
		button.add_theme_font_size_override("font_size", 18)
		button.disabled = true
		row.add_child(button)

		var hint := Label.new()
		hint.text = tr("Coming soon. %s") % tr(entry["hint"])
		hint.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		hint.size_flags_vertical = Control.SIZE_SHRINK_CENTER
		hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		hint.add_theme_font_size_override("font_size", 11)
		hint.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
		row.add_child(hint)

		_coming_soon_box.add_child(row)


func _apply_theme_colors() -> void:
	var hint := ThemeManager.color("text_hint")
	_daily_hint.add_theme_color_override("font_color", hint)
	for row in _coming_soon_box.get_children():
		for child in row.get_children():
			if child is Label:
				child.add_theme_color_override("font_color", hint)


func _on_daily_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/DailyTournament.tscn")


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Play.tscn")
