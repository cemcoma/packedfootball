class_name PackData
extends RefCounted

## Client-side pack listing data -- mirrors the shape backend/main.py's
## GET /pack/list returns. Display-only, same boundary PlayerCard.gd draws
## for match simulation: no purchasing logic lives here, since opening a
## pack is a real-money-adjacent, server-validated operation (see Shop.gd
## calling Backend.call_endpoint for POST /pack/open).
##
## "type" is a free-form category string (standard/tournament/special/timed
## today, extendable to more without any code change here -- its display
## order comes from /pack/list's `sections`, i.e. Firestore's
## pack_types/{type}.order; see pack_database.py's own docstring). "max_opens"/"remaining_opens"/
## "expires_at"/"available_at"/"description" are all optional on the
## Firestore side.
##
## "rates"/"pos_rates" are the odds-disclosure fields app store policies
## require (tier/position -> probability, 0..1) -- shown by
## PackInfoPopup.gd, opened from PackView's info button. Always present in
## practice (pack_database.PACK_DATABASE defines them for every pack), but
## default to {} here since a pack doc predating this feature would
## otherwise have no such field at all.
##
## Most packs the backend returns are purchasable ("available" true), but
## it can also return ones that aren't -- an inactive/sold-out/expired pack
## an admin opted into still showing (e.g. a Champions Promo pack previewed ahead
## of its real on-sale date, tagged with "available_at" rather than hidden
## outright). "available" is what actually gates the Buy button; a pack the
## backend hides completely (the ordinary case for an inactive pack) never
## reaches here at all.

var sprite_key: String = ""

## Dictionary.get(key, default) only falls back to `default` when the key
## is entirely absent -- a present key holding JSON null (which is exactly
## what an unset optional field like "expires_at" round-trips to) comes
## back as null regardless, and assigning null into a statically-typed
## String/int var is a hard runtime error. These coerce either case (key
## missing, or key present but null) to a safe default.
static func _str(fields: Dictionary, key: String, default: String = "") -> String:
	var value = fields.get(key)
	return value if value is String else default


static func _bool(fields: Dictionary, key: String, default: bool) -> bool:
	var value = fields.get(key)
	return value if value is bool else default


static func _int(fields: Dictionary, key: String, default: int = 0) -> int:
	var value = fields.get(key)
	return value if typeof(value) in [TYPE_INT, TYPE_FLOAT] else default


static func _dict(fields: Dictionary, key: String, default: Dictionary) -> Dictionary:
	var value = fields.get(key)
	return value if value is Dictionary else default


var pack_id: String = ""  # the pack's slug
var pack_name: String = ""
var type: String = "standard"
var description: String = ""
var price: int = 0
## Which balance this pack is bought with ("credits"/"bucks"/"medals") --
## exactly one, never a combination. Absent means credits, matching the
## backend default, so packs that predate per-pack pricing keep working.
var price_currency: String = "credits"
var cards_per_pack: int = 0
var rates: Dictionary = {}  # tier -> probability (0..1), e.g. {"bronze": 0.6, ...} -- odds disclosure
var pos_rates: Dictionary = {}  # position category -> probability (0..1), e.g. {"goalkeeper": 0.25, ...}
## Slots pinned to a tier instead of rolled, [{"tier", "count"}, ...]. The
## odds table is the remainder after these, so both are disclosed together.
var guarantees: Array = []
## Item drops -- rarity -> probability (0..1) -- and how many are rolled. Same
## disclosure rules as the card odds; {} / 0 for a pack that sells no items.
var item_rates: Dictionary = {}
var items_per_pack: int = 0
var max_opens = null  # int or null (unlimited)
var times_opened: int = 0
var remaining_opens = null  # int or null (unlimited)
var expires_at: String = ""

var available: bool = true  # can this actually be bought right now?
var unavailable_reason: String = ""  # e.g. "This pack has sold out" -- only meaningful when !available
var available_at: String = ""  # e.g. a not-yet-active pack's planned on-sale date -- purely a display hint


static func from_fields(fields: Dictionary) -> PackData:
	var pack := PackData.new()
	pack.pack_id = _str(fields, "pack_id")
	pack.pack_name = _str(fields, "name")
	pack.type = _str(fields, "type", "standard")
	pack.description = _str(fields, "description")
	pack.price = _int(fields, "price")
	pack.price_currency = _str(fields, "price_currency", "credits")
	pack.cards_per_pack = _int(fields, "cards_per_pack")
	pack.rates = _dict(fields, "rates", {})
	pack.pos_rates = _dict(fields, "pos_rates", {})
	var guarantees_raw = fields.get("guarantees")
	pack.guarantees = guarantees_raw if guarantees_raw is Array else []
	pack.item_rates = _dict(fields, "item_rates", {})
	pack.items_per_pack = _int(fields, "items_per_pack", 0)
	pack.max_opens = fields.get("max_opens")  # untyped var -- null is a valid value here, no coercion needed
	pack.times_opened = _int(fields, "times_opened")
	pack.remaining_opens = fields.get("remaining_opens")
	pack.expires_at = _str(fields, "expires_at")
	pack.sprite_key = _str(fields, "sprite_key", "")
	
	pack.available = _bool(fields, "available", true)
	pack.unavailable_reason = _str(fields, "unavailable_reason")
	pack.available_at = _str(fields, "available_at")
	return pack


## Everything in one opening. Items are drawn as cards and share the reveal
## carousel, so they count -- an Equipment Pack is 3, not 0.
func contents_count() -> int:
	return cards_per_pack + items_per_pack


## Only cards take bench space; items are a field on users/{uid}.
func bench_slots_needed() -> int:
	return cards_per_pack


## "1 guaranteed SPECIAL", or "" for a pack that pins nothing. Shown above the
## odds table, because the table is the odds for the REMAINING slots.
func guarantee_label() -> String:
	var parts: Array = []
	for entry in guarantees:
		if not (entry is Dictionary):
			continue
		var count := int(entry.get("count", 1))
		parts.append("%d x %s" % [count, PlayerCard.tier_label(str(entry.get("tier", "")))])
	if parts.is_empty():
		return ""
	return tr("Guaranteed: %s") % ", ".join(parts)


func is_limited() -> bool:
	return max_opens != null


func limited_label() -> String:
	if not is_limited():
		return ""
	return "%d packs left to open!" % remaining_opens


## What to show in place of (or alongside) the Buy button when this pack
## isn't purchasable right now. "" means it is purchasable -- show the
## normal Buy button instead. Prefers a planned on-sale date over the raw
## unavailable_reason when both are present, since "Available Jan 15" is
## more useful to a player than "This pack is not currently available".
func tag_text() -> String:
	if available:
		return ""
	if available_at != "":
		return TranslationServer.translate("Available %s") % TimeFormat.local_date(available_at)
	if unavailable_reason != "":
		return unavailable_reason
	return TranslationServer.translate("Not available")

func get_texture() -> Texture2D:
	if sprite_key != "":
		var specific_path := "res://sprites/packs/%s.png" % sprite_key
		if ResourceLoader.exists(specific_path):
			return load(specific_path)

	var type_path := "res://sprites/packs/%s.png" % type.to_lower()
	if ResourceLoader.exists(type_path):
		return load(type_path)

	return load("res://sprites/packs/StandardPack1.png")
