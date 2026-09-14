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
"""

from __future__ import annotations

import base64
import hmac
import os
import random
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import firebase_admin
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import auth as firebase_auth
from firebase_admin import firestore
from pydantic import BaseModel

# Local-dev convenience only: fills in os.environ from backend/.env (copy
# .env.example -> .env, gitignored, never touches the deployed service) so
# running `uvicorn main:app` locally doesn't need a dozen `export`s first.
# Never overrides a variable that's already set (dotenv's own default), so
# on Cloud Run -- where secrets arrive via --set-env-vars/--set-secrets and
# no .env file exists in the image at all -- this is a harmless no-op that
# changes nothing.
load_dotenv()

# Make packedfootball/'s modules (gameEngine, packEngine, player.*, game_state)
# importable as top-level names, the same way packedfootball/main.py already
# runs them. Deliberately NOT importing firebase_config here: that file is
# gitignored (it holds the client's public API key, which this server-side
# Admin SDK code doesn't need anyway) and so isn't present in Cloud Build's
# upload -- the project id comes from an env var instead, set at deploy time.
_PACKEDFOOTBALL_DIR = Path(__file__).resolve().parent.parent / "packedfootball"
sys.path.insert(0, str(_PACKEDFOOTBALL_DIR))

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")

from game_state import GameState, player_to_fields
from gameEngine import game
from formations import FORMATIONS, get_formation, is_similar_position
from packEngine import PLAYER_CLASS_MAP, TIER_RANGES, PackManager, generate_starter_roster
from player.classes.midfielder import Midfielder

from admin_firestore_client import AdminFirestoreClient

firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})

STARTER_FORMATION = "4-4-2"
STARTER_TIER = "bronze"

QUICK_MATCH_REWARD_CREDITS = {"loss":10,"draw":25,"win":100}

app = FastAPI(title="Packed Football backend")

#allowed websites to call this backend
ALLOWED_ORIGINS = ["https://cemcoma.github.io"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class _Team:
    def __init__(self, name, players):
        self.name = name
        self.players = players


async def verify_id_token(authorization: str = Header(...)) -> str:
    """Extracts and verifies the caller's Firebase ID token, returns their uid."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception as exc:
        raise HTTPException(401, f"Invalid ID token: {exc}") from exc
    return decoded["uid"]


def _game_state_for(uid: str) -> GameState:
    return GameState(AdminFirestoreClient(uid), PLAYER_CLASS_MAP, Midfielder)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/account/bootstrap")
async def bootstrap_account(uid: str = Depends(verify_id_token)):
    """Ensures uid has a profile document, creating one with a full bronze
    starter roster if this is the account's first time here. Idempotent --
    safe to call on every sign-in (mirrors game_state.py's
    load_or_create_profile, which already does exactly this for the Python
    client, just with an empty default_roster since packedfootball/main.py
    builds its own local starter squad instead of asking the backend for
    one). The Godot client calls this once right after sign-in succeeds
    (see mobile/scripts/GameProfile.gd's load_all()), which never had an
    equivalent local-squad fallback -- without this, a brand new account
    created straight through Godot had no cards and no roster at all.
    """
    state = _game_state_for(uid)
    existing = await state.client.get_document(f"users/{uid}")
    if existing is not None:
        return {"created": False}

    seed = secrets.randbits(63)
    roster = generate_starter_roster(STARTER_FORMATION, STARTER_TIER, seed=seed)
    profile = await state.load_or_create_profile(
        default_roster=roster, default_display_name=uid[:8], default_formation=STARTER_FORMATION
    )
    return {"created": True, "formation": profile["formation"], "roster_size": len(profile["roster"])}


def _pack_unavailable_reason(config: dict) -> Optional[str]:
    """Why this pack can't be opened right now, or None if it can. Shared by
    /pack/open (to reject one) and /pack/list (to filter the catalog down
    to what's actually purchasable) so the two never disagree.

    "max_opens" and "expires_at" are optional Firestore-only fields (see
    packEngine.PACK_DATABASE's own comment) -- absent means unlimited/never
    expires, matching every pack that predates this check.
    """
    if not config.get("active", False):
        return "This pack is not currently available"

    max_opens = config.get("max_opens")
    times_opened = config.get("times_opened", 0)
    if max_opens is not None and times_opened >= max_opens:
        return "This pack has sold out"

    expires_at = config.get("expires_at")
    if expires_at:
        try:
            if datetime.now(timezone.utc) > datetime.fromisoformat(expires_at):
                return "This pack has expired"
        except ValueError:
            pass  # malformed expires_at shouldn't block opening -- fail open, not closed

    return None


def _pack_is_teased(config: dict) -> bool:
    """A pack that's currently unavailable but should still be shown
    (grayed out, tagged with why -- see PackData.tag_text() on the Godot
    side) instead of hidden outright, e.g. a UCL Promo pack previewed
    ahead of its real on-sale date. Opt-in only, via either of two
    Firestore-only fields an admin sets directly on the pack's doc (no
    redeploy): "visible": true, and/or "available_at" (which alone implies
    it -- setting a planned on-sale date is itself a decision to preview
    the pack). Every pack that predates these fields keeps today's
    default: an unavailable pack is hidden, full stop.
    """
    return bool(config.get("visible")) or config.get("available_at") is not None


@app.get("/pack/list")
async def list_packs(uid: str = Depends(verify_id_token)):
    """Every pack worth showing in the shop right now: everything actually
    purchasable, plus any currently-unavailable pack an admin opted into
    still previewing (see _pack_is_teased). This is purely "what to show",
    not the source of truth for "what's allowed" -- /pack/open enforces
    _pack_unavailable_reason independently regardless of what this
    returned, so a teased pack's Buy button being disabled client-side
    isn't the only thing stopping someone from opening it early.
    """
    docs = await AdminFirestoreClient(uid).list_collection("packs")
    packs = []
    for doc in docs:
        unavailable_reason = _pack_unavailable_reason(doc)
        is_available = unavailable_reason is None
        if not is_available and not _pack_is_teased(doc):
            continue  # hidden entirely -- the default for any unavailable pack

        max_opens = doc.get("max_opens")
        times_opened = doc.get("times_opened", 0)
        packs.append(
            {
                "pack_id": int(doc["id"]),
                "name": doc.get("name"),
                "type": doc.get("type", "standard"),
                "description": doc.get("description", ""),
                "price": doc.get("price"),
                "price_currency": doc.get("price_currency", "credits"),
                "cards_per_pack": doc.get("cards_per_pack"),
                "rates": doc.get("rates", {}),
                "pos_rates": doc.get("pos_rates", {}),
                "max_opens": max_opens,
                "times_opened": times_opened,
                "remaining_opens": (max_opens - times_opened) if max_opens is not None else None,
                "expires_at": doc.get("expires_at"),
                "available": is_available,
                "unavailable_reason": unavailable_reason,
                "available_at": doc.get("available_at"),
            }
        )
    packs.sort(key=lambda p: p["pack_id"])
    return {"packs": packs}


# What a pack's "price_currency" is allowed to be -- these are exactly the
# balance fields on users/{uid}, since the check and the deduction both
# index the profile by this name.
PACK_PRICE_CURRENCIES = ("credits", "bucks", "medals")


class OpenPackRequest(BaseModel):
    pack_id: int


@app.post("/pack/open")
async def open_pack(req: OpenPackRequest, uid: str = Depends(verify_id_token)):
    packs_client = AdminFirestoreClient(uid)
    pack_path = f"packs/{req.pack_id}"
    config = await packs_client.get_document(pack_path)
    if config is None:
        raise HTTPException(404, "Unknown pack_id")
    unavailable_reason = _pack_unavailable_reason(config)
    if unavailable_reason is not None:
        raise HTTPException(403, unavailable_reason)

    state = _game_state_for(uid)
    profile = await state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])

    # A pack is priced in exactly ONE currency -- deliberately no joint
    # "5 medals AND 200 credits" pricing, which is what keeps this a single
    # field rather than a cost map. Absent means credits, so every pack that
    # predates this field keeps working untouched (no migration).
    price_currency = config.get("price_currency", "credits")
    if price_currency not in PACK_PRICE_CURRENCIES:
        raise HTTPException(500, f"Pack has unsupported price_currency: {price_currency}")

    price = config["price"]
    if profile[price_currency] < price:
        raise HTTPException(402, f"Not enough {price_currency}")

    seed = secrets.randbits(63)
    cards = PackManager({req.pack_id: config}, seed=seed).open_pack(req.pack_id)

    remaining = profile[price_currency] - price
    await state.update_profile_fields({price_currency: remaining})
    for card in cards:
        await state.add_inventory_card(card)
    await packs_client.set_document(pack_path, {"times_opened": firestore.Increment(1)}, merge=True)

    # Every balance, not just the one spent: the client mirrors all three
    # and shouldn't have to guess which one moved. credits_remaining stays
    # in the response under its original name so nothing that already reads
    # it breaks.
    balances = {currency: profile[currency] for currency in PACK_PRICE_CURRENCIES}
    balances[price_currency] = remaining
    return {
        "seed": seed,
        "credits_remaining": balances["credits"],
        "bucks_remaining": balances["bucks"],
        "medals_remaining": balances["medals"],
        "cards": [
            {**player_to_fields(c), "player_id": c.player_id, "doc_id": getattr(c, "doc_id", None)}
            for c in cards
        ],
    }


CREDIT_EXCHANGE_RATES = {
    "exchange_10": {"bucks_cost": 10, "credits_reward": 1000},
    "exchange_25": {"bucks_cost": 25, "credits_reward": 2600},
    "exchange_100": {"bucks_cost": 100, "credits_reward": 12500},
    "exchange_200": {"bucks_cost": 200, "credits_reward": 30000},
}


@app.get("/currency/exchange/list")
async def list_exchange_rates(uid: str = Depends(verify_id_token)):
    """The Credits Exchange tab's catalog -- fixed, code-defined rates (not
    Firestore-backed like packs/deals, since these aren't meant to be
    admin-editable without a redeploy). Returned rather than hardcoded
    client-side so the client never has to duplicate these numbers.
    """
    return {"rates": [{"tier_id": k, **v} for k, v in CREDIT_EXCHANGE_RATES.items()]}


class RedeemExchangeRequest(BaseModel):
    tier_id: str


@app.post("/currency/exchange/redeem")
async def redeem_exchange(req: RedeemExchangeRequest, uid: str = Depends(verify_id_token)):
    tier = CREDIT_EXCHANGE_RATES.get(req.tier_id)
    if tier is None:
        raise HTTPException(404, "Unknown tier_id")

    state = _game_state_for(uid)
    profile = await state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])
    if profile["bucks"] < tier["bucks_cost"]:
        raise HTTPException(402, "Not enough bucks")

    new_bucks = profile["bucks"] - tier["bucks_cost"]
    new_credits = profile["credits"] + tier["credits_reward"]
    # One combined write (rather than two separate set_bucks/set_credits
    # calls) so a crash mid-redeem can't leave bucks deducted with the
    # credits reward never actually landing.
    await state.update_profile_fields({"bucks": new_bucks, "credits": new_credits})
    return {"bucks_remaining": new_bucks, "credits_remaining": new_credits}


BUCKS_IAP_CATALOG = {
    "bucks_10": {"bucks_amount": 10, "usd_reference_price_cents": 100},
    "bucks_55": {"bucks_amount": 55, "usd_reference_price_cents": 500},
    "bucks_125": {"bucks_amount": 125, "usd_reference_price_cents": 1000},
    "bucks_300": {"bucks_amount": 300, "usd_reference_price_cents": 2000},
}


@app.get("/currency/bucks/list")
async def list_bucks_catalog(uid: str = Depends(verify_id_token)):
    """The Bucks tab's real-money catalog. product_id is what the client
    passes to the platform IAP plugin (App Store today -- see
    mobile/scripts/autoload/IapClient.gd) to start a real purchase.
    usd_reference_price_cents is a display fallback only; once a real IAP
    plugin is wired client-side, prefer StoreKit's own localized price per
    product over this field -- Apple owns actual regional pricing.
    """
    return {"products": [{"product_id": k, **v} for k, v in BUCKS_IAP_CATALOG.items()]}


REVENUECAT_WEBHOOK_SECRET = os.environ.get("REVENUECAT_WEBHOOK_SECRET", "")

# RevenueCat's own "store" values -> this project's existing platform naming
# (iap_transactions records have always used "appstore"/"playstore"/"web";
# keep that convention rather than storing RevenueCat's raw enum values).
REVENUECAT_STORE_TO_PLATFORM = {
    "APP_STORE": "appstore",
    "PLAY_STORE": "playstore",
    "STRIPE": "web",
    "RC_BILLING": "web",
}


async def verify_revenuecat_webhook(authorization: str = Header(default="")) -> None:
    """RevenueCat signs webhook requests with whatever literal string you
    configure as the "Authorization header value" in their dashboard --
    not HMAC-signed, just an exact shared-secret match, so this compares
    the raw header against REVENUECAT_WEBHOOK_SECRET directly (constant-
    time, to not leak the secret's length/contents through timing). Fails
    closed if the env var isn't set at all -- an empty configured secret
    must never make every request "match" by both sides being empty.
    """
    if not REVENUECAT_WEBHOOK_SECRET or not hmac.compare_digest(authorization, REVENUECAT_WEBHOOK_SECRET):
        raise HTTPException(401, "Invalid webhook authorization")


@app.post("/webhooks/revenuecat", dependencies=[Depends(verify_revenuecat_webhook)])
async def revenuecat_webhook(payload: dict):
    """Grants bucks for a real-money purchase RevenueCat has already
    verified with Apple/Google itself -- this is the one endpoint in the
    whole Bucks feature that must never trust the CLIENT, but it fully
    trusts RevenueCat (gated by verify_revenuecat_webhook above) the same
    way /pack/open trusts this server's own RNG. Replaces the earlier
    design where the client sent a raw platform receipt directly here for
    this server to verify against Apple itself -- RevenueCat now owns that
    verification, and calls this independently of whether the client that
    made the purchase is even still running by the time this lands.

    Only handles NON_RENEWING_PURCHASE (RevenueCat's event type for a
    consumable, one-time purchase -- exactly what a bucks top-up is, not a
    subscription). Any other event type is acknowledged with 200 and
    ignored, not rejected -- RevenueCat retries non-2xx responses
    indefinitely, and an event type this endpoint will never care about
    should never end up in an infinite retry loop.

    iap_transactions/{event_id} is the anti-replay guard, same mechanism
    the pre-RevenueCat design already used -- just keyed by RevenueCat's
    own event id instead of a raw Apple transaction id now.
    """
    event = payload.get("event", {})
    if event.get("type") != "NON_RENEWING_PURCHASE":
        return {"status": "ignored", "reason": f"event type {event.get('type')!r} not handled"}

    event_id = event.get("id")
    uid = event.get("app_user_id")
    product_id = event.get("product_id")
    if not event_id or not uid or not product_id:
        raise HTTPException(400, "Missing required event fields")

    product = BUCKS_IAP_CATALOG.get(product_id)
    if product is None:
        # Not one of our bucks products -- ack without granting, don't retry-loop forever.
        return {"status": "ignored", "reason": f"unknown product_id {product_id!r}"}

    txn_client = AdminFirestoreClient(uid)
    txn_path = f"iap_transactions/{event_id}"
    if await txn_client.get_document(txn_path) is not None:
        return {"status": "already_processed"}

    state = _game_state_for(uid)
    profile = await state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])
    new_bucks = profile["bucks"] + product["bucks_amount"]
    await state.set_bucks(new_bucks)
    await txn_client.set_document(
        txn_path,
        {
            "uid": uid,
            "product_id": product_id,
            "platform": REVENUECAT_STORE_TO_PLATFORM.get(event.get("store", ""), event.get("store", "").lower()),
            "bucks_granted": product["bucks_amount"],
            "redeemed_at": datetime.now(timezone.utc).isoformat(),
        },
        merge=False,
    )
    return {"status": "granted", "bucks_remaining": new_bucks}


async def _deal_unavailable_reason(
    config: dict, deals_client: AdminFirestoreClient, deal_id: str, uid: str
) -> Optional[str]:
    """Why this deal can't be redeemed by THIS uid right now, or None if it
    can. Structural copy of _pack_unavailable_reason, but async -- the
    per-account cap (max_redemptions_per_account) genuinely needs a
    Firestore read that packs' global-only cap never needed. Shared by
    /deals/list (so a deal you've personally exhausted shows its tag
    instead of a live Buy button, even while still globally available to
    everyone else) and /deals/redeem (which re-checks server-side
    regardless of what the client showed).
    """
    if not config.get("active", False):
        return "This deal is not currently available"

    max_redemptions = config.get("max_redemptions")
    times_redeemed = config.get("times_redeemed", 0)
    if max_redemptions is not None and times_redeemed >= max_redemptions:
        return "This deal is no longer available"

    expires_at = config.get("expires_at")
    if expires_at:
        try:
            if datetime.now(timezone.utc) > datetime.fromisoformat(expires_at):
                return "This deal has expired"
        except ValueError:
            pass  # malformed expires_at shouldn't block redeeming -- fail open, not closed

    max_per_account = config.get("max_redemptions_per_account")
    if max_per_account is not None:
        account_doc = await deals_client.get_document(f"deals/{deal_id}/redemptions/{uid}")
        account_times = account_doc.get("times_redeemed", 0) if account_doc is not None else 0
        if account_times >= max_per_account:
            return "You've already redeemed this deal"

    return None


def _deal_is_teased(config: dict) -> bool:
    """Same opt-in "show it anyway, grayed out" rule packs use -- see
    _pack_is_teased."""
    return bool(config.get("visible")) or config.get("available_at") is not None


@app.get("/deals/list")
async def list_deals(uid: str = Depends(verify_id_token)):
    deals_client = AdminFirestoreClient(uid)
    docs = await deals_client.list_collection("deals")
    deals = []
    for doc in docs:
        unavailable_reason = await _deal_unavailable_reason(doc, deals_client, doc["id"], uid)
        is_available = unavailable_reason is None
        if not is_available and not _deal_is_teased(doc):
            continue  # hidden entirely -- the default for any unavailable deal

        max_redemptions = doc.get("max_redemptions")
        times_redeemed = doc.get("times_redeemed", 0)
        deals.append(
            {
                "deal_id": doc["id"],
                "name": doc.get("name"),
                "description": doc.get("description", ""),
                "cost_currency": doc.get("cost_currency"),
                "cost_amount": doc.get("cost_amount"),
                "reward_credits": doc.get("reward_credits", 0),
                "reward_bucks": doc.get("reward_bucks", 0),
                "max_redemptions": max_redemptions,
                "times_redeemed": times_redeemed,
                "remaining_redemptions": (max_redemptions - times_redeemed) if max_redemptions is not None else None,
                "expires_at": doc.get("expires_at"),
                "available": is_available,
                "unavailable_reason": unavailable_reason,
                "available_at": doc.get("available_at"),
            }
        )
    return {"deals": deals}


class RedeemDealRequest(BaseModel):
    deal_id: str


@app.post("/deals/redeem")
async def redeem_deal(req: RedeemDealRequest, uid: str = Depends(verify_id_token)):
    deals_client = AdminFirestoreClient(uid)
    deal_path = f"deals/{req.deal_id}"
    config = await deals_client.get_document(deal_path)
    if config is None:
        raise HTTPException(404, "Unknown deal_id")
    unavailable_reason = await _deal_unavailable_reason(config, deals_client, req.deal_id, uid)
    if unavailable_reason is not None:
        raise HTTPException(403, unavailable_reason)

    cost_currency = config.get("cost_currency", "credits")
    if cost_currency not in ("credits", "bucks"):
        raise HTTPException(500, f"Deal has unsupported cost_currency: {cost_currency}")

    state = _game_state_for(uid)
    profile = await state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])
    cost_amount = config.get("cost_amount", 0)
    if profile[cost_currency] < cost_amount:
        raise HTTPException(402, f"Not enough {cost_currency}")

    new_credits = profile["credits"] + config.get("reward_credits", 0)
    new_bucks = profile["bucks"] + config.get("reward_bucks", 0)
    if cost_currency == "credits":
        new_credits -= cost_amount
    else:
        new_bucks -= cost_amount

    await state.update_profile_fields({"credits": new_credits, "bucks": new_bucks})
    await deals_client.set_document(deal_path, {"times_redeemed": firestore.Increment(1)}, merge=True)
    await deals_client.set_document(
        f"{deal_path}/redemptions/{uid}", {"times_redeemed": firestore.Increment(1)}, merge=True
    )
    return {"credits_remaining": new_credits, "bucks_remaining": new_bucks}


PLAYER_LEADERBOARD_STATS = {
    "goals": "statistics.goals",
    "assists": "statistics.assists",
    "matches_played": "statistics.matches_played",
}


@app.get("/leaderboard/players")
async def leaderboard_players(stat: str = "goals", limit: int = 20, uid: str = Depends(verify_id_token)):
    field_path = PLAYER_LEADERBOARD_STATS.get(stat)
    if field_path is None:
        raise HTTPException(400, f"stat must be one of {list(PLAYER_LEADERBOARD_STATS)}")
    limit = max(1, min(limit, 100))

    docs = await AdminFirestoreClient(uid).query_top("players", field_path, limit)
    return {
        "stat": stat,
        "entries": [
            {
                "player_id": d["id"],
                "fname": d.get("fname"),
                "lname": d.get("lname"),
                "position": d.get("position"),
                "tier": d.get("tier"),
                "owner_uid": d.get("owner_uid"),
                "value": d.get("statistics", {}).get(stat, 0),
            }
            for d in docs
        ],
    }


# Only "wins" for now, by design -- the mobile Leaderboard screen's Users
# tab is a deliberately minimal first pass (see mobile/README.md). Shaped
# the same way as PLAYER_LEADERBOARD_STATS/leaderboard_players above (a
# dict of allowed stats, checked the same way) so adding another one later
# (credits, bucks, ...) is just another entry, not new plumbing.
USER_LEADERBOARD_STATS = {
    "wins": "wins",
}


@app.get("/leaderboard/users")
async def leaderboard_users(stat: str = "wins", limit: int = 20, uid: str = Depends(verify_id_token)):
    field_path = USER_LEADERBOARD_STATS.get(stat)
    if field_path is None:
        raise HTTPException(400, f"stat must be one of {list(USER_LEADERBOARD_STATS)}")
    limit = max(1, min(limit, 100))

    docs = await AdminFirestoreClient(uid).query_top("users", field_path, limit)
    return {
        "stat": stat,
        "entries": [
            {
                "uid": d["id"],
                "display_name": d.get("display_name"),
                "value": d.get(stat, 0),
            }
            for d in docs
        ],
    }


def _validate_formation_positions(profile: dict) -> None:
    """Raises 400 if any roster player's card position can't legally fill
    their assigned formation slot -- an exact match, or is_similar_position()
    (see formations.py) at a penalty. The Team scene's own bench picker
    already only ever allows these two cases, so reaching this only means a
    client lied about its roster/formation pairing.

    Called for both sides BEFORE anything about this match gets written to
    Firestore (see /match/simulate) -- a rejected request leaves no trace at
    all: no games/{id} doc created, and this never touches either user's
    own saved roster/formation.
    """
    slots = get_formation(profile["formation"])
    for i, p in enumerate(profile["roster"]):
        role = slots[i]["role"]
        if p.position != role and not is_similar_position(p.position, role):
            raise HTTPException(400, f"Player {i + 1} ({p.position}) cannot play {role} in {profile['formation']}")


def _run_match(caller_profile: dict, opponent_profile: dict, seed: int) -> dict:
    """Runs one simulated match and returns everything both /match/simulate
    and /match/quick need for their HTTP response: the score, the base64
    replay (see packedfootball/replay.py's ReplayRecorder), and every
    player from both sides serialized in the exact index order
    gameEngine.game.all_players uses (caller's 11, then opponent's 11) --
    MatchPlayback.gd needs this to show real names during playback, the
    same way packedfootball/main.py's local test replay ships a matching
    roster sidecar.
    """
    match = game(
        _Team(caller_profile["display_name"], caller_profile["roster"]),
        _Team(opponent_profile["display_name"], opponent_profile["roster"]),
        seed=seed,
        record_replay=True,
        formation_home=caller_profile["formation"],
        formation_away=opponent_profile["formation"],
    )
    match.run_match(max_steps=10800, render=False)  # 90 real-minute match, matching packedfootball/main.py's own loop
    my_score, opp_score = match.scores
    replay_b64 = base64.b64encode(match.replay.encode()).decode()
    roster_fields = [player_to_fields(p) for p in caller_profile["roster"]] + [
        player_to_fields(p) for p in opponent_profile["roster"]
    ]
    return {"score": [my_score, opp_score], "replay": replay_b64, "roster": roster_fields}


def _teams_snapshot(uid: str, caller_profile: dict, opponent_uid: str, opponent_profile: dict) -> dict:
    """The roster/formation snapshot embedded in a games/{id} doc at match
    start -- both players/{id}.attributes and players/{id}.statistics can
    (legitimately, or from tampering) look different by the time anyone
    checks afterwards, so this is the actual record of what was played,
    independent of whatever either account's cards look like now. Shared
    by both /match/simulate and /match/quick so a dispute or bug gets
    investigated against the same shape regardless of which mode it was.
    """
    return {
        "initiator": {
            "uid": uid,
            "display_name": caller_profile["display_name"],
            "formation": caller_profile["formation"],
            "players": [player_to_fields(p) for p in caller_profile["roster"]],
        },
        "opponent": {
            "uid": opponent_uid,
            "display_name": opponent_profile["display_name"],
            "formation": opponent_profile["formation"],
            "players": [player_to_fields(p) for p in opponent_profile["roster"]],
        },
    }


async def _persist_player_stats(caller_state: GameState, caller_profile: dict) -> None:
    """Writes the CALLER's players' updated statistics (goals/assists/
    matches_played) back to their own players/{id} docs after a match.

    _run_match() (just above) mutates these in place during simulation --
    player.py's scored()/assisted()/match_played(), called from
    gameEngine.py's game -- but a Python object mutation isn't a Firestore
    write; without this, /leaderboard/players (which already queries
    players/{id}.statistics.* directly) would only ever see the zeros every
    card starts at. GameState.save_roster() re-persists every field
    (player_to_fields()), not just statistics, but nothing else about a
    player changes mid-match, so that's a no-op for everything except the
    stats that actually did change.

    Deliberately caller-only: the opponent (real or bot) never chose to
    play this specific match -- having a saved account is not agreeing to
    any one match -- so their own players' stats aren't touched here,
    matching how neither endpoint has ever updated the opponent's own
    account-level wins/losses/draws.
    Also sets up cleanly for a future where a player's own match count
    matters for something like a contract -- that should only ever move
    for whoever actually chose to play.
    """
    await caller_state.save_roster(caller_profile["roster"])


def _generate_bot_opponent() -> tuple[str, dict]:
    """A freshly-rolled bot squad -- random formation AND random tier (the
    full TIER_RANGES spread, bronze through icon) so a Quick Match bot can
    plausibly be "the best or worst player" too, not always a bronze
    pushover. Never persisted anywhere; exists only for this one match.
    """
    formation = random.choice(list(FORMATIONS.keys()))
    tier = random.choice(list(TIER_RANGES.keys()))
    roster = generate_starter_roster(formation, tier, seed=secrets.randbits(63))
    bot_uid = f"bot_{secrets.token_hex(6)}"  # never collides with a real Firebase uid's shape
    profile = {"display_name": f"{tier.capitalize()} Bot", "formation": formation, "roster": roster}
    return bot_uid, profile


async def _pick_opponent_profile(uid: str) -> tuple[str, dict]:
    """Picks a random opponent for a Quick Match directly from users/{uid}
    -- any account with a complete (11-player) saved roster is a candidate,
    tried in random order, fetched fresh at match time (no separate
    "opted in" collection to go stale or need republishing). Or, if none
    exists at all (or every candidate's own saved data turns out stale/
    invalid), a freshly-generated bot instead (see _generate_bot_opponent).
    Quick Match should always find *someone* to play, even the very first
    account ever on this deployment, or if every real candidate happens to
    have bad data -- that's their problem to fix, not a reason to block
    this caller's match.

    Returns (opponent_uid, profile); opponent_uid is a "bot_..." sentinel
    (never a real Firebase uid) when a bot was used.
    """
    candidates = await AdminFirestoreClient(uid).list_collection("users")
    candidate_uids = [
        c["id"] for c in candidates if c["id"] != uid and len(c.get("roster_player_ids", [])) == 11
    ]
    random.shuffle(candidate_uids)

    for candidate_uid in candidate_uids:
        state = GameState(AdminFirestoreClient(candidate_uid), PLAYER_CLASS_MAP, Midfielder)
        profile = await state.load_or_create_profile(default_roster=[], default_display_name=candidate_uid[:8])
        print(profile["display_name"])
        if len(profile["roster"]) != 11:
            continue  # roster_player_ids pointed at a players/{id} doc that's since been deleted
        try:
            _validate_formation_positions(profile)
        except HTTPException:
            continue  # this candidate's own saved data is invalid -- try another, or fall back to a bot below
        return candidate_uid, profile

    return _generate_bot_opponent()


@app.post("/match/quick")
async def quick_match(uid: str = Depends(verify_id_token)):
    """Quick Match: always-available, casual match against a randomly
    picked opponent (see _pick_opponent_profile) for a small credit reward
    (see QUICK_MATCH_REWARD_CREDITS). Records wins/losses/draws like
    /match/simulate does.
    """
    caller_state = _game_state_for(uid)
    caller_profile = await caller_state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])
    if len(caller_profile["roster"]) != 11:
        raise HTTPException(400, "Your roster must have exactly 11 players")
    _validate_formation_positions(caller_profile)

    opponent_uid, opponent_profile = await _pick_opponent_profile(uid)
    is_bot = opponent_uid.startswith("bot_")
    seed = secrets.randbits(63)

    # Same "in_progress" -> "finished" two-phase write /match/simulate uses,
    # so a crash mid-simulation leaves an honestly-stuck record rather than
    # none at all. Same "teams" roster/formation snapshot too (see
    # _teams_snapshot) -- lets a bug or suspected tampering get checked
    # afterwards against exactly what was actually played, bot opponents
    # included (opponent_uid is just their "bot_..." sentinel, same as
    # everywhere else that isn't a real Firebase uid).
    games_client = caller_state.client
    game_id = await games_client.add_document(
        "games",
        {
            "status": "in_progress",
            "mode": "quick",
            "participants": [uid, opponent_uid],
            "initiator_uid": uid,
            "opponent_uid": opponent_uid,
            "opponent_is_bot": is_bot,
            "seed": seed,
            "teams": _teams_snapshot(uid, caller_profile, opponent_uid, opponent_profile),
            "created_at": firestore.SERVER_TIMESTAMP,
            "finished_at": None,
            "score": None,
        },
    )

    result = _run_match(caller_profile, opponent_profile, seed)
    my_score, opp_score = result["score"]

    await games_client.set_document(
        f"games/{game_id}",
        {"status": "finished", "finished_at": firestore.SERVER_TIMESTAMP, "score": result["score"]},
        merge=True,
    )

    await _persist_player_stats(caller_state, caller_profile)

    credits_earned = 0

    wins, losses, draws = caller_profile["wins"], caller_profile["losses"], caller_profile["draws"]
    if my_score > opp_score:
        wins += 1
        credits_earned = QUICK_MATCH_REWARD_CREDITS["win"]
    elif my_score == opp_score:
        draws += 1
        credits_earned = QUICK_MATCH_REWARD_CREDITS["draw"]
    else:
        losses += 1
        credits_earned = QUICK_MATCH_REWARD_CREDITS["loss"]
    await caller_state.record_match_result(wins, losses, draws)
    new_credits = caller_profile["credits"] + credits_earned
    await caller_state.set_credits(new_credits)

    return {
        "seed": seed,
        "score": result["score"],
        "opponent_display_name": opponent_profile["display_name"],
        "opponent_is_bot": is_bot,
        "credits_earned": credits_earned,
        "credits_remaining": new_credits,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "game_id": game_id,
        "replay": result["replay"],
        "roster": result["roster"],
    }


class SimulateMatchRequest(BaseModel):
    opponent_uid: str
    seed: Optional[int] = None


@app.post("/match/simulate")
async def simulate_match(req: SimulateMatchRequest, uid: str = Depends(verify_id_token)):
    if req.opponent_uid == uid:
        raise HTTPException(400, "Cannot challenge yourself")

    caller_state = _game_state_for(uid)
    caller_profile = await caller_state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])
    if len(caller_profile["roster"]) != 11:
        raise HTTPException(400, "Your roster must have exactly 11 players")
    _validate_formation_positions(caller_profile)

    # Confirming the uid is a real, existing account first (rather than
    # calling load_or_create_profile on it directly) stops a typo'd/made-up
    # opponent_uid from silently creating a junk profile document below --
    # load_or_create_profile's whole point is creating one for a uid that
    # doesn't have one yet, which is exactly wrong for an opponent that
    # should already exist.
    opponent_doc = await AdminFirestoreClient(req.opponent_uid).get_document(f"users/{req.opponent_uid}")
    if opponent_doc is None:
        raise HTTPException(404, "Unknown opponent")

    opponent_state = GameState(AdminFirestoreClient(req.opponent_uid), PLAYER_CLASS_MAP, Midfielder)
    opponent_profile = await opponent_state.load_or_create_profile(
        default_roster=[], default_display_name=opponent_doc.get("display_name", req.opponent_uid[:8])
    )
    if len(opponent_profile["roster"]) != 11:
        raise HTTPException(400, "Opponent roster must have exactly 11 players")
    _validate_formation_positions(opponent_profile)

    seed = req.seed if req.seed is not None else secrets.randbits(63)

    # Record the game as it starts (status "in_progress"), then flip it to
    # "finished" once the simulation actually completes below -- so a crash
    # mid-simulation would leave an honestly-stuck "in_progress" record
    # rather than no record at all.
    games_client = caller_state.client
    game_doc = {
        "status": "in_progress",
        "participants": [uid, req.opponent_uid],
        "initiator_uid": uid,
        "opponent_uid": req.opponent_uid,
        "seed": seed,
        "teams": _teams_snapshot(uid, caller_profile, req.opponent_uid, opponent_profile),
        "created_at": firestore.SERVER_TIMESTAMP,
        "finished_at": None,
        "score": None,
    }
    game_id = await games_client.add_document("games", game_doc)

    result = _run_match(caller_profile, opponent_profile, seed)
    my_score, opp_score = result["score"]

    await games_client.set_document(
        f"games/{game_id}",
        {"status": "finished", "finished_at": firestore.SERVER_TIMESTAMP, "score": result["score"]},
        merge=True,
    )

    wins, losses, draws = caller_profile["wins"], caller_profile["losses"], caller_profile["draws"]
    if my_score > opp_score:
        wins += 1
    elif my_score == opp_score:
        draws += 1
    else:
        losses += 1

    await caller_state.record_match_result(wins, losses, draws)

    return {
        "seed": seed,
        "score": result["score"],
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "game_id": game_id,
        "replay": result["replay"],
        "roster": result["roster"],
    }
