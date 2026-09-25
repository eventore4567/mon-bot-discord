"""Socle commun des vues de mini-jeux : propriétaire, double-clic, fin de partie.

Ce module ne réinvente rien de ce qui existe déjà. Le côté économique est complet
depuis longtemps et reste la seule autorité :

  - ``game_rewards.reward_game_winner``  — crédit atomique, limite quotidienne,
    référence de transaction, écriture dans ``game_transactions`` (l'historique) ;
  - ``game_rewards.acquire_play_lock``   — une seule manche d'un jeu à la fois ;
  - ``game_rewards.secure_pick`` / ``secure_randint`` — l'aléa, quand de l'argent
    réel en dépend ;
  - ``game_rewards.check_cooldown``      — le délai entre deux parties.

Ce qui manquait était entièrement du côté des composants Discord, et chaque jeu
le réécrivait à sa façon — parfois à moitié :

  - vérifier que celui qui clique est bien le joueur ;
  - refuser le deuxième clic pendant que le premier est traité ;
  - désactiver les boutons à la fin, et à l'expiration ;
  - proposer de rejouer sans retaper la commande ;
  - refuser d'envoyer un bouton sans libellé NI pictogramme.

Ce dernier point n'est pas théorique : « Course à l'emoji » demandait de cliquer
sur 🍒 et envoyait cinq boutons parfaitement vides, parce qu'une couche de style
retirait l'emoji sans savoir qu'il était le jeu. Le jeu était injouable et rien
ne le signalait. ``valider_composants`` refuse désormais ce message avant qu'il
parte.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import discord

logger = logging.getLogger("bot.game-ui")

# Un bouton doit porter au moins l'un des deux. Discord accepte le contraire —
# il affiche un rectangle vide, et le joueur ne sait pas sur quoi il clique.
CHAMPS_VISIBLES = ("label", "emoji")


class BoutonInvisibleError(ValueError):
    """Un composant partirait sans rien d'affichable."""


def valider_composants(vue: discord.ui.View) -> None:
    """Refuse une vue dont un bouton n'a ni libellé ni pictogramme.

    Lève plutôt que de journaliser : un bouton vide rend la manche injouable, et
    un jeu injouable envoyé « en silence avec un avertissement dans les logs »
    est exactement ce qui a échappé à tout le monde pendant des semaines.
    """
    for item in vue.children:
        if not isinstance(item, discord.ui.Button):
            continue
        if item.style is discord.ButtonStyle.link:
            continue
        libelle = str(item.label or "").strip().strip("​").strip()
        if libelle or item.emoji is not None:
            continue
        raise BoutonInvisibleError(
            f"Bouton sans libellé ni pictogramme (custom_id={item.custom_id!r}) : "
            "le joueur verrait un rectangle vide."
        )


def composants_invisibles(vue: discord.ui.View) -> list[str]:
    """Les custom_id des boutons invisibles, sans lever. Pour les audits."""
    try:
        valider_composants(vue)
    except BoutonInvisibleError:
        return [
            str(item.custom_id)
            for item in vue.children
            if isinstance(item, discord.ui.Button)
            and item.style is not discord.ButtonStyle.link
            and not str(item.label or "").strip().strip("​").strip()
            and item.emoji is None
        ]
    return []


class VueDeJeu(discord.ui.View):
    """Vue de mini-jeu : un propriétaire, un clic à la fois, une fin propre.

    ``proprietaire_id`` est le seul membre autorisé à cliquer ; passer ``None``
    ouvre la vue à tout le monde (courses communautaires, drops). Les autres
    reçoivent un message éphémère plutôt qu'un clic ignoré sans explication.
    """

    def __init__(
        self,
        proprietaire_id: int | None,
        *,
        timeout: float | None = 60.0,
        message_intrus: str = "Cette partie appartient à quelqu'un d'autre.",
    ) -> None:
        super().__init__(timeout=timeout)
        self.proprietaire_id = int(proprietaire_id) if proprietaire_id is not None else None
        self.message_intrus = message_intrus
        self.message: discord.Message | None = None
        self.terminee = False
        self.expiree = False
        # Un verrou, pas un simple drapeau : deux clics quasi simultanés peuvent
        # tous deux lire « pas encore terminé » avant que l'un n'ait écrit.
        self._verrou = asyncio.Lock()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.terminee:
            await self._refuser(interaction, "Cette partie est terminée.")
            return False
        if self.proprietaire_id is not None and interaction.user.id != self.proprietaire_id:
            await self._refuser(interaction, self.message_intrus)
            return False
        return True

    @staticmethod
    async def _refuser(interaction: discord.Interaction, texte: str) -> None:
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(texte, ephemeral=True)
        except discord.HTTPException:
            logger.debug("Refus d'interaction non délivré.", exc_info=True)

    async def jouer_un_coup(self, action: Callable[[], Awaitable[None]]) -> bool:
        """Exécute un coup, au plus un à la fois. Faux si un coup est en cours.

        Le verrou est pris AVANT toute lecture d'état : c'est la seule façon
        d'empêcher deux clics simultanés de créditer deux fois la même manche.
        """
        if self._verrou.locked():
            return False
        async with self._verrou:
            if self.terminee:
                return False
            await action()
        return True

    def desactiver_tout(self) -> None:
        """Grise tous les composants. À appeler avant la dernière édition."""
        for enfant in self.children:
            if hasattr(enfant, "disabled"):
                enfant.disabled = True

    def terminer(self) -> None:
        """Fin de partie : plus aucun clic n'est accepté, les boutons sont gris."""
        self.terminee = True
        self.desactiver_tout()
        self.stop()

    async def on_timeout(self) -> None:
        """Expiration : la partie se ferme visiblement, jamais en silence.

        Sans cette édition, le joueur garde des boutons actifs qui ne répondent
        plus — le pire état possible, parce que rien ne dit que c'est fini.
        """
        self.expiree = True
        self.terminee = True
        self.desactiver_tout()
        if self.message is None:
            return
        try:
            await self.message.edit(view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.debug("Vue expirée non mise à jour (message disparu).", exc_info=True)


class BoutonRejouer(discord.ui.Button):
    """Relance la même commande sans la retaper.

    Réservé au joueur de la manche : sinon n'importe qui relancerait une partie
    au nom de quelqu'un d'autre, en consommant son cooldown.
    """

    def __init__(self, relancer: Callable[[discord.Interaction], Awaitable[None]], *, row: int | None = None):
        super().__init__(label="Rejouer", emoji="🔁", style=discord.ButtonStyle.secondary, row=row)
        self._relancer = relancer

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            await self._relancer(interaction)
        except Exception:
            logger.warning("Relance de partie impossible.", exc_info=True)
            await VueDeJeu._refuser(interaction, "Impossible de relancer la partie pour le moment.")


__all__ = [
    "VueDeJeu",
    "BoutonRejouer",
    "BoutonInvisibleError",
    "valider_composants",
    "composants_invisibles",
]
