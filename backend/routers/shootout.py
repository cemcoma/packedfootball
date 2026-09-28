"""The daily penalty shootout: one a day, kick by kick.

Unlike /match/*, the player makes the decisions, so this is a session rather
than one call: /start opens it, /kick resolves one penalty at a time, and the
last kick settles and pays. It costs NO energy -- it is a login bonus, not a
match.

The server keeps no engine state. A session stores its seed and the input
log (one map per kick -- see services.minigames.encode_input) given so far,
and every /kick rebuilds the shootout from scratch and replays that log; the
engine is deterministic, so the twelfth kick of a replayed shootout is the
twelfth kick of the original. That is also what keeps it
honest: the bot's corners are rolled from a seed the client never sees while
the shootout is live, so there is nothing to read ahead.

The rules -- the streak, the prestige ramp, what a day pays -- are all in
services/minigames.py, which has no Firestore and no FastAPI in it and is
unit-tested directly. This file is only the HTTP shape.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import admin_client, game_state_for, verify_id_token
from engine import PenaltyShootout
from formations import FORMATIONS
from packEngine import generate_starter_roster
from services import minigames as minigames_service
from services.match import BOT_KIT, _Team, bot_profile_from_doc, validate_formation_positions

router = APIRouter(tags=["shootout"])


class StartRequest(BaseModel):
    # Squad indexes, first kick to last, every player once. Optional so an
    # older client still starts -- the engine then orders best-first.
    takers: list[int] | None = None


class KickRequest(BaseModel):
    kick: int
    aim: int | None = None
    dive: int | None = None


def _today_session(live: dict | None, today: str) -> dict | None:
    """The session doc only if it belongs to today.

    Guarded by the date because a stale session outlives its day: its
    `attempt` would otherwise be counted against today's allowance, and its
    "live" status would resume yesterday's shootout.
    """
    return live if live and live.get("game_date") == today else None


def _attempts_used(live: dict | None, state: dict) -> int:
    """How many of today's attempts are gone. Defaults to 1 when the streak
    says today was played but the session is missing -- losing the doc must
    not hand out a free extra go."""
    if not state["played_today"]:
        return 0
    return int((_today_session(live, state["today"]) or {}).get("attempt", 1))


def _coin_toss(seed: int) -> bool:
    """Who takes the first kick, derived from the seed so a replayed session
    never needs it stored."""
    return bool(seed & 1)


async def _load_player(uid: str) -> dict:
    state = game_state_for(uid)
    profile = await state.load_or_create_profile(default_roster=[], default_display_name=uid[:8])
    if len(profile["roster"]) != 11:
        raise HTTPException(400, "Your roster must have exactly 11 players")
    validate_formation_positions(profile)
    return profile


async def _load_bot(client, day: int, prestige: int, seed: int) -> tuple[str, dict]:
    """The day's named bot, or a generated stand-in.

    The grid is seeded by scripts/seed_bots.py. Before that has run there is
    no bot to meet, so rather than close the feature the cell falls back to a
    squad rolled from this shootout's own seed -- reproducible like everything
    else here, and visibly not a real manager.
    """
    pool = await client.get_document(minigames_service.bot_pool_path(day))
    bot_id = minigames_service.bot_id_from_pool(pool, prestige)
    if bot_id:
        doc = await client.get_document(f"bots/{bot_id}")
        profile = bot_profile_from_doc(bot_id, doc) if doc else None
        if profile:
            return bot_id, profile

    rates = minigames_service.bot_rates(day, prestige)
    formation = sorted(FORMATIONS)[seed % len(FORMATIONS)]
    return f"unseeded_day_{day}", {
        "display_name": f"Day {day} Bot",
        "formation": formation,
        "roster": generate_starter_roster(formation, seed=seed, tier_rates=rates),
        "kit": BOT_KIT,
    }


def _replay(player_profile: dict, bot_profile: dict, session: dict) -> PenaltyShootout:
    """The session's shootout, rebuilt and wound forward through its inputs."""
    shootout = PenaltyShootout(
        _Team(player_profile["display_name"], player_profile["roster"]),
        _Team(bot_profile["display_name"], bot_profile["roster"]),
        seed=session["seed"],
        team_a_starts=_coin_toss(session["seed"]),
        # The order the player picked; a session from before the picker has
        # none, and replays best-first exactly as it was played.
        team_a_takers=session.get("takers") or None,
    )
    for aim, dive in minigames_service.decode_inputs(session):
        shootout.take_kick(aim=aim, dive=dive)
    return shootout


def _appearance(shootout: PenaltyShootout, team: int, idx: int) -> dict:
    """A player's look. The screen plays the taker's own goal celebration,
    the one he does in a match, so it needs his `celebration` slot."""
    return dict(getattr(shootout.teams[team].players[idx], "appearance", None) or {})


def _with_appearance(shootout: PenaltyShootout, entry: dict) -> dict:
    """`entry` (a kick or `upcoming`) plus its taker's look -- a copy, so the
    engine's own history is left as the engine wrote it."""
    if not entry:
        return entry
    return {**entry, "taker_appearance": _appearance(shootout, entry["team"], entry["taker_idx"])}


def _view(shootout: PenaltyShootout, session: dict, finished: bool) -> dict:
    """What the client is allowed to see. The seed is held back until the
    shootout is over -- it reproduces every corner the bot has left."""
    view = {
        "attempt": session.get("attempt", 1),
        # Both shirts, caller's first, the way a match response carries them --
        # the shootout draws real figures, so it needs real kits.
        "kits": session.get("kits", []),
        "day": session.get("day"),
        "prestige": session.get("prestige"),
        "bot_name": session.get("bot_name", ""),
        "bot_tier": session.get("bot_tier", ""),
        # Both sides, caller first, for the scoreboard.
        "names": session.get("names", []),
        "score": list(shootout.scores),
        "kicks_taken": list(shootout.kicks_taken),
        "kicks": shootout.history,
        # Who is about to kick, so the screen can name them before the first
        # one has happened -- history is empty at that point.
        "upcoming": _with_appearance(shootout, shootout.upcoming()),
        "you_start": _coin_toss(session["seed"]),
        "finished": finished,
        # "kick" is your own corner, "keep" is a guess at the bot's.
        "next": None if finished else ("kick" if shootout.current_turn == 0 else "keep"),
        "kick_index": len(shootout.history),
    }
    if finished:
        view["seed"] = session["seed"]
        view["winner"] = shootout.winner
        view["won"] = shootout.winner == 0
    return view


@router.get("/shootout/daily")
async def get_daily_shootout(uid: str = Depends(verify_id_token)):
    """Where the streak stands and what today would pay.

    A plain READ: the day rollover is derived, never persisted here, so
    opening the screen costs no write (same posture as GET /energy).
    """
    client = admin_client(uid)
    profile = await client.get_document(f"users/{uid}")
    state = minigames_service.state_from_doc(
        await client.get_document(minigames_service.state_path(uid))
    )
    live = await client.get_document(minigames_service.session_path(uid))

    today_session = _today_session(live, state["today"]) or {}
    allowed = minigames_service.attempts_allowed(profile)
    attempts_used = _attempts_used(live, state)
    in_progress = today_session.get("status") == "live"
    settled = state["played_today"] and today_session.get("status") == "finished"

    return {
        **state,
        "attempts_used": attempts_used,
        "attempts_allowed": allowed,
        "can_play": in_progress or attempts_used < allowed,
        "in_progress": in_progress,
        "retry_track": minigames_service.RETRY_TRACK,
        "retry_available": settled and minigames_service.can_buy_retry(
            bool(today_session.get("won", False)), attempts_used, allowed
        ),
    }


@router.get("/shootout/daily/takers")
async def get_shootout_takers(uid: str = Depends(verify_id_token)):
    """Your XI for the pre-match picker: each player's penalty score and the
    best-first order Auto-select fills with. Indexes are squad slots, the
    same ones /start takes back."""
    player = await _load_player(uid)
    return minigames_service.picker_squad(player["roster"])


@router.post("/shootout/daily/start")
async def start_daily_shootout(
    req: StartRequest | None = None, uid: str = Depends(verify_id_token)
):
    """Open today's shootout, or hand back the one already in progress.

    Idempotent while a session is live, so a reconnecting client resumes
    rather than starting a second shootout on the same attempt -- and the
    order sent is ignored then, because the live one's is already locked in.
    """
    client = admin_client(uid)
    player = await _load_player(uid)

    profile = await client.get_document(f"users/{uid}")
    state = minigames_service.state_from_doc(
        await client.get_document(minigames_service.state_path(uid))
    )
    live = await client.get_document(minigames_service.session_path(uid))

    today_session = _today_session(live, state["today"])
    if today_session and today_session.get("status") == "live":
        _, bot = await _load_bot(
            client, today_session["day"], today_session["prestige"], today_session["seed"]
        )
        return _view(_replay(player, bot, today_session), today_session, finished=False)

    attempts_used = _attempts_used(live, state)
    if attempts_used >= minigames_service.attempts_allowed(profile):
        raise HTTPException(
            409,
            "Today's shootout is done -- watch an ad to try again, or come back tomorrow.",
        )

    try:
        takers = minigames_service.taker_order(
            req.takers if req else None, len(player["roster"])
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    seed = secrets.randbits(63)
    day, prestige = state["day"], state["prestige"]
    bot_id, bot = await _load_bot(client, day, prestige, seed)
    session = {
        "game_date": state["today"],
        "attempt": attempts_used + 1,
        "seed": seed,
        "bot_id": bot_id,
        "bot_name": bot["display_name"],
        "kits": [player.get("kit") or "", bot.get("kit") or ""],
        # The caller's name is left EMPTY rather than "You" when a profile
        # somehow has none: the client says what to call a nameless player,
        # in the player's own language.
        "names": [player.get("display_name") or "", bot["display_name"]],
        "bot_tier": minigames_service.bot_tier_for_day(day),
        "day": day,
        "prestige": prestige,
        "inputs": [],
        "status": "live",
    }
    if takers is not None:
        # A flat list of ints -- Firestore only refuses arrays INSIDE arrays.
        session["takers"] = takers
    await client.set_document(minigames_service.session_path(uid), session, merge=False)
    return _view(_replay(player, bot, session), session, finished=False)


@router.post("/shootout/daily/kick")
async def take_daily_kick(req: KickRequest, uid: str = Depends(verify_id_token)):
    """One penalty.

    Send `aim` when it is your kick and `dive` when it is the bot's; the other
    side's choice is rolled from the seed. Sending the wrong one is refused
    rather than quietly honoured -- picking the keeper's dive on your own kick
    would be picking whether you score.
    """
    client = admin_client(uid)
    player = await _load_player(uid)
    session = await client.get_document(minigames_service.session_path(uid))
    if not session or session.get("status") != "live":
        raise HTTPException(409, "No shootout in progress")

    _, bot = await _load_bot(client, session["day"], session["prestige"], session["seed"])
    shootout = _replay(player, bot, session)

    if req.kick != len(shootout.history):
        raise HTTPException(409, f"Out of step: the next kick is {len(shootout.history)}")

    my_kick = shootout.current_turn == 0
    if my_kick and req.dive is not None:
        raise HTTPException(400, "It is your kick -- send `aim`, not `dive`")
    if not my_kick and req.aim is not None:
        raise HTTPException(400, "The bot is kicking -- send `dive`, not `aim`")

    try:
        kick = shootout.take_kick(aim=req.aim, dive=req.dive)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    kick = _with_appearance(shootout, kick)

    inputs = list(session.get("inputs") or [])
    inputs.append(minigames_service.encode_input(req.aim, req.dive))
    session["inputs"] = inputs

    finished = shootout.is_finished
    if not finished:
        await client.set_document(
            minigames_service.session_path(uid), {"inputs": inputs}, merge=True
        )
        return {"kick": kick, **_view(shootout, session, finished=False)}

    await client.set_document(
        minigames_service.session_path(uid),
        {"inputs": inputs, "result": shootout.result()},
        merge=True,
    )
    won = shootout.winner == 0
    paid = await client.run_transaction(
        lambda tx: minigames_service.settle_in_tx(tx, uid, won)
    )
    view = _view(shootout, session, finished=True)
    return {
        "kick": kick,
        **view,
        "rewards": paid["rewards"],
        "prestiged": paid["prestiged"],
        "prestige": paid["prestige"],
        # The end screen's ad button: the same rule GET /shootout/daily uses.
        "retry_available": minigames_service.can_buy_retry(
            won, int(session.get("attempt", 1)), paid["attempts_allowed"]
        ),
        **{f"{currency}_remaining": amount for currency, amount in paid["balances"].items()},
    }
