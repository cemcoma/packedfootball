extends Control

## A tournament: your tier, your group's table, and the button that plays
## your next match.
##
## ONE SCREEN, TWO LEAGUES. The daily and weekly formats differ only in URL
## prefix and a handful of sentences, both of which come from
## TournamentSession -- whoever opened this screen set the format there.
## Everything that could differ NUMERICALLY (how many matches, how big a
## group, how many go up, what a position pays) arrives in the payload, so
## the backend can be retuned without a client release. Nothing on this
## screen assumes ten matches or a group of six.
##
## ONE request builds the whole thing. GET {format}/today returns the tier,
## the standings, the energy block, the rules and the reward table together,
## because the screen is useless until it has all of it and four round trips
## on a phone is four chances to show a half-built page. The reward table is
## drawn INTO the standings (StandingsTable's Reward column), not as a list
## of its own.
##
## That same request is also what SETTLES the previous period. There is no
## scheduler and no notification system, so the day a player comes back their
## previous group is resolved before this screen is built and the result
## rides along in `pending_results` -- which is why the "you were promoted"
## banner can exist at all.
##
## Countdowns tick locally from the seconds the server sent (see TimeFormat),
## never from a parsed timestamp, so a device with a wrong clock still shows
## the right numbers.
##
## THE PLAY-EVERYTHING REWARD. Playing every match of the period earns a
## bonus that is paid only when the player presses Claim -- the server marks
## it earned, this screen asks for it (POST /claim), and the credits move in
## front of them. The panel beside the standings shows the progress bar
## towards it; the same Claim also appears on the previous period's result
## banner, because a last match played minutes before the reset is claimable
## afterwards and would otherwise be lost.
##
## The scene's nodes are still named FullDay* from when the daily league was
## the only one. They serve both formats; the period they cover is whatever
## `required` in the payload says.

const MATCH_SCENE := "res://scenes/Match.tscn"

@onready var _tier_label: Label = %TierLabel
@onready var _countdown_label: Label = %CountdownLabel

@onready var _status_label: Label = %StatusLabel
@onready var _progress_label: Label = %ProgressLabel
@onready var _standings: StandingsTable = %Standings
@onready var _rules_label: Label = %RulesLabel
@onready var _table_panel: PanelContainer = %TablePanel
@onready var _full_day_panel_frame: PanelContainer = %FullDayPanel
@onready var _full_day_panel: PanelContainer = %FullDayPanel
@onready var _full_day_heading: Label = %FullDayHeading
@onready var _full_day_bar: ProgressBar = %FullDayBar
@onready var _full_day_label: Label = %FullDayLabel
@onready var _full_day_reward: CurrencyAmount = %FullDayReward
@onready var _full_day_claim_button: Button = %FullDayClaimButton

@onready var _join_button: Button = %JoinButton
@onready var _play_button: Button = %PlayButton
@onready var _back_button: Button = %BackButton
@onready var _busy_popup: Control = %BusyPopup

@onready var _banner: Control = %ResultBanner
@onready var _banner_label: Label = %BannerLabel
@onready var _banner_claim_button: Button = %BannerClaimButton
@onready var _banner_button: Button = %BannerButton

var _state: Dictionary = {}
var _busy: bool = false
var _seconds_remaining: float = 0.0
## The previous period's id/group while the result banner is up with a
## claimable reward -- what the banner's Claim sends, since the current
## period's entry is a different document.
var _banner_claim: Dictionary = {}


func _ready() -> void:
	_join_button.pressed.connect(_on_join_pressed)
	_play_button.pressed.connect(_on_play_pressed)
	_back_button.pressed.connect(_on_back_pressed)
	_banner_button.pressed.connect(func() -> void: _banner.visible = false)
	_full_day_claim_button.pressed.connect(_on_claim_full_day_pressed.bind({}))
	_banner_claim_button.pressed.connect(_on_banner_claim_pressed)

	_banner.visible = false
	_busy_popup.visible = false

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	await _load(tr(TournamentSession.text("loading")))


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

	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_GET, TournamentSession.endpoint("/today")
	)

	_busy_popup.visible = false
	_busy = false

	if not res.ok:
		_set_status(tr("Could not load the tournament -- try again."), true)
		# The scene's own placeholder text is the daily league's, so a failed
		# load on the weekly screen would offer "Enter today's tournament"
		# and a 0/10 bar. Re-render from the (empty) state instead: the
		# button takes this format's wording and the reward panel hides.
		_refresh_full_day()
		_refresh_buttons()
		return
	_apply_state(res.data)


func _apply_state(data: Dictionary) -> void:
	_state = data
	_seconds_remaining = float(_int(data, "seconds_remaining", 0))

	var tier_name = data.get("tier_name")
	_tier_label.text = tier_name if tier_name is String else tr("Tournament")
	_countdown_label.text = TimeFormat.ends_in(int(_seconds_remaining))

	# Into the shared cache, which is what the HUD strip reads.
	GameProfile.apply_energy(data.get("energy"))

	# The reward table rides along on the standings -- each row shows what
	# its position pays, so there is no separate rewards list to keep in step.
	var standings = data.get("standings")
	var rewards = data.get("rewards")
	_standings.set_rows(
		standings if standings is Array else [],
		rewards if rewards is Array else [],
		bool(data.get("is_top_tier", false)),
		bool(data.get("is_bottom_tier", false)),
	)

	_refresh_progress()
	_refresh_rules()
	_refresh_full_day()
	_refresh_buttons()
	_apply_theme_colors()
	_show_pending_results(data.get("pending_results"))


static func _int(data: Dictionary, key: String, default: int) -> int:
	var value = data.get(key)
	return int(value) if typeof(value) in [TYPE_INT, TYPE_FLOAT] else default


## The play-everything block out of a payload. The backend sends it as
## `full_period` and, for the daily screen that shipped first, `full_day`
## as well; reading both means this screen works against either build.
static func _full_period_of(data: Dictionary):
	var block = data.get("full_period")
	return block if block is Dictionary else data.get("full_day")


# -- state -> UI ---------------------------------------------------------------


func _refresh_progress() -> void:
	var played := _int(_state, "matches_played", 0)
	var total := _int(_state, "matches_max", 0)
	var size := _int(_state, "group_size", 0)
	var capacity := _int(_state, "group_capacity", 0)

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
	var floor_pts := _int(rules, "promotion_floor", 0)
	var drop_pts := _int(rules, "relegation_floor", 0)
	var min_group := _int(rules, "min_group_for_promotion", 0)

	# How many go up and down is COUNTED from the response, never written
	# down here: the daily league promotes two and the weekly three, and a
	# sentence that said "top 2" on both would be wrong on one of them.
	var promote = rules.get("promote_positions")
	var relegate = rules.get("relegate_positions")
	var up_count: int = promote.size() if promote is Array else 0
	var down_count: int = relegate.size() if relegate is Array else 0

	# The two paths genuinely work differently, and a player in a short group
	# who was told "the top three go up" would be misled -- so the screen says
	# which rule is currently in force rather than one generic sentence.
	if mode == "positional":
		_rules_label.text = tr("Full group: with at least %d points the top %d go up, the bottom %d go down.") % [floor_pts, up_count, down_count]
	else:
		_rules_label.text = tr("Group isn't full, so points decide: %d or more goes up, under %d goes down. Needs %d players in the group to go up at all.") % [floor_pts, drop_pts, min_group]


## The play-every-match panel: hidden until joined, a bar filling towards
## the last match, then a live Claim, then "Claimed". The reward amount is
## shown throughout so the bar is a bar TOWARDS something.
func _refresh_full_day() -> void:
	var full_day = _full_period_of(_state)
	_full_day_panel.visible = full_day is Dictionary
	if not (full_day is Dictionary):
		return

	var played := _int(full_day, "played", 0)
	var required := _int(full_day, "required", 0)
	var claimable: bool = bool(full_day.get("claimable", false))
	var claimed: bool = bool(full_day.get("claimed", false))
	var reward = full_day.get("reward")
	var reward_dict: Dictionary = reward if reward is Dictionary else {}

	_full_day_heading.text = tr("Play all %d matches") % required
	_full_day_bar.max_value = required
	_full_day_bar.value = mini(played, required)
	_full_day_label.text = "%d / %d" % [mini(played, required), required]

	# One currency is all the reward table carries today; show the first
	# non-zero one, which is how a two-currency reward would degrade too.
	var currency := "credits"
	var amount := 0
	for key in ["credits", "bucks", "medals"]:
		if _int(reward_dict, key, 0) > 0:
			currency = key
			amount = _int(reward_dict, key, 0)
			break
	_full_day_reward.set_amount(currency, amount)
	_full_day_reward.set_sizes(16, 12)

	if claimed:
		_full_day_claim_button.text = tr("Claimed")
		_full_day_claim_button.disabled = true
	elif claimable:
		CurrencyDisplay.set_button_price(_full_day_claim_button, tr("Claim"), amount, currency)
		_full_day_claim_button.disabled = _busy
	else:
		_full_day_claim_button.text = tr("%d more to go") % (required - played)
		_full_day_claim_button.icon = null
		_full_day_claim_button.disabled = true


func _refresh_buttons() -> void:
	var joined: bool = bool(_state.get("joined", false))
	var closed: bool = bool(_state.get("join_closed", false))
	var played := _int(_state, "matches_played", 0)
	var total := _int(_state, "matches_max", 0)
	var out_of_matches: bool = total > 0 and played >= total
	# The HUD's bar, not GameProfile's block: it ticks the next point down
	# locally, so it is the only live reading of the bar.
	var out_of_energy: bool = CurrencyHud.energy() <= 0

	_join_button.visible = not joined
	_play_button.visible = joined

	if not joined:
		_join_button.disabled = _busy or closed
		_join_button.text = tr("Entries closed") if closed else tr(TournamentSession.text("join"))
		if closed:
			var reopens := TimeFormat.coarse_duration(int(_seconds_remaining))
			_set_status(tr(TournamentSession.text("closed_window")) % reopens, false)
		return

	_refresh_full_day()  # its Claim follows _busy too
	_play_button.disabled = _busy or out_of_matches or out_of_energy
	if out_of_matches:
		_play_button.text = tr("All %d matches played") % total
		_set_status(tr(TournamentSession.text("all_played")), false)
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

	_banner_label.text = tr(TournamentSession.text("last_result")) % [
		position, _ordinal_suffix(position), headline, reward_text
	]

	# A period played out but never claimed: offer it here, keyed to THAT
	# period's entry, or it would silently expire behind the current panel.
	_banner_claim = {}
	var full_period = _full_period_of(pending)
	var claimable: bool = full_period is Dictionary and bool(full_period.get("claimable", false))
	_banner_claim_button.visible = claimable
	if claimable:
		_banner_claim = {
			"period_id": str(pending.get("period_id", pending.get("day_id", ""))),
			"group_id": str(pending.get("group_id", "")),
		}
		var reward = full_period.get("reward")
		var amount := _int(reward if reward is Dictionary else {}, "credits", 0)
		CurrencyDisplay.set_button_price(
			_banner_claim_button, tr(TournamentSession.text("claim_last")), amount, "credits"
		)
		_banner_claim_button.disabled = false
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
	MenuTile.style_button(_join_button, ThemeManager.color("accent"))
	MenuTile.style_button(_play_button, ThemeManager.color("accent"))
	MenuTile.style_button(_back_button, ThemeManager.color("surface_border"))
	var heading := ThemeManager.color("heading")

	# The table used to sit straight on the background photo, where its header
	# row and the quieter "stay" rows were competing with the crowd behind them.
	_table_panel.add_theme_stylebox_override(
		"panel",
		MenuTile.pixel_frame(MenuTile.BASE_FILL, ThemeManager.color("surface_border"), 3, true)
	)
	_full_day_panel_frame.add_theme_stylebox_override(
		"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, heading, 3, true)
	)
	_style_full_day_bar(heading)

	_tier_label.add_theme_color_override("font_color", heading)
	_countdown_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	_progress_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	_rules_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	# The full-day panel is a themed PanelContainer, so its labels take the
	# Theme's own colour -- only the heading is lifted to match the title.
	_full_day_heading.add_theme_color_override("font_color", heading)
	# The banner text is inside a themed PanelContainer, which carries its own
	# background in both modes -- so it takes the Theme's Label colour. Forcing
	# white here would vanish against the light theme's near-white panel.


## Hard-edged like everything else: a rounded, anti-aliased bar is the one
## thing that gives away that a pixel-art screen is using stock widgets.
func _style_full_day_bar(accent: Color) -> void:
	var fill := StyleBoxFlat.new()
	fill.anti_aliasing = false
	fill.set_corner_radius_all(0)
	fill.bg_color = accent
	_full_day_bar.add_theme_stylebox_override("fill", fill)

	var track := StyleBoxFlat.new()
	track.anti_aliasing = false
	track.set_corner_radius_all(0)
	track.bg_color = Color(accent.r, accent.g, accent.b, 0.18)
	track.border_color = Color(accent.r, accent.g, accent.b, 0.45)
	track.set_border_width_all(1)
	_full_day_bar.add_theme_stylebox_override("background", track)


# -- actions -------------------------------------------------------------------


func _on_join_pressed() -> void:
	if _busy:
		return
	_busy = true
	_refresh_buttons()
	_busy_popup.set_status(tr(TournamentSession.text("joining")))
	_busy_popup.visible = true

	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST, TournamentSession.endpoint("/join")
	)

	_busy_popup.visible = false
	_busy = false

	if not res.ok:
		# 409 is "entries closed" or "already in"; 400 is a roster problem.
		# Each needs a different fix from the player, so they get different
		# sentences rather than one generic retry prompt.
		if res.status == 409:
			_set_status(tr(TournamentSession.text("closed_now")), true)
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

	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST, TournamentSession.endpoint("/match")
	)

	if not res.ok:
		_busy_popup.visible = false
		_busy = false
		if res.status == 402:
			_set_status(tr("Not enough energy -- it refills over time, or top up in the Shop."), true)
		elif res.status == 409:
			_set_status(tr(TournamentSession.text("all_played_short")), true)
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
	# So Continue and Exit come back HERE instead of the Menu, mid-run --
	# and to the format being played, since TournamentSession keeps it.
	MatchSession.return_scene = TournamentSession.SCREEN_SCENE

	_busy_popup.set_status(tr("Kick off!"))
	await get_tree().create_timer(0.3).timeout
	get_tree().change_scene_to_file(MATCH_SCENE)


## POST /claim for the play-everything reward. `target` is {} for the
## current period's entry (the server resolves it from the profile) or the
## previous period's period_id + group_id from the result banner. On success
## the balances in the response are applied straight to the shared cache, so
## the chip moves the moment the button is pressed -- that's the whole point
## of claiming by hand rather than paying out silently.
func _on_claim_full_day_pressed(target: Dictionary) -> void:
	if _busy:
		return
	_busy = true
	_full_day_claim_button.disabled = true
	_banner_claim_button.disabled = true

	var body := {"type": TournamentSession.claim_type()}
	body.merge(target)
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_POST, "/claim", body)

	_busy = false
	if not res.ok:
		# 409 is "already claimed" or "not earned" -- both mean this screen
		# is behind the server, so re-read rather than guess.
		_set_status(
			tr("Already claimed.") if res.status == 409 else tr("Could not claim -- try again."),
			res.status != 409,
		)
		if res.status == 409:
			await _load(tr("Refreshing..."))
		else:
			_refresh_full_day()
			_banner_claim_button.disabled = false
		return

	GameProfile.apply_currency_balances(
		res.data.get("credits_remaining"),
		res.data.get("bucks_remaining"),
		res.data.get("medals_remaining"),
	)

	var rewards = res.data.get("rewards")
	var parts: Array = []
	if rewards is Dictionary:
		for currency in rewards.keys():
			parts.append("%d %s" % [int(rewards[currency]), CurrencyDisplay.lowercase_label_for(currency)])
	_set_status(tr("Claimed %s!") % ", ".join(parts), false)

	if target.is_empty():
		# The current period's: mark it locally so the panel flips to Claimed
		# without a round trip -- the server already did the same.
		var full_period = _full_period_of(_state)
		if full_period is Dictionary:
			full_period["claimable"] = false
			full_period["claimed"] = true
		_refresh_full_day()
	else:
		_banner_claim_button.visible = false
		_banner_claim = {}


func _on_banner_claim_pressed() -> void:
	if _banner_claim.is_empty():
		return
	await _on_claim_full_day_pressed(_banner_claim)


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file(TournamentSession.HUB_SCENE)
