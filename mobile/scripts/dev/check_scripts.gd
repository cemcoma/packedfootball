extends SceneTree

## Headless load check for the scripts and scenes items touched. There is no
## GDScript test runner in this project; this is the nearest thing.
##
##     make godot-check
##
## WHAT IT PROVES: every listed script parses, and every listed scene loads and
## instantiates. That is enough to catch the things that actually break here --
## a typo, a renamed node a %UniqueName no longer finds, a scene referencing a
## script that no longer compiles.
##
## WHAT IT DOES NOT PROVE: that autoload references resolve. `--script` does not
## feed project.godot's autoloads to the GDScript analyzer, so every file that
## mentions ThemeManager or GameProfile logs "Identifier not found" -- including
## untouched ones like PlayerCardView.gd. Those lines are noise from the
## harness, not findings. READ THE `ok`/`FAIL` COLUMN AND THE PARSE ERRORS,
## nothing else.
##
## Run --import first after adding any class_name, or every file that uses the
## new class fails here for want of a global class cache entry.

const SCRIPTS := [
	"res://scripts/data/ItemData.gd",
	"res://scripts/data/PlayerCard.gd",
	"res://scripts/data/PackData.gd",
	"res://scripts/components/ItemView.gd",
	"res://scripts/components/PackInfoPopup.gd",
	"res://scripts/screens/Items.gd",
	"res://scripts/screens/PlayerDetail.gd",
	"res://scripts/screens/TeamHub.gd",
	"res://scripts/screens/Inventory.gd",
	"res://scripts/screens/Shop.gd",
	"res://scripts/screens/PackReveal.gd",
	"res://scripts/autoload/ItemSession.gd",
	"res://scripts/autoload/GameProfile.gd",
	"res://scripts/autoload/PackSession.gd",
]

const SCENES := [
	"res://scenes/components/ItemView.tscn",
	"res://scenes/components/PackInfoPopup.tscn",
	"res://scenes/Items.tscn",
	"res://scenes/TeamHub.tscn",
	"res://scenes/PlayerDetail.tscn",
	"res://scenes/PackReveal.tscn",
	"res://scenes/Inventory.tscn",
	"res://scenes/Shop.tscn",
]

func _init() -> void:
	var failures := 0
	for path in SCRIPTS:
		var res = load(path)
		if res == null:
			print("FAIL script  ", path)
			failures += 1
		else:
			print("ok   script  ", path)
	for path in SCENES:
		var packed = load(path)
		if packed == null or not packed.can_instantiate():
			print("FAIL scene   ", path)
			failures += 1
			continue
		var node = packed.instantiate()
		if node == null:
			print("FAIL inst    ", path)
			failures += 1
		else:
			print("ok   scene   ", path)
			node.queue_free()
	print("\n%d failures  (Parse Error lines above are real; \"Identifier not found\"" % failures)
	print("for an autoload is this harness, not your code -- see the docstring)")
	quit(1 if failures > 0 else 0)
