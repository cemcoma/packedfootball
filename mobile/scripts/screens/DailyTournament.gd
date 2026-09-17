extends Control

## The daily tournament: your tier, your group's table, and the button that
## plays the next of your ten matches.
##
## ONE request builds this whole screen. GET /tournament/today returns the
## tier, the standings, the energy block, the rules and the reward table
## together, because the screen is useless until it has all of it and four
## round trips on a phone is four chances to show a half-built page.
##
## That same request is also what SETTLES yesterday. There is no scheduler and
## no notification system, so the day a player comes back, their previous
## group is resolved before this screen is built and the result rides along in
## `pending_results` -- which is why the "you were promoted" banner can exist
## at all.
##
## Countdowns tick locally from the seconds the server sent (see TimeFormat),
## never from a parsed timestamp, so a device with a wrong clock still shows
## the right numbers.

const HUB_SCENE := "res://scenes/Tournament.tscn"
const MATCH_SCENE := "res://scenes/Match.tscn"

@onready var _tier_label: Label = %TierLabel
@onready var _countdown_label: Label = %CountdownLabel
@onready var _energy_bar: EnergyBar = %EnergyBar
@onready var _credits_chip: CurrencyChip = %CreditsChip

@onready var _status_label: Label = %StatusLabel
@onready var _progress_label: Label = %ProgressLabel
@onready var _standings: StandingsTable = %Standings
@onready var _rules_label: Label = %RulesLabel
@onready var _rewards_box: VBoxContainer = %RewardsBox
@onready var _rewards_heading: Label = %RewardsHeading

@onready var _join_button: Button = %JoinButton
@onready var _play_button: Button = %PlayButton
@onready var _back_button: Button = %BackButton
@onready var _busy_popup: Control = %BusyPopup

@onready var _banner: Control = %ResultBanner
@onready var _banner_label: Label = %BannerLabel
@onready var _banner_button: Button = %BannerButton

var _state: Dictionary = {}
var _busy: bool = false
var _seconds_remaining: float = 0.0


func _ready() -> void:
	_join_button.pressed.connect(_on_join_pressed)
	_play_button.pressed.connect(_on_play_pressed)
	_back_button.pressed.connect(_on_back_pressed)
	_banner_button.pressed.connect(func() -> void: _banner.visible = false)

	_credits_chip.set_currency("credits")
	_banner.visible = false
	_busy_popup.visible = false

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	await _load(tr("Loading today's tournament..."))


func _process(delta: float) -> void:
	if _seconds_remaining <= 0.0:
		return
	_seconds_remaining -= delta
	_countdown_label.text = TimeFormat.ends_in(int(ceil(_seconds_remaining)))


# -- fetching ------------------------------------------------------------------


func _load(status: String) -> void:
	if _busy:
		return
	_busy = true
	_busy_popup.set_status(status)
	_busy_popup.visible = true

	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/tournament/today")

	_busy_popup.visible = false
	_busy = false

	if not res.ok:
		_set_status(tr("Could not load the tournament -- try again."), true)
		return
	_apply_state(res.data)


func _apply_state(data: Dictionary) -> void:
	_state = data
	_seconds_remaining = float(_int(data, "seconds_remaining", 0))

	var tier_name = data.get("tier_name")
	_tier_label.text = tier_name if tier_name is String else tr("Tournament")
	_countdown_label.text = TimeFormat.ends_in(int(_seconds_remaining))

	# Into the shared cache too, not just this bar -- Menu, Play and Shop all
	# show the same number and should not be stale after a tournament match.
	GameProfile.apply_energy(data.get("energy"))
	_energy_bar.set_energy(GameProfile.energy)
	_credits_chip.set_amount(GameProfile.credits)

	var standings = data.get("standings")
	_standings.set_rows(standings if standings is Array else [])

	_refresh_progress()
	_refresh_rules()
	_refresh_rewards()
	_refresh_buttons()
	_apply_theme_colors()
	_show_pending_results(data.get("pending_results"))


static func _int(data: Dictionary, key: String, default: int) -> int:
	var value = data.get(key)
	return int(value) if typeof(value) in [TYPE_INT, TYPE_FLOAT] else default


# -- state -> UI ---------------------------------------------------------------


func _refresh_progress() -> void:
	var played := _int(_state, "matches_played", 0)
	var total := _int(_state, "matches_max", 10)
	var size := _int(_state, "group_size", 0)
	var capacity := _int(_state, "group_capacity", 6)

	if not bool(_state.get("joined", false)):
		_progress_label.text = tr("Not entered yet.")
		return
	_progress_label.text = tr("Match %d of %d  ·  %d of %d players in your group") % [
		mini(played + 1, total), total, size, capacity
	]


func _refresh_rules() -> void:
	var rules = _state.get("rules")
	if not (rules is Dictionary):
		_rules_label.text = ""
		return

	var mode := str(_state.get("settlement_mode", ""))
	var floor_pts := _int(rules, "promotion_floor", 20)
	var drop_pts := _int(rules, "relegation_floor", 10)
	var min_group := _int(rules, "min_group_for_promotion", 3)

	# The two paths genuinely work differently, and a player in a short group
	# who was told "top 2 go up" would be misled -- so the screen says which
	# rule is currently in force rather than one generic sentence.
	if mode == "positional":
		_rules_label.text = tr("Full group: the top 2 go up with at least %d points, the bottom 2 go down.") % floor_pts
	else:
		_rules_label.text = tr("Group isn't full, so points decide: %d or more goes up, under %d goes down. Needs %d players in the group to go up at all.") % [floor_pts, drop_pts, min_group]


func _refresh_rewards() -> void:
	for child in _rewards_box.get_children():
		_rewards_box.remove_child(child)
		child.queue_free()

	var rewards = _state.get("rewards")
	if not (rewards is Array) or rewards.is_empty():
		var none := Label.new()
		none.text = tr("No placement rewards in this tier.")
		none.add_theme_font_size_override("font_size", 11)
		none.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
		_rewards_box.add_child(none)
		return

	for entry in rewards:
		if not (entry is Dictionary):
			continue
		_rewards_box.add_child(_reward_row(entry))


## One reward line: the finishing position, then each currency as an amount
## beside its logo. CurrencyAmount already does amount-plus-logo, so the
## currency is never named here either.
func _reward_row(entry: Dictionary) -> HBoxContainer:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)

	var position := Label.new()
	position.text = "%d." % _int(entry, "position", 0)
	position.custom_minimum_size = Vector2(24, 0)
	position.add_theme_font_size_override("font_size", 12)
	row.add_child(position)

	for currency in ["medals", "bucks", "credits"]:
		var amount := _int(entry, currency, 0)
		if amount <= 0:
			continue
		var view: CurrencyAmount = preload("res://scenes/components/CurrencyAmount.tscn").instantiate()
		row.add_child(view)
		view.set_amount(currency, amount)
		view.set_sizes(16, 12)

	return row


func _refresh_buttons() -> void:
	var joined: bool = bool(_state.get("joined", false))
	var closed: bool = bool(_state.get("join_closed", false))
	var played := _int(_state, "matches_played", 0)
	var total := _int(_state, "matches_max", 10)
	var out_of_matches: bool = played >= total
	var out_of_energy: bool = _energy_bar.energy() <= 0

	_join_button.visible = not joined
	_play_button.visible = joined

	if not joined:
		_join_button.disabled = _busy or closed
		_join_button.text = tr("Entries closed") if closed else tr("Enter today's tournament")
		if closed:
			var reopens := TimeFormat.coarse_duration(int(_seconds_remaining))
			_set_status(tr("Entries are closed for the last hour of the day -- the next tournament starts in %s.") % reopens, false)
		return

	_play_button.disabled = _busy or out_of_matches or out_of_energy
	if out_of_matches:
		_play_button.text = tr("All %d matches played") % total
		_set_status(tr("You're done for today. Come back when the day resets."), false)
	elif out_of_energy:
		_play_button.text = tr("Out of energy")
		_set_status(tr("No energy left -- it refills over time, or top up in the Shop."), true)
	else:
		_play_button.text = tr("Play match %d of %d") % [played + 1, total]


func _show_pending_results(pending) -> void:
	if not (pending is Dictionary):
		return
	var me = pending.get("me")
	if not (me is Dictionary):
		return

	var outcome := str(me.get("outcome", "stay"))
	var position := _int(me, "position", 0)
	var clamped: bool = bool(me.get("tier_clamped", false))

	var headline := ""
	match outcome:
		"promote":
			# A top-tier winner "promotes" nowhere -- the rule said up, the
			# ceiling refused. Saying "you stayed" would read as failure.
			headline = tr("You held the top tier!") if clamped else tr("You were promoted!")
		"relegate":
			headline = tr("You stayed up.") if clamped else tr("You were relegated.")
		_:
			headline = tr("You held your tier.")

	var reward_text := ""
	var rewards = me.get("rewards")
	if rewards is Dictionary and not rewards.is_empty():
		var parts: Array = []
		for currency in rewards.keys():
			parts.append("%d %s" % [int(rewards[currency]), CurrencyDisplay.lowercase_label_for(currency)])
		reward_text = tr("\nYou earned %s.") % ", ".join(parts)

	_banner_label.text = tr("Yesterday: finished %d%s\n\n%s%s") % [
		position, _ordinal_suffix(position), headline, reward_text
	]
	_banner.visible = true


static func _ordinal_suffix(n: int) -> String:
	if n % 100 in [11, 12, 13]:
		return TranslationServer.translate("th")
	match n % 10:
		1: return TranslationServer.translate("st")
		2: return TranslationServer.translate("nd")
		3: return TranslationServer.translate("rd")
	return TranslationServer.translate("th")


func _set_status(text: String, warn: bool) -> void:
	_status_label.text = text
	_status_label.add_theme_color_override(
		"font_color",
		ThemeManager.color("warning") if warn else ThemeManager.color("text_hint")
	)


## Labels here sit on the plain screen background rather than inside a themed
## Panel -- see ThemeManager's note on text_hint.
func _apply_theme_colors() -> void:
	var heading := ThemeManager.color("heading")
	_tier_label.add_theme_color_override("font_color", heading)
	_rewards_heading.add_theme_color_override("font_color", heading)
	_countdown_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	_progress_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	_rules_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	# The banner text is inside a themed PanelContainer, which carries its own
	# background in both modes -- so it takes the Theme's Label colour. Forcing
	# white here would vanish against the light theme's near-white panel.


# -- actions -------------------------------------------------------------------


func _on_join_pressed() -> void:
	if _busy:
		return
	_busy = true
	_refresh_buttons()
	_busy_popup.set_status(tr("Entering today's tournament..."))
	_busy_popup.visible = true

	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_POST, "/tournament/join")

	_busy_popup.visible = false
	_busy = false

	if not res.ok:
		# 409 is "entries closed" or "already in"; 400 is a roster problem.
		# Each needs a different fix from the player, so they get different
		# sentences rather than one generic retry prompt.
		if res.status == 409:
			_set_status(tr("Entries are closed for today -- try again after the reset."), true)
		elif res.status == 400:
			_set_status(tr("Your squad isn't match-ready. Fill all 11 slots on the Squad screen."), true)
		else:
			_set_status(tr("Could not enter -- try again."), true)
		_refresh_buttons()
		return

	_apply_state(res.data)


func _on_play_pressed() -> void:
	if _busy:
		return
	_busy = true
	_refresh_buttons()
	_busy_popup.set_status(tr("Finding an opponent..."))
	_busy_popup.visible = true

	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_POST, "/tournament/match")

	if not res.ok:
		_busy_popup.visible = false
		_busy = false
		if res.status == 402:
			_set_status(tr("Not enough energy -- it refills over time, or top up in the Shop."), true)
		elif res.status == 409:
			_set_status(tr("You've played all your matches for today."), true)
		else:
			_set_status(tr("Could not start the match -- try again."), true)
		# Re-read rather than trusting local state: a 409 usually means this
		# screen is behind on what the server thinks.
		await _load(tr("Refreshing..."))
		return

	MatchSession.set_from_match_response(res.data)
	if not MatchSession.has_pending():
		_busy_popup.visible = false
		_busy = false
		_set_status(tr("The match finished, but its replay couldn't be loaded."), true)
		await _load(tr("Refreshing..."))
		return

	GameProfile.apply_currency_balances(res.data.get("credits_remaining"))
	GameProfile.apply_energy(res.data.get("energy"))
	# So Continue and Exit come back HERE instead of the Menu, mid-run.
	MatchSession.return_scene = "res://scenes/DailyTournament.tscn"

	_busy_popup.set_status(tr("Kick off!"))
	await get_tree().create_timer(0.3).timeout
	get_tree().change_scene_to_file(MATCH_SCENE)


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file(HUB_SCENE)
