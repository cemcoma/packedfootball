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

const PRE_MATCH_SCENE := "res://scenes/PreMatch.tscn"
const Shop := preload("res://scripts/screens/Shop.gd")
const CURRENCY_AMOUNT := preload("res://scenes/components/CurrencyAmount.tscn")

@onready var _tier_label: Label = %TierLabel
@onready var _countdown_label: Label = %CountdownLabel

@onready var _status_label: Label = %StatusLabel
@onready var _progress_label: Label = %ProgressLabel
@onready var _standings: StandingsTable = %Standings
@onready var _rules_label: Label = %RulesLabel
## The global table's pager (Weekend League only): Top / My position, Prev / Next.
@onready var _pager_row: HBoxContainer = %PagerRow
@onready var _pager_mode: OptionButton = %PagerMode
@onready var _prev_page_button: Button = %PrevPageButton
@onready var _page_label: Label = %PageLabel
@onready var _next_page_button: Button = %NextPageButton
@onready var _table_panel: PanelContainer = %TablePanel
@onready var _full_day_panel_frame: PanelContainer = %FullDayPanel
@onready var _full_day_panel: PanelContainer = %FullDayPanel
@onready var _full_day_heading: Label = %FullDayHeading
@onready var _full_day_bar: ProgressBar = %FullDayBar
@onready var _full_day_label: Label = %FullDayLabel
@onready var _full_day_rewards: HBoxContainer = %FullDayRewards
@onready var _full_day_claim_button: Button = %FullDayClaimButton

@onready var _join_button: Button = %JoinButton
@onready var _energy_button: Button = %EnergyButton 
@onready var _play_button: Button = %PlayButton
@onready var _back_button: Button = %BackButton
@onready var _busy_popup: Control = %BusyPopup

@onready var _banner: Control = %ResultBanner
@onready var _banner_label: Label = %BannerLabel
@onready var _banner_claim_box: Control = %BannerClaimBox
@onready var _banner_claim_rewards: HBoxContainer = %BannerClaimRewards
@onready var _banner_claim_button: Button = %BannerClaimButton
@onready var _banner_button: Button = %BannerButton

var _state: Dictionary = {}
var _busy: bool = false
var _seconds_remaining: float = 0.0
## True while a windowed format hasn't opened yet: the countdown counts to the opening.
var _counting_to_open: bool = false
## The previous period's id/group while the result banner is up with a
## claimable reward -- what the banner's Claim sends, since the current
## period's entry is a different document.
var _banner_claim: Dictionary = {}


func _ready() -> void:
	_join_button.pressed.connect(_on_join_pressed)
	_play_button.pressed.connect(_on_play_pressed)
	_back_button.pressed.connect(_on_back_pressed)
	_energy_button.pressed.connect(_on_energy_pressed)
	_banner_button.pressed.connect(func() -> void: _banner.visible = false)
	_full_day_claim_button.pressed.connect(_on_claim_full_day_pressed.bind({}))
	_banner_claim_button.pressed.connect(_on_banner_claim_pressed)
	_standings.row_pressed.connect(_on_standings_row_pressed)
	_pager_mode.add_item(tr("Top"))
	_pager_mode.add_item(tr("My position"))
	_pager_mode.item_selected.connect(_on_pager_mode_selected)
	_prev_page_button.pressed.connect(_on_page_step.bind(-1))
	_next_page_button.pressed.connect(_on_page_step.bind(1))
	_pager_row.visible = false

	_banner.visible = false
	_busy_popup.visible = false

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	await _load(tr(TournamentSession.text("loading")))


func _process(delta: float) -> void:
	if _seconds_remaining <= 0.0:
		return
	_seconds_remaining -= delta
	_countdown_label.text = _countdown_text(int(ceil(_seconds_remaining)))
	if _counting_to_open and _seconds_remaining <= 0.0:
		_counting_to_open = false
		_load(tr("Refreshing..."))


func _countdown_text(seconds: int) -> String:
	if _counting_to_open:
		return tr("Opens in %s") % TimeFormat.coarse_duration(seconds)
	return TimeFormat.ends_in(seconds)


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
	var opens_in := _int(data, "opens_in_seconds", 0)
	_counting_to_open = opens_in > 0
	_seconds_remaining = float(opens_in if _counting_to_open else _int(data, "seconds_remaining", 0))

	var tier_name = data.get("tier_name")
	_tier_label.text = tier_name if tier_name is String else tr("Tournament")
	_countdown_label.text = _countdown_text(int(_seconds_remaining))

	# Into the shared cache, which is what the HUD strip reads.
	GameProfile.apply_energy(data.get("energy"))

	_apply_standings()
	_refresh_progress()
	_refresh_rules()
	_refresh_full_day()
	_refresh_buttons()
	_apply_theme_colors()
	_show_pending_results(data.get("pending_results"))


## The reward table rides along on the standings -- each row shows what
## its position pays, so there is no separate rewards list to keep in step.
func _apply_standings() -> void:
	var standings = _state.get("standings")
	var rewards = _state.get("rewards")
	_standings.set_rows(
		standings if standings is Array else [],
		rewards if rewards is Array else [],
		bool(_state.get("is_top_tier", false)),
		bool(_state.get("is_bottom_tier", false)),
	)
	_refresh_pager()


## Only a global table sends `standings_total`; a group fits on one screen.
func _refresh_pager() -> void:
	_pager_row.visible = _state.has("standings_total")
	if not _pager_row.visible:
		return
	var page := _int(_state, "standings_page", 0)
	var pages := maxi(1, _int(_state, "standings_pages", 1))
	var minutes := _int(_state, "standings_age_seconds", 0) / 60
	_page_label.text = tr("Page %d of %d · updated %d min ago") % [page + 1, pages, minutes]
	_prev_page_button.disabled = _busy or page <= 0
	_next_page_button.disabled = _busy or page >= pages - 1
	var mine := _my_page()
	_pager_mode.select(1 if mine >= 0 and page == mine else 0 if page == 0 else -1)


## The page the caller's row is on, -1 while they aren't ranked yet.
func _my_page() -> int:
	var position := _int(_state, "my_position", 0)
	return (position - 1) / maxi(1, _int(_state, "standings_page_size", 10)) if position > 0 else -1


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
	if capacity <= 0:
		_progress_label.text = tr("Match %d of %d  ·  %d players") % [mini(played + 1, total), total, size]
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
	var own_rules := TournamentSession.text("rules")
	if own_rules != "":
		_rules_label.text = tr(own_rules) % floor_pts
		return
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

	_full_day_heading.text = tr("Play all %d matches") % required
	_full_day_bar.max_value = required
	_full_day_bar.value = mini(played, required)
	_full_day_label.text = "%d / %d" % [mini(played, required), required]

	_fill_reward_row(_full_day_rewards, full_day.get("reward"), 16, 12)

	if claimed:
		_full_day_claim_button.text = tr("Claimed")
		_full_day_claim_button.disabled = true
	elif claimable:
		_full_day_claim_button.text = tr("Claim")
		_full_day_claim_button.disabled = _busy
	else:
		_full_day_claim_button.text = tr("%d more to go") % (required - played)
		_full_day_claim_button.disabled = true


## Every currency in `reward` as amount-plus-logo, in the standings' order.
## A Button holds one icon, so a multi-currency payout sits beside its Claim.
func _fill_reward_row(row: HBoxContainer, reward, icon_size: int, font_size: int) -> void:
	for child in row.get_children():
		row.remove_child(child)
		child.queue_free()
	if not (reward is Dictionary):
		return
	for currency in StandingsTable.REWARD_CURRENCY_ORDER:
		var amount := _int(reward, currency, 0)
		if amount <= 0:
			continue
		var view: CurrencyAmount = CURRENCY_AMOUNT.instantiate()
		row.add_child(view)
		view.set_amount(currency, amount)
		view.set_sizes(icon_size, font_size)


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
	_energy_button.visible = joined and not out_of_matches and out_of_energy

	if not joined:
		_join_button.disabled = _busy or closed
		_join_button.text = tr("Entries closed") if closed else tr(TournamentSession.text("join"))
		if _counting_to_open:
			_join_button.text = tr("Not open yet")
			_set_status(tr(TournamentSession.text("not_open")) % TimeFormat.coarse_duration(int(_seconds_remaining)), false)
		elif closed:
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
		_set_status(tr("No energy left."), true)
	else:
		_play_button.text = tr("Play match %d of %d") % [played + 1, total]
		_energy_button.visible = false


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
			var champion := TournamentSession.text("champion")
			if clamped and champion != "":
				headline = tr(champion)
			else:
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
	_banner_claim_box.visible = claimable
	if claimable:
		_banner_claim = {
			"period_id": str(pending.get("period_id", pending.get("day_id", ""))),
			"group_id": str(pending.get("group_id", "")),
		}
		_fill_reward_row(_banner_claim_rewards, full_period.get("reward"), 18, 14)
		_banner_claim_button.text = tr(TournamentSession.text("claim_last"))
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
	MenuTile.style_button(_energy_button, ThemeManager.color("accent"))
	MenuTile.style_button(_back_button, ThemeManager.color("surface_border"))
	for button in [_pager_mode, _prev_page_button, _next_page_button]:
		MenuTile.style_button(button, ThemeManager.color("surface_border"), false, Vector2(8, 2))
	MenuTile.style_popup(_pager_mode, ThemeManager.color("surface_border"))
	_page_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
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
	if not await ContractWarning.confirm(self):
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

	# Credits wait in MatchSession for the result screen (see Play.gd).
	GameProfile.apply_energy(res.data.get("energy"))
	# So Continue and Exit come back HERE instead of the Menu, mid-run --
	# and to the format being played, since TournamentSession keeps it.
	MatchSession.return_scene = TournamentSession.SCREEN_SCENE

	_busy_popup.set_status(tr("Kick off!"))
	await get_tree().create_timer(0.3).timeout
	get_tree().change_scene_to_file(PRE_MATCH_SCENE)


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
		_banner_claim_box.visible = false
		_banner_claim = {}


func _on_banner_claim_pressed() -> void:
	if _banner_claim.is_empty():
		return
	await _on_claim_full_day_pressed(_banner_claim)


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file(TournamentSession.HUB_SCENE)


func _on_standings_row_pressed(uid: String) -> void:
	ManagerSession.open(uid, TournamentSession.SCREEN_SCENE)


func _on_pager_mode_selected(index: int) -> void:
	if index == 0:
		await _fetch_page(0)
		return
	var mine := _my_page()
	if mine < 0:
		_set_status(tr("You'll show up in the table within a few minutes."), false)
		_refresh_pager()
		return
	await _fetch_page(mine)


func _on_page_step(delta: int) -> void:
	await _fetch_page(maxi(0, _int(_state, "standings_page", 0) + delta))


## GET {format}/standings?page=n, folded into the state the screen already holds.
func _fetch_page(page: int) -> void:
	if _busy:
		return
	_busy = true
	_refresh_pager()
	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_GET, TournamentSession.endpoint("/standings?page=%d" % page)
	)
	_busy = false
	if not res.ok or not (res.data is Dictionary):
		_set_status(tr("Could not load the table -- try again."), true)
		_refresh_pager()
		return
	_state.merge(res.data, true)
	_apply_standings()


func _on_energy_pressed() -> void:
	Shop.open_energy(get_tree(), TournamentSession.SCREEN_SCENE)
