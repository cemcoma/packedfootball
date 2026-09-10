"""Minimal Firebase Auth + Firestore REST client for the pygbag/Pyodide runtime.

Why this exists: Firebase only ships client SDKs for web/Android/iOS/Flutter/Unity,
not Python. This app is Python compiled to WebAssembly (via pygbag), so instead of an
SDK we talk to Firebase's plain HTTPS REST APIs:
  - Identity Toolkit (Auth)      https://firebase.google.com/docs/reference/rest/auth
  - Secure Token (refresh)       https://firebase.google.com/docs/reference/rest/auth#section-refresh-token
  - Firestore                    https://firebase.google.com/docs/firestore/reference/rest

Networking has to work two different ways depending on where the code is running:
  - In the browser (emscripten/WASM), raw sockets don't exist. We inject a small JS
    snippet that calls the browser's own `fetch`, and drive it from Python via
    pygbag's `platform.jsiter()` bridge. This is the same trick pygbag's own
    support/cross/aio/fetch.py uses, extended here to support custom headers
    (needed for the Firestore "Authorization: Bearer <token>" header) and the
    PATCH/DELETE verbs (needed for Firestore writes), neither of which pygbag's
    built-in helper supports.
  - On desktop (plain `python3 main.py`, e.g. local dev/testing), we just use the
    `requests` library. Same call sites, same return shape, so game code never has
    to know which environment it's running in.

CLIENT-TRUSTED PHASE: there is no backend yet. This client signs in (anonymously, or
with a registered email/password) and writes directly to Firestore with the user's
own ID token. Firestore Security Rules
(see firestore.rules) are what stop one user from writing another user's documents;
they do NOT stop a user from lying about their own data (e.g. editing their own
credits). That's an accepted, explicit trade-off for this phase -- see the
conversation this shipped from. Moving pack-opening and match-result writes behind a
Cloud Run service (which enforces the rules the client currently just trusts) is the
planned next step, not part of this file.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Desktop-only: where the anonymous account's refresh token is cached between
# launches so `python3 main.py` resumes the same account instead of minting a
# new one every run. Deliberately outside the repo so it's never committed.
# Under emscripten (the pygbag/browser build) this file doesn't exist -- the
# browser has no persistent filesystem across reloads by default, so that
# path still mints a fresh anonymous account each run. Wiring that up to
# platform.window.localStorage (which does persist) is a follow-up; see
# _load_persisted_refresh_token below.
_DESKTOP_SESSION_FILE = Path.home() / ".packedfootball" / "session.json"

IDENTITY_TOOLKIT_URL = "https://identitytoolkit.googleapis.com/v1/accounts"
SECURE_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
FIRESTORE_URL = "https://firestore.googleapis.com/v1"


class FirebaseError(RuntimeError):
    """Raised for any non-2xx response from a Firebase REST endpoint."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"Firebase request failed (HTTP {status}): {body}")

    @property
    def identity_error_code(self) -> str | None:
        """The short Identity Toolkit error code (e.g. "EMAIL_EXISTS"), if any.

        Auth failures come back as JSON like {"error": {"message": "EMAIL_EXISTS", ...}}.
        Returns None for non-auth errors or bodies that aren't shaped like that.
        """
        try:
            return json.loads(self.body)["error"]["message"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return None


# --------------------------------------------------------------------------- #
# Low-level transport: one code path for emscripten (browser fetch via JS),
# one for desktop (requests). Everything above this uses `_http.request(...)`
# and never has to think about which one it's on.
# --------------------------------------------------------------------------- #

_FETCH_JS = r"""
window.PFFetch = {};
window.PFFetch.request = function* (method, url, headersJson, body) {
    var headers = JSON.parse(headersJson);
    var opts = { method: method, headers: headers };
    if (body !== null && body !== undefined && body !== "") {
        opts.body = body;
    }
    var result = null;
    fetch(new Request(url, opts))
        .then(function (resp) {
            return resp.text().then(function (text) {
                return { status: resp.status, text: text };
            });
        })
        .then(function (r) { result = r; })
        .catch(function (err) {
            result = { status: 0, text: JSON.stringify({ error: String(err) }) };
        });
    while (result === null) { yield; }
    yield JSON.stringify(result);
};
"""


class _HttpTransport:
    """Sends one HTTP request and returns (status_code, response_text)."""

    def __init__(self):
        self.is_emscripten = sys.platform == "emscripten"
        self._requests = None
        if self.is_emscripten:
            import platform  # pygbag's browser-interop shim, not stdlib platform

            self._platform = platform
            try:
                platform.window.eval(_FETCH_JS)
            except AttributeError:
                # Not actually running under pygbag's browser shim despite the
                # platform check -- fall back to desktop mode.
                self.is_emscripten = False
        if not self.is_emscripten:
            import requests

            self._requests = requests

    async def request(
        self, method: str, url: str, headers: dict[str, str], body: str | None = None
    ) -> tuple[int, str]:
        if self.is_emscripten:
            await asyncio.sleep(0)
            raw = await self._platform.jsiter(
                self._platform.window.PFFetch.request(method, url, json.dumps(headers), body or "")
            )
            parsed = json.loads(raw)
            return parsed["status"], parsed["text"]
        else:
            resp = self._requests.request(method, url, headers=headers, data=body)
            return resp.status_code, resp.text


# --------------------------------------------------------------------------- #
# Firestore field <-> plain Python value encoding.
# Firestore's REST wire format wraps every value in a type tag, e.g.
# {"integerValue": "5"} (yes, integers are strings on the wire) or
# {"mapValue": {"fields": {...}}}. These helpers convert both directions so
# the rest of the game only ever deals with plain dicts/lists/ints/strings.
# --------------------------------------------------------------------------- #


def _encode_value(value: Any) -> dict:
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {k: _encode_value(v) for k, v in value.items()}}}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_encode_value(v) for v in value]}}
    raise TypeError(f"Cannot encode {type(value)} as a Firestore value")


def _decode_value(value: dict) -> Any:
    if "nullValue" in value:
        return None
    if "booleanValue" in value:
        return value["booleanValue"]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "stringValue" in value:
        return value["stringValue"]
    if "timestampValue" in value:
        return value["timestampValue"]
    if "mapValue" in value:
        fields = value["mapValue"].get("fields", {})
        return {k: _decode_value(v) for k, v in fields.items()}
    if "arrayValue" in value:
        return [_decode_value(v) for v in value["arrayValue"].get("values", [])]
    raise ValueError(f"Unrecognized Firestore value: {value!r}")


def encode_fields(data: dict) -> dict:
    return {k: _encode_value(v) for k, v in data.items()}


def decode_fields(document: dict) -> dict:
    return {k: _decode_value(v) for k, v in document.get("fields", {}).items()}


# --------------------------------------------------------------------------- #
# Public client
# --------------------------------------------------------------------------- #


@dataclass
class _Session:
    id_token: str | None = None
    refresh_token: str | None = None
    uid: str | None = None
    expires_at: float = 0.0  # loop-time seconds; 0 means "unknown, refresh before use"


class FirebaseClient:
    """Signs in anonymously and reads/writes this user's own Firestore documents.

    Usage:
        client = FirebaseClient(api_key="...", project_id="...")
        await client.sign_in_anonymously()
        await client.set_document(f"users/{client.uid}", {"credits": 1000}, merge=True)
        profile = await client.get_document(f"users/{client.uid}")
    """

    def __init__(self, api_key: str, project_id: str):
        self.api_key = api_key
        self.project_id = project_id
        self._http = _HttpTransport()
        self._session = _Session()

    @property
    def uid(self) -> str | None:
        return self._session.uid

    @property
    def is_signed_in(self) -> bool:
        return self._session.id_token is not None

    # -- Auth ---------------------------------------------------------------

    async def try_resume_session(self) -> bool:
        """Attempts to resume a previously signed-in session from a stored
        refresh token. Works no matter how that session originally signed
        in (anonymous or email/password) -- the refresh endpoint doesn't
        care. Returns True if resumed, False if there was nothing stored or
        the stored token no longer works (e.g. revoked).

        Token persistence across launches is desktop-only for now (a local
        file) -- see _load_persisted_refresh_token. On the browser build
        this always returns False, so callers should fall back to showing a
        sign-in screen.
        """
        stored_refresh = self._load_persisted_refresh_token()
        if not stored_refresh:
            return False
        self._session.refresh_token = stored_refresh
        try:
            await self._refresh_id_token()
            return True
        except FirebaseError:
            return False

    async def sign_in_anonymously(self) -> str:
        """Creates a brand new anonymous (guest) account.

        Does not attempt to resume an existing session -- call
        try_resume_session() first if that's what you want. Returns the uid.
        """
        payload = await self._identity_toolkit_call("signUp", {"returnSecureToken": True})
        self._complete_sign_in(payload)
        return self._session.uid

    async def register_with_email(self, email: str, password: str) -> str:
        """Creates a brand new email/password account. Returns the uid.

        Raises FirebaseError with identity_error_code == "EMAIL_EXISTS" if
        that email is already registered.
        """
        payload = await self._identity_toolkit_call(
            "signUp", {"email": email, "password": password, "returnSecureToken": True}
        )
        self._complete_sign_in(payload)
        return self._session.uid

    async def sign_in_with_email(self, email: str, password: str) -> str:
        """Signs in to an existing email/password account. Returns the uid.

        Raises FirebaseError with identity_error_code in
        {"EMAIL_NOT_FOUND", "INVALID_PASSWORD", "INVALID_LOGIN_CREDENTIALS"}
        for the obvious reasons.
        """
        payload = await self._identity_toolkit_call(
            "signInWithPassword", {"email": email, "password": password, "returnSecureToken": True}
        )
        self._complete_sign_in(payload)
        return self._session.uid

    async def _identity_toolkit_call(self, action: str, body: dict) -> dict:
        status, text = await self._http.request(
            "POST",
            f"{IDENTITY_TOOLKIT_URL}:{action}?key={self.api_key}",
            headers={"Content-Type": "application/json"},
            body=json.dumps(body),
        )
        return self._parse_or_raise(status, text)

    def _complete_sign_in(self, payload: dict) -> None:
        self._apply_auth_payload(payload)
        self._persist_refresh_token(self._session.refresh_token)

    async def _refresh_id_token(self) -> None:
        if not self._session.refresh_token:
            raise FirebaseError(0, "No refresh token available; call sign_in_anonymously() first")
        status, text = await self._http.request(
            "POST",
            f"{SECURE_TOKEN_URL}?key={self.api_key}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=f"grant_type=refresh_token&refresh_token={self._session.refresh_token}",
        )
        payload = self._parse_or_raise(status, text)
        # This endpoint uses shortened key names (id_token, refresh_token, user_id).
        self._session.id_token = payload["id_token"]
        self._session.refresh_token = payload["refresh_token"]
        self._session.uid = payload["user_id"]
        # Refresh tokens can rotate on use, so re-persist the (possibly new) one.
        self._persist_refresh_token(self._session.refresh_token)

    def _apply_auth_payload(self, payload: dict) -> None:
        self._session.id_token = payload["idToken"]
        self._session.refresh_token = payload["refreshToken"]
        self._session.uid = payload["localId"]

    def sign_out(self) -> None:
        """Clears the current session and forgets the cached login.

        After this, try_resume_session() will return False and is_signed_in
        is False, so the caller (main.py) should route back to the AUTH
        scene. Use this for a "Log Out" / "Switch Account" button -- without
        it there's no way back to the login screen once a device has a
        cached session, since boot always tries to resume silently first.
        """
        self._session = _Session()
        self._clear_persisted_refresh_token()

    # Persists the refresh token across launches so the same anonymous
    # account resumes next time instead of a new one being minted.
    #
    # Desktop (plain `python3 main.py`): a local file works fine.
    #
    # Emscripten (pygbag/browser build): NOT implemented yet. The browser
    # doesn't expose a normal filesystem across reloads, so this currently
    # falls through to "no stored token" and mints a fresh anonymous account
    # every browser session. The fix is to read/write
    # `platform.window.localStorage` (via the same `platform` shim used for
    # networking) instead of a file -- left as a follow-up since it needs an
    # actual browser round trip to verify, and desktop dev doesn't exercise
    # this branch at all.
    def _load_persisted_refresh_token(self) -> str | None:
        if self._http.is_emscripten:
            return None
        try:
            data = json.loads(_DESKTOP_SESSION_FILE.read_text())
            return data.get("refresh_token")
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _persist_refresh_token(self, refresh_token: str) -> None:
        if self._http.is_emscripten:
            return
        try:
            _DESKTOP_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            _DESKTOP_SESSION_FILE.write_text(json.dumps({"refresh_token": refresh_token}))
        except OSError:
            pass

    def _clear_persisted_refresh_token(self) -> None:
        if self._http.is_emscripten:
            return
        try:
            _DESKTOP_SESSION_FILE.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    # -- Firestore ------------------------------------------------------------

    def _doc_url(self, path: str) -> str:
        path = path.strip("/")
        return f"{FIRESTORE_URL}/projects/{self.project_id}/databases/(default)/documents/{path}"

    def _auth_headers(self) -> dict[str, str]:
        if not self._session.id_token:
            raise FirebaseError(0, "Not signed in; call sign_in_anonymously() first")
        return {"Authorization": f"Bearer {self._session.id_token}", "Content-Type": "application/json"}

    async def get_document(self, path: str) -> dict | None:
        """Returns the document's fields as a plain dict, or None if it doesn't exist."""
        status, text = await self._http.request("GET", self._doc_url(path), headers=self._auth_headers())
        if status == 404:
            return None
        payload = self._parse_or_raise(status, text)
        return decode_fields(payload)

    async def list_collection(self, path: str) -> list[dict]:
        """Returns [{"id": doc_id, **fields}, ...] for every document in a collection."""
        status, text = await self._http.request("GET", self._doc_url(path), headers=self._auth_headers())
        payload = self._parse_or_raise(status, text)
        results = []
        for doc in payload.get("documents", []):
            doc_id = doc["name"].rsplit("/", 1)[-1]
            results.append({"id": doc_id, **decode_fields(doc)})
        return results

    async def set_document(self, path: str, data: dict, merge: bool = True) -> None:
        """Creates or overwrites a document at an exact path (e.g. "users/<uid>").

        merge=True only touches the given fields (like client-SDK set(merge=True)).
        merge=False replaces the whole document with exactly these fields.
        """
        url = self._doc_url(path)
        if merge:
            mask = "&".join(f"updateMask.fieldPaths={field_name}" for field_name in data.keys())
            url = f"{url}?{mask}" if mask else url
        status, text = await self._http.request(
            "PATCH", url, headers=self._auth_headers(), body=json.dumps({"fields": encode_fields(data)})
        )
        self._parse_or_raise(status, text)

    async def add_document(self, collection_path: str, data: dict, doc_id: str | None = None) -> str:
        """Creates a new document in a collection. Returns the document id.

        Pass doc_id to choose the id yourself (fails if it already exists);
        omit it to let Firestore generate one (e.g. for users/<uid>/inventory).
        """
        url = self._doc_url(collection_path)
        if doc_id:
            url = f"{url}?documentId={doc_id}"
        status, text = await self._http.request(
            "POST", url, headers=self._auth_headers(), body=json.dumps({"fields": encode_fields(data)})
        )
        payload = self._parse_or_raise(status, text)
        return payload["name"].rsplit("/", 1)[-1]

    async def delete_document(self, path: str) -> None:
        status, text = await self._http.request("DELETE", self._doc_url(path), headers=self._auth_headers())
        if status not in (200, 404):
            raise FirebaseError(status, text)

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _parse_or_raise(status: int, text: str) -> dict:
        if status // 100 != 2:
            raise FirebaseError(status, text)
        return json.loads(text) if text else {}
