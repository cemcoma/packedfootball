class_name NetError
extends RefCounted

## Turns HTTPRequest's transport result into something a player can act on.
##
## Both callers used to read only `result[1]`, the HTTP status -- but a request
## that never reached a server has no status, so it came back 0 and the screen
## said "HTTP 0". The failure kind is in `result[0]`, and it is the half that
## distinguishes "you are offline" from "the server said no".

## HTTPRequest.Result -> message. Anything not listed falls through to a
## generic retry, which is all that is honestly known about it.
const MESSAGES := {
	HTTPRequest.RESULT_CANT_CONNECT: "Can't reach the server. Check your internet connection.",
	HTTPRequest.RESULT_CANT_RESOLVE: "Can't reach the server. Check your internet connection.",
	HTTPRequest.RESULT_CONNECTION_ERROR: "The connection dropped. Check your internet connection and try again.",
	HTTPRequest.RESULT_TLS_HANDSHAKE_ERROR: "Couldn't connect securely. Check your connection, and that your device's date and time are correct.",
	HTTPRequest.RESULT_TIMEOUT: "The server took too long to answer. Try again.",
	HTTPRequest.RESULT_NO_RESPONSE: "The server didn't answer. Try again.",
}

const GENERIC := "Something went wrong reaching the server. Try again."


## True when the request never completed a round trip, whatever the status says.
static func is_transport_failure(result_code: int) -> bool:
	return result_code != HTTPRequest.RESULT_SUCCESS


static func message_for(result_code: int) -> String:
	var key: String = MESSAGES.get(result_code, GENERIC)
	return TranslationServer.translate(key)
