"""Invitations obligatoires pour les jeux 1 contre 1 SentriX.

Aucun duel ne démarre avant le clic ACCEPTER de la personne défiée.
Seul le destinataire accepte/refuse ; l'initiateur peut annuler. Les verrous
provisoires sont libérés sans cooldown ni récompense lors d'un refus/timeout.
Le bouton accepté lance le jeu existant avec ses propres choix privés.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import discord

from utils import sentrix_panels as panels

logger = logging.getLogger("bot.game-invitations")
StartGame = Callable[[discord.Message], Awaitable[None]]
CancelGame = Callable[[], Awaitable[None]]


class DuelInvitation(discord.ui.View):
    def __init__(
        self, *, challenger_id: int, opponent_id: int,
        start: StartGame, cancel: CancelGame, timeout: float = 45.0,
    ):
        super().__init__(timeout=timeout)
        self.challenger_id = challenger_id
        self.opponent_id = opponent_id
        self.start = start
        self.cancel = cancel
        self.message: discord.Message | None = None
        self.status = "pending"
        self._lock = asyncio.Lock()
        self.add_item(_InvitationAction("✅ Accepter", "accept", discord.ButtonStyle.success))
        self.add_item(_InvitationAction("❌ Refuser / annuler", "decline", discord.ButtonStyle.danger))

    async def resolve(self, interaction: discord.Interaction, choice: str) -> None:
        async with self._lock:
            if self.status != "pending":
                return await interaction.response.send_message(
                    "Cette invitation n'est plus disponible.", ephemeral=True
                )
            uid = interaction.user.id
            if choice == "accept" and uid != self.opponent_id:
                return await interaction.response.send_message(
                    "Seul le membre défié peut accepter cette partie.", ephemeral=True
                )
            if choice == "decline" and uid not in (self.opponent_id, self.challenger_id):
                return await interaction.response.send_message(
                    "Seuls les deux joueurs peuvent refuser ou annuler.", ephemeral=True
                )
            await interaction.response.defer()
            if choice == "accept":
                self.status = "accepted"
                self.stop()
                try:
                    if self.message is None:
                        raise RuntimeError("Invitation sans message Discord")
                    await self.start(self.message)
                except Exception:
                    logger.exception("Impossible de lancer le duel après acceptation")
                    await self.cancel()
                    if self.message:
                        await panels.editer(
                            self.message,
                            panels.Panneau(
                                titre="⚠️ Duel indisponible",
                                sous_titre="Le duel n'a pas pu démarrer. Aucun joueur n'a été pénalisé.",
                                kind="warning",
                            ),
                        )
                return
            self.status = "declined"
            self.stop()
            await self.cancel()
            if self.message:
                await panels.editer(
                    self.message,
                    panels.Panneau(
                        titre="🚫 Défi annulé",
                        sous_titre="La partie n'a pas commencé. Aucun cooldown ni récompense.",
                        kind="neutral",
                    ),
                )

    async def on_timeout(self) -> None:
        async with self._lock:
            if self.status != "pending":
                return
            self.status = "expired"
            await self.cancel()
            if self.message:
                try:
                    await panels.editer(
                        self.message,
                        panels.Panneau(
                            titre="⏱️ Défi expiré",
                            sous_titre="Invitation non acceptée en 45 secondes.",
                            kind="warning",
                        ),
                    )
                except (discord.HTTPException, AttributeError):
                    logger.debug("Invitation expirée : message non modifiable", exc_info=True)


class _InvitationAction(discord.ui.Button):
    def __init__(self, label: str, action: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        view: DuelInvitation = panels.vue_source(self)
        await view.resolve(interaction, self.action)
