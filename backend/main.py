"""Authoritative game backend: the Cloud Run service that closes the
CLIENT-TRUSTED gap firestore.rules and game_state.py's own module
docstring call out -- nothing stops a client from lying about its own
state over a bare ID-token-authenticated Firestore write.

Pack opening and match results happen here instead, using a
server-generated seed and the *same* gameEngine/packEngine code any client
would otherwise run locally -- so a client can no longer just tell the
server it won, or that it opened five icon cards. It reads/writes
Firestore with the Admin SDK (AdminFirestoreClient), which is not subject
to firestore.rules, instead of the user's own ID token.

This file is only the assembly: it builds the app, opens it to the allowed
origins, and mounts each router. Nothing to change here to change the game.

    config.py      every tunable -- prices, payouts, caps, catalogs
    engine.py      the one doorway to packedfootball/'s simulation code
    deps.py        who is calling (verify_id_token) and what they can touch
    routers/       one module per area of the API; URLs are written in full
    services/      the work an endpoint delegates to (match simulation)

Routers are mounted with no prefix -- each decorator carries its whole URL,
so a path can be found by grepping for the path.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import ALLOWED_ORIGINS
from routers import (
    account,
    claims,
    currency,
    deals,
    energy,
    leaderboard,
    managers,
    matches,
    packs,
    players,
    tournaments,
    ads
)

app = FastAPI(title="Packed Football backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

for _router in (
    account.router,
    packs.router,
    players.router,
    currency.router,
    energy.router,
    deals.router,
    leaderboard.router,
    managers.router,
    matches.router,
    tournaments.router,
    ads.router,
    claims.router,
):
    app.include_router(_router)
