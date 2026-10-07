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
## Play.gd's /match/quick response populated it with. It is NOT cleared here
## -- "Detailed Stats" opens MatchStats.tscn, which reads the same data --
## so clearing happens on the way back to the Menu instead.
##
## "Something went wrong? Report it" files a bug report against this match
## (POST /match/report): a category, a few optional words, and the game id
## -- which is all the server needs, because the seed and both rosters as
## played are already on the games/{id} doc, so the match can be re-run
## exactly. Hidden for the demo replay and for local test matches, which
## have no game doc to report against.

const MATCH_STATS_SCENE := "res://scenes/MatchStats.tscn"

## Mirrors backend/config.py's MATCH_REPORT_CATEGORIES, in the order the
## dropdown shows them: [key the server takes, label].
const REPORT_CATEGORIES := [
	["stuck_players", "Players stuck or standing still"],
	["ball_physics", "Ball went through someone / teleported"],
	["goalkeeper", "Goalkeeper did something absurd"],
	["wrong_score", "Score doesn't match what I saw"],
	["replay_glitch", "Replay froze, skipped or the camera lost the ball"],
	["other", "Something else"],
]

## [label, stat key, format]. "int" renders a plain total, "fewer" one where
## the lower side is ahead, "pct" a percentage, "rating" one decimal place.
const SUMMARY_ROWS := [
	["Shots", "shots", "int"],
	["On target", "shots_on_target", "int"],
	["Passes", "passes", "int"],
	["Pass accuracy", "pass_accuracy", "pct"],
	["Tackles won", "tackles_won", "int"],
	["Fouls", "fouls", "fewer"],
	["Saves", "saves", "int"],
	["Avg rating", "avg_rating", "rating"],
]

@onready var _outcome_label: Label = %OutcomeLabel
@onready var _score_label: Label = %ScoreLabel
@onready var _credits_label: Label = %CreditsLabel
@onready var _credits_icon: TextureRect = %CreditsIcon
@onready var _double_button: Button = %DoubleButton
@onready var _home_scorers: VBoxContainer = %HomeScorers
@onready var _away_scorers: VBoxContainer = %AwayScorers
@onready var _stats_grid: GridContainer = %StatsGrid
@onready var _details_button: Button = %DetailsButton
@onready var _continue_button: Button = %ContinueButton
@onready var _loading_popup: Control = %LoadingPopup
@onready var _report_button: Button = %ReportButton
@onready var _report_overlay: Control = %ReportOverlay
@onready var _report_category: OptionButton = %ReportCategory
@onready var _report_text: TextEdit = %ReportText
@onready var _report_footnote: Label = %ReportFootnote
@onready var _report_cancel_button: Button = %ReportCancelButton
@onready var _report_send_button: Button = %ReportSendButton

var _reporting: bool = false


func _ready() -> void:
	_continue_button.pressed.connect(_on_continue_pressed)
	_details_button.pressed.connect(_on_details_pressed)
	_double_button.pressed.connect(_on_double_pressed)
	AdManager.ad_reward_completed.connect(_on_ad_completed)
	_report_button.pressed.connect(_on_report_pressed)
	_report_cancel_button.pressed.connect(func() -> void: _report_overlay.visible = false)
	_report_send_button.pressed.connect(_on_report_send_pressed)
	for entry in REPORT_CATEGORIES:
		_report_category.add_item(tr(entry[1]))
	_report_overlay.visible = false
	# Nothing to report against without a game doc (demo replay, local test).
	_report_button.visible = MatchSession.game_id != ""
	_report_footnote.add_theme_color_override("font_color", ThemeManager.color("text_hint"))

	# The outcome is on screen now, so the strip can show the payout.
	MatchSession.release_held_profile()

	var score: Array = MatchSession.score
	var my_score: int = score[0] if score.size() == 2 else 0
	var opp_score: int = score[1] if score.size() == 2 else 0
	var opponent_name: String = MatchSession.opponent_display_name if MatchSession.opponent_display_name != "" else tr("Opponent")
	var my_name: String = GameProfile.display_name_or_you()

	# Decision: dont show that they are bots the user doesnt need to know
	if MatchSession.opponent_is_bot:
		pass
		#opponent_name += tr(" (Bot)")

	if my_score > opp_score:
		_outcome_label.text = tr("You Won!")
		_outcome_label.add_theme_color_override("font_color", Color(0.4, 1.0, 0.4))
	elif my_score == opp_score:
		_outcome_label.text = tr("Draw")
		_outcome_label.add_theme_color_override("font_color", Color(1.0, 0.9, 0.4))
	else:
		_outcome_label.text = tr("You Lost")
		_outcome_label.add_theme_color_override("font_color", Color(1.0, 0.4, 0.4))

	_score_label.text = tr("%s %d - %d %s") % [my_name, my_score, opp_score, opponent_name]
	# The logo beside it is what says which currency this is -- the name
	# never appears on screen. Texture set here rather than in the scene
	# so CurrencyDisplay.ICONS stays the only place a logo path lives.
	_credits_label.text = "+%s" % CurrencyDisplay.format_amount(MatchSession.credits_earned)
	_credits_icon.texture = CurrencyDisplay.icon_for("credits")
	_refresh_double_button(my_score > opp_score)

	_populate_scorers(my_name, MatchSession.TEAM_HOME, _home_scorers)
	_populate_scorers(opponent_name, MatchSession.TEAM_AWAY, _away_scorers)
	_populate_summary()

	# Nothing to drill into without per-player numbers (an older backend, or
	# the bundled demo replay).
	_details_button.disabled = not MatchSession.has_match_stats()


func _populate_scorers(team_name: String, team: int, into: VBoxContainer) -> void:
	for child in into.get_children():
		into.remove_child(child)
		child.queue_free()

	var heading := Label.new()
	heading.text = team_name
	heading.add_theme_font_size_override("font_size", 15)
	heading.add_theme_color_override("font_color", Color(0.75, 0.85, 1.0))
	heading.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	into.add_child(heading)

	var scorers: Array = MatchSession.scorers(team)
	if scorers.is_empty():
		var none := Label.new()
		none.text = "-"
		none.add_theme_font_size_override("font_size", 12)
		none.add_theme_color_override("font_color", Color(0.6, 0.6, 0.6))
		none.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		into.add_child(none)
		return

	for entry in scorers:
		var minutes: Array = entry.get("minutes", [])
		var stamps: Array = []
		for minute in minutes:
			stamps.append("%d'" % int(minute))
		var row := Label.new()
		row.text = "%s  %s" % [entry.get("name", "?"), ", ".join(stamps)]
		row.add_theme_font_size_override("font_size", 13)
		row.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		into.add_child(row)


## Three columns: your value, the stat's name, their value -- so the two
## sides read against each other with the label between them.
func _populate_summary() -> void:
	for child in _stats_grid.get_children():
		_stats_grid.remove_child(child)
		child.queue_free()

	if not MatchSession.has_match_stats():
		var unavailable := Label.new()
		unavailable.text = tr("Match stats unavailable for this match.")
		unavailable.add_theme_font_size_override("font_size", 12)
		unavailable.add_theme_color_override("font_color", Color(0.65, 0.65, 0.65))
		_stats_grid.add_child(unavailable)
		return

	var home: Dictionary = MatchSession.team_summary(MatchSession.TEAM_HOME)
	var away: Dictionary = MatchSession.team_summary(MatchSession.TEAM_AWAY)

	for row in SUMMARY_ROWS:
		var label: String = tr(row[0])
		var key: String = row[1]
		var kind: String = row[2]
		var home_text := _format_stat(home.get(key, 0), kind)
		var away_text := _format_stat(away.get(key, 0), kind)
		var flip := -1 if kind == "fewer" else 1

		_stats_grid.add_child(_value_label(home_text, flip * _compare(home.get(key, 0), away.get(key, 0)), HORIZONTAL_ALIGNMENT_RIGHT))
		_stats_grid.add_child(_name_label(label))
		_stats_grid.add_child(_value_label(away_text, flip * _compare(away.get(key, 0), home.get(key, 0)), HORIZONTAL_ALIGNMENT_LEFT))


func _format_stat(value, kind: String) -> String:
	match kind:
		"pct":
			return "%d%%" % int(round(float(value)))
		"rating":
			return "%.1f" % float(value)
		_:
			return str(int(value))


func _compare(mine, theirs) -> int:
	if float(mine) > float(theirs):
		return 1
	if float(mine) < float(theirs):
		return -1
	return 0


func _value_label(text: String, advantage: int, alignment: int) -> Label:
	var label := Label.new()
	label.text = text
	label.horizontal_alignment = alignment
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	label.add_theme_font_size_override("font_size", 14)
	if advantage > 0:
		label.add_theme_color_override("font_color", Color(0.5, 1.0, 0.5))
	elif advantage < 0:
		label.add_theme_color_override("font_color", Color(0.85, 0.85, 0.85))
	return label


func _name_label(text: String) -> Label:
	var label := Label.new()
	label.text = text
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.add_theme_font_size_override("font_size", 13)
	label.add_theme_color_override("font_color", Color(0.65, 0.65, 0.7))
	return label


func _on_details_pressed() -> void:
	get_tree().change_scene_to_file(MATCH_STATS_SCENE)


## Offered after a win that paid something, while today's doubles last. The
## server re-checks all of it (services/ads.double_win_credits) before paying.
func _refresh_double_button(won: bool) -> void:
	var track := AdManager.TRACK_DOUBLE_WIN
	var left := GameProfile.ad_max(track) - GameProfile.ad_watched(track)
	_double_button.visible = (
		won and MatchSession.credits_earned > 0 and MatchSession.game_id != ""
		and not MatchSession.is_local and AdManager.ads_supported() and left > 0
	)
	_double_button.text = tr("Double it with an ad (%d left)") % left


func _on_double_pressed() -> void:
	_double_button.disabled = true
	if not AdManager.show_ad_for_track(AdManager.TRACK_DOUBLE_WIN, MatchSession.game_id):
		_double_button.text = tr("Ad not ready -- try again in a moment.")
		_double_button.disabled = false


## AdManager's signal is global, so the track has to be checked.
func _on_ad_completed(track: String, status: String) -> void:
	if track != AdManager.TRACK_DOUBLE_WIN:
		return
	match status:
		"granted":
			_credits_label.text = "+%s" % CurrencyDisplay.format_amount(MatchSession.credits_earned * 2)
			_double_button.visible = false
		"pending":
			_double_button.text = tr("Reward is on its way -- it lands within a minute.")
		_:
			_double_button.text = tr("Ad was closed early or failed to verify.")
			_double_button.disabled = false


# -- bug report ---------------------------------------------------------------


func _on_report_pressed() -> void:
	if _reporting:
		return
	_report_overlay.visible = true
	_report_text.grab_focus()


func _on_report_send_pressed() -> void:
	if _reporting or MatchSession.game_id == "":
		return
	var index := _report_category.selected
	if index < 0 or index >= REPORT_CATEGORIES.size():
		index = REPORT_CATEGORIES.size() - 1  # "Something else"

	_reporting = true
	_report_send_button.disabled = true
	_report_cancel_button.disabled = true
	_report_send_button.text = tr("Sending...")

	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST,
		"/match/report",
		{
			"game_id": MatchSession.game_id,
			"category": REPORT_CATEGORIES[index][0],
			"description": _report_text.text,
		},
	)

	_reporting = false
	_report_cancel_button.disabled = false
	_report_send_button.disabled = false
	_report_send_button.text = tr("Send report")

	if not res.ok:
		_report_footnote.text = tr("Could not send the report -- try again.")
		_report_footnote.add_theme_color_override("font_color", ThemeManager.color("warning"))
		return

	# Sent. The button stays so a second, better-worded report can replace
	# the first (the server keeps one per match per player), but it says so.
	_report_overlay.visible = false
	_report_button.text = tr("Reported -- thanks! Tap to add more")


## The squad already has its post-match stats from the response (see
## MatchSession.release_held_profile); only an older backend's reply needs a reload.
func _on_continue_pressed() -> void:
	_continue_button.disabled = true
	_details_button.disabled = true
	# Read the destination BEFORE clear(), which resets it -- otherwise a
	# tournament match silently lands back on the Menu mid-run.
	var destination := MatchSession.return_scene
	var reload := not MatchSession.squad_is_current()
	MatchSession.clear()
	if reload:
		_loading_popup.set_status(tr("Loading players..."))
		_loading_popup.visible = true
		await GameProfile.load_all()
	get_tree().change_scene_to_file(destination)
