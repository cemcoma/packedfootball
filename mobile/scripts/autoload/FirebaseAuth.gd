extends Node

## Ported from packedfootball/firebase_client.py -- same endpoints, same
## request/response shapes, same session-resume-via-refresh-token idea.
## Registered as an autoload singleton (see project.godot) so any scene can
## call FirebaseAuth.sign_in_with_email() etc. and read FirebaseAuth.uid,
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

## Firebase's own minimum -- signUp rejects anything shorter with
## WEAK_PASSWORD. Checked client-side too (see Auth.gd) so the obvious case
## never costs a round trip.
const MIN_PASSWORD_LENGTH := 6

## Identity Toolkit answers a failed request with an all-caps code in
## error.message (sometimes with a " : explanation" suffix, e.g.
## "WEAK_PASSWORD : Password should be at least 6 characters"). These are
## what a manager reads instead. Anything not listed falls through as the
## raw code, which at least says what went wrong to whoever reads the bug
## report.
##
## INVALID_LOGIN_CREDENTIALS is what newer projects return for BOTH a wrong
## password and an unknown email (email enumeration protection); the older
## split codes are kept for projects that still have it off.
const ERROR_MESSAGES := {
	"INVALID_LOGIN_CREDENTIALS": "Wrong email or password.",
	"INVALID_PASSWORD": "Wrong password.",
	"EMAIL_NOT_FOUND": "No account with that email.",
	"INVALID_EMAIL": "That email address isn't valid.",
	"MISSING_EMAIL": "Please enter your email.",
	"MISSING_PASSWORD": "Please enter your password.",
	"WEAK_PASSWORD": "Password must be at least %d characters." % MIN_PASSWORD_LENGTH,
	"EMAIL_EXISTS": "An account with that email already exists.",
	"USER_DISABLED": "This account has been disabled.",
	"TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts -- please wait a bit and try again.",
	"RESET_PASSWORD_EXCEED_LIMIT": "Too many reset emails sent -- please wait a bit and try again.",
	"OPERATION_NOT_ALLOWED": "Email sign-in isn't enabled for this app.",
}

var uid: String = ""
var id_token: String = ""
var refresh_token: String = ""

var is_signed_in: bool:
	get:
		return id_token != ""


## accept_gzip is disabled on every request in this file (and in Backend.gd /
## Firestore.gd) on purpose. Google's endpoints answer with
## "Content-Encoding: gzip", and in a web export the BROWSER has already
## decompressed the body by the time Godot sees it -- but the header is
## still there, so HTTPRequest tries to gunzip an already-plain body and
## hands back bytes that aren't UTF-8 JSON. The status is still 2xx, so
## _parse_response falls through to its "Unexpected response body" branch.
## Turning gzip off costs a slightly larger transfer on these small JSON
## payloads and nothing else.
func _post_json(url: String, body: Dictionary) -> Dictionary:
	var http := HTTPRequest.new()
	http.accept_gzip = false
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
	http.accept_gzip = false
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
			message = _friendly_error(parsed["error"].get("message", message))
		return {"ok": false, "error": message}

	if not (parsed is Dictionary):
		# Include the status and a slice of what actually came back -- a bare
		# "Unexpected response body" gives nothing to act on, and this branch
		# only fires when the status WAS 2xx, so the body is the only clue
		# there is.
		push_warning("Auth response was HTTP %d but unparseable: %s" % [response_code, body_text.left(200)])
		return {"ok": false, "error": "Unexpected response body (HTTP %d, %d bytes)" % [response_code, body_bytes.size()]}
	return {"ok": true, "data": parsed}


## The readable version of an Identity Toolkit error code (see
## ERROR_MESSAGES), or the code itself when there isn't one.
static func _friendly_error(raw: String) -> String:
	var code := raw.get_slice(" : ", 0).strip_edges()
	return ERROR_MESSAGES.get(code, raw)


func _apply_auth_payload(data: Dictionary) -> void:
	id_token = data.get("idToken", "")
	refresh_token = data.get("refreshToken", "")
	uid = data.get("localId", "")


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


## Asks Firebase to email a password-reset link -- the email itself (sender,
## template, where the link lands) is whatever the Firebase console's
## Authentication > Templates has set; nothing about it lives in this app.
## Signs nobody in and touches no session state: the manager comes back
## and signs in with the new password like anyone else.
##
## With email enumeration protection on (the default for new projects)
## Firebase answers OK for an unknown address too, so a success here means
## "if that account exists, it has mail", not "that account exists".
func send_password_reset(email: String) -> Dictionary:
	var url := "%s:sendOobCode?key=%s" % [IDENTITY_TOOLKIT_URL, FirebaseConfig.FIREBASE_API_KEY]
	var res := await _post_json(url, {"requestType": "PASSWORD_RESET", "email": email})
	if not res.ok:
		return res
	return {"ok": true}


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
