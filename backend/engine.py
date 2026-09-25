"""The one doorway to the packedfootball/ game engine.

packedfootball/ is not a package -- its modules import each other as plain
top-level names (`from gameEngine import ...`), the same way
packedfootball/main.py runs them. That only works if its directory is on
sys.path, so THIS module puts it there and then re-exports everything the
backend uses.

Import engine symbols from here, never straight from `gameEngine` or
`packEngine`: a module that does the latter works only if something else
happened to import this one first, which is the kind of dependency that
holds right up until someone reorders an import or runs a single router on
its own.

Deliberately NOT importing firebase_config: that file is gitignored (it
holds the client's public API key, which the Admin SDK doesn't need) and so
isn't in Cloud Build's upload -- the project id comes from an env var
instead, see config.FIREBASE_PROJECT_ID.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PACKEDFOOTBALL_DIR = Path(__file__).resolve().parent.parent / "packedfootball"
if str(_PACKEDFOOTBALL_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKEDFOOTBALL_DIR))

# game_config.py holds the static rules (pitch, formations, tiers,
# appearance, starting balances) and imports nothing from the package, so
# there is no longer an import cycle to order these around: formations.py
# and player/ read the pitch from game_config, not from gameEngine. Each
# module still re-exports what it used to define, which is why these
# imports read exactly as they did before the move.
#
# ruff: noqa: E402 -- these cannot move above the sys.path lines above.
import items as item_rules
from game_state import GameState, fields_to_player, player_to_fields
from gameEngine import ENGINE_VERSION, game
from formations import FORMATIONS, get_formation, is_similar_position
from replay import FORMAT_VERSION as REPLAY_FORMAT_VERSION
from packEngine import PLAYER_CLASS_MAP, POSITION_CATEGORIES, TIER_RANGES, PackManager, generate_starter_roster, tier_family
from player.classes.midfielder import Midfielder
from player.player import APPEARANCE_OPTION_COUNTS, APPEARANCE_SLOTS, DEFAULT_APPEARANCE

__all__ = [
    "APPEARANCE_OPTION_COUNTS",
    "APPEARANCE_SLOTS",
    "DEFAULT_APPEARANCE",
    "ENGINE_VERSION",
    "FORMATIONS",
    "GameState",
    "Midfielder",
    "PLAYER_CLASS_MAP",
    "POSITION_CATEGORIES",
    "PackManager",
    "REPLAY_FORMAT_VERSION",
    "TIER_RANGES",
    "fields_to_player",
    "game",
    "generate_starter_roster",
    "tier_family",
    "get_formation",
    "item_rules",
    "is_similar_position",
    "player_to_fields",
]
