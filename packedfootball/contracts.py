"""Contracts: how many more matches a card may play, and how often it may re-sign.

Stored as `contract` on players/{id}: {"max", "signed", "left"}. A match takes
one from `left` for every starter; a contract item may only be signed once
`left` is 0, and a card that has signed `max` contracts must be revived (a
fresh roll, for bucks) or released.
"""

from __future__ import annotations

import random

from game_config import CONTRACT_FIRST_MATCHES, CONTRACT_MAX_RANGE, tier_family

# Never the pack or match rng, so rolling a contract cannot move any seed.
_rng = random.SystemRandom()


def _max_range(tier: str) -> tuple[int, int]:
    return CONTRACT_MAX_RANGE.get(tier_family(tier), CONTRACT_MAX_RANGE["bronze"])


def fresh(tier: str) -> dict:
    """A new (or revived) card's contract: its first one already signed."""
    return {"max": _rng.randint(*_max_range(tier)), "signed": 1, "left": _rng.randint(*CONTRACT_FIRST_MATCHES)}


def sanitize(raw, tier: str) -> dict:
    """A stored contract, or a fixed generous one for cards saved before contracts existed."""
    if not isinstance(raw, dict):
        return {"max": _max_range(tier)[1], "signed": 1, "left": CONTRACT_FIRST_MATCHES[1]}
    return {
        "max": max(1, int(raw.get("max", 1))),
        "signed": max(0, int(raw.get("signed", 1))),
        "left": max(0, int(raw.get("left", 0))),
    }


def can_sign(contract: dict) -> str | None:
    """Why a contract item cannot be signed onto this card, or None. Mirrored by ItemData.equip_blocker."""
    if contract["left"] > 0:
        return "This player's contract hasn't ended yet"
    if contract["signed"] >= contract["max"]:
        return "No contracts left -- revive or release this player"
    return None


def sign(contract: dict, item: dict) -> dict:
    return {**contract, "signed": contract["signed"] + 1, "left": contract["left"] + int(item.get("v", 0))}


def needs_revive(contract: dict) -> bool:
    return contract["left"] <= 0 and contract["signed"] >= contract["max"]
