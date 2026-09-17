"""Everything about actually playing a match, kept out of the endpoints.

The two match endpoints differ only in how they find an opponent and what
they pay out; the simulation, the roster snapshot written to games/{id},
and the stat write-back are identical, and live here so they stay that way.
"""

from __future__ import annotations

import base64
import random
import secrets

from fastapi import HTTPException

from config import BOT_KIT
from admin_firestore_client import AdminFirestoreClient
from engine import (
    FORMATIONS,
    GameState,
    Midfielder,
    PLAYER_CLASS_MAP,
    TIER_RANGES,
    game,
    generate_starter_roster,
    get_formation,
    is_similar_position,
    player_to_fields,
)


class _Team:
    def __init__(self, name, players):
        self.name = name
        self.players = players


def validate_formation_positions(profile: dict) -> None:
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


def run_match(caller_profile: dict, opponent_profile: dict, seed: int) -> dict:
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
    # 10800 frames is REGULATION (90:00); run_match plays stoppage time on
    # top of that, so a real match finishes a few minutes later.
    match.run_match(max_steps=10800, render=False)
    my_score, opp_score = match.scores
    replay_b64 = base64.b64encode(match.replay.encode()).decode()
    roster_fields = [player_to_fields(p) for p in caller_profile["roster"]] + [
        player_to_fields(p) for p in opponent_profile["roster"]
    ]
    return {
        "score": [my_score, opp_score],
        "replay": replay_b64,
        "roster": roster_fields,
        # THIS match's per-player numbers, same index order as "roster".
        # "roster" carries career totals; the post-match screens want what
        # happened in this game.
        "player_match_stats": match.match_summary(),
        # Added time per half, in clock seconds, for the frontend to show as "+x" at the end of each half.
        "added_time": [frames // 2 for frames in match.added_time_frames],
        # Both sides' shirts, [caller, opponent], passed straight through
        # from each profile -- see game_state.load_or_create_profile on why
        # this end never parses them. A bot's comes from BOT_KIT.
        "kits": [caller_profile.get("kit", ""), opponent_profile.get("kit", "")],
        # Both sides' formation names, [caller, opponent], same order as
        # "kits". The client already knows its own; the opponent's is what
        # lets it lay their 11 out on a pitch (roster indices 11-21 are in
        # that formation's slot order -- see gameEngine._combine_formations).
        "formations": [caller_profile["formation"], opponent_profile["formation"]],
    }


def teams_snapshot(uid: str, caller_profile: dict, opponent_uid: str, opponent_profile: dict) -> dict:
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
            # What they actually wore. A manager can change their kit any
            # time, so without this a replayed game would be rendered in
            # whatever shirt they happen to own today, not the one in the
            # screenshot attached to the bug report.
            "kit": caller_profile.get("kit", ""),
            "players": [player_to_fields(p) for p in caller_profile["roster"]],
        },
        "opponent": {
            "uid": opponent_uid,
            "display_name": opponent_profile["display_name"],
            "formation": opponent_profile["formation"],
            "kit": opponent_profile.get("kit", ""),
            "players": [player_to_fields(p) for p in opponent_profile["roster"]],
        },
    }


async def persist_player_stats(caller_state: GameState, caller_profile: dict) -> None:
    """Writes the CALLER's players' updated statistics (goals/assists/
    matches_played) back to their own players/{id} docs after a match.

    run_match() (just above) mutates these in place during simulation --
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


def _generate_bot_opponent(card_tier_pool=None) -> tuple[str, dict]:
    """A freshly-rolled bot squad -- random formation AND random card tier so
    a Quick Match bot can plausibly be "the best or worst player" too, not
    always a bronze pushover. Never persisted anywhere; exists only for this
    one match.

    `card_tier_pool` narrows which card tiers it can roll. Quick Match passes
    nothing and keeps the full TIER_RANGES spread; a tournament passes a
    tier-appropriate pool, because an icon bot in the bronze league is not a
    match, it is a guaranteed loss.
    """
    formation = random.choice(list(FORMATIONS.keys()))
    tier = random.choice(list(card_tier_pool or TIER_RANGES.keys()))
    roster = generate_starter_roster(formation, tier, seed=secrets.randbits(63))
    bot_uid = f"bot_{secrets.token_hex(6)}"  # never collides with a real Firebase uid's shape
    profile = {
        "display_name": f"{tier.capitalize()} Bot",
        "formation": formation,
        "roster": roster,
        "kit": BOT_KIT,
    }
    return bot_uid, profile


async def pick_opponent_profile(uid: str) -> tuple[str, dict]:
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
    return await pick_opponent_from_candidates(uid, candidate_uids)


async def pick_opponent_from_candidates(
    uid: str,
    candidate_uids: list[str],
    *,
    max_attempts: int | None = None,
    card_tier_pool=None,
) -> tuple[str, dict]:
    """The shared "find a playable opponent among these uids" loop.

    TWO STAGES, and the split is the whole point. Hydrating a profile reads
    users/{uid} PLUS all eleven players/{id} documents (see
    game_state._load_players), so validating a candidate the naive way costs
    ~12 reads EACH. Most rejections don't need the roster at all, so the
    cheap checks -- does this account have exactly 11 roster ids, is its
    formation one we know -- run against the user document alone, and only a
    candidate that survives is worth 11 more reads.

        best case   1 + 11 = 12 reads      (first candidate is fine)
        worst case  a few 1-read rejections, then 12

    `validate_formation_positions` genuinely needs each player's position, so
    it stays in the second stage, as does the dangling-player-doc check.

    The user document is read with get_document rather than
    load_or_create_profile, which would CREATE a profile for a uid that
    doesn't have one -- the same trap /match/simulate guards against.

    `max_attempts` bounds the worst case; None means "try them all", which is
    what Quick Match wants since its candidate list is already filtered.
    Falls back to a bot when nobody is playable, so a match always happens.
    """
    candidate_uids = [c for c in candidate_uids if c != uid]
    random.shuffle(candidate_uids)
    if max_attempts is not None:
        candidate_uids = candidate_uids[:max_attempts]

    for candidate_uid in candidate_uids:
        client = AdminFirestoreClient(candidate_uid)

        # Stage one: one read, no roster.
        doc = await client.get_document(f"users/{candidate_uid}")
        if doc is None:
            continue
        if len(doc.get("roster_player_ids") or []) != 11:
            continue
        if doc.get("formation") not in FORMATIONS:
            continue

        # Stage two: now pay for the eleven player documents.
        state = GameState(client, PLAYER_CLASS_MAP, Midfielder)
        profile = await state.load_or_create_profile(
            default_roster=[], default_display_name=doc.get("display_name", candidate_uid[:8])
        )
        if len(profile["roster"]) != 11:
            continue  # roster_player_ids pointed at a players/{id} doc that's since been deleted
        try:
            validate_formation_positions(profile)
        except HTTPException:
            continue  # this candidate's own saved data is invalid -- try another, or fall back to a bot
        return candidate_uid, profile

    return _generate_bot_opponent(card_tier_pool)
