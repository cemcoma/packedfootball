class_name StandingsTable
extends VBoxContainer

## A league table: position, manager, played, W-D-L, goal difference, points,
## what would happen to each manager if the day ended now, and -- when the
## tier pays placement rewards -- what each position earns, as
## amount-plus-logo on the row itself. Outcome and payout sit next to the
## standing they belong to, so "where does this leave me and what do I get"
## is answered in the table rather than in a list beside it.
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
	{"key": "display_name", "label": "Manager", "ratio": 3.2, "align": HORIZONTAL_ALIGNMENT_LEFT},
	{"key": "played", "label": "P", "ratio": 0.8, "align": HORIZONTAL_ALIGNMENT_CENTER},
	{"key": "_record", "label": "W-D-L", "ratio": 1.6, "align": HORIZONTAL_ALIGNMENT_CENTER},
	{"key": "_goal_diff", "label": "GD", "ratio": 1.0, "align": HORIZONTAL_ALIGNMENT_CENTER},
	{"key": "points", "label": "Pts", "ratio": 1.0, "align": HORIZONTAL_ALIGNMENT_CENTER},
]

## The outcome cell: the zone tint put into words, in the zone's colour. The
## words are the result banner's, so what the table says during the day is
## what the banner says the morning after. The ratio is sized for the longest
## of them in the pixel font, which is wider per character than the old one --
## at 1.9 "Kümede Kalır" lost a letter off each end.
const OUTCOME_COLUMN := {"label": "Outcome", "ratio": 2.9}

## The reward cell: wide enough for the richest payout (medals, cash and
## credits side by side) at the row's own font size, logos a touch smaller
## than the text so three of them don't crowd the row.
const REWARD_COLUMN := {"label": "Reward", "ratio": 2.6}
const REWARD_CURRENCY_ORDER := ["medals", "bucks", "credits"]
const REWARD_ICON_SIZE := 14
const CURRENCY_AMOUNT := preload("res://scenes/components/CurrencyAmount.tscn")

const ROW_HEIGHT := 30
const HEADER_FONT_SIZE := 11
const ROW_FONT_SIZE := 13

var _rows: Array = []
## position -> {"credits": n, "bucks": n, "medals": n}; empty means the tier
## pays nothing for placement and the column is left out altogether.
var _rewards_by_position: Dictionary = {}
## Whether this group plays in the top / bottom tier. `projected_outcome`
## is the rule's verdict before the tier edges clamp it, so a Gold League
## leader arrives as "promote" and a Bronze League straggler as "relegate";
## these turn those into "holds the top" and "stays up".
var _top_tier: bool = false
var _bottom_tier: bool = false


func _ready() -> void:
	add_theme_constant_override("separation", 2)
	ThemeManager.theme_changed.connect(_rebuild)


## `rows` is the standings array from /tournament/today verbatim -- each entry
## carries `projected_outcome`, which is what decides the zone tint.
## `rewards` is the same response's reward table (one entry per finishing
## position), matched to rows by position. The tier flags are the
## response's is_top_tier / is_bottom_tier.
func set_rows(rows: Array, rewards: Array = [], top_tier: bool = false, bottom_tier: bool = false) -> void:
	_rows = rows
	_top_tier = top_tier
	_bottom_tier = bottom_tier
	_rewards_by_position = {}
	for entry in rewards:
		if entry is Dictionary:
			_rewards_by_position[int(entry.get("position", 0))] = entry
	_rebuild()


func _has_rewards() -> bool:
	return not _rewards_by_position.is_empty()


func _rebuild() -> void:
	for child in get_children():
		remove_child(child)
		child.queue_free()

	_add_header()

	if _rows.is_empty():
		var empty := Label.new()
		empty.text = tr("Nobody has joined this group yet.")
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
		label.text = tr(column["label"])
		label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		label.size_flags_stretch_ratio = column["ratio"]
		label.horizontal_alignment = column["align"]
		label.add_theme_font_size_override("font_size", HEADER_FONT_SIZE)
		label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
		header.add_child(label)
	header.add_child(_header_label(OUTCOME_COLUMN, HORIZONTAL_ALIGNMENT_CENTER))
	if _has_rewards():
		var reward_label := Label.new()
		reward_label.text = tr(REWARD_COLUMN["label"])
		reward_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		reward_label.size_flags_stretch_ratio = REWARD_COLUMN["ratio"]
		reward_label.add_theme_font_size_override("font_size", HEADER_FONT_SIZE)
		reward_label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
		header.add_child(reward_label)
	add_child(header)


func _header_label(column: Dictionary, align: HorizontalAlignment) -> Label:
	var label := Label.new()
	label.text = tr(column["label"])
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	label.size_flags_stretch_ratio = column["ratio"]
	label.horizontal_alignment = align
	label.add_theme_font_size_override("font_size", HEADER_FONT_SIZE)
	label.add_theme_color_override("font_color", ThemeManager.color("text_hint"))
	return label


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
	line.add_child(_outcome_cell(str(row.get("projected_outcome", "stay"))))
	if _has_rewards():
		line.add_child(_reward_cell(int(row.get("position", 0))))

	return panel


## Where the day would leave this manager, in the colour of the row's zone
## -- kept even on the caller's own accented row, since the colour IS the
## information here.
func _outcome_cell(outcome: String) -> Label:
	var label := Label.new()
	label.text = _outcome_text(outcome)
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	label.size_flags_stretch_ratio = OUTCOME_COLUMN["ratio"]
	label.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.clip_text = true
	label.add_theme_font_size_override("font_size", ROW_FONT_SIZE)
	label.add_theme_color_override("font_color", _outcome_color(outcome))
	return label


func _outcome_text(outcome: String) -> String:
	match outcome:
		"promote":
			return tr("Holds top") if _top_tier else tr("Promotion")
		"relegate":
			return tr("Stays up") if _bottom_tier else tr("Relegation")
	return tr("Stays")


func _outcome_color(outcome: String) -> Color:
	match outcome:
		"promote":
			return ThemeManager.color("positive")
		"relegate":
			return ThemeManager.color("warning")
	return ThemeManager.color("text_hint")


## This position's payout, each currency as an amount beside its logo.
## CurrencyAmount colours the number in the currency's own colour, which is
## what makes three of them readable side by side without naming any. A
## position that pays nothing keeps an empty cell so the columns line up.
func _reward_cell(position: int) -> HBoxContainer:
	var cell := HBoxContainer.new()
	cell.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	cell.size_flags_stretch_ratio = REWARD_COLUMN["ratio"]
	cell.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	cell.add_theme_constant_override("separation", 8)
	var entry: Dictionary = _rewards_by_position.get(position, {})
	for currency in REWARD_CURRENCY_ORDER:
		var amount := int(entry.get(currency, 0))
		if amount <= 0:
			continue
		var view: CurrencyAmount = CURRENCY_AMOUNT.instantiate()
		cell.add_child(view)
		view.set_amount(currency, amount)
		view.set_sizes(REWARD_ICON_SIZE, ROW_FONT_SIZE - 1)
	return cell


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
