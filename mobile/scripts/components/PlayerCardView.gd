class_name PlayerCardView
extends Control

## Reusable "card" visual for a PlayerCard: a tier-colored rectangle showing
## overall/position/name/tier. The actual template lives in the companion
## PlayerCardView.tscn (open it in the editor to restyle) -- this script
## only fills in the fields and forwards taps. Used everywhere a card needs
## to be shown (the bench grid, the selected-slot detail panel in
## Team.tscn, and future screens like Shop/PVP) so there is exactly one
## template to redesign when real card art/a real character portrait
## exists, instead of every screen that shows a card needing its own
## update.
##
## Styling today is just PlayerCard.tier_color() as a flat background (the
## scene's "Background" ColorRect) -- see that function's own doc comment
## for the natural upgrade path (a per-tier Resource carrying a texture/
## shader instead of a plain Color) once real art exists.
##
## The "Model" child (see PlayerModelView.gd) is the placeholder layered
## character portrait -- a real appearance rolled server-side per card (see
## PlayerAppearance.gd's docstring), falling back to a mock look derived
## from player_id alone only for a card that predates that.

signal pressed

const OUT_OF_POSITION_COLOR := Color(1.0, 0.7, 0.3)  # same amber Team.gd uses for "unsaved changes"

@onready var _background: ColorRect = %Background
@onready var _overall_label: Label = %OverallLabel
@onready var _position_label: Label = %PositionLabel
@onready var _name_label: Label = %NameLabel
@onready var _tier_label: Label = %TierLabel
@onready var _tap_button: Button = %TapButton
@onready var _model_view: PlayerModelView = %Model

var _card: PlayerCard = null


func _ready() -> void:
	_tap_button.pressed.connect(_on_tap_button_pressed)


func _on_tap_button_pressed() -> void:
	pressed.emit()


func set_card(card: PlayerCard) -> void:
	_card = card
	_background.color = PlayerCard.tier_color(card.tier)
	_overall_label.text = str(card.overall())
	_position_label.text = card.position
	_name_label.text = card.display_name()
	_tier_label.text = card.tier.capitalize()
	_model_view.set_card(card)
	set_out_of_position(false)  # caller re-applies via set_out_of_position() if relevant to this context


## Tints the position label amber -- used by Team.gd wherever this card is
## shown assigned to (or being considered for) a slot whose role differs
## from card.position (a "similar position" substitution -- see
## Formations.is_similar_position -- since anything else is never allowed
## to reach this screen at all). Purely a display hint; the actual 0.9x
## attribute penalty only ever applies inside gameEngine.py's match
## simulation, never to what's shown here.
func set_out_of_position(is_out_of_position: bool) -> void:
	if is_out_of_position:
		_position_label.add_theme_color_override("font_color", OUT_OF_POSITION_COLOR)
	else:
		_position_label.remove_theme_color_override("font_color")


func set_highlighted(is_highlighted: bool) -> void:
	modulate = Color(1.15, 1.15, 0.85) if is_highlighted else Color.WHITE
