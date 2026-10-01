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

from config import BOT_KIT, QUICK_MATCH_CANDIDATES, TOURNAMENT_TIERS
from admin_firestore_client import AdminFirestoreClient
from engine import (
    FORMATIONS,
    GameState,
    Midfielder,
    PLAYER_CLASS_MAP,
    TIER_RANGES,
    fields_to_player,
    game,
    generate_starter_roster,
    get_formation,
    is_similar_position,
    player_to_fields,
    sanitize_tactics,
    TACTICS,
)
from services.tournament import bot_pool_path

# Stored bots (bots/{id}, see scripts/seed_bots.py) share the "bot_" uid
# prefix with the throwaway ones _generate_bot_opponent rolls, so every
# "is this a bot" check downstream (no record, no uid in the response, no
# stats persisted) already treats them right. The prefix is what tells the
# candidate loop to read bots/ instead of users/.
BOT_UID_PREFIX = "bot_"


def bot_profile_from_doc(bot_id: str, doc: dict) -> dict | None:
    """A bots/{id} doc as the profile shape run_match takes, or None when
    the doc can't field a legal XI. Unlike a user, a bot's eleven are
    embedded on its own doc rather than pointers into players/ -- one read
    instead of twelve, and no bot cards on the leaderboards."""
    fields_list = doc.get("players") or []
    if len(fields_list) != 11 or doc.get("formation") not in FORMATIONS:
        return None
    try:
        roster = [fields_to_player(f, PLAYER_CLASS_MAP, Midfielder) for f in fields_list]
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "display_name": doc.get("display_name") or bot_id[:12],
        "formation": doc["formation"],
        "roster": roster,
        "kit": doc.get("kit") or BOT_KIT,
        "tactics": sanitize_tactics(doc.get("tactics")),
        "wins": doc.get("wins", 0),
        "draws": doc.get("draws", 0),
        "losses": doc.get("losses", 0),
    }


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
    Firestore -- a rejected request leaves no trace at
    all: no games/{id} doc created, and this never touches either user's
    own saved roster/formation.
    """
    slots = get_formation(profile["formation"])
    for i, p in enumerate(profile["roster"]):
        role = slots[i]["role"]
        if p.position != role and not is_similar_position(p.position, role):
            raise HTTPException(400, f"Player {i + 1} ({p.position}) cannot play {role} in {profile['formation']}")


def run_match(caller_profile: dict, opponent_profile: dict, seed: int) -> dict:
    """Runs one simulated match and returns everything the match endpoints
    need for their HTTP response: the score, the base64
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
        tactics_home=caller_profile.get("tactics"),
        tactics_away=opponent_profile.get("tactics"),
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
        # Both sides' tactics maps, same order -- View Opponent and the result screen show the style.
        "tactics": [sanitize_tactics(caller_profile.get("tactics")), sanitize_tactics(opponent_profile.get("tactics"))],
    }


def teams_snapshot(uid: str, caller_profile: dict, opponent_uid: str, opponent_profile: dict) -> dict:
    """The roster/formation snapshot embedded in a games/{id} doc at match
    start -- both players/{id}.attributes and players/{id}.statistics can
    (legitimately, or from tampering) look different by the time anyone
    checks afterwards, so this is the actual record of what was played,
    independent of whatever either account's cards look like now. Shared
    by every match mode so a dispute or bug gets
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
            "tactics": sanitize_tactics(caller_profile.get("tactics")),
            "players": [player_to_fields(p) for p in caller_profile["roster"]],
        },
        "opponent": {
            "uid": opponent_uid,
            "display_name": opponent_profile["display_name"],
            "formation": opponent_profile["formation"],
            "kit": opponent_profile.get("kit", ""),
            "tactics": sanitize_tactics(opponent_profile.get("tactics")),
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


def _generate_bot_opponent(card_tier_rates: dict | None = None) -> tuple[str, dict]:
    """A freshly-rolled bot squad -- random formation AND random card tier so
    a Quick Match bot can plausibly be "the best or worst player" too, not
    always a bronze pushover. Never persisted anywhere; exists only for this
    one match.

    `card_tier_rates` ({tier: weight}) makes each card roll its own tier
    from those weights. Quick Match passes nothing and keeps one random
    tier from the full TIER_RANGES spread for the whole squad; a tournament
    passes its league's bot_card_rates (config.TOURNAMENT_TIERS), since an icon bot in
    the bronze league is not a match, it is a guaranteed loss.
    """
    formation = random.choice(list(FORMATIONS.keys()))
    if card_tier_rates:
        tier = max(card_tier_rates, key=card_tier_rates.get)  # the typical card, for the name
        roster = generate_starter_roster(formation, seed=secrets.randbits(63), tier_rates=card_tier_rates)
    else:
        tier = random.choice(list(TIER_RANGES.keys()))
        roster = generate_starter_roster(formation, tier, seed=secrets.randbits(63))
    bot_uid = f"bot_{secrets.token_hex(6)}"  # never collides with a real Firebase uid's shape
    profile = {
        "display_name": f"{tier.capitalize()} Bot",
        "formation": formation,
        "roster": roster,
        "kit": BOT_KIT,
        "tactics": {"style": random.choice(list(TACTICS))},
    }
    return bot_uid, profile


async def pick_opponent_profile(uid: str) -> tuple[str, dict]:
    """Quick Match's opponent: the first of QUICK_MATCH_CANDIDATES random
    managers who can field a legal XI, else a stored bot from a random
    tier's bot_pools/{tier} (else a freshly rolled one -- see
    pick_opponent_from_candidates), so a match always happens.

    Sampled rather than listed: the same handful of reads however many
    accounts there are. Returns (opponent_uid, profile); a bot's uid is its
    "bot_..." id.
    """
    client = AdminFirestoreClient(uid)
    # One spare, in case the caller lands in their own sample.
    docs = await client.sample_documents("users", QUICK_MATCH_CANDIDATES + 1)
    docs = [d for d in docs if d["id"] != uid][:QUICK_MATCH_CANDIDATES]
    random.shuffle(docs)
    for doc in docs:
        profile = await _playable_user_profile(doc["id"], doc)
        if profile is not None:
            return doc["id"], profile

    pool = await client.get_document(bot_pool_path(random.choice(list(TOURNAMENT_TIERS))))
    return await pick_opponent_from_candidates(
        uid, list((pool or {}).get("uids") or []), max_attempts=QUICK_MATCH_CANDIDATES
    )


async def _playable_user_profile(candidate_uid: str, doc: dict | None) -> dict | None:
    """users/{candidate_uid} as the profile run_match takes, given its
    already-read doc, or None when it can't field a legal XI. The cheap
    checks run on the doc alone; only a survivor pays for its eleven
    player reads (see pick_opponent_from_candidates)."""
    if doc is None:
        return None
    if len(doc.get("roster_player_ids") or []) != 11:
        return None
    if doc.get("formation") not in FORMATIONS:
        return None

    state = GameState(AdminFirestoreClient(candidate_uid), PLAYER_CLASS_MAP, Midfielder)
    profile = await state.load_or_create_profile(
        default_roster=[], default_display_name=doc.get("display_name", candidate_uid[:8])
    )
    if len(profile["roster"]) != 11:
        return None  # roster_player_ids pointed at a players/{id} doc that's since been deleted
    try:
        validate_formation_positions(profile)
    except HTTPException:
        return None  # this candidate's own saved data is invalid -- try another, or fall back to a bot
    return profile


async def pick_opponent_from_candidates(
    uid: str,
    candidate_uids: list[str],
    *,
    max_attempts: int | None = None,
    card_tier_rates: dict | None = None,
) -> tuple[str, dict]:
    """The shared "find a playable opponent among these uids" loop.

    TWO STAGES, and the split is the whole point. Hydrating a profile reads
    users/{uid} PLUS all eleven players/{id} documents (see
    game_state.load_players), so validating a candidate the naive way costs
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
    doesn't have one.

    `max_attempts` bounds the worst case; None means "try them all".
    Falls back to a bot when nobody is playable, so a match always happens.
    """
    candidate_uids = [c for c in candidate_uids if c != uid]
    random.shuffle(candidate_uids)
    if max_attempts is not None:
        candidate_uids = candidate_uids[:max_attempts]

    for candidate_uid in candidate_uids:
        client = AdminFirestoreClient(candidate_uid)

        # A stored bot: the whole squad is on its one doc.
        if candidate_uid.startswith(BOT_UID_PREFIX):
            bot_doc = await client.get_document(f"bots/{candidate_uid}")
            bot_profile = bot_profile_from_doc(candidate_uid, bot_doc) if bot_doc else None
            if bot_profile is None:
                continue
            try:
                validate_formation_positions(bot_profile)
            except HTTPException:
                continue
            return candidate_uid, bot_profile

        # Stage one reads the user doc; stage two (inside) the eleven players.
        profile = await _playable_user_profile(candidate_uid, await client.get_document(f"users/{candidate_uid}"))
        if profile is not None:
            return candidate_uid, profile

    return _generate_bot_opponent(card_tier_rates)
