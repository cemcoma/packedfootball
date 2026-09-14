class_name CurrencyDisplay
extends RefCounted

## Player-facing labels for the three currency keys the backend actually
## uses ("credits"/"bucks"/"medals" -- unchanged there, and unchanged as
## GameProfile's own property names/API field names client-side too,
## deliberately, to stay 1:1 with the backend contract). This is the one
## place that decides what a currency is actually CALLED on screen, so a
## future real localization pass has a single seam to hook into instead of
## every screen hardcoding its own English string.
##
## "bucks" displays as "Cash" specifically because "bucks" doesn't
## translate cleanly (Turkish "dolar" reads as literal US dollars, not a
## generic hard-currency concept) -- "Cash"/"Nakit" fits both languages.
## Nothing server-side, no Firestore field, no API field name, and no
## product id changed -- this is a display-only rename.

const LABELS := {
	"credits": "Credits",
	"bucks": "Cash",
	"medals": "Medals",
}

## Accent color per currency -- same "one color per category" idea
## PlayerCard.TIER_COLORS and PackData.TYPE_COLORS already use, so a
## currency reads the same everywhere it appears (chips, tiles, deal costs).
const COLORS := {
	"credits": Color(0.95, 0.75, 0.25),  # warm gold -- the everyday soft currency
	"bucks": Color(0.35, 0.8, 0.55),  # green -- the bought-with-real-money one
	"medals": Color(0.65, 0.7, 0.95),  # cool platinum -- tournament prestige
}

const FALLBACK_COLOR := Color(0.7, 0.7, 0.75)

const ICONS := {
	"credits": "res://sprites/currencies/credits.png",
	"bucks": "res://sprites/currencies/bucks.png",
	"medals": "res://sprites/currencies/medals.png",
}


## "Credits" / "Cash" / "Medals" -- for a title/tab/heading.
static func label_for(currency_key: String) -> String:
	return LABELS.get(currency_key, currency_key.capitalize())


## Defers to ThemeManager's palette so a dark/light swap moves currency
## accents too; COLORS below is the dark-mode fallback for any context
## where the autoload isn't reachable (tooling, a scene opened bare in the
## editor). Static, so it can't just reference the autoload directly --
## hence the explicit /root lookup.
static func color_for(currency_key: String) -> Color:
	var loop := Engine.get_main_loop()
	if loop is SceneTree:
		var manager := (loop as SceneTree).root.get_node_or_null("/root/ThemeManager")
		if manager != null:
			return manager.color(currency_key)
	return COLORS.get(currency_key, FALLBACK_COLOR)


## This currency's icon, or null if it hasn't been drawn yet -- callers are
## expected to have a no-art fallback (see CurrencyChip). ResourceLoader.exists()
## rather than a bare load() so a not-yet-created path is a quiet null
## instead of a red error every time a chip is built.
static func icon_for(currency_key: String) -> Texture2D:
	var path: String = ICONS.get(currency_key, "")
	if path == "" or not ResourceLoader.exists(path):
		return null
	return load(path) as Texture2D


## 12500 -> "12,500". Shop amounts get big enough (30,000-credit exchange
## tier) that unseparated digits are genuinely hard to read at a glance.
static func format_amount(value: int) -> String:
	var digits := str(absi(value))
	var out := ""
	var count := 0
	for i in range(digits.length() - 1, -1, -1):
		out = digits[i] + out
		count += 1
		if count % 3 == 0 and i > 0:
			out = "," + out
	return ("-" + out) if value < 0 else out


## "credits" / "cash" / "medals" -- for an inline amount like "10 cash" or
## "500 credits", matching how every such label in this project already reads.
static func lowercase_label_for(currency_key: String) -> String:
	return label_for(currency_key).to_lower()
