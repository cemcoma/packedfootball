class_name Tactics
extends RefCounted

## The play styles on the Tactics screen. The ids mirror
## packedfootball/game_config.py's TACTICS -- what each style actually does
## lives there; this is only the name and the one-line pitch. The backend
## reads users/{uid}.tactics through its own sanitize_tactics, so an id it
## doesn't know plays Balanced rather than breaking anything.
##
## users/{uid}.tactics is a map so later settings (captain, set-piece takers,
## crossing) are new keys, not new fields: sanitize() keeps keys it doesn't
## know, so an older client never strips what a newer one wrote.

const DEFAULT_STYLE := "balanced"
const STYLE_IDS: Array[String] = ["balanced", "possession", "long_ball", "wing_play"]

const _NAMES := {
	"balanced": "Balanced",
	"possession": "Possession",
	"long_ball": "Long Ball",
	"wing_play": "Wing Play",
}

const _DESCRIPTIONS := {
	"balanced": "No instructions beyond the formation: the side reads the game as it comes.",
	"possession": "Keep the ball and starve them of it. Suits the better side -- but the high line leaves room behind it for a quick striker.",
	"long_ball": "Defenders stay deep and go long; the side pushes up to win the second ball and the free kicks. Punishes a high line.",
	"wing_play": "Get it wide and get it in: wide men are the pass to find, full-backs overlap, runners attack every cross.",
}


static func sanitize(raw) -> Dictionary:
	var clean: Dictionary = raw.duplicate() if raw is Dictionary else {}
	# Type first: `in` on a typed Array logs an engine error for a non-String.
	var style = clean.get("style")
	if not (style is String and style in STYLE_IDS):
		clean["style"] = DEFAULT_STYLE
	return clean


## TranslationServer rather than tr(): everything here is static.
static func display_name(style: String) -> String:
	return TranslationServer.translate(_NAMES.get(style, _NAMES[DEFAULT_STYLE]))


static func description(style: String) -> String:
	return TranslationServer.translate(_DESCRIPTIONS.get(style, _DESCRIPTIONS[DEFAULT_STYLE]))
