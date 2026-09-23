extends Control

## EA-FC-style pack opening. PackSession.cards() (an already-decoded
## Array[PlayerCard] built by Shop.gd right after a successful POST
## /pack/open) is sorted worst -> best; the BEST card's tier is what
## colours the whole opening, hinting at what is inside before the pack
## bursts -- purple for a special, a cycling holo for an icon. Every
## effect (and the hook for replacing it with a sprite) lives in
## PackWalkoutStage.gd.
##
## Only the highlight cards are shown at all: anything at least
## WALKOUT_MIN_TIER rare, plus the best card in the pack whatever its
## tier. The rare ones get the real WALKOUT -- the player himself comes
## out of the light and celebrates before his card forms (see
## PackWalkoutStage.player_walkout()); a best card below that bar just has
## its card rise out of the beam, no player, no celebration. The rest are
## never animated at all -- they are already waiting in the strip
## underneath.
##
## Once the opening is over every card sits in that strip (see
## CardCarousel): the best pull centred, the rest queued to its right, and
## whichever one is centred described in full by the panel above it -- the
## same attribute list Team.gd's stats panel shows, deliberately duplicated
## rather than shared until a third call site wants it.
##
## Taps drive the sequence: one during the buildup or a walkout
## fast-forwards it, one on a card that has landed brings out the next
## (or the strip). Fast-forwarding steps the running Tween to completion
## rather than killing it -- a killed Tween never fires `finished`, so
## anything awaiting it would hang forever.

const PLAYER_CARD_SCENE := preload("res://scenes/components/PlayerCardView.tscn")

const ATTR_ROWS := [
	["Stamina", "stamina"], ["Speed", "speed"], ["Agility", "agility"], ["Passing", "passing"],
	["Ball Ctrl", "ballcontrol"], ["Defending", "defending"], ["Tackling", "tackling"], ["Dribbling", "dribbling"],
	["Shooting", "shooting"], ["Power", "power"], ["Accuracy", "accuracy"], ["Vision", "vision"],
	["Heading", "heading"],
]

## A card rare enough for the player to walk out and celebrate. The best
## card in the pack is always SHOWN even when it doesn't clear this bar --
## it just doesn't get the player, only the card.
const WALKOUT_MIN_TIER := "special"

## How big a card stands once it has walked out -- the rarer it is, the
## more of the screen it takes.
const WALKOUT_SCALE_BY_TIER := {
	"bronze": 1.0, "silver": 1.0, "gold": 1.00, "platinum": 1.10,
	"diamond": 1.2, "special": 1.3, "icon": 1.5,
}
const DEFAULT_WALKOUT_SCALE := 1.25

@onready var _reveal_layer: Control = %RevealLayer
@onready var _stage: PackWalkoutStage = %WalkoutStage
@onready var _skip_catcher: Button = %SkipCatcher
@onready var _skip_hint_label: Label = %SkipHintLabel

@onready var _browse_layer: Control = %BrowseLayer
@onready var _carousel: CardCarousel = %Carousel
@onready var _back_button: Button = %BackButton

## No stream assigned yet -- a ready-but-silent hook for whatever hero-moment
## sound gets supplied later. Guarded by `.stream != null` wherever it's
## played so an unset stream is a quiet no-op instead of a console warning.
@onready var _hero_sound: AudioStreamPlayer = %HeroSound

@onready var _detail_panel: PanelContainer = %DetailPanel
@onready var _detail_name_label: Label = %DetailNameLabel
@onready var _detail_meta_label: Label = %DetailMetaLabel
@onready var _detail_origin_label: Label = %DetailOriginLabel
@onready var _detail_attr_grid: GridContainer = %DetailAttrGrid

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
## player_id -> its PlayerCardView. Built by the walkout for the cards that
## get one and by the strip for the rest, then kept so selecting a card
## restyles just that one instead of rebuilding the strip mid-selection.
var _browse_views: Dictionary = {}

## The cards in the order the strip holds them, best first -- a carousel
## index is a position in here.
var _browse_order: Array = []

var _cards: Array = []  # PlayerCard, sorted worst -> best


func _ready() -> void:
	_skip_catcher.pressed.connect(_on_skip_pressed)
	_back_button.pressed.connect(_on_back_pressed)
	_carousel.focus_changed.connect(_on_focus_changed)
	_carousel.card_tapped.connect(_on_card_tapped)
	_quick_sell_button.pressed.connect(_on_quick_sell_pressed)
	_cancel_sell_button.pressed.connect(_exit_sell_mode)
	_sell_selected_button.pressed.connect(_on_sell_selected_pressed)
	_sell_confirm_button.pressed.connect(_on_sell_confirm_pressed)
	_sell_cancel_button.pressed.connect(_on_sell_cancel_pressed)
	_sell_confirm_overlay.visible = false

	# The tap hint is drawn straight over the screen background with no
	# panel behind it -- its own pale grey override made it invisible in
	# light mode. See ThemeManager's note on text_hint. The detail panel
	# below carries palette colours of its own, so it goes the same way.
	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()

	var pack_texture: Texture2D = PackSession.pack_texture
	_cards = PackSession.cards().duplicate()
	_cards.sort_custom(_is_worse_pull)
	PackSession.clear()

	if _cards.is_empty():
		_stage.dismiss()
		_show_browse_state()  # reached directly with nothing pending -- nothing to animate
		return

	_play_reveal_sequence(pack_texture)


func _apply_theme_colors() -> void:
	_skip_hint_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))

	# The same pixel frame PlayerDetail puts its own panels in -- a dark tile
	# in both themes, so the text on it takes MenuTile's colours.
	_detail_panel.add_theme_stylebox_override("panel", MenuTile.pixel_frame(
		MenuTile.BASE_FILL, ThemeManager.color("surface_border"), 3, true, Vector2(10, 8)
	))
	_detail_name_label.add_theme_color_override("font_color", MenuTile.TITLE_COLOR)
	_detail_meta_label.add_theme_color_override("font_color", ThemeManager.color("heading"))
	_detail_origin_label.add_theme_color_override("font_color", MenuTile.SUBTITLE_COLOR)

	# The attribute rows accent the centred card's primary stats, so they
	# carry a colour override and have to be rebuilt when the palette moves
	# under them -- same reason PlayerDetail rebuilds its own.
	var index: int = _carousel.focus_index()
	if index >= 0 and index < _browse_order.size():
		_show_card_detail(_browse_order[index])


## Ascending sort predicate ("does a belong before b") -- worst tier first,
## best tier (ties broken by overall()) sorts last for the hero moment.
static func _is_worse_pull(a: PlayerCard, b: PlayerCard) -> bool:
	var rank_a := PlayerCard.tier_rank(a.tier)
	var rank_b := PlayerCard.tier_rank(b.tier)
	if rank_a != rank_b:
		return rank_a < rank_b
	return a.overall() < b.overall()


static func _walkout_scale_for(tier: String) -> Vector2:
	var s: float = WALKOUT_SCALE_BY_TIER.get(PlayerCard.tier_family(tier), DEFAULT_WALKOUT_SCALE)
	return Vector2(s, s)


## Rare enough for the player to walk out and celebrate -- by tier FAMILY,
## so every special_* edition counts as special.
static func _is_walkout_tier(tier: String) -> bool:
	return PlayerCard.tier_rank(tier) >= PlayerCard.tier_rank(WALKOUT_MIN_TIER)


## Which cards are shown at all, worst -> best so the best pull lands last.
func _walkout_cards() -> Array:
	var out: Array = []
	for card in _cards:
		if _is_walkout_tier(card.tier):
			out.append(card)
	if out.is_empty() or out[-1] != _cards[-1]:
		out.append(_cards[-1])
	return out

func _on_skip_pressed() -> void:
	_stage.fast_forward()


func _play_reveal_sequence(pack_texture: Texture2D) -> void:
	await get_tree().process_frame

	_stage.setup(pack_texture, _cards[-1].tier)
	_skip_hint_label.text = tr("Tap to speed up")
	await _stage.play_charge()

	if _hero_sound.stream != null:
		_hero_sound.play()
	await _stage.play_burst()

	var walkouts: Array = _walkout_cards()
	for i in walkouts.size():
		var card: PlayerCard = walkouts[i]
		var view: PlayerCardView = PLAYER_CARD_SCENE.instantiate()
		_stage.add_card(view)
		# set_card() reaches into %BackgroundTexture/%OverallLabel/etc.,
		# which stay null until the view is actually in the tree -- so it
		# has to come after add_child(), not right after instantiate().
		view.set_card(card)
		_browse_views[card.player_id] = view

		# For a rare card the player walks out and celebrates first; the
		# card only forms once he's done. A lesser card is just a card.
		if _is_walkout_tier(card.tier):
			await _stage.player_walkout(card)
		await _stage.walk_out(view, _walkout_scale_for(card.tier))
		# a glow, in the card's own tier colour, that breathes until the
		# card is put away
		view.set_celebrating(true, PlayerCard.tier_color(card.tier))
		_skip_hint_label.text = tr("Tap to continue")
		await _skip_catcher.pressed
		view.set_celebrating(false)
		if i < walkouts.size() - 1:
			await _stage.put_away(view)

	_stage.dismiss()
	_show_browse_state()


## Every card ends up here, walked out or not: the ones that did already
## have a PlayerCardView (reparent it out of the stage), the ones that
## didn't get one made now.
func _show_browse_state() -> void:
	_reveal_layer.visible = false
	_skip_catcher.visible = false
	_skip_hint_label.visible = false

	# Best first, so the pull worth seeing is the one already centred and
	# the rest queue up to its right.
	_browse_order = _cards.duplicate()
	_browse_order.reverse()
	for card in _browse_order:
		var view: PlayerCardView = _browse_views.get(card.player_id)
		var walked_out: bool = view != null
		if walked_out:
			view.get_parent().remove_child(view)
		else:
			view = PLAYER_CARD_SCENE.instantiate()

		view.set_celebrating(false)
		_carousel.add_view(view)  
		if not walked_out:
			view.set_card(card) 
		_browse_views[card.player_id] = view

	_browse_layer.visible = true
	_exit_sell_mode()
	_carousel.snap_to(0, false)
	_on_focus_changed(_carousel.focus_index())


## The centred card is the one the panel describes, and the only one still
## wearing the celebration glow.
func _on_focus_changed(index: int) -> void:
	for i in _browse_order.size():
		var card: PlayerCard = _browse_order[i]
		var view: PlayerCardView = _browse_views.get(card.player_id)
		if view != null:
			view.set_celebrating(i == index, PlayerCard.tier_color(card.tier))

	if index < 0 or index >= _browse_order.size():
		_clear_card_detail()
		return
	_show_card_detail(_browse_order[index])


## A tap on a card off to the side brings it in; on the centred one it only
## means anything while selling.
func _on_card_tapped(index: int) -> void:
	if index != _carousel.focus_index():
		_carousel.snap_to(index)
		return
	if not _sell_mode or index < 0 or index >= _browse_order.size():
		return

	var player_id: String = _browse_order[index].player_id
	if _selected_ids.has(player_id):
		_selected_ids.erase(player_id)
	else:
		_selected_ids.append(player_id)
	_restyle_card(player_id)
	_update_sell_ui()


func _show_card_detail(card: PlayerCard) -> void:
	_detail_name_label.text = card.full_name()
	_detail_meta_label.text = tr("%s  ·  %s  ·  Overall %d") % [
		card.position, PlayerCard.tier_label(card.tier), card.overall()
	]
	_detail_origin_label.text = "%s, %s" % [card.hometown, card.country]

	for child in _detail_attr_grid.get_children():
		_detail_attr_grid.remove_child(child)
		child.queue_free()
	# The stats this card's position is judged on are accented, the same way
	# PlayerDetail marks them -- the lookup goes through the position, so a
	# row pair is never one of PRIMARY_STATS_BY_POSITION's keys.
	var primary: Array = card.primary_stats()
	for row in ATTR_ROWS:
		_add_attr_cells(tr(row[0]), int(card.attributes.get(row[1], 0)), row[1] in primary)


## Reached when the last card is sold out from under the panel.
func _clear_card_detail() -> void:
	_detail_name_label.text = ""
	_detail_meta_label.text = ""
	_detail_origin_label.text = ""
	for child in _detail_attr_grid.get_children():
		_detail_attr_grid.remove_child(child)
		child.queue_free()


## Name left, value right -- the same pair of cells PlayerDetail's own
## attribute grid is built from. `highlight` marks a primary stat; every
## other row takes the Theme's own Label colour.
func _add_attr_cells(label_text: String, value: int, highlight: bool) -> void:
	var accent := ThemeManager.color("accent")

	var name_label := Label.new()
	name_label.text = label_text
	name_label.add_theme_font_size_override("font_size", 12)
	if highlight:
		name_label.add_theme_color_override("font_color", accent)
	_detail_attr_grid.add_child(name_label)

	var value_label := Label.new()
	value_label.text = str(value)
	value_label.add_theme_font_size_override("font_size", 12)
	value_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	value_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	if highlight:
		value_label.add_theme_color_override("font_color", accent)
	_detail_attr_grid.add_child(value_label)


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

	# The strip reports its new centre as each card leaves it, so what the
	# panel reads has to be right before the first one goes.
	var kept: Array = []
	for card in _cards:
		if not sold.has(card.player_id):
			kept.append(card)
	_cards = kept
	_browse_order = _cards.duplicate()
	_browse_order.reverse()

	for pid in sold:
		GameProfile.release_card(pid)
		var view: PlayerCardView = _browse_views.get(pid)
		if view != null:
			_carousel.remove_view(view)
			view.queue_free()
		_browse_views.erase(pid)
	GameProfile.apply_inventory_cap(res.data.get("inventory_cap"))
	GameProfile.apply_currency_balances(res.data.get("credits_remaining"))

	_exit_sell_mode()
