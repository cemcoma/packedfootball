extends Control

## Leaderboard: Managers (ranked by wins) and four player boards -- Goals,
## Assists, Rating, Clean sheets -- ten rows a page, from GET
## /leaderboard/users and /leaderboard/players. The player boards take a
## position filter (a family like Attackers, or one exact position), so
## "best striker" is Goals + ST.
##
## Rating is a career average and only counts once a card has been rated
## RATED_MATCHES_FOR_AVERAGE times (player.py), so the board can't be
## topped by one lucky 9.5; the row says how many matches it's over.
## Clean sheets only ever move for keepers, so that board is a keeper
## board whatever the filter says.
##
## Every row is a button. A manager row opens that manager (ManagerView:
## name, record, league, their XI); a player row opens the manager who
## owns the card -- a player is only interesting as somebody's player.
## The Manager screen comes back here through ManagerSession.return_scene.
##
## The top three wear podium backdrops -- gold, silver, bronze -- and
## everyone else a plain dark one, so a page that starts at 11 has no
## podium on it: the colours mean "top three overall", not "top of this
## page". Rows are built at runtime (there's nothing to restyle in the
## scene), each a PanelContainer with its own StyleBoxFlat, rebuilt on a
## theme swap like every other runtime-styled widget.
##
## Pages are fetched on demand and cached per tab for the life of this
## screen, so flipping back a page or between tabs is instant; leaving and
## returning refetches, which is as fresh as a leaderboard needs to be.

const MANAGER_VIEW_SCENE := "res://scenes/ManagerView.tscn"
const RETURN_SCENE := "res://scenes/Leaderboard.tscn"

## Tab key -> the backend stat it asks for ("" = the managers board).
const TAB_STATS := {
	"users": "",
	"goals": "goals",
	"assists": "assists",
	"avg_rating": "avg_rating",
	"clean_sheets": "clean_sheets",
}

## The position dropdown, in order: [what the backend takes, label]. The
## four families are packEngine.POSITION_CATEGORIES' keys; the exact
## positions are PLAYER_CLASS_MAP's, GK first then back to front.
const POSITION_FILTERS := [
	["", "All positions"],
	["goalkeeper", "Goalkeepers"],
	["defender", "Defenders"],
	["midfielder", "Midfielders"],
	["attacker", "Attackers"],
	["GK", "GK"], ["CB", "CB"], ["LB", "LB"], ["RB", "RB"], ["LWB", "LWB"], ["RWB", "RWB"],
	["CDM", "CDM"], ["CM", "CM"], ["CAM", "CAM"], ["LM", "LM"], ["RM", "RM"],
	["LW", "LW"], ["RW", "RW"], ["ST", "ST"],
]

## Podium backdrops by rank. Anything past the table is PLAIN_BACKDROP.
const PODIUM_BACKDROPS := {
	1: Color(0.80, 0.62, 0.12),
	2: Color(0.66, 0.66, 0.70),
	3: Color(0.62, 0.40, 0.20),
}
const PLAIN_BACKDROP := Color(0.0, 0.0, 0.0, 0.62)
## Podium text is dark on the bright backdrops, light on the plain one.
const PODIUM_TEXT := Color(0.08, 0.07, 0.05)
const PLAIN_TEXT := Color(0.96, 0.96, 0.98)
const ROW_HEIGHT := 44
## The signed-in manager's own row gets the accent ring so they can find
## themselves on a page without reading every name.
const ME_RING_WIDTH := 2

@onready var _title_label: Label = %TitleLabel
@onready var _tab_panel: PanelContainer = %TabPanel
@onready var _list_backdrop: PanelContainer = %ListBackdrop

@onready var _users_tab_button: Button = %UsersTabButton
@onready var _goals_tab_button: Button = %GoalsTabButton
@onready var _assists_tab_button: Button = %AssistsTabButton
@onready var _rating_tab_button: Button = %RatingTabButton
@onready var _clean_sheets_tab_button: Button = %CleanSheetsTabButton
@onready var _position_option: OptionButton = %PositionOption
@onready var _status_label: Label = %StatusLabel
@onready var _rows_list: VBoxContainer = %RowsList
@onready var _prev_button: Button = %PrevButton
@onready var _page_label: Label = %PageLabel
@onready var _next_button: Button = %NextButton
@onready var _back_button: Button = %BackButton

## Static, so opening a manager and coming back lands on the board you were
## reading rather than the first tab -- the scene is rebuilt from scratch on
## that trip, and per-instance state would not survive it.
static var _tab: String = "users"  # a TAB_STATS key
static var _position: String = ""  # a POSITION_FILTERS key; player boards only
static var _page: Dictionary = {}  # board key -> current page
## board key -> page -> the response body (entries, has_more). A board is
## a tab plus, for players, the position filter, so each filter pages on
## its own.
var _cache: Dictionary = {}
var _loading: bool = false


func _ready() -> void:
	_users_tab_button.pressed.connect(_on_tab_pressed.bind("users"))
	_goals_tab_button.pressed.connect(_on_tab_pressed.bind("goals"))
	_assists_tab_button.pressed.connect(_on_tab_pressed.bind("assists"))
	_rating_tab_button.pressed.connect(_on_tab_pressed.bind("avg_rating"))
	_clean_sheets_tab_button.pressed.connect(_on_tab_pressed.bind("clean_sheets"))
	for entry in POSITION_FILTERS:
		_position_option.add_item(tr(entry[1]))
	_position_option.item_selected.connect(_on_position_selected)
	_prev_button.pressed.connect(_on_page_step.bind(-1))
	_next_button.pressed.connect(_on_page_step.bind(1))
	_back_button.pressed.connect(_on_back_pressed)
	ThemeManager.theme_changed.connect(_render)
	ThemeManager.theme_changed.connect(_style_chrome)

	_restore_view()
	_style_chrome()
	await _show_page()


## Put the controls back where the static state says they were. Neither
## `button_pressed` nor `select()` emits the signals the user's own taps do,
## so this can't loop back into _on_tab_pressed/_on_position_selected.
##
## The row cache is deliberately NOT kept: a leaderboard that came back
## instantly would be showing ranks from before the trip.
func _restore_view() -> void:
	var tab_buttons := {
		"users": _users_tab_button,
		"goals": _goals_tab_button,
		"assists": _assists_tab_button,
		"avg_rating": _rating_tab_button,
		"clean_sheets": _clean_sheets_tab_button,
	}
	if tab_buttons.has(_tab):
		tab_buttons[_tab].button_pressed = true

	for i in POSITION_FILTERS.size():
		if POSITION_FILTERS[i][0] == _position:
			_position_option.select(i)
			break
	_position_option.visible = _is_player_board()


func _is_player_board() -> bool:
	return _tab != "users"


## The cache/page key for what's on screen right now.
func _board_key() -> String:
	return _tab if not _is_player_board() else "%s/%s" % [_tab, _position]


func _on_tab_pressed(tab: String) -> void:
	if tab == _tab:
		return
	_tab = tab
	_position_option.visible = _is_player_board()
	_style_chrome()  # the lit tab is ours to paint, not the Theme's
	await _show_page()


func _on_position_selected(index: int) -> void:
	if index < 0 or index >= POSITION_FILTERS.size():
		return
	var chosen: String = POSITION_FILTERS[index][0]
	if chosen == _position:
		return
	_position = chosen
	await _show_page()


func _on_page_step(delta: int) -> void:
	if _loading:
		return
	var key := _board_key()
	var current: int = int(_page.get(key, 0))
	var next: int = maxi(0, current + delta)
	if next == current:
		return
	_page[key] = next
	await _show_page()


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Menu.tscn")


# -- fetching ------------------------------------------------------------------


func _show_page() -> void:
	var key := _board_key()
	var page: int = int(_page.get(key, 0))
	if not _cache.has(key):
		_cache[key] = {}
	if not _cache[key].has(page):
		await _fetch(key, page)
	_render()


func _fetch(key: String, page: int) -> void:
	_loading = true
	_prev_button.disabled = true
	_next_button.disabled = true
	_status_label.text = tr("Loading...")

	var path: String
	if _is_player_board():
		path = "/leaderboard/players?stat=%s&page=%d" % [TAB_STATS[_tab], page]
		if _position != "":
			path += "&position=" + _position.uri_encode()
	else:
		path = "/leaderboard/users?page=%d" % page
	var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, path)

	_loading = false
	if not res.ok:
		_status_label.text = tr("Could not load the leaderboard -- try again later.")
		return
	_status_label.text = ""
	_cache[key][page] = res.data


# -- state -> UI ---------------------------------------------------------------


func _render() -> void:
	for child in _rows_list.get_children():
		_rows_list.remove_child(child)
		child.queue_free()

	var key := _board_key()
	var page: int = int(_page.get(key, 0))
	var data: Dictionary = _cache.get(key, {}).get(page, {})
	var entries_raw = data.get("entries")
	var entries: Array = entries_raw if entries_raw is Array else []

	_page_label.text = tr("Page %d") % (page + 1)
	_prev_button.disabled = _loading or page == 0
	_next_button.disabled = _loading or not bool(data.get("has_more", false))

	if entries.is_empty():
		var empty_label := Label.new()
		if page > 0:
			empty_label.text = tr("Nothing on this page.")
		elif _tab == "avg_rating":
			empty_label.text = tr("No player has been rated in %d matches yet.") % PlayerCard.RATED_MATCHES_FOR_AVERAGE
		else:
			empty_label.text = tr("No entries yet.")
		empty_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		_rows_list.add_child(empty_label)
		return

	for entry in entries:
		if entry is Dictionary:
			_rows_list.add_child(_build_row(entry))


## One row: rank, name, the number(s) -- on a podium or plain backdrop,
## the whole thing a button.
func _build_row(entry: Dictionary) -> Control:
	var rank := _int(entry, "rank", 0)
	var is_me: bool = bool(entry.get("is_me", false))
	var on_podium: bool = PODIUM_BACKDROPS.has(rank)

	var panel := PanelContainer.new()
	panel.custom_minimum_size = Vector2(0, ROW_HEIGHT)
	# Hard-edged like every other panel; the podium colours still carry the
	# rank, and the border is what separates a row from its neighbour.
	var style := StyleBoxFlat.new()
	style.anti_aliasing = false
	style.set_corner_radius_all(0)
	style.bg_color = PODIUM_BACKDROPS.get(rank, PLAIN_BACKDROP)
	style.content_margin_left = 12
	style.content_margin_right = 12
	style.set_border_width_all(ME_RING_WIDTH)
	style.border_color = (
		ThemeManager.color("accent") if is_me
		else Color(0.0, 0.0, 0.0, 0.55) if on_podium
		else ThemeManager.color("surface_border")
	)
	panel.add_theme_stylebox_override("panel", style)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	panel.add_child(row)

	var text_color := PODIUM_TEXT if on_podium else PLAIN_TEXT

	var rank_label := Label.new()
	rank_label.text = "%d." % rank
	rank_label.custom_minimum_size = Vector2(36, 0)
	rank_label.add_theme_font_size_override("font_size", 16 if on_podium else 14)
	_style_text(rank_label, text_color, on_podium)
	row.add_child(rank_label)

	var name_label := Label.new()
	name_label.text = _display_name(entry)
	name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	name_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	name_label.add_theme_font_size_override("font_size", 16 if on_podium else 14)
	_style_text(name_label, text_color, on_podium)
	row.add_child(name_label)

	var value_label := Label.new()
	value_label.text = _value_text(entry)
	value_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	value_label.add_theme_font_size_override("font_size", 13)
	_style_text(value_label, text_color, on_podium)
	row.add_child(value_label)

	# Transparent button over the whole row, same tap-anywhere pattern as
	# PlayerCardView and PackView.
	var button := Button.new()
	button.flat = true
	button.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	button.pressed.connect(_on_row_pressed.bind(entry))
	panel.add_child(button)
	return panel


## The theme paints every Label white with a shadow; the podium rows are
## bright, so their text goes dark and the shadow comes off.
func _style_text(label: Label, color: Color, on_podium: bool) -> void:
	label.add_theme_color_override("font_color", color)
	if on_podium:
		label.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0))


func _display_name(entry: Dictionary) -> String:
	if _tab == "users":
		var name_raw = entry.get("display_name")
		return name_raw if name_raw is String and name_raw != "" else tr("Manager")
	var fname_raw = entry.get("fname")
	var lname_raw = entry.get("lname")
	var name := ("%s %s" % [fname_raw if fname_raw is String else "", lname_raw if lname_raw is String else ""]).strip_edges()
	if name == "":
		name = tr("Unknown Player")
	var position_raw = entry.get("position")
	if position_raw is String and position_raw != "":
		name += "  ·  %s" % position_raw
	return name


func _value_text(entry: Dictionary) -> String:
	match _tab:
		"users":
			return tr("%d W  %d D  %d L") % [_int(entry, "wins", 0), _int(entry, "draws", 0), _int(entry, "losses", 0)]
		"assists":
			return tr("%d assists") % _int(entry, "value", 0)
		"clean_sheets":
			return tr("%d clean sheets") % _int(entry, "value", 0)
		"avg_rating":
			var value = entry.get("value")
			var rating: float = float(value) if typeof(value) in [TYPE_INT, TYPE_FLOAT] else 0.0
			return tr("%.2f over %d matches") % [rating, _int(entry, "matches_played", 0)]
	return tr("%d goals") % _int(entry, "value", 0)


## A manager row opens that manager; a player row opens their owner.
func _on_row_pressed(entry: Dictionary) -> void:
	var uid_raw = entry.get("uid") if _tab == "users" else entry.get("owner_uid")
	if not (uid_raw is String) or uid_raw == "":
		return
	ManagerSession.open(uid_raw, RETURN_SCENE)


static func _int(data: Dictionary, key: String, default: int) -> int:
	var value = data.get(key)
	return int(value) if typeof(value) in [TYPE_INT, TYPE_FLOAT] else default


## The tabs, the list frame and the pager, in the same pixel frame the rest of
## the app wears. Called again on every tab change so the lit tab follows.
func _style_chrome() -> void:
	var accent := ThemeManager.color("accent")
	var muted := ThemeManager.color("surface_border")
	_title_label.add_theme_color_override("font_color", MenuTile.TITLE_COLOR)
	for panel in [_tab_panel, _list_backdrop]:
		panel.add_theme_stylebox_override(
			"panel", MenuTile.pixel_frame(MenuTile.BASE_FILL, muted, 3, true, Vector2(8, 6))
		)
	var tabs := {
		"users": _users_tab_button,
		"goals": _goals_tab_button,
		"assists": _assists_tab_button,
		"avg_rating": _rating_tab_button,
		"clean_sheets": _clean_sheets_tab_button,
	}
	for key in tabs:
		MenuTile.style_button(tabs[key], accent if key == _tab else muted, key == _tab)
	MenuTile.style_popup(_position_option, accent)
	MenuTile.style_button(_position_option, accent)
	for button in [_back_button, _prev_button, _next_button]:
		MenuTile.style_button(button, muted)
