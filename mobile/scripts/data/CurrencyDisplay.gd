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


## "Credits" / "Cash" / "Medals" -- for a title/tab/heading.
static func label_for(currency_key: String) -> String:
	return LABELS.get(currency_key, currency_key.capitalize())


## "credits" / "cash" / "medals" -- for an inline amount like "10 cash" or
## "500 credits", matching how every such label in this project already reads.
static func lowercase_label_for(currency_key: String) -> String:
	return label_for(currency_key).to_lower()
