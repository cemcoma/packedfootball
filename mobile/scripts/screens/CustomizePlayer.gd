extends Control

## Restyle one player, reached from Player Details. Pick a look, press Save
## Player, pay CREDITS_PER_CHANGE for each slot you actually changed.
##
## The price is per CHANGED SLOT, not per visit: new hair and new hair colour
## in one sitting is 200 credits, and pressing Save with nothing changed
## costs nothing. The running total is on screen before you commit, next to
## the balance it comes out of, so the charge is never a surprise -- which is
## also why this screen shows credits at all.
##
## Every picker is built at RUNTIME from PlayerAppearance.SLOTS, the same way
## CustomizeKit builds itself from KitDesign: slots with a palette get
## swatches, slots with shapes get named buttons, and a sixth slot added to
## that file appears here with no scene editing. Nothing in this screen knows
## what a mohawk is.
##
## The save is a backend call (POST /player/customize), not a direct write:
## it moves credits and mutates players/{id}, both of which firestore.rules
## denies the client outright. That endpoint re-derives the cost from what
## the card actually has, so the total shown here is a quote, never the
## amount charged.

## Mirrors backend/main.py's CUSTOMIZE_CREDITS_PER_SLOT. Only ever used for
## the quote shown below -- the server charges its own number.
const CREDITS_PER_CHANGE := 100

const SWATCH_SIZE := Vector2(46.0, 46.0)
const SHAPE_BUTTON_SIZE := Vector2(96.0, 40.0)
const SWATCH_CORNER := 6
const SELECTED_BORDER := 3
const UNSELECTED_BORDER := 1

@onready var _title_label: Label = %TitleLabel
@onready var _credits_chip: CurrencyChip = %CreditsChip
@onready var _preview: PlayerModelView = %Preview
@onready var _preview_caption: Label = %PreviewCaption
@onready var _options_box: VBoxContainer = %OptionsBox
@onready var _cost_label: Label = %CostLabel
@onready var _credits_texture: TextureRect = %Creditstexture
@onready var _status_label: Label = %StatusLabel
@onready var _save_button: Button = %SaveButton
@onready var _back_button: Button = %BackButton

var _card: PlayerCard = null
## What the card looked like when this screen opened -- the baseline every
## change is priced against. Reset after a successful save, so saving twice
## doesn't charge twice for the same haircut.
var _saved_appearance: Dictionary = {}
var _edited_appearance: Dictionary = {}
var _saving: bool = false

var _option_buttons: Dictionary = {}  # slot -> Array[Button]
var _headings: Array = []  # Label, recoloured on a theme swap


func _ready() -> void:
	_save_button.pressed.connect(_on_save_pressed)
	_back_button.pressed.connect(_on_back_pressed)
	_credits_chip.set_currency("credits")
	# Sourced from CurrencyDisplay rather than left to the .tscn, so the one
	# ICONS table stays the only place a logo path lives.
	_credits_texture.texture = CurrencyDisplay.icon_for("credits")

	# _refresh rather than just _apply_theme_colors: the swatch borders are
	# painted from the palette too, not only the labels.
	ThemeManager.theme_changed.connect(_refresh)

	_card = PlayerSession.card()
	if _card == null:
		_go_back()
		return

	_saved_appearance = _card.resolved_appearance()
	_edited_appearance = _saved_appearance.duplicate()

	_title_label.text = tr("Customize %s") % _card.full_name()
	_preview.set_card(_card)
	_build_options()
	_refresh()


# -- building the pickers -----------------------------------------------------


func _build_options() -> void:
	for slot in PlayerAppearance.SLOTS:
		var heading := Label.new()
		heading.text = tr(PlayerAppearance.SLOT_LABELS.get(slot, slot.capitalize()))
		heading.add_theme_font_size_override("font_size", 14)
		_options_box.add_child(heading)
		_headings.append(heading)

		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 6)
		_options_box.add_child(row)

		# A palette means swatches; no palette means this slot picks a shape,
		# which has a name worth showing instead.
		var is_color: bool = not PlayerAppearance.colors_for(slot).is_empty()
		var buttons: Array = []
		for index in range(PlayerAppearance.option_count(slot)):
			var button := Button.new()
			if is_color:
				button.custom_minimum_size = SWATCH_SIZE
				button.tooltip_text = PlayerAppearance.option_name(slot, index)
			else:
				button.custom_minimum_size = SHAPE_BUTTON_SIZE
				button.toggle_mode = true
				button.text = PlayerAppearance.option_name(slot, index)
			button.pressed.connect(_on_option_pressed.bind(slot, index))
			row.add_child(button)
			buttons.append(button)
		_option_buttons[slot] = buttons


## A flat colour applied to every button state, so the swatch doesn't wash
## out on hover -- lifted wholesale from CustomizeKit's colour grid.
func _style_swatch(button: Button, color: Color, selected: bool) -> void:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.set_corner_radius_all(SWATCH_CORNER)
	style.set_border_width_all(SELECTED_BORDER if selected else UNSELECTED_BORDER)
	style.border_color = (
		ThemeManager.color("accent") if selected else ThemeManager.color("surface_border")
	)
	for state in ["normal", "hover", "pressed", "focus", "disabled"]:
		button.add_theme_stylebox_override(state, style)


# -- state -> UI --------------------------------------------------------------


func _changed_slots() -> Array:
	var changed: Array = []
	for slot in PlayerAppearance.SLOTS:
		if _edited_appearance.get(slot) != _saved_appearance.get(slot):
			changed.append(slot)
	return changed


func _refresh() -> void:
	_preview.set_appearance(_edited_appearance)
	_credits_chip.set_amount(GameProfile.credits)
	_refresh_option_buttons()
	_refresh_cost()
	_apply_theme_colors()


func _refresh_option_buttons() -> void:
	for slot in PlayerAppearance.SLOTS:
		var buttons: Array = _option_buttons.get(slot, [])
		var colors: Array = PlayerAppearance.colors_for(slot)
		var chosen: int = _edited_appearance.get(slot, 0)
		for index in range(buttons.size()):
			var button: Button = buttons[index]
			if colors.is_empty():
				button.button_pressed = index == chosen
			else:
				_style_swatch(button, colors[index], index == chosen)


func _refresh_cost() -> void:
	var changed := _changed_slots()
	var cost: int = changed.size() * CREDITS_PER_CHANGE
	var affordable: bool = cost <= GameProfile.credits

	_preview_caption.text = "%s  ·  %s" % [_card.position, tr(_card.tier.capitalize())]

	# Every one of these ends ON THE NUMBER, because the logo sits directly
	# after this label and is what gives that number its unit -- so the
	# currency never has to be named. Nothing is appended after the amount
	# for the same reason; how much the manager actually has is the chip in
	# the header, which carries its own logo.
	if changed.is_empty():
		_cost_label.text = tr("Each change costs %s") % CurrencyDisplay.format_amount(CREDITS_PER_CHANGE)
	else:
		var names: Array = []
		for slot in changed:
			names.append(tr(PlayerAppearance.SLOT_LABELS.get(slot, slot)))
		_cost_label.text = "%s%s  ·  %s" % [
			"" if affordable else tr("Not enough for "),
			", ".join(names),
			CurrencyDisplay.format_amount(cost),
		]

	_save_button.disabled = _saving or changed.is_empty() or not affordable
	# Negative: this one is money going OUT, where Release's is money coming in.
	CurrencyDisplay.set_button_price(_save_button, tr("Save Player"), -cost)


## Labels here sit on the plain screen background rather than inside a themed
## Panel -- see ThemeManager's note on text_hint. The cost line goes amber
## when the changes cost more than the balance can cover.
func _apply_theme_colors() -> void:
	var heading := ThemeManager.color("heading")
	_title_label.add_theme_color_override("font_color", heading)
	for label in _headings:
		(label as Label).add_theme_color_override("font_color", heading)
	_preview_caption.add_theme_color_override("font_color", ThemeManager.color("text_hint"))

	var cost: int = _changed_slots().size() * CREDITS_PER_CHANGE
	_cost_label.add_theme_color_override(
		"font_color",
		ThemeManager.color("warning") if cost > GameProfile.credits
		else ThemeManager.color("text_hint")
	)


func _set_status(text: String, positive: bool = false) -> void:
	_status_label.text = text
	_status_label.add_theme_color_override(
		"font_color",
		ThemeManager.color("positive") if positive else ThemeManager.color("warning")
	)


# -- input handlers -----------------------------------------------------------


func _on_option_pressed(slot: String, index: int) -> void:
	_edited_appearance[slot] = index
	_set_status("")
	_refresh()


func _on_save_pressed() -> void:
	if _saving:
		return
	var changed := _changed_slots()
	if changed.is_empty():
		return

	_saving = true
	_save_button.disabled = true
	_set_status(tr("Saving..."))

	# Only the changed slots go up. The endpoint keeps anything it isn't
	# sent, so this can't accidentally rewrite a slot added by a newer client
	# that this build doesn't know how to draw.
	var payload: Dictionary = {}
	for slot in changed:
		payload[slot] = _edited_appearance[slot]

	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST,
		"/player/customize",
		{"player_id": _card.player_id, "appearance": payload},
	)

	_saving = false

	if not res.ok:
		_set_status(
			tr("Not enough for these changes.") if res.status == 402
			else tr("Could not save this look -- try again.")
		)
		_refresh()
		return

	# The server's idea of the finished look, not ours -- it merges onto
	# whatever the doc actually held, which may include a slot this build
	# never sent.
	var applied = res.data.get("appearance")
	var appearance: Dictionary = applied if applied is Dictionary else _edited_appearance
	GameProfile.set_card_appearance(_card.player_id, appearance)
	GameProfile.apply_currency_balances(res.data.get("credits_remaining"))

	_saved_appearance = PlayerAppearance.normalize(appearance)
	_edited_appearance = _saved_appearance.duplicate()
	_refresh()
	_set_status(tr("Saved."), true)


func _on_back_pressed() -> void:
	# Unsaved changes are simply dropped, the same way CustomizeKit and the
	# Squad screen drop theirs -- nothing has been charged for yet.
	get_tree().change_scene_to_file("res://scenes/PlayerDetail.tscn")


## Only reached when there's no card to customize, which is decided in
## _ready() -- and the tree is still busy adding this scene's children at
## that point, so the swap has to be deferred.
func _go_back() -> void:
	get_tree().change_scene_to_file.call_deferred(PlayerSession.return_scene)
