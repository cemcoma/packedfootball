class_name KitDesign
extends RefCounted

### SUPER IMPORTANT ###
##
## A manager's shirt: a pattern plus two colors.
##
## Stored as ONE STRING on users/{uid}.kit, deliberately, so the shape can
## grow without a schema migration or a Firestore rules change every time:
##
##     v1;pattern=stripes;primary=1e6fe0;secondary=ffffff
##
## Version first, then `key=value` pairs in any order. The rules for keeping
## this extendable, which parse() below actually enforces:
##
##   - An UNKNOWN KEY is ignored, never an error. A client that doesn't know
##     about `shorts=` yet still renders the shirt correctly.
##   - A MISSING KEY falls back to its default, so adding `collar=` later
##     doesn't break the millions of v1 strings already written.
##   - An UNKNOWN PATTERN falls back to solid rather than failing, so a
##     newer client's "hoops" kit still shows up as a plausible shirt on an
##     older build instead of a blank one.
##   - ANY VALID 6-digit hex is accepted, not just the ones in
##     AVAILABLE_COLORS -- so growing the palette needs no client update to
##     be *displayable*, only to be *pickable*.
##   - A malformed string anywhere degrades to the default kit. This is
##     cosmetic data; it must never be able to take a screen down.
##
## When the format genuinely has to break, bump VERSION and branch on it in
## parse() -- the version is read first for exactly that reason.

const VERSION := "v1"

const PATTERN_SOLID := "solid"
const PATTERN_STRIPES := "stripes"

## Add to this and PATTERN_NAMES to ship a new pattern; the Customize Kit
## screen builds its buttons from these, so nothing else needs touching.
const PATTERNS := [PATTERN_SOLID, PATTERN_STRIPES]
const PATTERN_NAMES := {
	PATTERN_SOLID: "Solid",
	PATTERN_STRIPES: "Stripes",
}

const DEFAULT_PATTERN := PATTERN_SOLID
const DEFAULT_PRIMARY := "1e6fe0"
const DEFAULT_SECONDARY := "ffffff"

## The palette a manager can pick from. Both colors draw from the same list,
## and picking the same one twice is allowed (a plain one-color shirt).
## Extending this is a one-line change -- the screen builds its swatches
## from here, and any hex already saved keeps rendering even if it later
## leaves the list.
const AVAILABLE_COLORS := [
	{"name": "Royal Blue", "hex": "1e6fe0"},
	{"name": "Navy", "hex": "16214a"},
	{"name": "Sky", "hex": "5fc2f0"},
	{"name": "Forest", "hex": "17683a"},
	{"name": "Lime", "hex": "8ed43f"},
	{"name": "Crimson", "hex": "c8102e"},
	{"name": "Coral", "hex": "f4735a"},
	{"name": "Orange", "hex": "f08122"},
	{"name": "Gold", "hex": "f2c227"},
	{"name": "Purple", "hex": "6f3fa8"},
	{"name": "Magenta", "hex": "d13d8a"},
	{"name": "Teal", "hex": "129c96"},
	{"name": "White", "hex": "ffffff"},
	{"name": "Silver", "hex": "c3c7cc"},
	{"name": "Charcoal", "hex": "3a3d44"},
	{"name": "Black", "hex": "121216"},
]

var pattern: String = DEFAULT_PATTERN
var primary: String = DEFAULT_PRIMARY      # 6-digit hex, no leading '#'
var secondary: String = DEFAULT_SECONDARY


static func create(new_pattern: String, new_primary: String, new_secondary: String) -> KitDesign:
	var design := KitDesign.new()
	design.pattern = new_pattern if new_pattern in PATTERNS else DEFAULT_PATTERN
	design.primary = _clean_hex(new_primary, DEFAULT_PRIMARY)
	design.secondary = _clean_hex(new_secondary, DEFAULT_SECONDARY)
	return design


## Never fails and never returns null -- anything unparseable comes back as
## the default kit. See the class docstring for why every branch here is
## forgiving rather than strict.
static func parse(raw) -> KitDesign:
	var design := KitDesign.new()
	if not (raw is String) or String(raw).strip_edges() == "":
		return design

	for part in String(raw).split(";", false):
		var token := String(part).strip_edges()
		if token == "" or not token.contains("="):
			continue  # the version prefix, or junk -- neither is a field
		var key := token.get_slice("=", 0).strip_edges().to_lower()
		var value := token.get_slice("=", 1).strip_edges()
		match key:
			"pattern":
				var lowered := value.to_lower()
				if lowered in PATTERNS:
					design.pattern = lowered
			"primary":
				design.primary = _clean_hex(value, design.primary)
			"secondary":
				design.secondary = _clean_hex(value, design.secondary)
			# Anything else is a field from a newer client. Ignored on
			# purpose -- see the class docstring.
	return design


func serialize() -> String:
	return "%s;pattern=%s;primary=%s;secondary=%s" % [VERSION, pattern, primary, secondary]


func primary_color() -> Color:
	return color_from_hex(primary)


func secondary_color() -> Color:
	return color_from_hex(secondary)


## Any palette hex (or any valid 6-digit hex) as a Color. White for
## anything unparseable, so a bad value is a visible plain shirt rather
## than a crash.
static func color_from_hex(hex: String) -> Color:
	return Color.from_string("#" + _clean_hex(hex, DEFAULT_PRIMARY), Color.WHITE)


func copy() -> KitDesign:
	return KitDesign.create(pattern, primary, secondary)


func matches(other: KitDesign) -> bool:
	if other == null:
		return false
	return pattern == other.pattern and primary == other.primary and secondary == other.secondary


func pattern_name() -> String:
	return TranslationServer.translate(PATTERN_NAMES.get(pattern, pattern.capitalize()))


## Display name for a hex if it's in the palette, else the hex itself -- a
## color saved by a newer client is still describable, just unnamed.
static func color_name(hex: String) -> String:
	var cleaned := _clean_hex(hex, "")
	for entry in AVAILABLE_COLORS:
		if entry["hex"] == cleaned:
			return TranslationServer.translate(entry["name"])
	return "#" + cleaned.to_upper() if cleaned != "" else "Unknown"


## Normalises "#AABBCC"/"aabbcc" to "aabbcc", or returns `fallback` for
## anything that isn't a valid 6-digit hex.
static func _clean_hex(value, fallback: String) -> String:
	if not (value is String):
		return fallback
	var hex := String(value).strip_edges().lstrip("#").to_lower()
	if hex.length() != 6 or not hex.is_valid_hex_number(false):
		return fallback
	return hex
