extends Node

## Calls the Cloud Run backend (packedfootball/backend/main.py) with the
## signed-in user's ID token as a bearer credential -- GDScript port of
## firebase_client.py's call_backend(), split into its own autoload since
## this project splits Firestore/Auth into separate scripts rather than
## firebase_client.py's one monolithic FirebaseClient class.
##
## GDScript has no try/except, so a failed call comes back as
## {"ok": false, ...} instead of raising -- same pattern as Firestore.gd.

func _auth_headers() -> PackedStringArray:
	return PackedStringArray(
		["Authorization: Bearer %s" % FirebaseAuth.id_token, "Content-Type: application/json"]
	)


## Returns {"ok": bool, "status": int, "data": Dictionary}. "data" is the
## parsed JSON response body on a 2xx status, {} otherwise.
func call_endpoint(method: HTTPClient.Method, path: String, body: Dictionary = {}) -> Dictionary:
	var http := HTTPRequest.new()
	add_child(http)
	var url := FirebaseConfig.BACKEND_URL + path
	var body_str := JSON.stringify(body) if not body.is_empty() else ""
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

	if status < 200 or status >= 300:
		push_warning("Backend call %s failed: HTTP %d %s" % [path, status, text])
		return {"ok": false, "status": status, "data": {}}

	var parsed = JSON.parse_string(text) if text != "" else {}
	return {"ok": true, "status": status, "data": (parsed if parsed is Dictionary else {})}
