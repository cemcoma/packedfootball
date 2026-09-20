extends Control

## One player, in full: every attribute, every tendency, every career stat,
## plus the two things you can do to a card you own -- release it for credits
## or pay to restyle it.
##
## Which player is PlayerSession.player_id (see that autoload: the id, never
## the card, so this screen can't show one that's already been released).
## Everything shown comes off the GameProfile cache; nothing here refetches.
##
## Release is the only destructive action in the app, and it's irreversible
## -- the card's players/{id} document is deleted server-side, not archived.
## Hence the confirm overlay, and hence the button being refused outright for
## a player in the starting XI (the backend refuses it too; this is so the
## reason is readable rather than a failed request).

## Attributes as they come out of player.py's Attributes dataclass, split
## into the three groups it documents: skills, the one physical field that
## isn't a 0-100 skill, and the tendencies that steer decisions rather than
## describing ability. The Squad screen shows a subset of this; "all details"
## means all of it.
const SKILL_ROWS := [
	["Stamina", "stamina"], ["Speed", "speed"], ["Agility", "agility"],
	["Passing", "passing"], ["Ball control", "ballcontrol"], ["Defending", "defending"],
	["Tackling", "tackling"], ["Dribbling", "dribbiling"], ["Shooting", "shooting"],
	["Power", "power"], ["Accuracy", "accuracy"], ["Vision", "vision"],
	["Heading", "heading"],
]

const TENDENCY_ROWS := [
	["Pass", "pass_tendency"], ["Shoot", "shoot_tendency"], ["Dribble", "drible_tendency"],
	["Aggression", "aggression"], ["Composure", "composure"], ["Clear", "clear_tendency"],
]

const STAT_ROWS := [
	["Matches", "matches_played"], ["Goals", "goals"], ["Assists", "assists"],
	["Shots", "shots"], ["On target", "shots_on_target"],
	["Passes", "passes"], ["Completed", "passes_completed"], ["Pass acc.", "_pass_accuracy"],
	["Tackles", "tackles"], ["Tackles won", "tackles_won"],
]

const KEEPER_STAT_ROWS := [
	["Saves", "saves"], ["Clean sheets", "clean_sheets"], ["Conceded", "goals_conceded"],
]

@onready var _name_label: Label = %NameLabel
@onready var _subtitle_label: Label = %SubtitleLabel
@onready var _credits_chip: CurrencyChip = %CreditsChip

@onready var _card_view: PlayerCardView = %CardView
@onready var _origin_label: Label = %OriginLabel

@onready var _attributes_heading: Label = %AttributesHeading
@onready var _attributes_grid: GridContainer = %AttributesGrid
@onready var _tendencies_heading: Label = %TendenciesHeading
@onready var _tendencies_grid: GridContainer = %TendenciesGrid
@onready var _career_heading: Label = %CareerHeading
@onready var _career_grid: GridContainer = %CareerGrid

@onready var _status_label: Label = %StatusLabel
@onready var _customize_button: Button = %CustomizeButton
@onready var _release_button: Button = %ReleaseButton
@onready var _back_button: Button = %BackButton

@onready var _confirm_overlay: Control = %ConfirmOverlay
@onready var _confirm_label: Label = %ConfirmLabel
@onready var _confirm_reward_label: Label = %ConfirmRewardLabel
@onready var _confirm_reward_icon: TextureRect = %ConfirmRewardIcon
@onready var _confirm_footnote: Label = %ConfirmFootnote
@onready var _confirm_button: Button = %ConfirmButton
@onready var _cancel_button: Button = %CancelButton

var _card: PlayerCard = null
var _releasing: bool = false


func _ready() -> void:
	_customize_button.pressed.connect(_on_customize_pressed)
	_release_button.pressed.connect(_on_release_pressed)
	_back_button.pressed.connect(_on_back_pressed)
	_confirm_button.pressed.connect(_on_confirm_release_pressed)
	_cancel_button.pressed.connect(_on_cancel_release_pressed)

	_credits_chip.set_currency("credits")
	_confirm_overlay.visible = false

	ThemeManager.theme_changed.connect(_apply_theme_colors)

	_card = PlayerSession.card()
	if _card == null:
		# Nothing selected, or the card was released from under us -- there is
		# no screen to show, so don't pretend there is.
		_go_back()
		return
	_refresh()


# -- state -> UI --------------------------------------------------------------


func _refresh() -> void:
	_credits_chip.set_amount(GameProfile.credits)
	_name_label.text = _card.full_name()
	_subtitle_label.text = tr("%s  ·  %s  ·  Overall %d") % [
		_card.position, PlayerCard.tier_label(_card.tier), _card.overall()
	]
	_origin_label.text = "%s\n%s\n%d cm" % [
		_card.hometown, _card.country, int(_card.attributes.get("height", 0))
	]
	_card_view.set_card(_card)

	_populate(_attributes_grid, SKILL_ROWS, _attribute_text)
	_populate(_tendencies_grid, TENDENCY_ROWS, _attribute_text)
	_populate_career()
	_refresh_buttons()
	_apply_theme_colors()


func _populate(grid: GridContainer, rows: Array, value_for: Callable) -> void:
	for child in grid.get_children():
		grid.remove_child(child)
		child.queue_free()
	for row in rows:
		_add_row(grid, tr(row[0]), value_for.call(row[1]))


func _populate_career() -> void:
	var rows: Array = STAT_ROWS.duplicate()
	# A keeper's saves/clean sheets matter and an outfielder's are noise --
	# same filter the Squad screen's statistics page applies.
	if _card.position == "GK":
		rows.append_array(KEEPER_STAT_ROWS)
	rows.append(["Avg rating", "_average_rating"])
	_populate(_career_grid, rows, _career_text)


func _add_row(grid: GridContainer, label_text: String, value_text: String) -> void:
	var name_label := Label.new()
	name_label.text = label_text
	name_label.add_theme_font_size_override("font_size", 12)
	grid.add_child(name_label)

	var value_label := Label.new()
	value_label.text = value_text
	value_label.add_theme_font_size_override("font_size", 12)
	value_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	value_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grid.add_child(value_label)


func _attribute_text(key: String) -> String:
	return str(int(_card.attributes.get(key, 0)))


func _career_text(key: String) -> String:
	if key == "_pass_accuracy":
		var passes: float = float(_card.statistics.get("passes", 0))
		if passes <= 0.0:
			return "-"
		return "%d%%" % int(round(100.0 * float(_card.statistics.get("passes_completed", 0)) / passes))
	if key == "_average_rating":
		# rating_sum/rating_count are storage rather than a stat -- derive the
		# average the same way player.py's average_rating() does.
		var count: float = float(_card.statistics.get("rating_count", 0))
		if count <= 0.0:
			return "-"
		return "%.2f" % (float(_card.statistics.get("rating_sum", 0.0)) / count)
	return str(int(_card.statistics.get(key, 0)))


## Release is refused for a player in the XI: deleting them would leave
## roster_player_ids pointing at a card that no longer exists.
func _is_starting() -> bool:
	return GameProfile.slot_assignment.has(_card.player_id)


## The payout rides INSIDE the Release button, as a signed amount and the
## credits logo -- see CurrencyDisplay.set_button_price. An XI player can't
## be released at all, so that button carries no price: showing one for a
## thing you can't do is worse than showing nothing.
func _refresh_buttons() -> void:
	_customize_button.text = tr("Customize")
	if _is_starting():
		_release_button.disabled = true
		CurrencyDisplay.set_button_price(_release_button, tr("Release (in XI)"), 0)
	else:
		_release_button.disabled = _releasing
		CurrencyDisplay.set_button_price(
			_release_button, tr("Release"), PlayerCard.release_credits(_card.tier)
		)


## Everything on this screen sits on the plain screen background rather than
## inside a themed Panel, so the headings and status line need the palette --
## see ThemeManager's note on text_hint.
func _apply_theme_colors() -> void:
	var heading := ThemeManager.color("heading")
	_subtitle_label.add_theme_color_override("font_color", heading)
	_attributes_heading.add_theme_color_override("font_color", heading)
	_tendencies_heading.add_theme_color_override("font_color", heading)
	_career_heading.add_theme_color_override("font_color", heading)
	_origin_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	# The confirm text sits inside a themed PanelContainer -- which has its own
	# background in both modes -- so it takes the Theme's Label colour and
	# needs no override at all. It used to hardcode white, from back when
	# PanelContainer was unthemed and fell through to Godot's dark default;
	# that white is now invisible on the light theme's near-white panel.
	# Only the reward amount is coloured, and that's the currency's accent.
	_confirm_reward_label.add_theme_color_override(
		"font_color", CurrencyDisplay.color_for("credits")
	)


func _set_status(text: String, positive: bool = false) -> void:
	_status_label.text = text
	_status_label.add_theme_color_override(
		"font_color",
		ThemeManager.color("positive") if positive else ThemeManager.color("warning")
	)


# -- input handlers -----------------------------------------------------------


func _on_customize_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/CustomizePlayer.tscn")


func _on_release_pressed() -> void:
	if _releasing or _is_starting():
		return
	_confirm_label.text = tr("Release %s?\n\n%s %s, overall %d.\n\nYou get") % [
		_card.full_name(), PlayerCard.tier_label(_card.tier), _card.position, _card.overall()
	]
	# The reward is its own row rather than part of the sentence above,
	# because it needs the logo beside it -- a Label can't carry an inline
	# texture, and naming the currency is exactly what we're avoiding.
	_confirm_reward_label.text = "+%s" % CurrencyDisplay.format_amount(
		PlayerCard.release_credits(_card.tier)
	)
	_confirm_reward_icon.texture = CurrencyDisplay.icon_for("credits")
	_confirm_overlay.visible = true


func _on_cancel_release_pressed() -> void:
	_confirm_overlay.visible = false


func _on_confirm_release_pressed() -> void:
	if _releasing:
		return
	_releasing = true
	_confirm_button.disabled = true
	_cancel_button.disabled = true
	_set_status(tr("Releasing..."))

	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST, "/player/release", {"player_id": _card.player_id}
	)

	_releasing = false
	_confirm_button.disabled = false
	_cancel_button.disabled = false
	_confirm_overlay.visible = false

	if not res.ok:
		# 409 is the backend's "that player is in your starting XI", which
		# this screen already blocks -- so seeing it means the cached lineup
		# disagrees with Firestore, not that the user did something wrong.
		_set_status(
			tr("That player is in your saved starting XI -- replace them on the Squad screen first.")
			if res.status == 409
			else tr("Could not release this player -- try again.")
		)
		_refresh_buttons()
		return

	GameProfile.release_card(_card.player_id)
	GameProfile.apply_inventory_cap(res.data.get("inventory_cap"))
	GameProfile.apply_currency_balances(res.data.get("credits_remaining"))
	PlayerSession.clear()
	_go_back()


func _on_back_pressed() -> void:
	_go_back()


## Deferred because one caller is _ready(): the tree is still busy adding
## this scene's own children at that point, and swapping the scene out from
## under it errors out (and leaves you on a screen with no card).
func _go_back() -> void:
	get_tree().change_scene_to_file.call_deferred(PlayerSession.return_scene)
