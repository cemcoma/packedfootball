"""Shared request plumbing: who is calling, and what they get to touch.

Every router depends on this and nothing here depends on a router, which is
what keeps the import graph a tree. It is also where firebase_admin gets
initialised -- at import rather than in main.py, so importing a single
router on its own (a test, a script, `python -c`) works without having to
remember to boot the SDK first.
"""

from __future__ import annotations

import firebase_admin
from fastapi import Header, HTTPException
from firebase_admin import auth as firebase_auth

import config
from admin_firestore_client import AdminFirestoreClient
from engine import GameState, Midfielder, PLAYER_CLASS_MAP

# get_app() raises when nothing is initialised yet; initialize_app() raises
# when something already is. Asking first makes this safe to import twice --
# which matters now that it is not main.py doing it exactly once.
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app(options={"projectId": config.FIREBASE_PROJECT_ID})


async def verify_id_token(authorization: str = Header(...)) -> str:
    """Extracts and verifies the caller's Firebase ID token, returns their uid."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception as exc:
        raise HTTPException(401, f"Invalid ID token: {exc}") from exc
    return decoded["uid"]


def game_state_for(uid: str) -> GameState:
    return GameState(AdminFirestoreClient(uid), PLAYER_CLASS_MAP, Midfielder)


def admin_client(uid: str) -> AdminFirestoreClient:
    """A Firestore handle acting as the Admin SDK, tagged with whose data it
    is about. Not subject to firestore.rules -- see that file's header for
    what the client is allowed to write directly and what has to come
    through here instead.
    """
    return AdminFirestoreClient(uid)
