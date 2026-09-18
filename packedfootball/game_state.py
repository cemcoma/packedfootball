"""Firestore-backed persistence for a signed-in user's profile, roster, and
card inventory. Used both directly by the Godot client
(mobile/scripts/autoload/Firestore.gd, with the signed-in user's own ID
token) and, for anything that needs to be authoritative, by backend/main.py's
Cloud Run service (via AdminFirestoreClient, not subject to firestore.rules
at all).

CLIENT-TRUSTED PHASE: a *direct* write here (as opposed to one mediated by
the backend) happens with the signed-in user's own ID token. Firestore
Security Rules stop one user from touching another user's data, but nothing
stops the user from lying about their own state over a write like that
(crediting themselves extra coins, say). That's an accepted trade-off for
whatever's still written this way -- today, formation/roster_player_ids
(Team.gd's save_team()) and display_name -- not an oversight; the
higher-stakes operations (pack opening, match simulation, both of which
touch credits and generate new cards) already moved behind the backend
specifically because of this. Tightening firestore.rules to deny direct
writes to the still-client-trusted fields, once nothing needs to write them
directly anymore, remains the natural next step (see backend/README.md's
"Still to do").

Schema:
    users/{uid}                -> {display_name, credits, bucks, medals, roster_player_ids: [id, ...]}
    users/{uid}/inventory/{id} -> {player_id} pointer, one per benched card
    players/{player_id}        -> the actual card fields (owner_uid, attributes,
                                   statistics, ...) -- the single copy roster
                                   and inventory both point into, so a
                                   cross-user leaderboard can query this
                                   collection directly instead of joining
                                   through every user's roster/inventory.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from player.player import Attributes

DEFAULT_STARTING_CREDITS = 1000
DEFAULT_STARTING_BUCKS = 0
DEFAULT_STARTING_MEDALS = 0
DEFAULT_FORMATION = "4-4-2"
# "" means "no kit chosen, renderer picks" -- see load_or_create_profile's
# docstring for why this end deliberately doesn't spell out a default shirt.
DEFAULT_KIT = ""


def player_to_fields(p) -> dict:
    """Serializes a player object into plain data Firestore can store."""
    return {
        "fname": p.fname,
        "lname": p.lname,
        "tier": p.tier,
        "position": p.position,
        "country": p.country,
        "hometown": p.hometown,
        "attributes": asdict(p.attributes),
        "statistics": dict(p.statistics),
        "appearance": dict(p.appearance),
    }


def fields_to_player(fields: dict, player_class_map: dict, default_class):
    """Reconstructs a player object from a previously-serialized dict."""
    attrs = Attributes(**fields["attributes"])
    player_cls = player_class_map.get(fields["position"], default_class)
    p = player_cls(
        fields["fname"],
        fields["lname"],
        fields["tier"],
        fields["position"],
        attrs,
        country=fields.get("country"),
        hometown=fields.get("hometown"),
        appearance=fields.get("appearance"),
    )
    p.statistics = dict(fields["statistics"])
    return p


class GameState:
    """Loads and saves one signed-in user's profile, roster, and inventory."""

    def __init__(self, client, player_class_map: dict, default_class):
        self.client = client
        self._player_class_map = player_class_map
        self._default_class = default_class

    def _to_player(self, fields: dict):
        return fields_to_player(fields, self._player_class_map, self._default_class)

    def _to_players(self, field_list: list[dict]) -> list:
        return [self._to_player(f) for f in field_list]

    # -- players collection (the shared copy roster/inventory point into) -----

    async def _ensure_player_doc(self, p) -> str:
        """Creates or updates this player's players/{id} doc, tagging p.player_id.

        Mirrors the .doc_id tagging pattern add_inventory_card uses for bench
        documents, but for the players collection itself: repeated calls (e.g.
        calling save_roster again) update the same doc instead of creating a
        duplicate one every time.
        """
        fields = player_to_fields(p)
        fields["owner_uid"] = self.client.uid
        player_id = getattr(p, "player_id", None)
        if player_id:
            await self.client.set_document(f"players/{player_id}", fields, merge=True)
            return player_id
        fields["created_at"] = datetime.now(timezone.utc).isoformat()
        player_id = await self.client.add_document("players", fields)
        p.player_id = player_id
        return player_id

    async def _load_player(self, player_id: str):
        fields = await self.client.get_document(f"players/{player_id}")
        if fields is None:
            return None
        p = self._to_player(fields)
        p.player_id = player_id
        return p

    async def load_players(self, player_ids: list[str]) -> list:
        """The cards behind these ids, in the order asked for, each tagged
        with its .player_id; an id whose players/ doc is gone is skipped
        rather than raised. One parallel batch, so a whole roster costs one
        round trip's latency -- which is why /account/bootstrap hands the
        client its squad from here instead of letting it fetch card by card.
        """
        players = await asyncio.gather(*(self._load_player(pid) for pid in player_ids))
        return [p for p in players if p is not None]

    # -- profile + roster -----------------------------------------------------

    async def load_or_create_profile(
        self, default_roster: list, default_display_name: str, default_formation: str = DEFAULT_FORMATION
    ) -> dict[str, Any]:
        """Returns {"credits", "bucks", "medals", "display_name", "wins",
        "losses", "draws", "roster", "formation", "kit"}.

        If this uid has no profile document yet (brand new account), creates
        one seeded with default_roster, default_display_name, default_formation,
        zeroed manager stats, and the starting credit grant, and returns that
        same shape back.

        "formation" mirrors mobile/scripts/GameProfile.gd's own field of the
        same name -- the Godot client is what actually writes/reads it
        day-to-day (see Team.gd), but it lives on this shared users/{uid}
        schema so the backend can read it too (see backend/main.py's
        /match/simulate, which needs to know each side's real formation
        instead of assuming everyone plays 4-4-2).

        "kit" is the same arrangement: the manager's shirt, written by the
        client's Customize Kit screen and read here only to hand back to
        whoever is rendering the match. It is passed through UNINSPECTED and
        UNVALIDATED on purpose -- the format is deliberately extendable (see
        mobile/scripts/data/KitDesign.gd), the only consumer is a renderer
        that already treats anything unparseable as the default kit, and
        nothing in the simulation or the economy reads it. Parsing it here
        would mean two implementations of the format to keep in step, and
        would make every future kit feature a backend deploy.
        DEFAULT_KIT is the empty string rather than a spelled-out default
        for the same reason: "unset, you decide" is one fewer place for the
        two ends to disagree about what a default shirt looks like.
        """
        uid = self.client.uid
        doc = await self.client.get_document(f"users/{uid}")
        if doc is None:
            roster_player_ids = await asyncio.gather(*(self._ensure_player_doc(p) for p in default_roster))
            doc = {
                "credits": DEFAULT_STARTING_CREDITS,
                "bucks": DEFAULT_STARTING_BUCKS,
                "medals": DEFAULT_STARTING_MEDALS,
                "display_name": default_display_name,
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "roster_player_ids": list(roster_player_ids),
                "formation": default_formation,
                "kit": DEFAULT_KIT,
            }
            await self.client.set_document(f"users/{uid}", doc, merge=False)
            return {
                "credits": doc["credits"],
                "bucks": doc["bucks"],
                "medals": doc["medals"],
                "display_name": doc["display_name"],
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "roster": list(default_roster),
                "formation": default_formation,
                "kit": DEFAULT_KIT,
            }
        return {
            "credits": doc.get("credits", DEFAULT_STARTING_CREDITS),
            "bucks": doc.get("bucks", DEFAULT_STARTING_BUCKS),
            "medals": doc.get("medals", DEFAULT_STARTING_MEDALS),
            "display_name": doc.get("display_name", default_display_name),
            "wins": doc.get("wins", 0),
            "losses": doc.get("losses", 0),
            "draws": doc.get("draws", 0),
            "roster": await self.load_players(doc.get("roster_player_ids", [])),
            "formation": doc.get("formation", DEFAULT_FORMATION),
            # Absent on every account created before kits existed.
            "kit": doc.get("kit", DEFAULT_KIT),
        }

    async def update_profile_fields(self, fields: dict) -> None:
        """Merges arbitrary top-level fields into this user's profile doc."""
        uid = self.client.uid
        await self.client.set_document(f"users/{uid}", fields, merge=True)

    async def save_roster(self, roster: list) -> None:
        roster_player_ids = await asyncio.gather(*(self._ensure_player_doc(p) for p in roster))
        await self.update_profile_fields({"roster_player_ids": list(roster_player_ids)})

    async def set_credits(self, credits: int) -> None:
        await self.update_profile_fields({"credits": credits})

    async def set_bucks(self, bucks: int) -> None:
        await self.update_profile_fields({"bucks": bucks})

    async def set_medals(self, medals: int) -> None:
        await self.update_profile_fields({"medals": medals})

    async def set_display_name(self, display_name: str) -> None:
        await self.update_profile_fields({"display_name": display_name})

    async def record_match_result(self, wins: int, losses: int, draws: int) -> None:
        await self.update_profile_fields({"wins": wins, "losses": losses, "draws": draws})

    # -- inventory (bench) ------------------------------------------------------

    async def load_inventory(self) -> list:
        """Returns benched cards, each tagged with a .doc_id for later updates."""
        uid = self.client.uid
        docs = await self.client.list_collection(f"users/{uid}/inventory")
        cards = await asyncio.gather(*(self._load_player(doc["player_id"]) for doc in docs))
        result = []
        for doc, card in zip(docs, cards):
            if card is None:
                continue  # dangling pointer (players/{id} doc missing) -- skip
            card.doc_id = doc["id"]
            result.append(card)
        return result

    async def add_inventory_card(self, card) -> None:
        """Persists a card as a new bench document and tags it with the new id."""
        uid = self.client.uid
        player_id = await self._ensure_player_doc(card)
        doc_id = await self.client.add_document(f"users/{uid}/inventory", {"player_id": player_id})
        card.doc_id = doc_id

    async def remove_inventory_card(self, card) -> None:
        """Deletes a card's bench document (call before it leaves the bench)."""
        uid = self.client.uid
        doc_id = getattr(card, "doc_id", None)
        if doc_id:
            await self.client.delete_document(f"users/{uid}/inventory/{doc_id}")

    async def save_team(self, roster: list, bench: list) -> None:
        """Persists a whole editing session's worth of swaps in one go.

        Meant to back a "Save Team" button: the caller can swap players
        between roster and bench locally, any number of times, with zero
        network calls, then call this once. It looks at .doc_id (present
        only on cards that came from Firestore's bench collection) to work
        out what actually moved since the last save:
          - a roster card that still has a .doc_id just moved bench->roster,
            so its stale bench document gets deleted.
          - a bench card with no .doc_id just moved roster->bench, so it
            gets a new bench document created.
        Cards that never moved are left untouched either way.
        """
        await self.save_roster(roster)

        uid = self.client.uid
        for card in roster:
            doc_id = getattr(card, "doc_id", None)
            if doc_id:
                await self.client.delete_document(f"users/{uid}/inventory/{doc_id}")
                card.doc_id = None

        for card in bench:
            if not getattr(card, "doc_id", None):
                await self.add_inventory_card(card)
