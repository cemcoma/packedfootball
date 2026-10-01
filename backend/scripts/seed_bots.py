"""Creates the stored bots that fill a tournament tier's matchmaking pool
before real players do -- bots/{id} plus the per-tier id list bot_pools/{tier}
that services.tournament.join_period seeds a new period's pool from --
shared by every tournament format, so one seeding run covers them all.

A stored bot is a permanent opponent: a manager name from
bots_sample_names.txt next to this script (one per line, "#" for a
comment -- the kind of handle a real player would pick, so the pool reads
as people), a formation, a kit, and a full XI whose cards each roll their tier from
its league's bot_card_rates in config.TOURNAMENT_TIERS (a bronze-league bot is mostly
silver with a few golds and the odd platinum) -- the same squad every time
it comes up, so the striker who scored against you yesterday is the same
striker today, and View Opponent shows a real team. The XI is
embedded on the bot's own doc rather than written to players/, so bot cards
never show up on the player leaderboards and picking one costs a single
read.

Bots never join a group, hold no tournament seat, and get no record of
their own; they are only ever the other side of a match. Nothing here
touches a pool that already exists -- a day already under way keeps the
bots it started with, tomorrow's pool picks up the new list.

Names are used once each: a name already on a bot, already reserved by a
real manager (display_names/), duplicated in the file or failing the
display-name rules is skipped, and when the file runs dry the run stops
short and says so rather than inventing names.

Idempotent per tier: tops each tier up to --per-tier bots and leaves the
existing ones alone (their ids stay in the pool list).

Usage:
    python3 backend/scripts/seed_bots.py [--per-tier 30] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import random
import secrets
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import firestore

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "packedfootball"))
import gameEngine  
import config 
from formations import FORMATIONS 
from game_config import TACTICS  # noqa: E402
from game_state import player_to_fields 
from packEngine import COUNTRIES, generate_starter_roster  # noqa: E402
from services.account import DisplayNameError, display_name_key, validate_display_name  # noqa: E402
from services.match import BOT_UID_PREFIX  # noqa: E402
from services.minigames import (  # noqa: E402
    bot_pool_path as minigames_bot_pool_path,
    bot_rates as minigames_bot_rates,
    bot_tier_for_day as minigames_bot_tier_for_day,
)
from services.tournament import (  # noqa: E402
    bot_card_rates as tournament_bot_card_rates,
    bot_pool_path,
    tier_name as tournament_tier_name,
)

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "packedfootball")
NAMES_FILE = Path(__file__).resolve().parent / "bots_sample_names.txt"

# A few shirt palettes so a run of bots doesn't all wear the default red.
KIT_PALETTES = [
    ("c8102e", "ffffff"), ("1e3a8a", "fbbf24"), ("111111", "e5e7eb"), ("047857", "ffffff"),
    ("7c3aed", "fde68a"), ("0ea5e9", "0f172a"), ("f59e0b", "1f2937"), ("dc2626", "1e3a8a"),
    ("14b8a6", "111827"), ("9333ea", "ffffff"), ("f97316", "0c4a6e"), ("64748b", "f8fafc"),
]


def load_names(db, rng: random.Random) -> list[str]:
    """The names still free to give a bot, shuffled: the file minus
    duplicates, minus what existing bots already wear, minus what a real
    manager has reserved, minus anything the display-name rules refuse."""
    if not NAMES_FILE.exists():
        raise SystemExit(f"{NAMES_FILE} is missing -- one bot name per line")
    taken = {display_name_key((d.to_dict() or {}).get("display_name", "")) for d in db.collection("bots").stream()}
    names, seen = [], set() 
    for line in NAMES_FILE.read_text(encoding="utf-8").splitlines():
        raw = line.split("#", 1)[0].strip()
        if not raw:
            continue
        try:
            name = validate_display_name(raw)
        except DisplayNameError as exc:
            print(f"  skipping {raw!r}: {exc.reason}")
            continue
        key = display_name_key(name)
        if key in seen or key in taken:
            continue
        if db.document(f"display_names/{key}").get().exists:
            print(f"  skipping {name!r}: a real manager has it")
            continue
        seen.add(key)
        names.append(name)
    rng.shuffle(names)
    return names


def make_bot(rng: random.Random, rates: dict, display_name: str, extra: dict) -> tuple[str, dict]:
    """One stored bot. `extra` is what marks which pool it belongs to -- a
    league tier, or a day and prestige of the shootout grid."""
    country = rng.choice(COUNTRIES)
    formation = rng.choice(list(FORMATIONS.keys()))
    roster = generate_starter_roster(formation, seed=rng.getrandbits(63), tier_rates=rates)
    primary, secondary = rng.choice(KIT_PALETTES)
    pattern = rng.choice(("solid", "stripes","quarters"))
    bot_id = f"{BOT_UID_PREFIX}{secrets.token_hex(6)}"
    return bot_id, {
        "display_name": display_name,
        **extra,
        "formation": formation,
        "kit": f"v1;pattern={pattern};primary={primary};secondary={secondary}",
        "players": [player_to_fields(p) for p in roster],
        "tactics": {"style": rng.choice(list(TACTICS))},
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "created_at": firestore.SERVER_TIMESTAMP,
    }


def seed_shootout_grid(db, rng: random.Random, names: list[str], dry_run: bool) -> None:
    """The daily shootout's opponents: one named bot per (day, prestige) cell.

    A 15 x PRESTIGE_LEVELS grid, so a player meets the same manager on day 12
    every cycle and a different one once they prestige. The day sets the tier
    (bronze up to special) and prestige only leans the mix one step up it --
    see services/minigames.bot_rates.

    Idempotent per cell: a cell that already holds a bot is left alone, so a
    rerun only fills the gaps and a widened grid only adds its new column.
    """
    days = config.PENALTY_SHOOTOUT_CYCLE_DAYS
    levels = config.PENALTY_SHOOTOUT_PRESTIGE_LEVELS
    print(f"\nShootout grid: {days} day(s) x {levels} prestige level(s)")

    for day in range(1, days + 1):
        pool_ref = db.document(minigames_bot_pool_path(day))
        pool = pool_ref.get()
        existing = list((pool.to_dict() or {}).get("uids") or []) if pool.exists else []
        missing = max(0, levels - len(existing))
        tier = minigames_bot_tier_for_day(day)
        if missing == 0:
            print(f"  day {day:>2} ({tier}): complete")
            continue
        if missing > len(names):
            print(f"  only {len(names)} name(s) left for {missing} bot(s) -- add more to {NAMES_FILE.name}")
            missing = len(names)
        print(f"  day {day:>2} ({tier}): {len(existing)} bot(s), creating {missing}")
        if missing == 0 or dry_run:
            continue

        batch = db.batch()
        new_ids = []
        for prestige in range(len(existing), len(existing) + missing):
            rates = minigames_bot_rates(day, prestige)
            bot_id, doc = make_bot(
                rng, rates, names.pop(),
                {"shootout_day": day, "shootout_prestige": prestige},
            )
            batch.set(db.collection("bots").document(bot_id), doc)
            new_ids.append(bot_id)
            tiers = " ".join(sorted({p["tier"] for p in doc["players"]}))
            print(f"    p{prestige} {bot_id}  {doc['display_name']:<24} {doc['formation']:<6} {tiers}")
        batch.set(pool_ref, {"day": day, "uids": existing + new_ids})
        batch.commit()

    if dry_run:
        print("Dry run, nothing changed.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-tier", type=int, default=20, help="How many bots each league tier should have")
    parser.add_argument("--dry-run", action="store_true", help="Report only, write nothing")
    args = parser.parse_args()

    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()
    rng = random.Random()
    names = load_names(db, rng)
    print(f"{len(names)} name(s) available in {NAMES_FILE.name}")

    for tier in range(config.TOURNAMENT_TOP_TIER, config.TOURNAMENT_BOTTOM_TIER + 1):
        pool_ref = db.document(bot_pool_path(tier))
        pool = pool_ref.get()
        existing = list((pool.to_dict() or {}).get("uids") or []) if pool.exists else []
        missing = max(0, args.per_tier - len(existing))
        if missing > len(names):
            print(f"  only {len(names)} name(s) left for {missing} bot(s) -- add more to {NAMES_FILE.name}")
            missing = len(names)
        print(f"{tournament_tier_name(tier)}: {len(existing)} bot(s), creating {missing}")
        if missing == 0 or args.dry_run:
            if args.dry_run:    
                print("Dry run, nothing changed.")
            continue
        

        batch = db.batch()
        new_ids = []
        for _ in range(missing):
            rates = tournament_bot_card_rates(tier) or {"silver": 1.0}
            bot_id, doc = make_bot(rng, rates, names.pop(), {"tier": tier})
            batch.set(db.collection("bots").document(bot_id), doc)
            new_ids.append(bot_id)
            tiers = " ".join(sorted({p["tier"] for p in doc["players"]}))
            print(f"  {bot_id}  {doc['display_name']:<24} {doc['formation']:<6} {tiers}")
        batch.set(pool_ref, {"tier": tier, "uids": existing + new_ids})
        batch.commit()

    seed_shootout_grid(db, rng, names, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
