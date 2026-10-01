"""A manager's tactics: how their side plays, on users/{uid}.tactics.

One map rather than a field per setting, so what comes later (captain,
set-piece takers, crossing instructions) is a new key here and nothing new
in the rules, the loader or the match plumbing. Only "style" exists today --
a key of game_config.TACTICS.

The client writes this map straight to Firestore (like formation and kit),
so every read goes through sanitize_tactics: a missing, unknown or malformed
value falls back to the default rather than reaching the engine.
"""

from game_config import DEFAULT_TACTIC, TACTICS, Tactic


def sanitize_tactics(raw) -> dict:
    """Whatever came back from Firestore, as a well-formed tactics map."""
    style = raw.get("style") if isinstance(raw, dict) else None
    return {"style": style if style in TACTICS else DEFAULT_TACTIC}


def tactic_for(tactics: dict | None) -> Tactic:
    """The engine's knobs for a tactics map; None or anything unknown is the default."""
    return TACTICS[sanitize_tactics(tactics)["style"]]
