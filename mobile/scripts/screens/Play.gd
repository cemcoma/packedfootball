extends Control

## Play hub: pick a match mode. Sits between Menu and the actual match --
## Menu's own "Play Match" button used to go straight to Match.tscn (always
## the bundled local demo replay); now it lands here first.
##
## Quick Match calls the backend's new POST /match/quick, which always
## finds *someone* to play (a real random signed-up user if one's around,
## otherwise a freshly-rolled bot -- see backend/main.py's
## _pick_opponent_profile) for a small flat credit reward, then hands the
## result to the MatchSession autoload before navigating to the real
## playback scene (MatchSession.gd's own docstring explains why an
## autoload is how that handoff works, since change_scene_to_file() can't
## carry data itself).
##
## The whole /match/quick call is one request-response round trip -- the
## backend picks an opponent AND simulates the match AND persists the
## result before it ever replies 
##
## Tournament leads to the tournament hub (Tournament.tscn), which offers the
## daily league -- ten matches a day in a group of six, drawn from your own
## tier, with promotion and relegation settled overnight.
##
## Both modes cost energy now (see backend config's QUICK_MATCH_ENERGY_COST),
## which is why the failure branch below has to tell 402 apart from everything
## else: "try again" is the one piece of advice that cannot work when the bar
## is empty.

@onready var _status_label: Label = %StatusLabel
@onready var _quick_match_button: Button = %QuickMatchButton
@onready var _tournament_button: Button = %TournamentButton
@onready var _back_button: Button = %BackButton

@onready var _quick_match_hint: Label = %QuickMatchHint
@onready var _tournament_hint: Label = %TournamentHint

@onready var _energy_bar: EnergyBar = %EnergyBar
@onready var _matchmaking_popup: Control = %MatchmakingPopup

@onready var _testing_toggle_button: Button = %TestingToggleButton
@onready var _testing_panel: VBoxContainer = %TestingPanel
@onready var _interval_option: OptionButton = %IntervalOption
@onready var _opponent_option: OptionButton = %OpponentOption
@onready var _run_local_button: Button = %RunLocalButton
@onready var _testing_status: Label = %TestingStatus
@onready var _check_game_id_field: LineEdit = %CheckGameIdField
@onready var _check_load_button: Button = %CheckLoadButton
@onready var _check_status: Label = %CheckStatus

var _matchmaking_active: bool = false

# -- TESTING panel (editor only) ---------------------------------------------
#
# Behind a TESTING toggle that only exists under the editor
# (OS.has_feature("editor")): both tools need this repo's Python engine on
# disk, which no exported build has, and nothing about them belongs on a
# phone. The engine is Python, so it can't run inside Godot; it runs
# beside it, as a child process polled from _process, and the result is
# played through the normal MatchSession path with is_local set so the
# post-match screens don't reload a profile nothing touched.
#
# Two tools:
#   - Run a local match: packedfootball/scripts/local_match.py. For A/B-ing
#     the engine's decision interval by feel against the CPU seconds each
#     setting costs -- see that script's docstring.
#   - Check a reported match: packedfootball/scripts/replay_game.py. Paste
#     the game id from a bug report (match_reports/, or backend/scripts/
#     list_match_reports.py) and the match is re-simulated from its
#     games/{id} doc -- seed and both rosters as played -- fetched with your
#     own Application Default Credentials, read-only. The status line shows
#     the report text and flags an engine-version or score mismatch, the
#     two signs the replay isn't the one the reporter saw.
# Nothing leaves this machine: no backend call, no Firestore write, and
# MatchSession.is_local keeps the post-match screens from reloading the
# profile afterwards.

## "adaptive" is what production runs (per-player, by distance to the ball;
## see gameEngine's ADAPTIVE_* constants); the numbers force a fixed frame
## interval on everyone, 2 being the old behaviour. Passed straight through
## as --decision-interval.
const TEST_INTERVALS := ["adaptive", "2", "3", "4", "6"]
## Bot tiers, same keys as packEngine.TIER_RANGES.
const TEST_OPPONENT_TIERS := ["bronze", "silver", "gold", "platinum", "diamond", "special_conf", "special_cont", "special_champ", "icon"]
const LOCAL_MATCH_SCRIPT := "res://../packedfootball/scripts/local_match.py"
const LOCAL_MATCH_DIR := "user://local_match"
## Tried in order; the editor's PATH on macOS often lacks Homebrew/python.org
## installs, so bare "python3" is the last resort rather than the first.
const PYTHON_CANDIDATES := ["/usr/local/bin/python3", "/opt/homebrew/bin/python3", "/usr/bin/python3", "python3"]

const REPLAY_GAME_SCRIPT := "res://../packedfootball/scripts/replay_game.py"

var _local_pid: int = -1
var _local_out_path: String = ""
var _local_started_msec: int = 0

var _check_pid: int = -1
var _check_out_path: String = ""
var _check_started_msec: int = 0


func _ready() -> void:
	_quick_match_button.pressed.connect(_on_quick_match_pressed)
	_tournament_button.pressed.connect(_on_tournament_pressed)
	_back_button.pressed.connect(_on_back_pressed)

	ThemeManager.theme_changed.connect(_apply_theme_colors)
	_apply_theme_colors()
	_refresh_energy()
	_setup_testing_panel()


func _refresh_energy() -> void:
	_energy_bar.set_energy(GameProfile.energy)
	if GameProfile.energy.is_empty():
		await GameProfile.refresh_energy()
		_energy_bar.set_energy(GameProfile.energy)


## The two hints sit straight on the screen background with no panel behind
## them, so the Theme's Label color doesn't reach them (they carry their own
## override) -- on light mode their pale grey was invisible. See
## ThemeManager's note on text_hint.
func _apply_theme_colors() -> void:
	var hint := ThemeManager.color("text_hint")
	_quick_match_hint.add_theme_color_override("font_color", hint)
	_tournament_hint.add_theme_color_override("font_color", hint)


func _show_matchmaking_popup(status: String) -> void:
	_matchmaking_active = true
	_matchmaking_popup.set_status(status)
	_matchmaking_popup.visible = true


func _set_matchmaking_status(status: String) -> void:
	if not _matchmaking_active:
		return  # the request already finished (or failed) before this fired
	_matchmaking_popup.set_status(status)


func _hide_matchmaking_popup() -> void:
	_matchmaking_active = false
	_matchmaking_popup.visible = false


func _on_quick_match_pressed() -> void:
	_quick_match_button.disabled = true
	_tournament_button.disabled = true
	_status_label.text = ""
	_show_matchmaking_popup(tr("Finding an opponent..."))

	# Not awaited -- fires on its own while the request below is in flight,
	# purely to move the status text along; see class docstring.
	get_tree().create_timer(1.2).timeout.connect(_on_matchmaking_midpoint)

	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_POST, "/match/quick")

	if not res.ok:
		_hide_matchmaking_popup()
		_status_label.text = ( # 402 is "out of energy"
			tr("You're out of energy -- it refills over time, or top up in the Shop.")
			if res.status == 402
			else tr("Could not start a match -- try again.")
		)
		_quick_match_button.disabled = false
		_tournament_button.disabled = false
		return

	GameProfile.apply_energy(res.data.get("energy"))
	_energy_bar.set_energy(GameProfile.energy)

	MatchSession.set_from_match_response(res.data)
	if not MatchSession.has_pending():
		_hide_matchmaking_popup()
		_status_label.text = tr("Match finished, but the replay couldn't be loaded -- try again.")
		_quick_match_button.disabled = false
		_tournament_button.disabled = false
		return

	# .get(key, default) only falls back to `default` when the key is
	# entirely absent -- a present-but-null value comes back as null
	# regardless, and null can't go into a statically-typed int var (same
	# concern PackData.gd's own _int() helper guards against). Updated here
	# (rather than waiting for a future full GameProfile reload) so Profile
	# screen reflects this match immediately.
	GameProfile.credits = _int(res.data, "credits_remaining", GameProfile.credits)
	GameProfile.wins = _int(res.data, "wins", GameProfile.wins)
	GameProfile.losses = _int(res.data, "losses", GameProfile.losses)
	GameProfile.draws = _int(res.data, "draws", GameProfile.draws)

	_set_matchmaking_status(tr("Match found!"))
	await get_tree().create_timer(0.4).timeout
	_hide_matchmaking_popup()
	get_tree().change_scene_to_file("res://scenes/Match.tscn")


func _on_matchmaking_midpoint() -> void:
	_set_matchmaking_status(tr("Getting players ready..."))


static func _int(data: Dictionary, key: String, default: int) -> int:
	var value = data.get(key)
	return value if typeof(value) in [TYPE_INT, TYPE_FLOAT] else default


func _on_tournament_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Tournament.tscn")


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")


# -- TESTING panel -------------------------------------------------------------


func _setup_testing_panel() -> void:
	if not OS.has_feature("editor"):
		return
	_testing_toggle_button.visible = true
	_testing_toggle_button.toggled.connect(func(on: bool) -> void: _testing_panel.visible = on)
	_testing_panel.visible = false
	_check_load_button.pressed.connect(_on_check_load_pressed)
	_check_game_id_field.text_submitted.connect(func(_text: String) -> void: _on_check_load_pressed())
	for interval in TEST_INTERVALS:
		_interval_option.add_item(interval + (" (live)" if interval == "adaptive" else ""))
	for tier in TEST_OPPONENT_TIERS:
		_opponent_option.add_item(tier.capitalize())
	_opponent_option.select(TEST_OPPONENT_TIERS.find("gold"))
	_run_local_button.pressed.connect(_on_run_local_pressed)
	_testing_status.text = (
		"Home side: your saved XI." if _has_complete_lineup()
		else "Home side: a generated Gold squad (sign in with a full XI to use yours)."
	)


func _has_complete_lineup() -> bool:
	if not GameProfile.is_loaded or GameProfile.slot_assignment.size() != 11:
		return false
	for player_id in GameProfile.slot_assignment:
		if player_id == "" or not GameProfile.all_cards.has(player_id):
			return false
	return true


## Your own squad in the shape local_match.py's --home-roster expects:
## player_to_fields dicts in formation-slot order. Reassembled from
## PlayerCard rather than kept as raw fields because nothing else has ever
## needed the raw doc after from_fields().
func _write_home_roster() -> String:
	var players: Array = []
	for player_id in GameProfile.slot_assignment:
		var card: PlayerCard = GameProfile.all_cards[player_id]
		players.append({
			"fname": card.fname, "lname": card.lname, "tier": card.tier, "position": card.position,
			"country": card.country, "hometown": card.hometown,
			"attributes": card.attributes, "statistics": card.statistics, "appearance": card.appearance,
		})
	var path := LOCAL_MATCH_DIR + "/home_roster.json"
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_string(JSON.stringify({
		"display_name": GameProfile.display_name, "formation": GameProfile.formation,
		"kit": GameProfile.kit, "players": players,
	}))
	file.close()
	return ProjectSettings.globalize_path(path)


func _python_path() -> String:
	for candidate in PYTHON_CANDIDATES:
		if not candidate.begins_with("/") or FileAccess.file_exists(candidate):
			return candidate
	return "python3"


func _on_run_local_pressed() -> void:
	if _local_pid != -1:
		return
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(LOCAL_MATCH_DIR))
	_local_out_path = ProjectSettings.globalize_path(LOCAL_MATCH_DIR + "/match.json")
	if FileAccess.file_exists(_local_out_path):
		DirAccess.remove_absolute(_local_out_path)

	var interval: String = TEST_INTERVALS[_interval_option.selected]
	var tier: String = TEST_OPPONENT_TIERS[_opponent_option.selected]
	var args: PackedStringArray = [
		ProjectSettings.globalize_path(LOCAL_MATCH_SCRIPT),
		"--out", _local_out_path,
		"--decision-interval", interval,
		"--opponent-tier", tier,
	]
	if _has_complete_lineup():
		args.append_array(PackedStringArray(["--home-roster", _write_home_roster()]))

	# create_process, not execute: a match is ~5-10s of CPU and execute()
	# would freeze the editor window for all of it. _process polls the pid.
	_local_pid = OS.create_process(_python_path(), args)
	if _local_pid == -1:
		_testing_status.text = "Could not start python3 -- see PYTHON_CANDIDATES in Play.gd."
		return
	_local_started_msec = Time.get_ticks_msec()
	_run_local_button.disabled = true
	_testing_status.text = "Simulating locally (interval %s vs %s bot)..." % [interval, tier.capitalize()]


func _process(_delta: float) -> void:
	if _local_pid != -1:
		if OS.is_process_running(_local_pid):
			_testing_status.text = "Simulating locally... %.0fs" % ((Time.get_ticks_msec() - _local_started_msec) / 1000.0)
		else:
			_local_pid = -1
			_run_local_button.disabled = false
			_on_local_match_finished()
	if _check_pid != -1:
		if OS.is_process_running(_check_pid):
			_check_status.text = "Re-simulating... %.0fs" % ((Time.get_ticks_msec() - _check_started_msec) / 1000.0)
		else:
			_check_pid = -1
			_check_load_button.disabled = false
			_on_check_finished()


func _on_local_match_finished() -> void:
	if not FileAccess.file_exists(_local_out_path):
		_testing_status.text = "The engine wrote nothing -- run local_match.py from a terminal to see why."
		return
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(_local_out_path))
	if not (parsed is Dictionary):
		_testing_status.text = "Unreadable output from local_match.py."
		return
	if parsed.has("error"):
		_testing_status.text = "Engine error: %s" % parsed["error"]
		push_error(parsed.get("traceback", parsed["error"]))
		return

	MatchSession.set_from_match_response(parsed)
	if not MatchSession.has_pending():
		_testing_status.text = "Simulated, but the replay couldn't be decoded."
		return
	MatchSession.is_local = true
	MatchSession.return_scene = "res://scenes/Play.tscn"
	# Not localized -- dev-only text, and the numbers are the point.
	print("[local match] interval=%s  decisions=%s  cpu=%ss  wall=%ss  score=%s" % [
		parsed.get("decision_interval"), parsed.get("decisions"), parsed.get("sim_seconds"), parsed.get("wall_seconds"), parsed.get("score")
	])
	get_tree().change_scene_to_file("res://scenes/Match.tscn")


# -- check a reported match ---------------------------------------------------


func _on_check_load_pressed() -> void:
	if _check_pid != -1 or _local_pid != -1:
		return
	var game_id := _check_game_id_field.text.strip_edges()
	if game_id == "":
		_check_status.text = "Enter a game id first."
		return
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(LOCAL_MATCH_DIR))
	_check_out_path = ProjectSettings.globalize_path(LOCAL_MATCH_DIR + "/check.json")
	if FileAccess.file_exists(_check_out_path):
		DirAccess.remove_absolute(_check_out_path)

	var args: PackedStringArray = [
		ProjectSettings.globalize_path(REPLAY_GAME_SCRIPT),
		"--out", _check_out_path,
		"--game-id", game_id,
	]
	_check_pid = OS.create_process(_python_path(), args)
	if _check_pid == -1:
		_check_status.text = "Could not start python3 -- see PYTHON_CANDIDATES in Play.gd."
		return
	_check_started_msec = Time.get_ticks_msec()
	_check_load_button.disabled = true
	_check_status.text = "Fetching games/%s and re-simulating..." % game_id


func _on_check_finished() -> void:
	if not FileAccess.file_exists(_check_out_path):
		_check_status.text = "The script wrote nothing -- run replay_game.py from a terminal to see why."
		return
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(_check_out_path))
	if not (parsed is Dictionary):
		_check_status.text = "Unreadable output from replay_game.py."
		return
	if parsed.has("error"):
		_check_status.text = "Error: %s" % parsed["error"]
		push_error(parsed.get("traceback", parsed["error"]))
		return

	# Not localized -- dev-only text, and the details are the point. Printed
	# as well as shown, since this screen is left the moment the match opens.
	var notes: Array = []
	notes.append("Checking %s (%s)  seed %s" % [parsed.get("game_id", "?"), parsed.get("mode", "?"), parsed.get("seed", "?")])
	if bool(parsed.get("engine_mismatch", false)):
		notes.append("ENGINE MISMATCH: recorded %s, this build runs %s -- the replay may differ from what was reported." % [
			parsed.get("recorded_engine_version", "?"), parsed.get("engine_version", "?")
		])
	if bool(parsed.get("score_mismatch", false)):
		notes.append("Score now %s, recorded %s." % [parsed.get("score"), parsed.get("recorded_score")])
	var reports = parsed.get("reports")
	if reports is Array and not reports.is_empty():
		for r in reports:
			if r is Dictionary:
				var text := str(r.get("description", ""))
				notes.append("Report [%s]: %s" % [r.get("category", "?"), text if text != "" else "(no text)"])
	else:
		notes.append("No reports filed against this match.")
	_check_status.text = "\n".join(notes)
	for line in notes:
		print("[check replay] " + line)

	MatchSession.clear()
	MatchSession.set_from_match_response(parsed)
	if not MatchSession.has_pending():
		_check_status.text = "Re-simulated, but the replay couldn't be decoded."
		return
	MatchSession.is_local = true
	MatchSession.return_scene = "res://scenes/Play.tscn"
	get_tree().change_scene_to_file("res://scenes/Match.tscn")
