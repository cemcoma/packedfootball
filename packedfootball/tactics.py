"""A manager's tactics: how their side plays, on users/{uid}.tactics.

One map rather than a field per setting, so what comes later (crossing
instructions) is a new key here and nothing new in the rules, the loader or
the match plumbing. "style" is a key of game_config.TACTICS; the captain and
set-piece takers (ROLE_KEYS) are players/{id} ids, absent meaning Auto.

The client writes this map straight to Firestore (like formation and kit),
so every read goes through sanitize_tactics: a missing, unknown or malformed
value falls back to the default rather than reaching the engine.
"""

from game_config import DEFAULT_TACTIC, TACTICS, Tactic

# The stats each taker is judged on: the blends the engine resolves them with
# (_resolve_penalty, free_kick.technique_ability, player._choose_cross_target).
# Mirrored in mobile/scripts/data/Tactics.gd for the ratings the Tactics screen shows.
SET_PIECE_DUTIES: dict[str, dict[str, float]] = {
    "penalty_taker": {"shooting": 0.8, "accuracy": 0.2},
    "corner_taker": {"passing": 0.6, "vision": 0.4},
    "free_kick_taker": {"shooting": 0.7, "accuracy": 0.3},
}
ROLE_KEYS: tuple[str, ...] = ("captain", *SET_PIECE_DUTIES)
MAX_PLAYER_ID_LENGTH = 64


def sanitize_tactics(raw) -> dict:
    """Whatever came back from Firestore, as a well-formed tactics map."""
    raw = raw if isinstance(raw, dict) else {}
    style = raw.get("style")
    clean = {"style": style if style in TACTICS else DEFAULT_TACTIC}
    for key in ROLE_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and 0 < len(value) <= MAX_PLAYER_ID_LENGTH:
            clean[key] = value
    return clean


def tactic_for(tactics: dict | None) -> Tactic:
    """The engine's knobs for a tactics map; None or anything unknown is the default."""
    return TACTICS[sanitize_tactics(tactics)["style"]]


def duty_rating(attrs, duty: str) -> float:
    """How good a player is at one set-piece duty, on the stat scale."""
    return sum(getattr(attrs, stat) * weight for stat, weight in SET_PIECE_DUTIES[duty].items())
