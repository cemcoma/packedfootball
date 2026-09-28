"""Minigames: self-contained modes that are not a full match simulation.

Re-exported here so callers say `from minigames import PenaltyShootout`
rather than naming the module inside -- backend/engine.py already does.
"""

from .minigamesEngine import (
    MINIGAMES_ENGINE_VERSION,
    PenaltyShootout,
    best_taker_order,
    penalty_score,
    run_shootout,
)

__all__ = [
    "MINIGAMES_ENGINE_VERSION",
    "PenaltyShootout",
    "best_taker_order",
    "penalty_score",
    "run_shootout",
]
