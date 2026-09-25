extends Control

const ITEM_VIEW := preload("res://scenes/components/ItemView.tscn")

func _ready() -> void:
	var bg := ColorRect.new()
	bg.color = Color(0.09, 0.10, 0.13)
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	var root := VBoxContainer.new()
	root.position = Vector2(16, 12)
	root.add_theme_constant_override("separation", 10)
	add_child(root)

	var full := HBoxContainer.new()
	full.add_theme_constant_override("separation", 8)
	root.add_child(full)
	var samples := [
		{"id": "1", "r": "bronze",   "s": "passing",   "v": 2, "k": "outfield"},
		{"id": "2", "r": "gold",     "s": "shooting",  "v": 4, "k": "outfield"},
		{"id": "3", "r": "diamond",  "s": "speed",     "v": 8, "k": "outfield"},
		{"id": "4", "r": "special",  "s": "agility",   "v": 10, "k": "keeper"},
		{"id": "5", "r": "icon",     "s": "slots",     "v": 2, "k": "any"},
	]
	for s in samples:
		var v: ItemView = ITEM_VIEW.instantiate()
		full.add_child(v)
		v.set_item(s)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 4)
	root.add_child(row)
	for i in range(5):
		var v: ItemView = ITEM_VIEW.instantiate()
		row.add_child(v)
		v.set_compact(true)
		if i < 3:
			v.set_item(samples[i])
		else:
			v.set_empty()

	# Kit swatches -- every pattern, so the scoreboard can be checked without
	# a match that happens to use them.
	var kits := HBoxContainer.new()
	kits.add_theme_constant_override("separation", 10)
	root.add_child(kits)
	for spec in [["solid", "1e6fe0", "ffffff"], ["stripes", "d01f1f", "ffffff"],
			["quarters", "1a9c4a", "f2d024"], ["stripes", "111111", "e8e8e8"]]:
		var d := KitDesign.create(spec[0], spec[1], spec[2])
		var sw := KitSwatch.new()
		sw.custom_minimum_size = Vector2(44, 50)
		kits.add_child(sw)
		sw.set_design(d)
