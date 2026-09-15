class_name StandingsTable
extends VBoxContainer

## A league table: position, manager, played, W-D-L, goal difference, points.
##
## Rows are PanelContainers rather than cells in a GridContainer, and that is
## the whole reason this component exists. A league table needs promotion and
## relegation ZONES tinted -- the standard football affordance, and it saves a
## column that would otherwise have to spell out "promoted" per row -- and a
## GridContainer cannot put a background behind a logical row, only behind
## individual cells.
##
## Columns are laid out with size_flags_stretch_ratio so they line up across
## rows without a fixed pixel width, which would break at phone size.
## MatchResult._populate_summary() is the precedent for the cell labels.

## Column widths as ratios of the row. Position and the numbers are narrow;
## the manager name takes whatever is left.
const COLUMNS := [
	{"key": "position", "label": "#", "ratio": 0.7, "align": HORIZONTAL_ALIGNMENT_CENTER},
	{"key": "display_name", "label": "Manager", "ratio": 4.0, "align": HORIZONTAL_ALIGNMENT_LEFT},
	{"key": "played", "label": "P", "ratio": 0.8, "align": HORIZONTAL_ALIGNMENT_CENTER},
	{"key": "_record", "label": "W-D-L", "ratio": 1.6, "align": HORIZONTAL_ALIGNMENT_CENTER},
	{"key": "_goal_diff", "label": "GD", "ratio": 1.0, "align": HORIZONTAL_ALIGNMENT_CENTER},
	{"key": "points", "label": "Pts", "ratio": 1.0, "align": HORIZONTAL_ALIGNMENT_CENTER},
]

const ROW_HEIGHT := 30
const HEADER_FONT_SIZE := 11
const ROW_FONT_SIZE := 13

var _rows: Array = []


func _ready() -> void:
	add_theme_constant_override("separation", 2)
	ThemeManager.theme_changed.connect(_rebuild)


## `rows` is the standings array from /tournament/today verbatim -- each entry
## carries `projected_outcome`, which is what decides the zone tint.
func set_rows(rows: Array) -> void:
	_rows = rows
	_rebuild()


func _rebuild() -> void:
	for child in get_children():
		remove_child(child)
		child.queue_free()

	_add_header()

	if _rows.is_empty():
		var empty := Label.new()
		empty.text = "Nobody has joined this group yet."
		empty.add_theme_font_size_override("font_size", ROW_FONT_SIZE)
		empty.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
		add_child(empty)
		return

	for row in _rows:
		add_child(_build_row(row))


func _add_header() -> void:
	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 6)
	for column in COLUMNS:
		var label := Label.new()
		label.text = column["label"]
		label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		label.size_flags_stretch_ratio = column["ratio"]
		label.horizontal_alignment = column["align"]
		label.add_theme_font_size_override("font_size", HEADER_FONT_SIZE)
		label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
		header.add_child(label)
	add_child(header)


func _build_row(row: Dictionary) -> PanelContainer:
	var panel := PanelContainer.new()
	panel.custom_minimum_size = Vector2(0, ROW_HEIGHT)
	panel.add_theme_stylebox_override("panel", _row_style(row))

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 6)
	margin.add_theme_constant_override("margin_right", 6)
	panel.add_child(margin)

	var line := HBoxContainer.new()
	line.add_theme_constant_override("separation", 6)
	margin.add_child(line)

	var is_me: bool = bool(row.get("is_me", false))
	for column in COLUMNS:
		var label := Label.new()
		label.text = _cell_text(row, column["key"])
		label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		label.size_flags_stretch_ratio = column["ratio"]
		label.size_flags_vertical = Control.SIZE_SHRINK_CENTER
		label.horizontal_alignment = column["align"]
		label.clip_text = true
		label.add_theme_font_size_override("font_size", ROW_FONT_SIZE)
		# Your own row is the one you look for first, so it gets the accent;
		# everyone else takes the theme's default label colour.
		if is_me:
			label.add_theme_color_override("font_color", ThemeManager.color("accent"))
		line.add_child(label)

	return panel


static func _cell_text(row: Dictionary, key: String) -> String:
	match key:
		"_record":
			return "%d-%d-%d" % [
				int(row.get("wins", 0)), int(row.get("draws", 0)), int(row.get("losses", 0))
			]
		"_goal_diff":
			var diff := int(row.get("goal_diff", 0))
			return "+%d" % diff if diff > 0 else str(diff)
	var value = row.get(key, "")
	if value is float:
		return str(int(value))
		
	return str(value) if not (value is String) else value


## Zone tint by what WOULD happen if the day ended now -- the server computes
## that with the same rule settlement uses, so the colours cannot promise
## something the payout then refuses.
func _row_style(row: Dictionary) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.set_corner_radius_all(4)

	var outcome := str(row.get("projected_outcome", "stay"))
	var tint: Color
	match outcome:
		"promote":
			tint = ThemeManager.color("positive")
		"relegate":
			tint = ThemeManager.color("warning")
		_:
			tint = ThemeManager.color("surface_border")

	style.bg_color = Color(tint.r, tint.g, tint.b, 0.16)
	if bool(row.get("is_me", false)):
		# Your row is outlined as well as tinted -- at a glance you should be
		# able to find yourself without reading a single name.
		style.set_border_width_all(1)
		style.border_color = ThemeManager.color("accent")
	return style
