extends Node

## Calls the Cloud Run backend (packedfootball/backend/main.py) with the
## signed-in user's ID token as a bearer credential -- GDScript port of
## firebase_client.py's call_backend(), split into its own autoload since
## this project splits Firestore/Auth into separate scripts rather than
## firebase_client.py's one monolithic FirebaseClient class.
##
## GDScript has no try/except, so a failed call comes back as
## {"ok": false, ...} instead of raising -- same pattern as Firestore.gd.

## Seconds before a request is given up on and comes back as a failure.
## Generous, because /match/quick simulates a whole match before answering
## and a cold Cloud Run instance adds its start-up on top; the point is
## only that a dead connection ends in an error the caller can show instead
## of a spinner that never stops.
const REQUEST_TIMEOUT_SECONDS := 60.0


func _auth_headers() -> PackedStringArray:
	return PackedStringArray(
		["Authorization: Bearer %s" % FirebaseAuth.id_token, "Content-Type: application/json"]
	)


## Returns {"ok": bool, "status": int, "data": Dictionary}. "data" is the
## parsed JSON response body -- on a 2xx the endpoint's result, on an error
## whatever FastAPI sent back (typically {"detail": "..."}), {} when the
## body wasn't a JSON object or the request never left.
func call_endpoint(method: HTTPClient.Method, path: String, body: Dictionary = {}) -> Dictionary:
	var http := HTTPRequest.new()
	http.accept_gzip = false
	http.timeout = REQUEST_TIMEOUT_SECONDS
	add_child(http)
	var url := FirebaseConfig.BACKEND_URL + path
	# A method that conventionally carries a body (POST/PUT/PATCH) needs real
	# body framing even when there's nothing to send -- an empty string ("")
	# body for one of these left Cloud Run's own front end rejecting the
	# request outright with "411 Length Required" before it ever reached
	# main.py, for any body-less call (e.g. /match/quick, /account/bootstrap,
	# both called with no body argument at all). "{}" is a real, non-empty
	# JSON value FastAPI safely ignores on any endpoint that doesn't declare
	# a body parameter, so it's a safe default regardless of what's actually
	# being called. GET (and everything else with no body convention) is
	# untouched -- only the methods that expect one get this fallback.
	var carries_body := method in [HTTPClient.METHOD_POST, HTTPClient.METHOD_PUT, HTTPClient.METHOD_PATCH]
	var body_str := JSON.stringify(body) if (not body.is_empty() or carries_body) else ""
	var err := http.request(url, _auth_headers(), method, body_str)
	if err != OK:
		http.queue_free()
		push_warning("Backend call %s (error %s)" % [path, err])
		return {"ok": false, "status": 0, "data": {}}

	var result: Array = await http.request_completed
	http.queue_free()
	var status: int = result[1]
	var body_bytes: PackedByteArray = result[3]
	var text := body_bytes.get_string_from_utf8()

	var parsed = JSON.parse_string(text) if text != "" else {}
	var data: Dictionary = parsed if parsed is Dictionary else {}
	if status < 200 or status >= 300:
		push_warning("Backend call %s failed: HTTP %d %s" % [path, status, text])
		return {"ok": false, "status": status, "data": data}

	return {"ok": true, "status": status, "data": data}
