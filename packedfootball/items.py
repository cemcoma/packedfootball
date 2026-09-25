"""Equipment: small permanent stat buffs socketed into a card.

An item is a flat bonus to one attribute -- "+4 shooting" -- that only tells
because game_config.stat_ability keeps rising past 100 (see STAT_OVERDRIVE).
A point above 100 is worth about a third of a point below it, so a fully
kitted bronze plays like a better bronze, never like an icon.

WHERE ITEMS LIVE. Nowhere of their own. An equipped item is an entry in the
`items` array on players/{player_id}, which is already read whenever the card
is; an unequipped one is an entry in `item_pool` on users/{uid}, already read
once at /account/bootstrap. Both are a few dozen bytes against a 1 MiB
document limit, so a full club costs ~24 KB and zero extra reads. A separate
items/{id} collection would cost one read per item on every load, for data
that is meaningless away from its owner.

NON-REMOVABLE. Socketing is one-way: replacing an item destroys it, no
refund. That is deliberate and it is the whole economy -- a squad needs ~40
items and would otherwise be done forever, whereas destroy-on-upgrade makes
demand recurring. It also keeps optimal play from degenerating into moving
one good item onto whoever is playing today.

THE BASE CARD IS NEVER TOUCHED. `effective_attributes` returns a new
Attributes; `player.attributes` stays the rolled card. game_state.py is the
one place that applies them, and it writes `base_attributes` back, so
re-saving a loaded card cannot bake a buff in twice.
"""

from __future__ import annotations

import secrets
from dataclasses import asdict

from player.player import Attributes, PHYSICAL_FIELDS, TENDENCY_FIELDS

# Slots are flat at every tier -- an icon is already better, it does not also
# get more room. The extender is the only way past three, it takes a slot
# itself, and one card may hold one, so the most any card ever plays with is
# four stat items.
ITEM_SLOTS_BASE = 3
ITEM_SLOT_EXTENDER_BONUS = 2
SLOT_EXTENDER_STAT = "slots"

# Rarity -> how many points the item is worth. Reuses TIER_RANGES' family
# names, which is the project's one rarity ordering -- colour, sort order and
# the odds disclosure all already go by it (PlayerCard.TIER_COLORS).
ITEM_VALUES = {
    "bronze": 2,
    "silver": 3,
    "gold": 4,
    "platinum": 6,
    "diamond": 8,
    "special": 10,
    "icon": 12,
}

# What the slot extender is worth at each rarity it is sold at. It is not a
# stat buff, so it does not use ITEM_VALUES.
SLOT_EXTENDER_RARITIES = ("icon",)

# The two product lines. A keeper item is wasted on a striker and vice versa,
# so each item is tagged with the line it was made for and can only be
# socketed into a card of that kind. Two lines over overlapping stats is a
# cheap way to double the SKU count without inventing new effects.
KIND_OUTFIELD = "outfield"
KIND_KEEPER = "keeper"
KIND_ANY = "any"

# Every skill attribute is sellable: the overdrive tail means all of them now
# tell above 100. Tendencies (how often a card shoots) and height are not
# skills and are left out, exactly as packEngine leaves them out of a tier
# roll.
OUTFIELD_STATS = (
    "speed", "agility", "stamina", "power",
    "passing", "accuracy", "vision", "ballcontrol",
    "dribbling", "shooting", "heading", "defending", "tackling",
)

# Keeper-line stats: shot-stopping (agility/vision/ballcontrol drive
# _save_chance), distribution, and enough pace to sweep.
KEEPER_STATS = (
    "agility", "vision", "ballcontrol",
    "passing", "power", "accuracy", "speed",
)

BUFFABLE_STATS = frozenset(
    f
    for f in Attributes.__dataclass_fields__
    if f not in TENDENCY_FIELDS and f not in PHYSICAL_FIELDS
)


def stats_for_kind(kind: str) -> tuple:
    return KEEPER_STATS if kind == KIND_KEEPER else OUTFIELD_STATS


def new_item_id() -> str:
    """Items are array entries, not documents, so they carry their own id --
    it is what an equip request names."""
    return secrets.token_hex(8)


def make_item(rarity: str, stat: str, kind: str = KIND_OUTFIELD, item_id: str | None = None) -> dict:
    """One item record. Short keys because these are stored inline on a
    document that is read on every card load."""
    if stat == SLOT_EXTENDER_STAT:
        value = ITEM_SLOT_EXTENDER_BONUS
    else:
        value = ITEM_VALUES.get(rarity, ITEM_VALUES["bronze"])
    return {
        "id": item_id or new_item_id(),
        "r": rarity,
        "s": stat,
        "v": value,
        "k": kind,
    }


def is_slot_extender(item: dict) -> bool:
    return item.get("s") == SLOT_EXTENDER_STAT


def capacity(items: list[dict] | None) -> int:
    """How many entries this card's `items` array may hold. The extender
    raises it by two AND occupies one of them, hence four stat items."""
    if items and any(is_slot_extender(i) for i in items):
        return ITEM_SLOTS_BASE + ITEM_SLOT_EXTENDER_BONUS
    return ITEM_SLOTS_BASE


def kind_for_position(position: str) -> str:
    return KIND_KEEPER if position == "GK" else KIND_OUTFIELD


def fits(item: dict, position: str) -> bool:
    kind = item.get("k", KIND_OUTFIELD)
    return kind == KIND_ANY or kind == kind_for_position(position)


def can_equip(items: list[dict] | None, item: dict, position: str) -> str | None:
    """Why this item cannot go on this card, or None if it can. One function
    so the backend's rejection and the client's disabled button agree."""
    items = list(items or [])
    if not fits(item, position):
        return "That item is not for this position"
    if is_slot_extender(item):
        if any(is_slot_extender(i) for i in items):
            return "This card already has a slot extender"
        return None
    # One per stat. Three speed items on every man was measured at W14-D5-L1
    # against the same XI unkitted, where three MIXED ones are W10-D4-L6 --
    # stacking a single stat, pace above all, is what breaks the ladder, not
    # the size of the buffs. This also makes a kit a set of decisions rather
    # than "put pace on everything".
    if any(i.get("s") == item.get("s") for i in items):
        return "This card already has an item for that stat"
    if len(items) >= capacity(items):
        return "This card has no free item slots"
    return None


def effective_attributes(attributes: Attributes, items: list[dict] | None) -> Attributes:
    """`attributes` plus every item's buff, as a NEW Attributes.

    The caller's object is not touched: overall(), the squad optimiser and
    every save path read the base card, and a mutated one would be written
    back as though the buff were rolled.

    Attributes.__post_init__ clamps to STAT_CEILING, so the cap is enforced
    here for free -- the same gate generation and Firestore already pass
    through.
    """
    if not items:
        return attributes
    values = asdict(attributes)
    for item in items:
        stat = item.get("s")
        if stat not in BUFFABLE_STATS:
            continue  # the slot extender, or a stat this build no longer has
        values[stat] = values.get(stat, 0) + int(item.get("v", 0))
    return Attributes(**values)


def sanitize_pool(items) -> list[dict]:
    """The unequipped pool on users/{uid}: same shape checks as sanitize, but
    no slot limit -- the pool is a bag, not a card."""
    if not isinstance(items, list):
        return []
    clean = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        stat = entry.get("s")
        if stat != SLOT_EXTENDER_STAT and stat not in BUFFABLE_STATS:
            continue
        clean.append(
            {
                "id": str(entry.get("id") or new_item_id()),
                "r": str(entry.get("r", "bronze")),
                "s": str(stat),
                "v": int(entry.get("v", 0)),
                "k": str(entry.get("k", KIND_OUTFIELD)),
            }
        )
    return clean


def sanitize(items, position: str | None = None) -> list[dict]:
    """Whatever came back from Firestore, as a list of well-formed items.

    Anything unrecognised is dropped rather than raised on: these arrays are
    written by a backend that will gain item types this build has never heard
    of, and a card that fails to load is worse than a card missing a buff.
    """
    if not isinstance(items, list):
        return []
    extenders, buffs = [], []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        stat = entry.get("s")
        if stat != SLOT_EXTENDER_STAT and stat not in BUFFABLE_STATS:
            continue
        if position is not None and not fits(entry, position):
            continue
        clean = {
            "id": str(entry.get("id") or new_item_id()),
            "r": str(entry.get("r", "bronze")),
            "s": str(stat),
            "v": int(entry.get("v", 0)),
            "k": str(entry.get("k", KIND_OUTFIELD)),
        }
        if stat == SLOT_EXTENDER_STAT:
            extenders.append(clean)
        elif not any(b["s"] == stat for b in buffs):
            buffs.append(clean)  # one per stat, same rule can_equip applies
    # Trimmed rather than trusted: a doc holding more than the slots allow --
    # a bug, or an edited write -- would otherwise buff a card past anything a
    # legal equip could reach.
    extenders = extenders[:1]
    room = ITEM_SLOTS_BASE + (ITEM_SLOT_EXTENDER_BONUS - 1 if extenders else 0)
    return extenders + buffs[:room]
