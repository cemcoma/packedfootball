class_name TimeFormat
extends RefCounted

## Durations as text. Static only, no state -- same shape as
## CurrencyDisplay.gd, and the one place a countdown gets worded.
##
## The countdowns take SECONDS, never a date. The backend already returns
## `seconds_remaining` and `seconds_to_next`, and the screen ticks them down
## locally with _process(delta). That is deliberate: parsing an ISO timestamp
## client-side would make every countdown depend on the device clock being
## right, and a phone an hour fast would show a tournament that ended already.
## Counting down a number the server handed us is immune to that.
##
## The cost is drift over a long session -- a screen left open for an hour
## accumulates whatever the frame loop loses. Any refresh re-anchors it, which
## is often enough for a countdown measured in hours.
##
## Absolute dates (a pack's expires_at / available_at) are the exception, at
## the bottom: those are shown as a calendar date in the device's own time
## zone, which reads the clock's ZONE, never its time.

const MONTHS_SHORT := ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


## "4h 12m", "12m 30s", "45s". Two units at most, because the third is noise
## at every scale that matters here.
static func duration(seconds: int) -> String:
	seconds = maxi(0, seconds)
	var hours := seconds / 3600
	var minutes := (seconds % 3600) / 60
	var secs := seconds % 60

	if hours > 0:
		return TranslationServer.translate("%dh %02dm") % [hours, minutes]
	if minutes > 0:
		return TranslationServer.translate("%dm %02ds") % [minutes, secs]
	return TranslationServer.translate("%ds") % secs


## "4h 12m" with no seconds -- for anything measured in hours, where a
## ticking seconds digit is just a distraction.
static func coarse_duration(seconds: int) -> String:
	seconds = maxi(0, seconds)
	var hours := seconds / 3600
	var minutes := (seconds % 3600) / 60
	if hours > 0:
		return TranslationServer.translate("%dh %02dm") % [hours, minutes]
	if minutes > 0:
		return TranslationServer.translate("%dm") % minutes
	return TranslationServer.translate("under a minute")


## "Ends in 4h 12m" / "Ended". The phrase a tournament header wants.
static func ends_in(seconds: int) -> String:
	if seconds <= 0:
		return TranslationServer.translate("Ended")
	return TranslationServer.translate("Ends in %s") % coarse_duration(seconds)


## "+1 in 12m 30s" / "Full". What sits under an energy bar.
static func next_energy_in(seconds: int, is_full: bool) -> String:
	if is_full:
		return TranslationServer.translate("Full")
	return TranslationServer.translate("+1 in %s") % duration(seconds)


## A moment the server sent as ISO 8601 -- "2026-10-01T22:00:00+00:00", what
## FastAPI makes of a Firestore timestamp -- as "2 Oct 2026, 01:00" in the
## device's time zone. Anything unparseable comes back as it was, so a
## malformed admin-set field shows raw rather than blank.
static func local_datetime(iso: String) -> String:
	var local := _local_dict(iso)
	if local.is_empty():
		return iso
	return TranslationServer.translate("%d %s %d, %02d:%02d") % [
		local.day, month_short(local.month), local.year, local.hour, local.minute
	]


## Date only: "2 Oct 2026", still in the device's zone -- so a pack that
## opens at midnight UTC shows the day it actually opens where the player is.
static func local_date(iso: String) -> String:
	var local := _local_dict(iso)
	if local.is_empty():
		return iso
	return TranslationServer.translate("%d %s %d") % [local.day, month_short(local.month), local.year]


static func month_short(month: int) -> String:
	if month < 1 or month > MONTHS_SHORT.size():
		return str(month)
	return TranslationServer.translate(MONTHS_SHORT[month - 1])


## Time.get_datetime_dict_from_unix_time for `iso` shifted into the device's
## zone, or {} when the string isn't a date. Godot's own parser ignores a
## zone suffix, so the offset is split off and applied by hand.
static func _local_dict(iso: String) -> Dictionary:
	var text := iso.strip_edges()
	var offset_seconds := 0
	var time_start := text.find("T")
	if time_start < 0:
		time_start = text.find(" ")
	if text.ends_with("Z"):
		text = text.left(text.length() - 1)
	elif time_start >= 0:
		var sign_pos := maxi(text.rfind("+"), text.rfind("-"))
		if sign_pos > time_start:
			var digits := text.substr(sign_pos + 1).replace(":", "")
			if digits.length() >= 4 and digits.is_valid_int():
				offset_seconds = int(digits.substr(0, 2)) * 3600 + int(digits.substr(2, 2)) * 60
				if text[sign_pos] == "-":
					offset_seconds = -offset_seconds
			text = text.left(sign_pos)
	var fraction := text.find(".")
	if fraction >= 0:
		text = text.left(fraction)
	text = text.replace(" ", "T")

	var shape := RegEx.create_from_string("^\\d{4}-(\\d{2})-(\\d{2})(T(\\d{2}):(\\d{2})(:(\\d{2}))?)?$")
	var found := shape.search(text)
	if found == null:
		return {}
	# Godot's converter errors out loud on an impossible date; refuse it here.
	var year := int(text.left(4))
	var month := int(found.get_string(1))
	var day := int(found.get_string(2))
	var hour := int(found.get_string(4)) if found.get_string(4) != "" else 0
	var minute := int(found.get_string(5)) if found.get_string(5) != "" else 0
	var second := int(found.get_string(7)) if found.get_string(7) != "" else 0
	if month < 1 or month > 12 or day < 1 or day > _days_in_month(year, month):
		return {}
	if hour > 23 or minute > 59 or second > 59:
		return {}
	var unix := Time.get_unix_time_from_datetime_dict({
		"year": year, "month": month, "day": day, "hour": hour, "minute": minute, "second": second
	}) - offset_seconds
	var bias_minutes: int = int(Time.get_time_zone_from_system().get("bias", 0))
	return Time.get_datetime_dict_from_unix_time(unix + bias_minutes * 60)


static func _days_in_month(year: int, month: int) -> int:
	if month == 2:
		var leap := (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
		return 29 if leap else 28
	return 30 if month in [4, 6, 9, 11] else 31
