class_name ItemData
extends RefCounted

## Client-side equipment rules: mirrors packedfootball/items.py.
##
## An item is a flat buff to one attribute, socketed into a card. It stays a
## plain Dictionary on this end, exactly as the backend stores and sends it --
## there is nothing to model, and a class would only mean converting both ways
## at every boundary. Everything here is a static helper over that shape:
##
##     {"id": "a1b2..", "r": "gold", "s": "shooting", "v": 4, "k": "outfield"}
##
## The short keys are the server's: these ride inline on documents that are
## read on every card load, so they are kept small on purpose.
##
## THE SERVER DECIDES. can_equip() here exists so a button can be disabled and
## a reason shown before the request, not to be an authority -- /item/equip
## re-checks all of it. Keep the two in step by hand, the way PlayerCard's
## RELEASE_CREDITS is kept in step with the backend's own table.

## Mirrors items.py's ITEM_VALUES: rarity -> points of buff.
const ITEM_VALUES := {
	"bronze": 2,
	"silver": 3,
	"gold": 4,
	"platinum": 6,
	"diamond": 8,
	"special": 10,
	"icon": 12,
}

## Mirrors items.py. Three slots on every card at every tier; the extender
## occupies one and grants two, so four real buffs is the ceiling.
const SLOTS_BASE := 3
const SLOT_EXTENDER_BONUS := 2
const SLOT_EXTENDER_STAT := "slots"

const KIND_OUTFIELD := "outfield"
const KIND_KEEPER := "keeper"
const KIND_ANY := "any"

## What scrapping a spare pays. backend/config.py's
## ITEM_SCRAP_CREDITS_BY_RARITY is what actually pays out; this copy is so the
## button can show the amount before the request, exactly as
## PlayerCard.RELEASE_CREDITS does for cards.
const SCRAP_CREDITS := {
	"bronze": 5,
	"silver": 10,
	"gold": 25,
	"platinum": 60,
	"diamond": 150,
	"special": 300,
	"icon": 600,
}

## Stat name -> what it is called on screen. Translated through
## TranslationServer rather than tr(): everything in this file is static, and
## a static function cannot call tr(). PlayerCard.tier_label does the same.
const STAT_LABELS := {
	"speed": "Speed",
	"agility": "Agility",
	"stamina": "Stamina",
	"power": "Power",
	"passing": "Passing",
	"accuracy": "Accuracy",
	"vision": "Vision",
	"ballcontrol": "Ball Control",
	"dribbling": "Dribbling",
	"shooting": "Shooting",
	"heading": "Heading",
	"defending": "Defending",
	"tackling": "Tackling",
}


static func item_id(item: Dictionary) -> String:
	return str(item.get("id", ""))


static func rarity(item: Dictionary) -> String:
	return str(item.get("r", "bronze"))


static func stat(item: Dictionary) -> String:
	return str(item.get("s", ""))


static func value(item: Dictionary) -> int:
	return int(item.get("v", 0))


static func kind(item: Dictionary) -> String:
	return str(item.get("k", KIND_OUTFIELD))


static func is_slot_extender(item: Dictionary) -> bool:
	return stat(item) == SLOT_EXTENDER_STAT


## Rarity colour, straight from the card table -- items and cards share one
## rarity scale on purpose, so a gold item reads as a gold at a glance.
static func color(item: Dictionary) -> Color:
	return PlayerCard.tier_color(rarity(item))


static func rarity_rank(item: Dictionary) -> int:
	return PlayerCard.tier_rank(rarity(item))


static func stat_label(item: Dictionary) -> String:
	if is_slot_extender(item):
		return TranslationServer.translate("Slot Extender")
	return TranslationServer.translate(STAT_LABELS.get(stat(item), stat(item).capitalize()))


## "+4 Shooting", or "+2 Slots" for the extender.
static func label(item: Dictionary) -> String:
	if is_slot_extender(item):
		return "+%d %s" % [SLOT_EXTENDER_BONUS, TranslationServer.translate("Slots")]
	return "+%d %s" % [value(item), stat_label(item)]


static func scrap_credits(item: Dictionary) -> int:
	return int(SCRAP_CREDITS.get(PlayerCard.tier_family(rarity(item)), 5))


static func kind_for_position(position: String) -> String:
	return KIND_KEEPER if position == "GK" else KIND_OUTFIELD


static func fits(item: Dictionary, position: String) -> bool:
	var k := kind(item)
	return k == KIND_ANY or k == kind_for_position(position)


## How many entries a card's item list may hold.
static func capacity(items: Array) -> int:
	for item in items:
		if item is Dictionary and is_slot_extender(item):
			return SLOTS_BASE + SLOT_EXTENDER_BONUS
	return SLOTS_BASE


## Why this item can't go on this card, or "" if it can. Mirrors items.py's
## can_equip, message for message, so a disabled button and a 409 say the same
## thing.
static func equip_blocker(items: Array, item: Dictionary, position: String) -> String:
	if not fits(item, position):
		return TranslationServer.translate("That item is not for this position")
	if is_slot_extender(item):
		for existing in items:
			if existing is Dictionary and is_slot_extender(existing):
				return TranslationServer.translate("This card already has a slot extender")
		return ""
	for existing in items:
		if existing is Dictionary and stat(existing) == stat(item):
			return TranslationServer.translate("This card already has an item for that stat")
	if items.size() >= capacity(items):
		return TranslationServer.translate("This card has no free item slots")
	return ""


## `attributes` with every item's buff added, as a NEW Dictionary. The card's
## own `attributes` is left alone: overall(), SquadOptimizer and
## GameProfile.average_overall() all read it raw, and a mutated copy would
## quietly become the card.
static func apply(attributes: Dictionary, items: Array) -> Dictionary:
	if items.is_empty():
		return attributes
	var out := attributes.duplicate()
	for item in items:
		if not (item is Dictionary) or is_slot_extender(item):
			continue
		var name := stat(item)
		if not out.has(name):
			continue
		out[name] = int(out[name]) + value(item)
	return out


## Whatever came back from the server, as an Array of well-formed items.
## Anything unrecognised is dropped rather than shown as a broken tile --
## the backend will gain item types this build has never heard of.
static func sanitize(raw) -> Array:
	var clean: Array = []
	if not (raw is Array):
		return clean
	for entry in raw:
		if entry is Dictionary and entry.has("s"):
			clean.append(entry)
	return clean


## Best first, then by stat, so a grid reads the way the card grids do.
static func sort_best_first(items: Array) -> Array:
	var sorted_items := items.duplicate()
	sorted_items.sort_custom(func(a, b):
		var rank_a := rarity_rank(a)
		var rank_b := rarity_rank(b)
		if rank_a != rank_b:
			return rank_a > rank_b
		return stat(a) < stat(b)
	)
	return sorted_items
