class_name TimeFormat
extends RefCounted

## Durations as text. Static only, no state -- same shape as
## CurrencyDisplay.gd, and the one place a countdown gets worded.
##
## Everything here takes SECONDS, never a date. The backend already returns
## `seconds_remaining` and `seconds_to_next`, and the screen ticks them down
## locally with _process(delta). That is deliberate: parsing an ISO timestamp
## client-side would make every countdown depend on the device clock being
## right, and a phone an hour fast would show a tournament that ended already.
## Counting down a number the server handed us is immune to that.
##
## The cost is drift over a long session -- a screen left open for an hour
## accumulates whatever the frame loop loses. Any refresh re-anchors it, which
## is often enough for a countdown measured in hours.


## "4h 12m", "12m 30s", "45s". Two units at most, because the third is noise
## at every scale that matters here.
static func duration(seconds: int) -> String:
	seconds = maxi(0, seconds)
	var hours := seconds / 3600
	var minutes := (seconds % 3600) / 60
	var secs := seconds % 60

	if hours > 0:
		return "%dh %02dm" % [hours, minutes]
	if minutes > 0:
		return "%dm %02ds" % [minutes, secs]
	return "%ds" % secs


## "4h 12m" with no seconds -- for anything measured in hours, where a
## ticking seconds digit is just a distraction.
static func coarse_duration(seconds: int) -> String:
	seconds = maxi(0, seconds)
	var hours := seconds / 3600
	var minutes := (seconds % 3600) / 60
	if hours > 0:
		return "%dh %02dm" % [hours, minutes]
	if minutes > 0:
		return "%dm" % minutes
	return "under a minute"


## "Ends in 4h 12m" / "Ended". The phrase a tournament header wants.
static func ends_in(seconds: int) -> String:
	if seconds <= 0:
		return "Ended"
	return "Ends in %s" % coarse_duration(seconds)


## "+1 in 12m 30s" / "Full". What sits under an energy bar.
static func next_energy_in(seconds: int, is_full: bool) -> String:
	if is_full:
		return "Full"
	return "+1 in %s" % duration(seconds)
