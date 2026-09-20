extends Control

## EA-FC-style pack-opening reveal. PackSession.cards() (an already-decoded
## Array[PlayerCard] built by Shop.gd right after a successful POST
## /pack/open) get shown one at a time via Tween-driven scale/fade, worst
## tier first, best tier (PlayerCard.tier_rank(), ties broken by overall())
## saved for last as a bigger, longer "hero" moment -- how much bigger
## scales with the hero card's own tier (HERO_SCALE_BY_TIER: a modest
## 1.25x for a bronze hero up to 2x for icon). Then every card is
## reparented into a scrollable grid (the same disposable-child population
## pattern Shop.gd's pack grid and Team.gd's bench grid already use) where
## tapping one reuses PlayerCardView's own existing `pressed` signal
## (already proven in Team.gd) to show a stats popup mirroring Team.gd's
## own stats panel content -- same attribute list, deliberately duplicated
## rather than shared (see the plan this came from: pulling that out into
## a common component is a reasonable future cleanup once a third call
## site wants it, not something worth touching Team.gd's already-working
## code for today).
##
## Tapping anywhere while an earlier (non-hero) card is showing skips
## straight to the browse grid with every card already in its final
## resting state -- "skip" means skip all of it, not advance one card at a
## time. A killed Tween never fires `finished` (so `await tween.finished`
## would hang forever if skip just called `.kill()`), so skipping instead
## fast-forwards the active Tween to completion via `custom_step()` (a
## real step, still finishes normally) and force-expires the active hold
## timer via its `time_left` -- both let whatever's currently `await`-ed
## resume on the very next frame instead of leaving the reveal loop stuck
## mid-await.
##
## The hero card itself doesn't auto-advance at all -- see _wait_for_tap()
## -- so reaching it always ends in the same explicit tap regardless of
## whether earlier cards were skipped through or watched in full.

const PLAYER_CARD_SCENE := preload("res://scenes/components/PlayerCardView.tscn")

const ATTR_ROWS := [
	["Stamina", "stamina"], ["Speed", "speed"], ["Agility", "agility"], ["Passing", "passing"],
	["Ball Ctrl", "ballcontrol"], ["Defending", "defending"], ["Tackling", "tackling"], ["Dribbling", "dribbling"],
	["Shooting", "shooting"], ["Power", "power"], ["Accuracy", "accuracy"], ["Vision", "vision"],
	["Heading", "heading"],
]

const CARD_SCALE := Vector2(1.0, 1.0)
const CARD_HOLD_SECONDS := 0.6

const HERO_SCALE_BY_TIER := {
	"bronze": 1.25, "silver": 1.35, "gold": 1.45, "platinum": 1.55,
	"diamond": 1.7, "special": 1.85, "icon": 2.0,
}
const DEFAULT_HERO_SCALE := 1.25

@onready var _reveal_layer: Control = %RevealLayer
@onready var _skip_catcher: Button = %SkipCatcher
@onready var _skip_hint_label: Label = %SkipHintLabel

@onready var _browse_layer: Control = %BrowseLayer
@onready var _cards_grid: GridContainer = %CardsGrid
@onready var _back_button: Button = %BackButton

## No stream assigned yet -- a ready-but-silent hook for whatever hero-moment
## sound gets supplied later. Guarded by `.stream != null` wherever it's
## played so an unset stream is a quiet no-op instead of a console warning.
@onready var _hero_sound: AudioStreamPlayer = %HeroSound

@onready var _stats_popup: Control = %StatsPopup
@onready var _stats_card_view: PlayerCardView = %StatsCardView
@onready var _stats_extra_country: Label = %StatsExtraCountry
@onready var _stats_extra_gam: Label = %StatsExtraGam
@onready var _stats_attr_grid: GridContainer = %StatsAttrGrid
@onready var _close_stats_button: Button = %CloseStatsButton

@onready var _quick_sell_button: Button = %QuickSellButton
@onready var _sell_action_row: HBoxContainer = %SellActionRow
@onready var _sell_selected_button: Button = %SellSelectedButton
@onready var _cancel_sell_button: Button = %CancelSellButton
@onready var _sell_confirm_overlay: Control = %SellConfirmOverlay
@onready var _sell_confirm_label: Label = %SellConfirmLabel
@onready var _sell_confirm_button: Button = %SellConfirmButton
@onready var _sell_cancel_button: Button = %SellCancelButton

## Sell mode turns a tap from "inspect this card" into "mark it for release".
var _sell_mode: bool = false
var _selected_ids: Array = []
var _selling: bool = false
## player_id -> its card in the browse grid, so selecting one restyles just
## that card instead of rebuilding the grid mid-selection.
var _browse_views: Dictionary = {}

var _cards: Array = []  # PlayerCard, sorted worst -> best
var _views: Array = []  # PlayerCardView, same order as _cards, filled in as the reveal reaches each one
var _skip_requested: bool = false
var _active_tween: Tween = null
var _active_timer: SceneTreeTimer = null


func _ready() -> void:
	_skip_catcher.pressed.connect(_on_skip_pressed)
	_back_button.pressed.connect(_on_back_pressed)
	_close_stats_button.pressed.connect(_on_close_stats_pressed)
	_quick_sell_button.pressed.connect(_on_quick_sell_pressed)
	_cancel_sell_button.pressed.connect(_exit_sell_mode)
	_sell_selected_button.pressed.connect(_on_sell_selected_pressed)
	_sell_confirm_button.pressed.connect(_on_sell_confirm_pressed)
	_sell_cancel_button.pressed.connect(_on_sell_cancel_pressed)
	_sell_confirm_overlay.visible = false

	# "Tap to skip" is drawn straight over the screen background with no
	# panel behind it -- its own pale grey override made it invisible in
	# light mode. See ThemeManager's note on text_hint.
	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()

	_cards = PackSession.cards().duplicate()
	_cards.sort_custom(_is_worse_pull)
	PackSession.clear()

	if _cards.is_empty():
		_show_browse_state()  # reached directly with nothing pending -- nothing to animate
		return

	_play_reveal_sequence()


func _apply_theme_colors() -> void:
	_skip_hint_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))


## Ascending sort predicate ("does a belong before b") -- worst tier first,
## best tier (ties broken by overall()) sorts last for the hero moment.
static func _is_worse_pull(a: PlayerCard, b: PlayerCard) -> bool:
	var rank_a := PlayerCard.tier_rank(a.tier)
	var rank_b := PlayerCard.tier_rank(b.tier)
	if rank_a != rank_b:
		return rank_a < rank_b
	return a.overall() < b.overall()


static func _hero_scale_for(tier: String) -> Vector2:
	var s: float = HERO_SCALE_BY_TIER.get(PlayerCard.tier_family(tier), DEFAULT_HERO_SCALE)
	return Vector2(s, s)


func _on_skip_pressed() -> void:
	_skip_requested = true
	if _active_tween != null and _active_tween.is_valid():
		_active_tween.custom_step(9999.0)  # forces real completion -> still fires `finished`, unlike kill()
	if _active_timer != null:
		_active_timer.time_left = 0.0  # fires `timeout` next frame instead of after its full duration


func _hold(seconds: float) -> void:
	_active_timer = get_tree().create_timer(seconds)
	await _active_timer.timeout
	_active_timer = null


## The hero card doesn't auto-advance -- it waits for an actual tap, however
## long that takes. _skip_catcher is the same full-rect invisible button
## "tap to skip" already uses elsewhere in this sequence, so this shares its
## `pressed` signal rather than needing a second input listener; awaiting a
## signal directly like this is safe to call here specifically because the
## hero card is always the LAST one (see _is_worse_pull's sort), so nothing
## checks _skip_requested afterward -- there's nothing left to skip *to*.
func _wait_for_tap() -> void:
	await _skip_catcher.pressed


func _play_reveal_sequence() -> void:
	for i in range(_cards.size()):
		if _skip_requested:
			break
		var card: PlayerCard = _cards[i]
		var is_hero: bool = i == _cards.size() - 1
		var view: PlayerCardView = PLAYER_CARD_SCENE.instantiate()
		_reveal_layer.add_child(view)
		view.set_card(card)
		_views.append(view)

		var target_scale: Vector2 = _hero_scale_for(card.tier) if is_hero else CARD_SCALE
		view.pivot_offset = view.custom_minimum_size / 2.0
		view.position = _reveal_layer.size / 2.0 - view.pivot_offset
		view.scale = target_scale * 0.4
		view.modulate.a = 0.0

		var in_tween := create_tween()
		_active_tween = in_tween
		in_tween.tween_property(view, "scale", target_scale, 0.35).set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
		in_tween.parallel().tween_property(view, "modulate:a", 1.0, 0.25)
		await in_tween.finished
		_active_tween = null
		if _skip_requested:
			break

		if is_hero:
			view.set_celebrating(true)  # a glow that breathes until the card is put away
			if _hero_sound.stream != null:
				_hero_sound.play()
			_skip_hint_label.text = tr("Tap to continue")
			await _wait_for_tap()
		else:
			await _hold(CARD_HOLD_SECONDS)
			if _skip_requested:
				break

		if not is_hero:
			var out_tween := create_tween()
			_active_tween = out_tween
			out_tween.tween_property(view, "modulate:a", 0.0, 0.2)
			await out_tween.finished
			_active_tween = null

	_show_browse_state()


## Reached either after the sequence above finishes naturally, or (via
## skip) mid-sequence -- so this has to handle both "this card already got
## its own PlayerCardView from the loop above" (reparent, don't recreate)
## and "the loop broke before ever reaching this card" (create it fresh
## here) for every single card, not just the ones that got a turn.
func _show_browse_state() -> void:
	_skip_requested = false
	_active_tween = null
	_active_timer = null
	_reveal_layer.visible = false
	_skip_catcher.visible = false
	_skip_hint_label.visible = false

	for i in range(_cards.size()):
		var card: PlayerCard = _cards[i]
		var view: PlayerCardView
		var already_revealed: bool = i < _views.size()
		if already_revealed:
			view = _views[i]
			if view.get_parent() == _reveal_layer:
				_reveal_layer.remove_child(view)
		else:
			view = PLAYER_CARD_SCENE.instantiate()

		view.scale = Vector2.ONE
		view.modulate = Color.WHITE
		view.pivot_offset = Vector2.ZERO
		view.set_celebrating(false)
		_cards_grid.add_child(view)
		# set_card() reaches into %Background/%OverallLabel/etc., which stay
		# null until this node is actually in the tree -- must come after
		# add_child(), not right after instantiate() (that was the bug: any
		# card skipped past before its reveal turn crashed here).
		if not already_revealed:
			view.set_card(card)
		view.pressed.connect(_on_card_pressed.bind(card.player_id))
		_browse_views[card.player_id] = view

	_browse_layer.visible = true
	_exit_sell_mode()


## Bound by player_id rather than by the tapped PlayerCardView itself --
## same lookup Team.gd's own _on_card_view_pressed() already does
## (GameProfile.all_cards[player_id]), since every card opened this pack
## is already merged into that same dictionary (Shop.gd's
## GameProfile.add_purchased_cards(), before this screen ever loads).
func _on_card_pressed(player_id: String) -> void:
	var card: PlayerCard = GameProfile.all_cards.get(player_id)
	if card == null:
		return

	if _sell_mode:
		if _selected_ids.has(player_id):
			_selected_ids.erase(player_id)
		else:
			_selected_ids.append(player_id)
		_restyle_card(player_id)
		_update_sell_ui()
		return

	_stats_card_view.set_card(card)
	_stats_extra_country.text = "%s\n%s" % [card.hometown, card.country]

	for child in _stats_attr_grid.get_children():
		_stats_attr_grid.remove_child(child)
		child.queue_free()
	for row in ATTR_ROWS:
		var label_name: String = tr(row[0])
		var key: String = row[1]
		var value: int = card.attributes.get(key, 0)
		var name_label := Label.new()
		name_label.text = label_name
		_stats_attr_grid.add_child(name_label)
		var value_label := Label.new()
		value_label.text = str(value)
		_stats_attr_grid.add_child(value_label)

	var goals: int = card.statistics.get("goals", 0)
	var assists: int = card.statistics.get("assists", 0)
	var matches: int = card.statistics.get("matches_played", 0)
	_stats_extra_gam.text = tr("\nGoals: %d\nAssists: %d\nMatches: %d") % [goals, assists, matches]

	_stats_popup.visible = true


func _on_close_stats_pressed() -> void:
	_stats_popup.visible = false


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Shop.tscn")


# -- quick sell ----------------------------------------------------------------

## The selection marker is a badge, not a modulate tint: this screen tweens
## modulate for the reveal and resets it to white on a recycled card, so a
## tint here would be fought over (see PlayerCardView.set_badge).
func _restyle_card(player_id: String) -> void:
	var view: PlayerCardView = _browse_views.get(player_id)
	if view == null:
		return
	if _sell_mode and _selected_ids.has(player_id):
		var card: PlayerCard = GameProfile.all_cards.get(player_id)
		var payout := PlayerCard.release_credits(card.tier) if card != null else 0
		view.set_badge("+%s" % CurrencyDisplay.format_amount(payout),
			CurrencyDisplay.color_for("credits"))
	else:
		view.set_badge("")


func _total_payout() -> int:
	var total := 0
	for pid in _selected_ids:
		var card: PlayerCard = GameProfile.all_cards.get(pid)
		if card != null:
			total += PlayerCard.release_credits(card.tier)
	return total


func _on_quick_sell_pressed() -> void:
	_sell_mode = true
	_selected_ids.clear()
	_quick_sell_button.visible = false
	_sell_action_row.visible = true
	_update_sell_ui()


func _exit_sell_mode() -> void:
	_sell_mode = false
	_selected_ids.clear()
	_quick_sell_button.visible = not _browse_views.is_empty()
	_sell_action_row.visible = false
	_sell_confirm_overlay.visible = false
	for pid in _browse_views.keys():
		_restyle_card(pid)


func _update_sell_ui() -> void:
	CurrencyDisplay.set_button_price(
		_sell_selected_button, tr("Sell %d") % _selected_ids.size(), _total_payout()
	)
	_sell_selected_button.disabled = _selected_ids.is_empty() or _selling


func _on_sell_selected_pressed() -> void:
	if _selected_ids.is_empty() or _selling:
		return
	_sell_confirm_label.text = tr("Release %d player(s) for %s credits?\n\nThis cannot be undone.") % [
		_selected_ids.size(), CurrencyDisplay.format_amount(_total_payout())
	]
	_sell_confirm_overlay.visible = true


func _on_sell_cancel_pressed() -> void:
	if not _selling:
		_sell_confirm_overlay.visible = false


func _on_sell_confirm_pressed() -> void:
	if _selling or _selected_ids.is_empty():
		return
	_selling = true
	_sell_confirm_button.disabled = true
	_sell_cancel_button.disabled = true

	var sold := _selected_ids.duplicate()
	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST, "/player/release/batch", {"player_ids": sold}
	)

	_selling = false
	_sell_confirm_button.disabled = false
	_sell_cancel_button.disabled = false
	_sell_confirm_overlay.visible = false

	if not res.get("ok", false):
		print("Pack quick sell failed. Status: ", res.get("status"))
		_update_sell_ui()
		return

	for pid in sold:
		GameProfile.release_card(pid)
		var view: PlayerCardView = _browse_views.get(pid)
		if view != null:
			_cards_grid.remove_child(view)
			view.queue_free()
		_browse_views.erase(pid)
	GameProfile.apply_inventory_cap(res.data.get("inventory_cap"))
	GameProfile.apply_currency_balances(res.data.get("credits_remaining"))

	# _cards and _views are parallel, so they have to be trimmed together.
	var kept_cards: Array = []
	var kept_views: Array = []
	for i in _cards.size():
		if sold.has(_cards[i].player_id):
			continue
		kept_cards.append(_cards[i])
		if i < _views.size():
			kept_views.append(_views[i])
	_cards = kept_cards
	_views = kept_views

	_exit_sell_mode()
