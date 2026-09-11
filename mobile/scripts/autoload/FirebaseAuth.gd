extends Node

## Ported from packedfootball/firebase_client.py -- same endpoints, same
## request/response shapes, same session-resume-via-refresh-token idea.
## Registered as an autoload singleton (see project.godot) so any scene can
## call FirebaseAuth.sign_in_anonymously() etc. and read FirebaseAuth.uid,
## mirroring how firebase_client.FirebaseClient is one shared instance
## threaded through every pygame scene.
##
## Godot's HTTPRequest works natively on every export target (desktop, iOS,
## Android) with one code path -- no browser/desktop transport branching
## needed the way firebase_client.py's _HttpTransport had to do for pygbag.
##
## GDScript has no try/except, so every call here returns a Dictionary
## {"ok": true, ...} or {"ok": false, "error": "..."} instead of raising.

const IDENTITY_TOOLKIT_URL := "https://identitytoolkit.googleapis.com/v1/accounts"
const SECURE_TOKEN_URL := "https://securetoken.googleapis.com/v1/token"
const SESSION_PATH := "user://session.json"

var uid: String = ""
var id_token: String = ""
var refresh_token: String = ""

var is_signed_in: bool:
	get:
		return id_token != ""


func _post_json(url: String, body: Dictionary) -> Dictionary:
	var http := HTTPRequest.new()
	add_child(http)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var err := http.request(url, headers, HTTPClient.METHOD_POST, JSON.stringify(body))
	if err != OK:
		http.queue_free()
		return {"ok": false, "error": "Could not start request (error %s)" % err}

	var result: Array = await http.request_completed
	http.queue_free()
	return _parse_response(result)


func _post_form(url: String, form_body: String) -> Dictionary:
	var http := HTTPRequest.new()
	add_child(http)
	var headers := PackedStringArray(["Content-Type: application/x-www-form-urlencoded"])
	var err := http.request(url, headers, HTTPClient.METHOD_POST, form_body)
	if err != OK:
		http.queue_free()
		return {"ok": false, "error": "Could not start request (error %s)" % err}

	var result: Array = await http.request_completed
	http.queue_free()
	return _parse_response(result)


func _parse_response(result: Array) -> Dictionary:
	# result = [HTTPRequest.Result, response_code, headers, body: PackedByteArray]
	var response_code: int = result[1]
	var body_bytes: PackedByteArray = result[3]
	var body_text := body_bytes.get_string_from_utf8()
	var parsed = JSON.parse_string(body_text) if body_text != "" else null

	if response_code < 200 or response_code >= 300:
		var message := "HTTP %d" % response_code
		if parsed is Dictionary and parsed.has("error"):
			message = parsed["error"].get("message", message)
		return {"ok": false, "error": message}

	if not (parsed is Dictionary):
		return {"ok": false, "error": "Unexpected response body"}
	return {"ok": true, "data": parsed}


func _apply_auth_payload(data: Dictionary) -> void:
	id_token = data.get("idToken", "")
	refresh_token = data.get("refreshToken", "")
	uid = data.get("localId", "")


func sign_in_anonymously() -> Dictionary:
	var url := "%s:signUp?key=%s" % [IDENTITY_TOOLKIT_URL, FirebaseConfig.FIREBASE_API_KEY]
	var res := await _post_json(url, {"returnSecureToken": true})
	if not res.ok:
		return res
	_apply_auth_payload(res.data)
	_persist_refresh_token()
	return {"ok": true, "uid": uid}


func register_with_email(email: String, password: String) -> Dictionary:
	var url := "%s:signUp?key=%s" % [IDENTITY_TOOLKIT_URL, FirebaseConfig.FIREBASE_API_KEY]
	var res := await _post_json(url, {"email": email, "password": password, "returnSecureToken": true})
	if not res.ok:
		return res
	_apply_auth_payload(res.data)
	_persist_refresh_token()
	return {"ok": true, "uid": uid}


func sign_in_with_email(email: String, password: String) -> Dictionary:
	var url := "%s:signInWithPassword?key=%s" % [IDENTITY_TOOLKIT_URL, FirebaseConfig.FIREBASE_API_KEY]
	var res := await _post_json(url, {"email": email, "password": password, "returnSecureToken": true})
	if not res.ok:
		return res
	_apply_auth_payload(res.data)
	_persist_refresh_token()
	return {"ok": true, "uid": uid}


func try_resume_session() -> bool:
	var stored := _load_persisted_refresh_token()
	if stored == "":
		return false
	refresh_token = stored
	return await _refresh_id_token()


func _refresh_id_token() -> bool:
	if refresh_token == "":
		return false
	var url := "%s?key=%s" % [SECURE_TOKEN_URL, FirebaseConfig.FIREBASE_API_KEY]
	var form := "grant_type=refresh_token&refresh_token=%s" % refresh_token.uri_encode()
	var res := await _post_form(url, form)
	if not res.ok:
		return false
	# This endpoint's response uses snake_case keys, unlike Identity Toolkit's camelCase.
	var data: Dictionary = res.data
	id_token = data.get("id_token", "")
	refresh_token = data.get("refresh_token", "")
	uid = data.get("user_id", "")
	if id_token == "":
		return false
	_persist_refresh_token()
	return true


func sign_out() -> void:
	uid = ""
	id_token = ""
	refresh_token = ""
	_clear_persisted_refresh_token()


func _persist_refresh_token() -> void:
	var file := FileAccess.open(SESSION_PATH, FileAccess.WRITE)
	if file == null:
		push_warning("Could not persist session (error %s)" % FileAccess.get_open_error())
		return
	file.store_string(JSON.stringify({"refresh_token": refresh_token}))
	file.close()


func _load_persisted_refresh_token() -> String:
	if not FileAccess.file_exists(SESSION_PATH):
		return ""
	var file := FileAccess.open(SESSION_PATH, FileAccess.READ)
	if file == null:
		return ""
	var parsed = JSON.parse_string(file.get_as_text())
	file.close()
	if parsed is Dictionary:
		return parsed.get("refresh_token", "")
	return ""


func _clear_persisted_refresh_token() -> void:
	var file := FileAccess.open(SESSION_PATH, FileAccess.WRITE)
	if file:
		file.store_string("{}")
		file.close()
