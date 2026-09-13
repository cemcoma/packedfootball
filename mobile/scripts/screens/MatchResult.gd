extends Control

## Shown right after a real Quick Match finishes -- MatchPlayback.gd
## navigates here once FULL TIME's banner has run its course (see that
## script's _process()). Purely a recap of a result that already happened:
## /match/quick resolves the whole match (opponent pick, simulation,
## credit reward, Firestore persistence) synchronously server-side before
## Play.gd's request even returns, so nothing on this screen can change
## the outcome, only display it.
##
## Reads straight off the MatchSession autoload, still holding whatever
## Play.gd's /match/quick response populated it with -- MatchPlayback.gd
## deliberately left it alone rather than clearing it (see that script's
## own docstring). Clears it here once read, so a stray later visit to
## this scene (or back to Match.tscn) doesn't show a stale result.

@onready var _outcome_label: Label = %OutcomeLabel
@onready var _score_label: Label = %ScoreLabel
@onready var _credits_label: Label = %CreditsLabel
@onready var _continue_button: Button = %ContinueButton
@onready var _contraster: ColorRect = %Contraster
@onready var _loading_popup: Control = %LoadingPopup


func _ready() -> void:
	_continue_button.pressed.connect(_on_continue_pressed)

	var score: Array = MatchSession.score
	var my_score: int = score[0] if score.size() == 2 else 0
	var opp_score: int = score[1] if score.size() == 2 else 0
	var opponent_name: String = MatchSession.opponent_display_name if MatchSession.opponent_display_name != "" else "Opponent"
	if MatchSession.opponent_is_bot:
		opponent_name += " (Bot)"

	if my_score > opp_score:
		_outcome_label.text = "You Won!"
		_outcome_label.add_theme_color_override("font_color", Color(0.4, 1.0, 0.4))
	elif my_score == opp_score:
		_outcome_label.text = "Draw"
		_outcome_label.add_theme_color_override("font_color", Color(1.0, 0.9, 0.4))
	else:
		_outcome_label.text = "You Lost"
		_outcome_label.add_theme_color_override("font_color", Color(1.0, 0.4, 0.4))

	_score_label.text = "You %d - %d %s" % [my_score, opp_score, opponent_name]
	_credits_label.text = "+%d credits" % MatchSession.credits_earned

	MatchSession.clear()


## Re-fetches the squad from Firestore before heading back to Menu --
## /match/quick already persisted each played player's updated goals/
## assists/matches_played server-side (see backend/main.py's
## _persist_player_stats), but GameProfile.all_cards was only ever
## populated once at sign-in (see Auth.gd's _go_to_menu -> GameProfile.
## load_all()) and nothing had refreshed it since, so Team's own card
## views kept showing the pre-match stats until a full app restart. Same
## fix, same reason, in MatchPlayback.gd's _on_exit_pressed() for whoever
## backs out via the pause menu before ever reaching this screen.
func _on_continue_pressed() -> void:
	_continue_button.disabled = true
	_loading_popup.set_status("Loading players...")
	_loading_popup.visible = true
	await GameProfile.load_all()
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")
