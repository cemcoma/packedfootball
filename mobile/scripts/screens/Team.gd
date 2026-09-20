extends Control

## Squad management: pick a formation, tap a pitch slot to view that
## player's stats or (via "Replace") swap them for an eligible bench card,
## and save.
##
## The static structure (formation buttons, panel layout, bench grid,
## stats panel, bottom row) lives in the companion Team.tscn -- open it in
## the editor to rearrange/restyle. This script only connects signals and
## repopulates the genuinely dynamic parts: the bench/picker card grid
## (however many cards are eligible) and the pitch's slot markers (count
## and position depend on the chosen formation) -- neither can be static
## content, regardless of whether this were a .tscn or not. PlayerCardView
## instances are loaded from PlayerCardView.tscn via PLAYER_CARD_SCENE
## rather than PlayerCardView.new(), since that script expects the child
## nodes its .tscn defines (a bare .new() would have none of them).
##
## Data flow unchanged from before: all squad state (formation,
## slot_assignment, all_cards) lives in the GameProfile autoload, fetched
## once at login (see Auth.gd). This scene only owns pure view state: which
## slot is focused, whether we're picking a replacement, and the
## save-status message.

const PLAYER_CARD_SCENE := preload("res://scenes/components/PlayerCardView.tscn")

const ATTR_ROWS := [
	["Height", "height"],
	["Stamina", "stamina"], ["Speed", "speed"], ["Agility", "agility"], ["Passing", "passing"],
	["Ball Ctrl", "ballcontrol"], ["Defending", "defending"], ["Tackling", "tackling"], ["Dribbling", "dribbiling"],
	["Shooting", "shooting"], ["Power", "power"], ["Accuracy", "accuracy"], ["Vision", "vision"],
	["Heading", "heading"],
]

## Page 2 of the stats panel: career totals rather than attributes. Keys are
## the ones player.py's DEFAULT_STATISTICS defines; "_pass_accuracy" is
## derived. Keeper-only rows are filtered out for outfielders, whose zeroes
## there are just noise.
const STAT_ROWS := [
	["Matches", "matches_played"],
	["Goals", "goals"],
	["Assists", "assists"],
	["Shots", "shots"],
	["On target", "shots_on_target"],
	["Passes", "passes"],
	["Completed", "passes_completed"],
	["Pass acc.", "_pass_accuracy"],
	["Tackles won", "tackles_won"],
]

const KEEPER_STAT_ROWS := [
	["Saves", "saves"],
	["Clean sheets", "clean_sheets"],
	["Conceded", "goals_conceded"],
]

## Which page the stats panel is showing. Sticky across slot selections on
## purpose -- comparing the same page between players is the normal use.
enum StatsPage { ATTRIBUTES, STATISTICS }

var stats_page: int = StatsPage.ATTRIBUTES
var selected_slot: int = -1  # -1 = nothing focused
var picker_mode: bool = false  # only meaningful when selected_slot != -1
var status_text: String = ""

var _formation_buttons: Dictionary = {}  # name -> Button

@onready var _formation_button_442: Button = %FormationButton442
@onready var _formation_button_433: Button = %FormationButton433
@onready var _formation_button_352: Button = %FormationButton352
@onready var _formation_button_4231: Button = %FormationButton4231
@onready var _overall_label: Label = %OverallLabel
@onready var _auto_button: Button = %AutoButton

@onready var _pitch_view: PitchView = %Pitch
@onready var _panel_header: Label = %PanelHeader
@onready var _bench_scroll: ScrollContainer = %BenchScroll
@onready var _bench_grid: GridContainer = %BenchGrid
@onready var _cancel_button: Button = %CancelButton
@onready var _stats_panel: VBoxContainer = %StatsPanel
@onready var _out_of_position_label: Label = %OutOfPositionLabel
@onready var _stats_card_view: PlayerCardView = %StatsCard
@onready var _stats_extra_country: Label = %StatsExtraCountry
@onready var _stats_extra_gam: Label = %StatsExtraGam #goals assists matches
@onready var _stats_attr_grid: GridContainer = %StatsAttrGrid
@onready var _stats_page_label: Label = %StatsPageLabel
@onready var _stats_page_button: Button = %StatsPageButton
@onready var _replace_button: Button = %ReplaceButton
@onready var _clear_button: Button = %ClearButton
@onready var _close_button: Button = %CloseButton
@onready var _status_label: Label = %StatusLabel
@onready var _kit_button: Button = %KitButton
@onready var _save_button: Button = %SaveButton
@onready var _back_button: Button = %BackButton
@onready var _discard_overlay: Control = %DiscardConfirmOverlay
@onready var _discard_save_button: Button = %DiscardSaveButton
@onready var _discard_confirm_button: Button = %DiscardConfirmButton
@onready var _discard_cancel_button: Button = %DiscardCancelButton
@onready var _saving_popup: Control = %SavingPopup


func _ready() -> void:
	_formation_buttons = {
		"4-4-2": _formation_button_442,
		"4-3-3": _formation_button_433,
		"3-5-2": _formation_button_352,
		"4-2-3-1": _formation_button_4231,
	}
	for formation_name in _formation_buttons.keys():
		var button: Button = _formation_buttons[formation_name]
		button.pressed.connect(_on_formation_button_pressed.bind(formation_name))

	_auto_button.pressed.connect(_on_auto_pressed)
	_pitch_view.slot_pressed.connect(_on_slot_tapped)
	_cancel_button.pressed.connect(_on_cancel_picker_pressed)
	_replace_button.pressed.connect(_on_replace_pressed)
	_clear_button.pressed.connect(_on_clear_pressed)
	_close_button.pressed.connect(_on_close_stats_pressed)
	_stats_page_button.pressed.connect(_on_stats_page_pressed)
	_kit_button.pressed.connect(_on_kit_pressed)
	_save_button.pressed.connect(_on_save_pressed)
	_back_button.pressed.connect(_on_back_pressed)
	_discard_save_button.pressed.connect(_on_discard_save_pressed)
	_discard_confirm_button.pressed.connect(_on_discard_confirm_pressed)
	_discard_cancel_button.pressed.connect(func() -> void: _discard_overlay.visible = false)
	_discard_overlay.visible = false

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()

	_refresh_all()


## StatsPanel is a plain VBoxContainer -- nothing is drawn behind it -- so
## everything in it sits directly on the screen background and the Theme's
## Label color never reaches the labels that carry their own override. The
## pale blue heading and grey subtitle read fine on the dark backdrop and
## washed out on the light one. _refresh_bottom() recolors the status label
## on the same palette (it flips between positive and warning).
func _apply_theme_colors() -> void:
	_stats_page_label.add_theme_color_override("font_color", ThemeManager.color("heading"))
	_stats_extra_country.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	_out_of_position_label.add_theme_color_override("font_color", ThemeManager.color("warning"))
	_refresh_overall()
	_refresh_bottom()


# -- state -> UI --------------------------------------------------------------


func _refresh_all() -> void:
	_refresh_formation_buttons()
	_refresh_overall()
	_refresh_pitch()
	_refresh_right_panel()
	_refresh_bottom()


## Squad Overall, live -- it moves as slots are filled, so the effect of a
## swap is visible before saving rather than only back on the Menu.
##
## This is the penalty-aware number (see GameProfile.average_overall), which
## is what makes it honest here specifically: this is the one screen where
## you can put a winger at right back, and the number has to notice.
##
## Greyed out while the lineup is incomplete, because an average over 8
## players isn't comparable to one over 11 and shouldn't look like it is.
func _refresh_overall() -> void:
	var filled := 0
	for player_id in GameProfile.slot_assignment:
		if player_id != "":
			filled += 1
	var complete: bool = filled == GameProfile.slot_assignment.size()

	if filled == 0:
		_overall_label.text = tr("Overall --")
	elif complete:
		_overall_label.text = tr("Overall %d") % GameProfile.average_overall()
	else:
		_overall_label.text = tr("Overall %d  (%d/%d)") % [
			GameProfile.average_overall(), filled, GameProfile.slot_assignment.size()
		]
	_overall_label.add_theme_color_override(
		"font_color",
		ThemeManager.color("heading") if complete else ThemeManager.color("text_hint")
	)


func _refresh_formation_buttons() -> void:
	for formation_name in _formation_buttons.keys():
		var button: Button = _formation_buttons[formation_name]
		button.button_pressed = (formation_name == GameProfile.formation)


func _refresh_pitch() -> void:
	var slots := Formations.get_formation(GameProfile.formation)
	_pitch_view.set_formation(slots, GameProfile.slot_assignment, GameProfile.all_cards, selected_slot)


func _refresh_right_panel() -> void:
	var showing_stats: bool = selected_slot != -1 and not picker_mode
	var showing_picker: bool = selected_slot != -1 and picker_mode

	_stats_panel.visible = showing_stats
	_bench_scroll.visible = not showing_stats
	_cancel_button.visible = showing_picker

	if showing_stats:
		_panel_header.text = tr("Player")
		_populate_stats_panel()
	elif showing_picker:
		var slots := Formations.get_formation(GameProfile.formation)
		var role: String = slots[selected_slot]["role"]
		_panel_header.text = tr("Pick a %s:") % role
		_populate_bench_grid(_eligible_bench_ids(role), role)
	else:
		_panel_header.text = tr("Bench (tap a slot to assign)")
		_populate_bench_grid(_sorted_bench_ids(GameProfile.bench_ids()))


func _sorted_bench_ids(ids: Array) -> Array:
	var sorted_ids: Array = ids.duplicate()
	sorted_ids.sort_custom(func(a, b): return GameProfile.all_cards[a].overall() > GameProfile.all_cards[b].overall())
	return sorted_ids


## Exact-position matches first, then similar-position ones (see
## Formations.is_similar_position) -- each group sorted best-overall-first
## like before. Anything neither exact nor similar for this role is left
## out entirely, same as today.
func _eligible_bench_ids(role: String) -> Array:
	var exact: Array = []
	var similar: Array = []
	for player_id in GameProfile.bench_ids():
		var card: PlayerCard = GameProfile.all_cards[player_id]
		if card.position == role:
			exact.append(player_id)
		elif Formations.is_similar_position(card.position, role):
			similar.append(player_id)
	return _sorted_bench_ids(exact) + _sorted_bench_ids(similar)


## `role` is only passed when populating the picker (empty string in the
## plain bench-browse mode) -- it's what set_out_of_position() compares
## each card's own position against, so browsing the bench (no slot/role
## in play at all) never tags anything.
func _populate_bench_grid(ids: Array, role: String = "") -> void:
	# This can run from inside a card view's own "pressed" signal (tapping a
	# bench card -> _on_card_view_pressed -> _refresh_all() -> here), so the
	# old views can't be torn down with plain free() -- that's only safe once
	# their own signal has finished dispatching. remove_child() detaches them
	# immediately (so a same-frame add_child() below never sees a stale
	# leftover child), then queue_free() defers the actual deallocation.
	for child in _bench_grid.get_children():
		_bench_grid.remove_child(child)
		child.queue_free()

	if ids.is_empty():
		var empty_label := Label.new()
		empty_label.text = tr("No eligible players.") if (selected_slot != -1 and picker_mode) else tr("No bench players.")
		_bench_grid.add_child(empty_label)
		return

	for player_id in ids:
		var card: PlayerCard = GameProfile.all_cards[player_id]
		var view: PlayerCardView = PLAYER_CARD_SCENE.instantiate()
		_bench_grid.add_child(view)
		view.set_card(card)
		if role != "":
			view.set_out_of_position(card.position != role)
		view.pressed.connect(_on_card_view_pressed.bind(player_id))


func _populate_stats_panel() -> void:
	var player_id: String = GameProfile.slot_assignment[selected_slot]
	var card: PlayerCard = GameProfile.all_cards[player_id]
	_stats_card_view.set_card(card)

	var slots := Formations.get_formation(GameProfile.formation)
	var role: String = slots[selected_slot]["role"]
	var out_of_position: bool = card.position != role
	_stats_card_view.set_out_of_position(out_of_position)
	_out_of_position_label.visible = out_of_position
	if out_of_position:
		_out_of_position_label.text = tr("Out of position: a %s playing %s -- attributes reduced 10%% in matches.") % [card.position, role]

	for child in _stats_attr_grid.get_children():
		_stats_attr_grid.remove_child(child)
		child.queue_free()

	_stats_extra_country.text = "%s\n%s" % [
		card.hometown, card.country
	]

	if stats_page == StatsPage.STATISTICS:
		_populate_statistics_page(card)
	else:
		_populate_attributes_page(card)
	_update_stats_page_button()


func _populate_attributes_page(card: PlayerCard) -> void:
	_stats_page_label.text = tr("Attributes")
	for row in ATTR_ROWS:
		var key: String = row[1]
		var value: int = card.attributes.get(key, 0)
		# Height is centimetres, not a 0-100 skill (see player.py's
		# PHYSICAL_FIELDS -- it's excluded from the overall for that reason).
		_add_stat_row(tr(row[0]), "%d cm" % value if key == "height" else str(value))

	var goals: int = card.statistics.get("goals", 0)
	var assists: int = card.statistics.get("assists", 0)
	var matches: int = card.statistics.get("matches_played", 0)
	_stats_extra_gam.text = tr("\nGoals: %d\nAssists: %d\nMatches: %d") % [
		goals, assists, matches
	]


func _populate_statistics_page(card: PlayerCard) -> void:
	_stats_page_label.text = tr("Career Statistics")
	for row in STAT_ROWS:
		_add_stat_row(tr(row[0]), _career_stat_text(card, row[1]))
	if card.position == "GK":
		for row in KEEPER_STAT_ROWS:
			_add_stat_row(tr(row[0]), _career_stat_text(card, row[1]))

	# rating_sum/rating_count are storage rather than a stat -- derive the
	# average the same way player.py's average_rating() does.
	var count: float = float(card.statistics.get("rating_count", 0))
	if count > 0.0:
		var avg: float = float(card.statistics.get("rating_sum", 0.0)) / count
		_stats_extra_gam.text = tr("\nAvg rating\n%.2f") % avg
	else:
		_stats_extra_gam.text = tr("\nAvg rating\n-")


func _career_stat_text(card: PlayerCard, key: String) -> String:
	if key == "_pass_accuracy":
		var passes: float = float(card.statistics.get("passes", 0))
		if passes <= 0.0:
			return "-"
		return "%d%%" % int(round(100.0 * float(card.statistics.get("passes_completed", 0)) / passes))
	return str(int(card.statistics.get(key, 0)))


func _add_stat_row(label_text: String, value_text: String) -> void:
	var name_label := Label.new()
	name_label.text = label_text
	_stats_attr_grid.add_child(name_label)
	var value_label := Label.new()
	value_label.text = value_text
	_stats_attr_grid.add_child(value_label)


func _update_stats_page_button() -> void:
	_stats_page_button.text = (
		tr("Show Attributes") if stats_page == StatsPage.STATISTICS else tr("Show Statistics")
	)


func _on_stats_page_pressed() -> void:
	stats_page = (
		StatsPage.ATTRIBUTES if stats_page == StatsPage.STATISTICS else StatsPage.STATISTICS
	)
	_populate_stats_panel()


func _refresh_bottom() -> void:
	var dirty: bool = GameProfile.is_dirty()
	var message := status_text
	if (status_text == "" or status_text == tr("Saved!")) and dirty:
		message = tr("Unsaved changes")
	_status_label.text = message
	_status_label.add_theme_color_override(
		"font_color", ThemeManager.color("warning") if dirty else ThemeManager.color("positive")
	)
	_save_button.text = tr("Save Team*") if dirty else tr("Save Team")


# -- input handlers -----------------------------------------------------------


func _on_formation_button_pressed(formation_name: String) -> void:
	if formation_name == GameProfile.formation:
		_refresh_formation_buttons()  # keep the active one looking pressed
		return
	GameProfile.switch_formation(formation_name)
	selected_slot = -1
	picker_mode = false
	status_text = ""
	_refresh_all()


## Auto Pick: rebuild the whole XI as the strongest legal lineup for the
## formation currently selected.
##
## Deliberately reassigns EVERY slot rather than only filling the empty
## ones. "Give me the best team" is the ask, and the best team routinely
## needs someone already on the pitch to move -- a keeper aside, almost
## every improvement is a chain of swaps, not an insertion. Nothing is
## written until Save, and Back still discards, so an unwanted result costs
## one tap to undo.
##
## The pool is every card owned, XI included (see GameProfile.all_cards),
## which is the only way a player already in the lineup can be moved to a
## slot that suits them better.
func _on_auto_pressed() -> void:
	if GameProfile.all_cards.is_empty():
		status_text = tr("You don't own any players yet.")
		_refresh_bottom()
		return

	var before := GameProfile.average_overall()
	GameProfile.slot_assignment = SquadOptimizer.best_assignment(
		GameProfile.formation, GameProfile.all_cards.keys(), GameProfile.all_cards
	)

	# Any slot left empty means the squad genuinely has nobody eligible for
	# it -- no keeper, say -- and Save will refuse until that is fixed. Name
	# the roles rather than just the count, since "no GK" is actionable and
	# "10/11" is not.
	var slots := Formations.get_formation(GameProfile.formation)
	var missing: Array[String] = []
	for i in range(GameProfile.slot_assignment.size()):
		if GameProfile.slot_assignment[i] == "":
			var role: String = slots[i]["role"]
			if not missing.has(role):
				missing.append(role)

	if not missing.is_empty():
		status_text = tr("No eligible player for: %s") % ", ".join(missing)
	else:
		var after := GameProfile.average_overall()
		if after > before:
			status_text = tr("Best XI picked -- overall %d to %d.") % [before, after]
		else:
			status_text = tr("Already the best XI available.")

	selected_slot = -1
	picker_mode = false
	_refresh_all()


func _on_slot_tapped(i: int) -> void:
	if selected_slot == i:
		selected_slot = -1
		picker_mode = false
	else:
		selected_slot = i
		# Nothing to show stats for on an empty slot -- go straight to picking.
		picker_mode = (GameProfile.slot_assignment[i] == "")
	_refresh_all()


func _on_replace_pressed() -> void:
	picker_mode = true
	_refresh_all()


func _on_clear_pressed() -> void:
	GameProfile.slot_assignment[selected_slot] = ""
	selected_slot = -1
	picker_mode = false
	_refresh_all()


func _on_cancel_picker_pressed() -> void:
	# If the slot being replaced already had a player, fall back to viewing
	# their stats instead of fully deselecting.
	if selected_slot != -1 and GameProfile.slot_assignment[selected_slot] != "":
		picker_mode = false
	else:
		selected_slot = -1
		picker_mode = false
	_refresh_all()


func _on_close_stats_pressed() -> void:
	selected_slot = -1
	picker_mode = false
	_refresh_all()


func _on_card_view_pressed(player_id: String) -> void:
	if selected_slot == -1 or not picker_mode:
		return  # browsing only -- tapping does nothing
	var slots := Formations.get_formation(GameProfile.formation)
	var role: String = slots[selected_slot]["role"]
	var card: PlayerCard = GameProfile.all_cards[player_id]
	if card.position != role and not Formations.is_similar_position(card.position, role):
		return  # shouldn't happen (list is already filtered to exact-or-similar), but stay safe
	GameProfile.slot_assignment[selected_slot] = player_id
	selected_slot = -1
	picker_mode = false
	_refresh_all()


func _lineup_is_complete() -> bool:
	for player_id in GameProfile.slot_assignment:
		if player_id == "":
			return false
	return true


func _on_save_pressed() -> void:
	if not _lineup_is_complete():
		status_text = tr("Fill every slot before saving.")
		_refresh_bottom()
		return

	status_text = tr("Saving...")
	_refresh_bottom()

	var ok: bool = await GameProfile.save_team()
	status_text = tr("Saved!") if ok else tr("Save failed -- try again.")
	_refresh_all()


## Deliberately does NOT discard unsaved lineup changes the way Back does:
## formation/slot_assignment live on the GameProfile autoload, not on this
## scene, so they survive the trip to CustomizeKit and back and the manager
## picks up exactly where they left off.
func _on_kit_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/CustomizeKit.tscn")


## Back with unsaved lineup changes asks first -- the "Unsaved changes" line
## at the bottom is easy to miss, and a lineup silently reverting looked
## like a bug to testers. Save & Leave runs the normal save, so its own
## refusals (an empty slot, a failed request) land in the status line and
## keep the manager here, exactly as if they had pressed Save.
func _on_back_pressed() -> void:
	if GameProfile.is_dirty():
		_discard_overlay.visible = true
		return
	_leave()


func _leave() -> void:
	get_tree().change_scene_to_file("res://scenes/TeamHub.tscn")


func _on_discard_confirm_pressed() -> void:
	_discard_overlay.visible = false
	GameProfile.discard_changes()
	_leave()


## Save & Leave is a save the manager is waiting on to go somewhere, so it
## gets the modal "Saving changes..." rather than the status line: the wait
## reads as progress, and nothing can be tapped under it while the writes
## are in flight. An incomplete lineup never opens it -- that refusal is
## instant and lands in the status line like a plain Save.
func _on_discard_save_pressed() -> void:
	_discard_overlay.visible = false
	var will_save := _lineup_is_complete()
	if will_save:
		_saving_popup.set_status(tr("Saving changes..."))
		_saving_popup.visible = true
	await _on_save_pressed()
	if will_save:
		_saving_popup.visible = false
	if not GameProfile.is_dirty():
		_leave()
