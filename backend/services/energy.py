"""Energy: the first ceiling this backend has ever had on how many matches a
player can run in a day.

Two halves, deliberately split:

  - `regen()` and `describe()` are PURE -- no Firestore, no clock of their
    own, `now` passed in. They are where the real tests live, because the
    arithmetic is the part that goes wrong.
  - `spend()` is the transactional half, because two parallel requests would
    otherwise both spend the last point.

Energy is never ticked by a job. It is stored as a value plus the moment that
value was true, and every reader derives the current amount from the two. That
is what makes it survive a backend with no scheduler.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config

# users/{uid} field names, in one place -- they appear in this module, in the
# tournament service and in the energy router.
ENERGY_FIELD = "energy"
ENERGY_UPDATED_AT_FIELD = "energy_updated_at"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value, default: datetime | None = None) -> datetime:
    """An ISO-8601 string back into an aware datetime.

    Absent or malformed means "as of now", which for energy is the generous
    reading: a profile with no anchor is treated as having just been topped
    up rather than as owing the player hours of regen it can't prove.
    """
    fallback = default if default is not None else now_utc()
    if not isinstance(value, str) or not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return fallback
    # A stored value without a zone is one this build wrote before it started
    # stamping one; treat it as UTC rather than letting it compare-fail.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def regen(energy: int, updated_at: datetime, now: datetime) -> tuple[int, datetime]:
    """The current energy, and the anchor to store alongside it.

    Three branches carry the whole function:

      - `gained <= 0` returns `updated_at` UNTOUCHED. Returning `now` here is
        THE bug in this pattern: a player who opens the app every 44 minutes
        would reset the clock every time and never regenerate a single point.
      - Otherwise the anchor advances by exactly the intervals CONSUMED, not
        to `now`, so the remainder carries forward -- 89 minutes is one point
        plus 44 minutes of credit toward the next.
      - At the cap the anchor resets to `now`, because there is nothing to
        bank: the 45 minutes should start from the next spend, not from
        whenever the bar last happened to fill.
    """
    if energy >= config.ENERGY_MAX:
        return config.ENERGY_MAX, now

    elapsed = (now - updated_at).total_seconds()
    gained = int(elapsed // config.ENERGY_REGEN_SECONDS)
    if gained <= 0:
        return energy, updated_at

    topped_up = min(config.ENERGY_MAX, energy + gained)
    if topped_up >= config.ENERGY_MAX:
        return config.ENERGY_MAX, now
    return topped_up, updated_at + timedelta(seconds=gained * config.ENERGY_REGEN_SECONDS)


def from_profile(doc: dict | None, now: datetime | None = None) -> tuple[int, datetime]:
    now = now or now_utc()
    doc = doc or {}
    raw = doc.get(ENERGY_FIELD)
    energy = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else config.ENERGY_MAX
    energy = max(0, min(config.ENERGY_MAX, energy))
    updated_at = parse_timestamp(doc.get(ENERGY_UPDATED_AT_FIELD), now)
    return regen(energy, updated_at, now)


def describe(energy: int, updated_at: datetime, now: datetime | None = None) -> dict:
    """The energy block every endpoint returns.

    Hands the client SECONDS, never a timestamp, so it can tick a countdown
    locally with no date parsing and no exposure to device-clock skew
    """
    now = now or now_utc()
    if energy >= config.ENERGY_MAX:
        return {
            "energy": config.ENERGY_MAX,
            "energy_max": config.ENERGY_MAX,
            "seconds_to_next": 0,
            "seconds_to_full": 0,
            "regen_seconds": config.ENERGY_REGEN_SECONDS,
        }

    elapsed_in_interval = (now - updated_at).total_seconds() % config.ENERGY_REGEN_SECONDS
    seconds_to_next = int(config.ENERGY_REGEN_SECONDS - elapsed_in_interval)
    missing = config.ENERGY_MAX - energy
    return {
        "energy": energy,
        "energy_max": config.ENERGY_MAX,
        "seconds_to_next": seconds_to_next,
        "seconds_to_full": seconds_to_next + (missing - 1) * config.ENERGY_REGEN_SECONDS,
        "regen_seconds": config.ENERGY_REGEN_SECONDS,
    }


class NotEnoughEnergy(Exception):

    def __init__(self, have: int, need: int, seconds_to_next: int):
        self.have, self.need, self.seconds_to_next = have, need, seconds_to_next
        super().__init__(f"Not enough energy -- {need} needed, you have {have}")


async def spend(client, uid: str, cost: int, now: datetime | None = None) -> dict:
    """Takes `cost` energy from a profile and returns the resulting block.

    Transactional because two parallel requests would otherwise both read the
    same last point and both spend it. Regen is resolved INSIDE the
    transaction, so a point that arrived a second ago still counts.

    A cost of 0 is a read, not a write -- that is what lets
    QUICK_MATCH_ENERGY_COST be set to 0 to disable the gate on an endpoint
    without touching its code.
    """
    now = now or now_utc()
    user_path = f"users/{uid}"

    def _spend(tx):
        doc = tx.get(user_path)
        current, anchor = from_profile(doc, now)
        if cost <= 0:
            return current, anchor
        if current < cost:
            raise NotEnoughEnergy(current, cost, describe(current, anchor, now)["seconds_to_next"])
        fields = spend_fields(current, anchor, cost, now)
        tx.set(user_path, fields, merge=True)
        return fields[ENERGY_FIELD], parse_timestamp(fields[ENERGY_UPDATED_AT_FIELD], now)

    remaining, anchor = await client.run_transaction(_spend)
    return describe(remaining, anchor, now)


def spend_fields(energy: int, updated_at: datetime, cost: int, now: datetime | None = None) -> dict:
    """The users/{uid} fields that record a spend.

    Spending from a FULL bar is what starts the clock, so the anchor moves to
    `now` in that case and to the carried-forward anchor otherwise -- which is
    exactly what regen() already returned, so callers pass it straight through.
    """
    now = now or now_utc()
    remaining = max(0, energy - cost)
    anchor = now if energy >= config.ENERGY_MAX else updated_at
    return {
        ENERGY_FIELD: remaining,
        ENERGY_UPDATED_AT_FIELD: anchor.isoformat(),
    }
