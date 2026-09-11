extends Node

## Firestore REST client -- GDScript port of firebase_client.py's Firestore
## section (get_document/list_collection/set_document/add_document/
## delete_document + the field-value encode/decode helpers). Same wire
## contract, same CLIENT-TRUSTED-PHASE note as the Python client and
## firestore.rules: every call here uses the signed-in user's own ID token
## (via the FirebaseAuth autoload), and Security Rules -- not this file --
## are what stop one user from touching another user's documents.
##
## Registered as an autoload (see project.godot) so any scene can call
## Firestore.get_document(...) etc., the same way FirebaseAuth is used.
##
## GDScript has no try/except, so every call here returns a sentinel on
## failure (null for get_document, [] for list_collection, false/"" for the
## writes) instead of raising, and logs a push_warning with the detail.

const FIRESTORE_URL := "https://firestore.googleapis.com/v1"


func _doc_url(path: String) -> String:
	var trimmed := path.strip_edges().trim_prefix("/").trim_suffix("/")
	return "%s/projects/%s/databases/(default)/documents/%s" % [FIRESTORE_URL, FirebaseConfig.FIREBASE_PROJECT_ID, trimmed]


func _auth_headers() -> PackedStringArray:
	return PackedStringArray(
		["Authorization: Bearer %s" % FirebaseAuth.id_token, "Content-Type: application/json"]
	)


## Returns {"ok": bool, "status": int, "body": String}. "ok" only reflects
## whether the request could be sent at all -- callers still need to check
## "status" themselves (e.g. 404 is a normal "document missing" response,
## not a transport failure).
func _request(method: HTTPClient.Method, url: String, body: String = "") -> Dictionary:
	var http := HTTPRequest.new()
	add_child(http)
	var err := http.request(url, _auth_headers(), method, body)
	if err != OK:
		http.queue_free()
		return {"ok": false, "status": 0, "body": "Could not start request (error %s)" % err}

	var result: Array = await http.request_completed
	http.queue_free()
	var status: int = result[1]
	var body_bytes: PackedByteArray = result[3]
	return {"ok": true, "status": status, "body": body_bytes.get_string_from_utf8()}


## Returns the document's fields as a plain Dictionary, or null if it
## doesn't exist (or the request failed).
func get_document(path: String) -> Variant:
	var res := await _request(HTTPClient.METHOD_GET, _doc_url(path))
	if not res.ok:
		push_warning("Firestore get_document(%s) failed: %s" % [path, res.body])
		return null
	if res.status == 404:
		return null
	if res.status < 200 or res.status >= 300:
		push_warning("Firestore get_document(%s) HTTP %d: %s" % [path, res.status, res.body])
		return null
	var parsed = JSON.parse_string(res.body)
	if not (parsed is Dictionary):
		return null
	return decode_fields(parsed)


## Returns [{"id": doc_id, ...fields}, ...] for every document in a collection.
func list_collection(path: String) -> Array:
	var res := await _request(HTTPClient.METHOD_GET, _doc_url(path))
	if not res.ok or res.status < 200 or res.status >= 300:
		push_warning("Firestore list_collection(%s) failed" % path)
		return []
	var parsed = JSON.parse_string(res.body)
	if not (parsed is Dictionary):
		return []
	var results: Array = []
	for doc in parsed.get("documents", []):
		var doc_name: String = doc["name"]
		var doc_id: String = doc_name.split("/")[-1]
		var fields: Dictionary = decode_fields(doc)
		fields["id"] = doc_id
		results.append(fields)
	return results


## Creates or overwrites a document at an exact path (e.g. "users/<uid>").
## merge=true only touches the given fields (like client-SDK set(merge=true));
## merge=false replaces the whole document with exactly these fields.
## Returns true on success.
func set_document(path: String, data: Dictionary, merge: bool = true) -> bool:
	var url := _doc_url(path)
	if merge:
		var mask_parts: PackedStringArray = []
		for key in data.keys():
			mask_parts.append("updateMask.fieldPaths=%s" % key)
		if not mask_parts.is_empty():
			url = "%s?%s" % [url, "&".join(mask_parts)]

	var body := JSON.stringify({"fields": encode_fields(data)})
	var res := await _request(HTTPClient.METHOD_PATCH, url, body)
	if not res.ok or res.status < 200 or res.status >= 300:
		push_warning("Firestore set_document(%s) failed: %s" % [path, res.body])
		return false
	return true


## Creates a new document in a collection with an auto-generated id. Returns
## the new document's id, or "" on failure.
func add_document(collection_path: String, data: Dictionary) -> String:
	var url := _doc_url(collection_path)
	var body := JSON.stringify({"fields": encode_fields(data)})
	var res := await _request(HTTPClient.METHOD_POST, url, body)
	if not res.ok or res.status < 200 or res.status >= 300:
		push_warning("Firestore add_document(%s) failed: %s" % [collection_path, res.body])
		return ""
	var parsed = JSON.parse_string(res.body)
	if not (parsed is Dictionary) or not parsed.has("name"):
		return ""
	var doc_name: String = parsed["name"]
	return doc_name.split("/")[-1]


## Returns true if the document was deleted (or already didn't exist).
func delete_document(path: String) -> bool:
	var res := await _request(HTTPClient.METHOD_DELETE, _doc_url(path))
	if not res.ok:
		return false
	return res.status == 200 or res.status == 404


# -- Firestore field <-> plain value encoding (mirrors firebase_client.py's
# _encode_value/_decode_value: Firestore's REST wire format wraps every
# value in a type tag, e.g. {"integerValue": "5"} -- yes, integers are
# strings on the wire -- or {"mapValue": {"fields": {...}}}.) ---------------


static func _encode_value(value: Variant) -> Dictionary:
	if value == null:
		return {"nullValue": null}
	match typeof(value):
		TYPE_BOOL:
			return {"booleanValue": value}
		TYPE_INT:
			return {"integerValue": str(value)}
		TYPE_FLOAT:
			return {"doubleValue": value}
		TYPE_STRING, TYPE_STRING_NAME:
			return {"stringValue": String(value)}
		TYPE_DICTIONARY:
			var value_dict: Dictionary = value
			var fields := {}
			for key in value_dict.keys():
				fields[key] = _encode_value(value_dict[key])
			return {"mapValue": {"fields": fields}}
		TYPE_ARRAY, TYPE_PACKED_STRING_ARRAY:
			var value_array: Array = value
			var values := []
			for item in value_array:
				values.append(_encode_value(item))
			return {"arrayValue": {"values": values}}
	push_error("Cannot encode value of type %d as a Firestore value" % typeof(value))
	return {"nullValue": null}


static func _decode_value(value: Dictionary) -> Variant:
	if value.has("nullValue"):
		return null
	if value.has("booleanValue"):
		return value["booleanValue"]
	if value.has("integerValue"):
		var raw_int: String = value["integerValue"]
		return int(raw_int)
	if value.has("doubleValue"):
		var raw_double: float = value["doubleValue"]
		return raw_double
	if value.has("stringValue"):
		var raw_string: String = value["stringValue"]
		return raw_string
	if value.has("timestampValue"):
		var raw_timestamp: String = value["timestampValue"]
		return raw_timestamp
	if value.has("mapValue"):
		var map_value: Dictionary = value["mapValue"]
		var inner_fields: Dictionary = map_value.get("fields", {})
		var out := {}
		for key in inner_fields.keys():
			out[key] = _decode_value(inner_fields[key])
		return out
	if value.has("arrayValue"):
		var array_value: Dictionary = value["arrayValue"]
		var inner_values: Array = array_value.get("values", [])
		var out_arr := []
		for item in inner_values:
			out_arr.append(_decode_value(item))
		return out_arr
	push_error("Unrecognized Firestore value: %s" % value)
	return null


static func encode_fields(data: Dictionary) -> Dictionary:
	var out := {}
	for key in data.keys():
		out[key] = _encode_value(data[key])
	return out


static func decode_fields(document: Dictionary) -> Dictionary:
	var fields: Dictionary = document.get("fields", {})
	var out := {}
	for key in fields.keys():
		out[key] = _decode_value(fields[key])
	return out
