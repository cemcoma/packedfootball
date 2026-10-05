"""Card types and art that ship without an app update.

card_types/{tier} is a variant of an existing family with its own range and
card art; pack_art/{sprite_key} is pack art. backend/scripts/upload_art.py
writes both. Cached per instance so Firestore reads don't scale with players.
"""

from __future__ import annotations

import asyncio
import logging
import time

from engine import TIER_RANGES, tier_family

logger = logging.getLogger(__name__)

CACHE_SECONDS = 300
# The shortest gap between reads when /pack/open meets a tier it doesn't know.
FORCED_REFRESH_SECONDS = 10

# New families need client tables (colour, rank, release value), so only variants are remote.
FAMILIES = frozenset(tier_family(t) for t in TIER_RANGES)

_state: dict = {"loaded_at": None, "card_types": {}, "pack_art": {}}
_lock = asyncio.Lock()


def _has_art(doc: dict) -> bool:
    return isinstance(doc.get("url"), str) and isinstance(doc.get("sha256"), str)


def _valid_range(value) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    lo, hi = value
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (lo, hi)) or lo >= hi:
        return None
    return lo, hi


def card_types_from_docs(docs: list[dict]) -> dict[str, dict]:
    """{tier: doc} for the card_types docs that are usable; the rest are logged."""
    out = {}
    for doc in docs:
        tier = doc["id"]
        if tier_family(tier) not in FAMILIES:
            logger.warning("card_types/%s: unknown family %r, skipped", tier, tier_family(tier))
        elif not _has_art(doc):
            logger.warning("card_types/%s: no url/sha256, skipped", tier)
        else:
            out[tier] = doc
    return out


def pack_art_from_docs(docs: list[dict]) -> dict[str, dict]:
    return {doc["id"]: doc for doc in docs if _has_art(doc)}


def merged_ranges(card_types: dict[str, dict]) -> dict[str, tuple[int, int]]:
    """TIER_RANGES plus each remote variant's range. A static tier keeps its own range."""
    ranges = dict(TIER_RANGES)
    for tier, doc in card_types.items():
        if tier in ranges:
            continue
        valid = _valid_range(doc.get("range"))
        if valid is None:
            logger.warning("card_types/%s: bad range %r, not sellable", tier, doc.get("range"))
        else:
            ranges[tier] = valid
    return ranges


def _entry(doc: dict) -> dict:
    entry = {"url": doc["url"], "sha256": doc["sha256"]}
    if isinstance(doc.get("text_color"), str):
        entry["text_color"] = doc["text_color"]
    return entry


def build_manifest(card_types: dict[str, dict], pack_art: dict[str, dict]) -> dict:
    return {
        "cards": {tier: _entry(doc) for tier, doc in card_types.items()},
        "packs": {key: _entry(doc) for key, doc in pack_art.items()},
    }


def pack_tiers(config: dict) -> set[str]:
    """Every tier a pack config can roll: rates, slot_rates and guarantees."""
    tables = [config.get("rates") or {}, *(config.get("slot_rates") or {}).values()]
    tiers = {tier for table in tables for tier, weight in table.items() if weight}
    tiers.update(g["tier"] for g in config.get("guarantees") or [] if g.get("tier"))
    return tiers


async def refresh(client, max_age: float = CACHE_SECONDS) -> None:
    """Re-reads both collections if the cache is older than max_age. A failed
    read keeps the old cache: art must never break a login or a purchase."""
    async with _lock:
        now = time.monotonic()
        if _state["loaded_at"] is not None and now - _state["loaded_at"] < max_age:
            return
        try:
            card_docs, pack_docs = await asyncio.gather(
                client.list_collection("card_types"), client.list_collection("pack_art")
            )
        except Exception:
            logger.exception("remote art refresh failed; keeping the cached copy")
        else:
            _state["card_types"] = card_types_from_docs(card_docs)
            _state["pack_art"] = pack_art_from_docs(pack_docs)
        _state["loaded_at"] = now


def tier_ranges() -> dict[str, tuple[int, int]]:
    return merged_ranges(_state["card_types"])


def manifest() -> dict:
    return build_manifest(_state["card_types"], _state["pack_art"])
