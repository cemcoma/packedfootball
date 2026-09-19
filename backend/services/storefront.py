"""How the shop orders what it sells.

Two levels: the pack TYPE's order, which lives in Firestore as
pack_types/{type}.order (seeded from pack_database.PACK_TYPES, then owned
by the console), and within a type the pack's own `order` from its doc,
then its id. GET /pack/list reads pack_types/ fresh on every call --
deliberately not cached, the shop is where the money is and a stale order
is worse than four extra reads -- and returns the resulting category list
as `sections`, which the client's dropdown follows verbatim.

A type with no pack_types doc is not hidden: it sorts after every ordered
type (UNORDERED) so a pack of a brand-new type still appears the moment it
is active, and seed_packs.py points out the missing doc.

Extension point: per-player visibility. When pack_types docs grow rules
(min_wins, min_tier, vip...), a `visible_types(type_docs, profile)` here is
where they are applied, and /pack/list drops both the section and its
packs for that caller -- the client keeps knowing nothing about the rules.

Also home to parse_time, the one reading of a pack's or deal's expires_at /
available_at, so the two catalogs can never disagree on what a date means.

Pure functions, no Firestore or FastAPI: callable from a script or a REPL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

UNORDERED = float("inf")


def type_orders(type_docs: list[dict]) -> dict[str, float]:
    """{type: order} from the pack_types/ docs as list_collection returns
    them (each carries its id). A doc without a usable numeric order counts
    as unordered rather than as 0, so a half-filled doc can't jump the
    queue."""
    orders: dict[str, float] = {}
    for doc in type_docs:
        order = doc.get("order")
        orders[doc["id"]] = float(order) if isinstance(order, (int, float)) and not isinstance(order, bool) else UNORDERED
    return orders


def shop_sort_key(pack: dict, orders: dict[str, float]) -> tuple:
    """Sort key for one /pack/list entry: its type's order, then its own
    order (0 when the doc has none), then its id -- so two packs never tie
    into an arbitrary order."""
    own = pack.get("order")
    own = float(own) if isinstance(own, (int, float)) and not isinstance(own, bool) else 0.0
    return (orders.get(pack.get("type", ""), UNORDERED), own, str(pack.get("pack_id", "")))


def sections(packs_sorted: list[dict], orders: dict[str, float]) -> list[dict]:
    """The categories to show, in order: one entry per type present among
    the (already sorted) packs, in first-appearance order -- which, because
    the packs are sorted by type order, is the type order with any
    unordered types last. Each entry echoes the type's order (None when it
    has no doc) so a client can tell the two apart if it ever wants to."""
    seen: list[str] = []
    for pack in packs_sorted:
        pack_type = pack.get("type", "")
        if pack_type not in seen:
            seen.append(pack_type)
    return [
        {"type": t, "order": None if orders.get(t, UNORDERED) == UNORDERED else orders[t]}
        for t in seen
    ]


def parse_time(value) -> Optional[datetime]:
    """An expires_at / available_at as an aware datetime, or None when
    absent or malformed. Firestore hands back a datetime for a timestamp
    field and a string for one written as ISO text; both are accepted, and
    a naive value is taken as UTC. Malformed fails OPEN (None), so a typo
    in an admin-set field never blocks a purchase."""
    if not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
