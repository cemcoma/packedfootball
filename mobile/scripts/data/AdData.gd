class_name AdData
extends RefCounted

static func _str(fields: Dictionary, key: String, default: String = "") -> String:
	var value = fields.get(key)
	return value if value is String else default

static func _int(fields: Dictionary, key: String, default: int = 0) -> int:
	var value = fields.get(key)
	return value if typeof(value) in [TYPE_INT, TYPE_FLOAT] else default

static func _bool(fields: Dictionary, key: String, default: bool) -> bool:
	var value = fields.get(key)
	return value if value is bool else default

var track: String = "" # AdManager.TRACK_BUCK or TRACK_ENERGY
var title: String = ""
var description: String = ""
var reward_credits: int = 0
var reward_bucks: int = 0
var reward_energy: int = 0
var step_current: int = 0
var step_max: int = 0

## What each ad along the track pays, in order. Only shown when the steps
## actually differ -- a flat track says nothing the "n / m" doesn't.
var steps: Array = []

var available: bool = true
var unavailable_reason: String = ""

static func from_fields(fields: Dictionary) -> AdData:
	var ad := AdData.new()
	ad.track = _str(fields, "track")
	ad.title = _str(fields, "title")
	ad.description = _str(fields, "description")
	ad.reward_credits = _int(fields, "reward_credits")
	ad.reward_bucks = _int(fields, "reward_bucks")
	ad.reward_energy = _int(fields, "reward_energy")
	ad.step_current = _int(fields, "step_current")
	ad.step_max = _int(fields, "step_max")
	var steps = fields.get("steps")
	ad.steps = steps if steps is Array else []
	
	ad.available = _bool(fields, "available", true)
	ad.unavailable_reason = _str(fields, "unavailable_reason")
	return ad

func is_capped() -> bool:
	return step_current >= step_max
