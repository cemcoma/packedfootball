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

# THE ORDER OF THESE IMPORTS IS LOAD-BEARING. DO NOT SORT THEM.
#
# packedfootball/formations.py and packedfootball/gameEngine.py import each
# other at module level: formations does `from gameEngine import
# PITCH_HEIGHT, PITCH_WIDTH`, and gameEngine does `from formations import
# get_formation, is_similar_position`. Whichever one Python starts loading
# FIRST decides whether that resolves -- gameEngine reaches its formations
# import well after defining its own constants, so formations can finish;
# but formations loaded first reaches gameEngine before gameEngine has
# reached ITS import line, and startup dies with "cannot import name
# 'get_formation' from partially initialized module".
#
# game_state therefore comes first: it pulls in player.player, which pulls
# in gameEngine, so gameEngine is fully loaded before formations is touched.
# This is the order main.py used before this module existed. Alphabetising
# it takes the whole service down at boot -- which is exactly what happened
# when this file was first written with them sorted.
#
# The real fix is to break that cycle in packedfootball/; until someone
# does, this comment is the only thing preventing a tidy-up from breaking
# the deploy.
#
# ruff: noqa: E402 -- these cannot move above the sys.path lines above.
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
    "is_similar_position",
    "player_to_fields",
]
