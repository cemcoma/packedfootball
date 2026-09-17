"""Account-level rules: unique display names, and deleting an account.

Layered like services.tournament: the rules are pure functions of their
arguments (testable without Firestore), and the functions that write are
thin wrappers that read, call a rule, and write what it says.

    validate_display_name(raw)          pure -- the name a manager may have
    display_name_key(name)              pure -- the id its reservation lives at
    vacate_group(group, desk, uid)      pure -- how a tournament group closes over a leaver
    delete_account(uid)                 the sweep

DISPLAY NAMES are made unique with a reservation collection,
display_names/{key} -> {uid}, written in the same transaction as the name
itself. Firestore has no unique constraint, so the reservation document IS
the constraint: a transaction that reads it, finds someone else's uid and
aborts is what stops two managers from ending up with the same name. This
is also why firestore.rules no longer lets the client write display_name
directly -- a direct write would skip the reservation.

DELETION removes everything that is the account's own: the profile, its
inventory pointers, every players/{id} card it owns, the games it started,
its name reservation, its seat in an unsettled tournament group, and
finally the Firebase Auth user. It deliberately KEEPS iap_transactions
(financial records, keyed by the store's event id, needed to answer a
refund dispute) and games the account only appeared in as the OPPONENT --
those are the other manager's match history, and their results stand.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata

import config

# One or more of: any letter or digit in any script, space, underscore,
# dot, dash. \w is Unicode-aware in Python 3, which is what lets "Çağla"
# through without listing every alphabet.
_DISPLAY_NAME_PATTERN = re.compile(r"^[\w .\-]+$")


class DisplayNameError(ValueError):
    """A name the rules refuse. `.reason` is a short, user-facing code the
    client maps to its own wording: "empty", "too_short", "too_long",
    "characters"."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def validate_display_name(raw: str) -> str:
    """The name as it will be stored, or DisplayNameError.

    Whitespace is trimmed and runs collapsed to one space -- "Cem   T" is
    saved as "Cem T" rather than refused, since the difference is never
    what the manager meant.
    """
    name = " ".join(str(raw or "").split())
    if not name:
        raise DisplayNameError("empty")
    if len(name) < config.DISPLAY_NAME_MIN_LENGTH:
        raise DisplayNameError("too_short")
    if len(name) > config.DISPLAY_NAME_MAX_LENGTH:
        raise DisplayNameError("too_long")
    if not _DISPLAY_NAME_PATTERN.match(name):
        raise DisplayNameError("characters")
    return name


def display_name_key(name: str) -> str:
    """The reservation document id for a name: what two names have to
    share to count as the same.

    Casefolded (so "Cem" and "CEM" collide), NFKC-normalised (so a
    full-width or composed character can't dodge the check), spacing
    collapsed. Spaces are kept -- a Firestore document id only forbids
    "/" and the lone "." / ".." -- and the pattern above already keeps
    slashes out.
    """
    return " ".join(unicodedata.normalize("NFKC", str(name or "")).casefold().split())


def reservation_path(name: str) -> str:
    return f"display_names/{display_name_key(name)}"


# -- tournaments ----------------------------------------------------------------


def vacate_group(group: dict | None, desk: dict | None, uid: str) -> tuple[dict | None, dict | None]:
    """What to write when `uid` leaves `group`: (group fields, desk fields),
    either None when nothing needs writing.

    Only an UNSETTLED group is touched -- a settled one is history, and its
    member list is what the results screen was built from. The leaver comes
    out of member_uids, so settlement (which walks that list) never tries to
    pay a deleted account, and member_count follows.

    The seat they leave is offered to the next joiner ONLY when the tier's
    desk isn't already pointing at an open group. The desk is a single
    pointer: aiming it at this group while another one was half-full would
    strand that one at three members forever, because a full group sends
    the desk to None and the next joiner starts a fresh group rather than
    looking back. When the desk is empty, though, filling the gap is
    strictly better than opening group N+1 for one person.
    """
    if group is None:
        return None, None
    if (group.get("settlement") or {}).get("status") == "settled":
        return None, None
    members = list(group.get("member_uids") or [])
    if uid not in members:
        return None, None
    members = [m for m in members if m != uid]

    group_fields = {"member_uids": members, "member_count": len(members)}
    desk_fields = None
    if (desk or {}).get("open_group_id") is None and len(members) < config.TOURNAMENT_GROUP_CAPACITY:
        desk_fields = {"tier": int(group.get("tier", config.TOURNAMENT_DEFAULT_TIER)), "open_group_id": group.get("group_id")}
    return group_fields, desk_fields


async def leave_tournament(client, uid: str, profile: dict | None) -> bool:
    """Takes `uid` out of the tournament group their profile says they're
    in (today's, or an earlier day's that hasn't settled yet -- settlement
    is what clears these fields), and out of that tier's matchmaking pool.
    One transaction, so a joiner racing for the same seat sees a consistent
    group. Returns whether there was a group to leave."""
    from firebase_admin import firestore  # local, as services.tournament does
    from services import tournament as t

    day_id = (profile or {}).get("tournament_day_id")
    group_id = (profile or {}).get("tournament_group_id")
    if not day_id or not group_id:
        return False

    g_path = t.group_path(day_id, group_id)
    e_path = t.entry_path(day_id, group_id, uid)

    def _leave(tx):
        group = tx.get(g_path)
        tier = int((group or {}).get("tier", config.TOURNAMENT_DEFAULT_TIER))
        dk_path = t.desk_path(day_id, tier)
        p_path = t.pool_path(day_id, tier)
        docs = tx.get_all([dk_path, p_path])

        group_fields, desk_fields = vacate_group(group, docs[dk_path], uid)
        if group_fields is None:
            return False
        tx.set(g_path, group_fields, merge=True)
        if desk_fields is not None:
            tx.set(dk_path, desk_fields, merge=True)
        tx.delete(e_path)
        if docs[p_path] is not None:
            tx.set(p_path, {"uids": firestore.ArrayRemove([uid])}, merge=True)
        return True

    return await client.run_transaction(_leave)


# -- deletion --------------------------------------------------------------------


async def delete_account(client, uid: str) -> dict:
    """Removes everything listed in the module docstring, then the Auth user.

    ORDER MATTERS, and it is "Auth user last": if anything before it fails
    the manager can still sign in and press the button again, and every
    step is a no-op when re-run over what an earlier attempt already
    removed. Deleting the Auth user first would leave orphaned data that
    nobody can ever reach again.

    Returns counts, for the response and for the log.
    """
    from firebase_admin import auth as firebase_auth

    profile = await client.get_document(f"users/{uid}")

    left_group = await leave_tournament(client, uid, profile)

    # Cards: every players/{id} tagged with this owner -- roster, bench,
    # and anything a half-finished earlier operation left pointing nowhere.
    card_ids = await client.query_ids("players", "owner_uid", uid)
    inventory = await client.list_collection(f"users/{uid}/inventory")
    game_ids = await client.query_ids("games", "initiator_uid", uid)

    paths = [f"players/{cid}" for cid in card_ids]
    paths += [f"users/{uid}/inventory/{doc['id']}" for doc in inventory]
    paths += [f"games/{gid}" for gid in game_ids]

    # The name reservation, but only if it is actually this account's:
    # a stale profile could name something someone else has since taken.
    name = (profile or {}).get("display_name")
    if name:
        r_path = reservation_path(name)
        reservation = await client.get_document(r_path)
        if reservation is not None and reservation.get("uid") == uid:
            paths.append(r_path)

    paths.append(f"users/{uid}")
    deleted = await client.delete_paths(paths)

    try:
        await asyncio.to_thread(firebase_auth.delete_user, uid)
        auth_deleted = True
    except firebase_auth.UserNotFoundError:
        auth_deleted = False  # already gone -- a retry after a partial success

    return {
        "cards": len(card_ids),
        "games": len(game_ids),
        "left_group": left_group,
        "documents": deleted,
        "auth_user": auth_deleted,
    }
