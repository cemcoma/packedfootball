class_name ContractWarning
extends Control

## Before any match: if starters in the saved XI are out of contract (they play
## at -50%, SquadOptimizer.CONTRACT_FACTOR), ask first. "Go to Squad" opens the
## Squad screen; "Play anyway" lets the match start. Built in code because both
## match entries (Play's Quick Match, TournamentScreen's Play) need the same box.
##
##     if not await ContractWarning.confirm(self):
##         return

const SQUAD_SCENE := "res://scenes/Team.tscn"

signal chosen(play: bool)


## Display names of the saved XI's starters whose contract has run out.
static func ended_starters() -> Array:
	var names := []
	for id in GameProfile.saved_slot_assignment:
		var card: PlayerCard = GameProfile.all_cards.get(id)
		if card != null and card.contract_ended():
			names.append(card.display_name())
	return names


## True when the match may start: nobody is out of contract, or the player
## chose to play anyway. False means they went to the Squad screen.
static func confirm(host: Node) -> bool:
	var names := ended_starters()
	if names.is_empty():
		return true
	var popup := ContractWarning.new()
	host.add_child(popup)
	popup._build(names)
	var play: bool = await popup.chosen
	popup.queue_free()
	if not play:
		host.get_tree().change_scene_to_file(SQUAD_SCENE)
	return play


func _build(names: Array) -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP
	# Swallows Android back like LoadingPopup, so back can't leave mid-question.
	add_to_group(BackNavigation.LOADING_POPUP_GROUP)

	var scrim := ColorRect.new()
	scrim.color = Color(0, 0, 0, 0.7)
	scrim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(scrim)
	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(center)

	var warning := ThemeManager.color("warning")
	var panel := PanelContainer.new()
	panel.custom_minimum_size = Vector2(460, 0)
	panel.add_theme_stylebox_override("panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, warning, 3, true, Vector2(18, 14)))
	center.add_child(panel)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 12)
	panel.add_child(box)

	var title := Label.new()
	title.text = tr("Players out of contract")
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 20)
	title.add_theme_color_override("font_color", warning)
	box.add_child(title)

	var body := Label.new()
	body.text = tr("%d of your starters are out of contract and play at -50%%:\n%s\n\nAre you sure you want to play?") % [
		names.size(), ", ".join(names)
	]
	body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_theme_color_override("font_color", MenuTile.TITLE_COLOR)
	box.add_child(body)

	var row := HBoxContainer.new()
	row.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_theme_constant_override("separation", 16)
	box.add_child(row)
	var squad := Button.new()
	squad.text = tr("Go to Squad")
	MenuTile.style_button(squad, ThemeManager.color("accent"), true)
	squad.pressed.connect(func() -> void: chosen.emit(false))
	row.add_child(squad)
	var play := Button.new()
	play.text = tr("Play anyway")
	MenuTile.style_button(play, warning)
	play.pressed.connect(func() -> void: chosen.emit(true))
	row.add_child(play)
