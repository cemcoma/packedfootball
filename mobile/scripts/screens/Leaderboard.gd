extends Control

## Leaderboard: two tabs -- Users (ranked by wins) and Players (ranked by
## goals) -- backed by the new GET /leaderboard/users and the existing GET
## /leaderboard/players (see backend/main.py). Deliberately a minimal first
## pass, same spirit as Shop's own Currency tab: proves the page/tab/
## backend-round-trip shape end to end for early testers, not the final
## design -- more stats and polish land later.
##
## Each tab lazy-loads once (the first time it's opened) and caches its
## result for the rest of this screen's lifetime -- switching tabs back and
## forth doesn't refetch, matching how "for now" simple this whole screen
## is meant to be; a manual refresh can come later if that turns out to
## matter.

@onready var _users_tab_button: Button = %UsersTabButton
@onready var _players_tab_button: Button = %PlayersTabButton
@onready var _status_label: Label = %StatusLabel
@onready var _users_scroll: ScrollContainer = %UsersScroll
@onready var _users_list: VBoxContainer = %UsersList
@onready var _players_scroll: ScrollContainer = %PlayersScroll
@onready var _players_list: VBoxContainer = %PlayersList
@onready var _back_button: Button = %BackButton

var _users_loaded: bool = false
var _players_loaded: bool = false


func _ready() -> void:
	_users_tab_button.pressed.connect(_on_users_tab_pressed)
	_players_tab_button.pressed.connect(_on_players_tab_pressed)
	_back_button.pressed.connect(_on_back_pressed)

	await _load_users()


func _on_users_tab_pressed() -> void:
	_users_scroll.visible = true
	_players_scroll.visible = false
	if not _users_loaded:
		await _load_users()


func _on_players_tab_pressed() -> void:
	_users_scroll.visible = false
	_players_scroll.visible = true
	if not _players_loaded:
		await _load_players()


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")


func _load_users() -> void:
	_status_label.text = "Loading..."
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/leaderboard/users")
	if not res.ok:
		_status_label.text = "Could not load the leaderboard -- try again later."
		return
	_users_loaded = true
	_status_label.text = ""
	_populate_list(_users_list, res.data.get("entries", []), _format_user_row)


func _load_players() -> void:
	_status_label.text = "Loading..."
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/leaderboard/players")
	if not res.ok:
		_status_label.text = "Could not load the leaderboard -- try again later."
		return
	_players_loaded = true
	_status_label.text = ""
	_populate_list(_players_list, res.data.get("entries", []), _format_player_row)


## .get(key, default) only falls back to `default` when the key is entirely
## absent -- a present-but-null value (e.g. a manager who never set a
## display name) comes back as null regardless, and null can't go into a
## statically-typed String/int var. Same defensive pattern as PackData.gd's
## own _str()/_int() helpers.
func _format_user_row(rank: int, entry: Dictionary) -> String:
	var name_raw = entry.get("display_name")
	var name: String = name_raw if name_raw is String and name_raw != "" else "Manager"
	var value_raw = entry.get("value")
	var value: int = value_raw if typeof(value_raw) in [TYPE_INT, TYPE_FLOAT] else 0
	return "%d. %s -- %d wins" % [rank, name, value]


func _format_player_row(rank: int, entry: Dictionary) -> String:
	var fname_raw = entry.get("fname")
	var lname_raw = entry.get("lname")
	var fname: String = fname_raw if fname_raw is String else ""
	var lname: String = lname_raw if lname_raw is String else ""
	var name := ("%s %s" % [fname, lname]).strip_edges()
	if name == "":
		name = "Unknown Player"
	var position_raw = entry.get("position")
	var position: String = position_raw if position_raw is String and position_raw != "" else ""
	var value_raw = entry.get("value")
	var value: int = value_raw if typeof(value_raw) in [TYPE_INT, TYPE_FLOAT] else 0
	var label := "%d. %s" % [rank, name]
	if position != "":
		label += " (%s)" % position
	return "%s -- %d goals" % [label, value]


## Same remove_child()-then-queue_free() pairing Team.gd's bench grid and
## Shop.gd's pack grid both use, safe to call again from a lazy-load re-run.
func _populate_list(list: VBoxContainer, entries: Array, formatter: Callable) -> void:
	for child in list.get_children():
		list.remove_child(child)
		child.queue_free()

	if entries.is_empty():
		var empty_label := Label.new()
		empty_label.text = "No entries yet."
		list.add_child(empty_label)
		return

	for i in range(entries.size()):
		var entry = entries[i]
		if not (entry is Dictionary):
			continue
		var row := Label.new()
		row.text = formatter.call(i + 1, entry)
		list.add_child(row)
