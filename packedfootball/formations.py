"""
Football Formations Registry -- the helpers over game_config.FORMATIONS.

The formations themselves (and POSITION_GROUPS) live in game_config.py with
the rest of the game's static rules; they are re-exported from here so
``from formations import FORMATIONS`` keeps working.
"""
from game_config import FORMATIONS, POSITION_GROUPS  # noqa: F401 -- re-exported


def get_formation(name: str) -> dict:
    return FORMATIONS.get(name, FORMATIONS["4-4-2"])


def is_similar_position(position_a: str, position_b: str) -> bool:
    """True if position_a can fill a position_b slot at a penalty rather
    than being blocked outright -- i.e. they're different but share at
    least one POSITION_GROUPS entry. False for an exact match (that's not
    "similar", it's just correct) and for any pairing that shares no group
    (e.g. GK/anything, CB/anything, or two positions too far apart like
    CDM and RW).
    """
    if position_a == position_b:
        return False
    return any(position_a in group and position_b in group for group in POSITION_GROUPS)