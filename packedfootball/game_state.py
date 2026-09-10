"""Firestore-backed persistence for a signed-in user's profile, roster, and
card inventory, plus the public lobby entries PvP matchmaking reads from.

CLIENT-TRUSTED PHASE: every write here happens with the signed-in user's own
ID token, straight from the game client. Firestore Security Rules stop one
user from touching another user's data, but nothing here validates that the
user isn't lying about their own state (crediting themselves extra coins,
say). That's an accepted trade-off for this phase, not an oversight -- see
firebase_client.py's module docstring. Moving credit- and inventory-affecting
writes behind a Cloud Run service that enforces what these rules currently
just trust is the planned next step.

Schema:
    users/{uid}                -> {display_name, credits, roster: [card, ...]}
    users/{uid}/inventory/{id} -> one document per benched (non-starting) card
    lobby/{uid}                -> public squad snapshot used for PvP discovery
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from player.player import Attributes

DEFAULT_STARTING_CREDITS = 1000
DEFAULT_STARTING_ELO = 1200


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
    )
    p.statistics = dict(fields.get("statistics", p.statistics))
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

    # -- profile + roster -----------------------------------------------------

    async def load_or_create_profile(self, default_roster: list, default_display_name: str) -> dict[str, Any]:
        """Returns {"credits", "display_name", "wins", "losses", "draws",
        "elo", "campaign_level", "roster"}.

        If this uid has no profile document yet (brand new account), creates
        one seeded with default_roster, default_display_name, zeroed manager
        stats, and the starting credit grant, and returns that same shape back.
        """
        uid = self.client.uid
        doc = await self.client.get_document(f"users/{uid}")
        if doc is None:
            doc = {
                "credits": DEFAULT_STARTING_CREDITS,
                "display_name": default_display_name,
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "elo": DEFAULT_STARTING_ELO,
                "campaign_level": 0,
                "roster": [player_to_fields(p) for p in default_roster],
            }
            await self.client.set_document(f"users/{uid}", doc, merge=False)
            return {
                "credits": doc["credits"],
                "display_name": doc["display_name"],
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "elo": DEFAULT_STARTING_ELO,
                "campaign_level": 0,
                "roster": list(default_roster),
            }
        return {
            "credits": doc.get("credits", DEFAULT_STARTING_CREDITS),
            "display_name": doc.get("display_name", default_display_name),
            "wins": doc.get("wins", 0),
            "losses": doc.get("losses", 0),
            "draws": doc.get("draws", 0),
            "elo": doc.get("elo", DEFAULT_STARTING_ELO),
            "campaign_level": doc.get("campaign_level", 0),
            "roster": self._to_players(doc.get("roster", [])),
        }

    async def update_profile_fields(self, fields: dict) -> None:
        """Merges arbitrary top-level fields into this user's profile doc."""
        uid = self.client.uid
        await self.client.set_document(f"users/{uid}", fields, merge=True)

    async def save_roster(self, roster: list) -> None:
        await self.update_profile_fields({"roster": [player_to_fields(p) for p in roster]})

    async def set_credits(self, credits: int) -> None:
        await self.update_profile_fields({"credits": credits})

    async def set_display_name(self, display_name: str) -> None:
        await self.update_profile_fields({"display_name": display_name})

    async def record_match_result(self, wins: int, losses: int, draws: int) -> None:
        await self.update_profile_fields({"wins": wins, "losses": losses, "draws": draws})

    async def set_elo(self, elo: int) -> None:
        await self.update_profile_fields({"elo": elo})

    async def set_campaign_level(self, campaign_level: int) -> None:
        await self.update_profile_fields({"campaign_level": campaign_level})

    # -- inventory (bench) ------------------------------------------------------

    async def load_inventory(self) -> list:
        """Returns benched cards, each tagged with a .doc_id for later updates."""
        uid = self.client.uid
        docs = await self.client.list_collection(f"users/{uid}/inventory")
        cards = []
        for doc in docs:
            card = self._to_player(doc)
            card.doc_id = doc["id"]
            cards.append(card)
        return cards

    async def add_inventory_card(self, card) -> None:
        """Persists a card as a new bench document and tags it with the new id."""
        uid = self.client.uid
        doc_id = await self.client.add_document(f"users/{uid}/inventory", player_to_fields(card))
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

    # -- PvP lobby --------------------------------------------------------------

    async def publish_lobby_entry(
        self, display_name: str, roster: list, wins: int = 0, elo: int = DEFAULT_STARTING_ELO, campaign_level: int = 0
    ) -> None:
        """Publishes a public snapshot used for both PvP matchmaking (the
        roster) and the leaderboard (wins/elo/campaign_level). One document
        serves both since they're both "things anyone signed in can see
        about this player" -- no separate leaderboard collection needed.
        """
        uid = self.client.uid
        overall = round(sum(p.overall for p in roster) / len(roster)) if roster else 0
        await self.client.set_document(
            f"lobby/{uid}",
            {
                "display_name": display_name,
                "overall": overall,
                "wins": wins,
                "elo": elo,
                "campaign_level": campaign_level,
                "roster": [player_to_fields(p) for p in roster],
            },
            merge=False,
        )

    async def list_opponents(self) -> list[dict[str, Any]]:
        """Returns other users' published squads for the PvP menu.

        Each entry: {"uid", "display_name", "overall", "elo", "players": [player, ...]}
        """
        entries = await self.client.list_collection("lobby")
        uid = self.client.uid
        opponents = []
        for entry in entries:
            if entry["id"] == uid:
                continue
            opponents.append(
                {
                    "uid": entry["id"],
                    "display_name": entry.get("display_name", entry["id"][:8]),
                    "overall": entry.get("overall", 0),
                    "elo": entry.get("elo", DEFAULT_STARTING_ELO),
                    "players": self._to_players(entry.get("roster", [])),
                }
            )
        return opponents

    async def list_leaderboard(self) -> list[dict[str, Any]]:
        """Returns every published player's standings for the leaderboard.

        Each entry: {"uid", "display_name", "wins", "elo", "campaign_level"}.
        Includes the caller themself (unlike list_opponents) so they can see
        their own rank. Doesn't need roster/player data, so it skips the
        player deserialization list_opponents does.
        """
        entries = await self.client.list_collection("lobby")
        return [
            {
                "uid": entry["id"],
                "display_name": entry.get("display_name", entry["id"][:8]),
                "wins": entry.get("wins", 0),
                "elo": entry.get("elo", DEFAULT_STARTING_ELO),
                "campaign_level": entry.get("campaign_level", 0),
            }
            for entry in entries
        ]
