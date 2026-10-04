extends SceneTree

## Decodes one match as replay v1 and v2 and checks they agree within v2's
## quantisation (positions 0.02, velocities 0.25). Run via `make replay-check`.

const POS_TOLERANCE := 0.0101
const VEL_TOLERANCE := 0.1251


func _init() -> void:
	var args := OS.get_cmdline_user_args()
	var started := Time.get_ticks_msec()
	var a := ReplayReader.load_from_bytes(FileAccess.get_file_as_bytes(args[0]))
	var v1_ms := Time.get_ticks_msec() - started
	started = Time.get_ticks_msec()
	var b := ReplayReader.load_from_bytes(FileAccess.get_file_as_bytes(args[1]))
	var v2_ms := Time.get_ticks_msec() - started

	var problems := _compare(a, b)
	if problems.is_empty():
		print("ok   %d samples, %d events (v1 %d ms, v2 %d ms)" % [a["samples"].size(), a["events"].size(), v1_ms, v2_ms])
	else:
		for problem in problems.slice(0, 10):
			print("FAIL ", problem)
	quit(0 if problems.is_empty() else 1)


func _compare(a: Dictionary, b: Dictionary) -> Array:
	if a.is_empty() or b.is_empty():
		return ["a replay failed to decode"]
	var problems: Array = []
	if b["version"] != 2:
		problems.append("second file decoded as version %s, not 2" % b["version"])
	if a["sample_interval_ticks"] != b["sample_interval_ticks"]:
		problems.append("sample interval differs")
	if a["samples"].size() != b["samples"].size():
		return problems + ["sample count %d vs %d" % [a["samples"].size(), b["samples"].size()]]
	if a["events"] != b["events"]:
		problems.append("events differ")

	for i in range(a["samples"].size()):
		var sa: Dictionary = a["samples"][i]
		var sb: Dictionary = b["samples"][i]
		if sa["tick"] != sb["tick"] or sa["ball_controller"] != sb["ball_controller"]:
			problems.append("sample %d: tick/controller differ" % i)
		for key in ["x", "y", "vx", "vy", "height"]:
			if not is_equal_approx(sa["ball"][key], sb["ball"][key]):
				problems.append("sample %d: ball %s %s vs %s" % [i, key, sa["ball"][key], sb["ball"][key]])
		for p in range(ReplayReader.NUM_PLAYERS):
			var pa: Dictionary = sa["players"][p]
			var pb: Dictionary = sb["players"][p]
			if absf(pa["x"] - pb["x"]) > POS_TOLERANCE or absf(pa["y"] - pb["y"]) > POS_TOLERANCE:
				problems.append("sample %d player %d: position off by more than %s" % [i, p, POS_TOLERANCE])
			if absf(pa["vx"] - pb["vx"]) > VEL_TOLERANCE or absf(pa["vy"] - pb["vy"]) > VEL_TOLERANCE:
				problems.append("sample %d player %d: velocity off by more than %s" % [i, p, VEL_TOLERANCE])
	return problems
