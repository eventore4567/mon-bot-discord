"""Vérification SentriX entièrement dans Discord (06/11/2026).

Demande : « enlève la vérif de SentriX qui demande à accéder à ton compte ; il
vérifie lui-même sans aller sur un site ». Le bouton du salon de vérification
ouvrait un site avec connexion Discord (OAuth « SentriX souhaite accéder à votre
compte »). Désormais :

1. « Se vérifier » ouvre, en privé, un petit test : cliquer sur l'émoji nommé
   parmi quatre (un bot qui clique au hasard échoue trois fois sur quatre) ;
2. la bonne réponse lance EXACTEMENT les contrôles du site
   (web.public_verification_v120._complete_verification) : règlement, âge du
   compte, délai d'arrivée, verrou après échecs, analyse adaptative, rôles, MP,
   journal ;
3. trop d'erreurs verrouillent la vérification quelques minutes, comme sur le site.

Aucun site, aucune autorisation de compte, aucune donnée en plus.
"""
from __future__ import annotations

import json
import logging
import secrets
from typing import Any

import discord

logger = logging.getLogger("bot.verification-discord")

#: Même identifiant que le bouton « Commencer » des anciens panneaux : la vue
#: persistante V51 (cogs/verification_polish_v51.py) le reprend après un redémarrage.
BOUTON_DEMARRER = "sentrix:verification:v51:start"

CHOIX = (
    ("🍎", "pomme"), ("🍌", "banane"), ("🍇", "raisin"), ("🍒", "cerise"),
    ("🍋", "citron"), ("🍉", "pastèque"), ("🥕", "carotte"), ("🍓", "fraise"),
    ("🍐", "poire"), ("🥝", "kiwi"), ("🍍", "ananas"), ("🥥", "noix de coco"),
)
CHOIX_PAR_TEST = 4
DUREE_TEST = 120

_ARTICLES = {
    "pomme": "la", "banane": "la", "cerise": "la", "pastèque": "la", "carotte": "la",
    "fraise": "la", "poire": "la", "noix de coco": "la",
}


def _avec_article(nom: str) -> str:
    article = _ARTICLES.get(nom, "le")
    return f"{article} **{nom}**"


def tirer_test(alea: secrets.SystemRandom | None = None) -> tuple[tuple[str, str], list[tuple[str, str]]]:
    """La réponse attendue et les quatre propositions, dans un ordre aléatoire."""
    alea = alea or secrets.SystemRandom()
    propositions = alea.sample(CHOIX, CHOIX_PAR_TEST)
    return alea.choice(propositions), propositions


def message_d_erreur(reponse: Any) -> str:
    """Le texte d'une erreur de _complete_verification (une réponse JSON aiohttp)."""
    try:
        corps = json.loads(getattr(reponse, "body", b"") or b"{}")
        texte = str(corps.get("error") or "").strip()
        if texte:
            return texte
    except Exception:  # noqa: BLE001
        pass
    return "La vérification n'a pas pu aboutir. Réessayez dans un instant."


def _carte(titre: str, texte: str, *, couleur: int, rangee: discord.ui.ActionRow | None = None):
    vue = discord.ui.LayoutView(timeout=DUREE_TEST)
    carte = discord.ui.Container(accent_colour=discord.Colour(couleur))
    carte.add_item(discord.ui.TextDisplay(f"### {titre}\n{texte}"))
    if rangee is not None:
        carte.add_item(rangee)
    vue.add_item(carte)
    return vue


class TestHumain:
    """Un test en cours pour UN membre : une bonne réponse, quatre boutons."""

    def __init__(self, bot, guild: discord.Guild, membre_id: int, *, reglement: bool):
        self.bot = bot
        self.guild = guild
        self.membre_id = int(membre_id)
        self.reglement = reglement
        self.attendu, self.propositions = tirer_test()
        self.termine = False

    def vue(self, titre: str = "🔐 Vérification") -> discord.ui.LayoutView:
        rangee = discord.ui.ActionRow()
        for emoji, nom in self.propositions:
            bouton = discord.ui.Button(emoji=emoji, style=discord.ButtonStyle.secondary)
            bouton.callback = self._reponse(nom)
            rangee.add_item(bouton)
        texte = f"Cliquez sur {_avec_article(self.attendu[1])}."
        if self.reglement:
            texte += "\n-# En répondant, vous acceptez le règlement du serveur."
        return _carte(titre, texte, couleur=0x5865F2, rangee=rangee)

    def _reponse(self, nom: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.membre_id or self.termine:
                return await interaction.response.defer()
            self.termine = True
            if nom != self.attendu[1]:
                return await self._mauvaise_reponse(interaction)
            return await self._bonne_reponse(interaction)

        return callback

    async def _mauvaise_reponse(self, interaction: discord.Interaction):
        from web import public_verification_v120 as web_verif

        verrou = await web_verif._record_failure(self.bot, self.guild.id, self.membre_id)
        if verrou > 0:
            return await interaction.response.edit_message(view=_carte(
                "⛔ Trop d'erreurs",
                f"Réessayez dans environ **{max(1, (verrou + 59) // 60)} minute(s)**.",
                couleur=0xED4245,
            ))
        suivant = TestHumain(self.bot, self.guild, self.membre_id, reglement=self.reglement)
        return await interaction.response.edit_message(
            view=suivant.vue(titre="❌ Mauvaise réponse, encore une fois")
        )

    async def _bonne_reponse(self, interaction: discord.Interaction):
        from web import public_verification_v120 as web_verif

        await interaction.response.edit_message(view=_carte(
            "⏳ Vérification en cours", "SentriX contrôle votre compte, quelques secondes…",
            couleur=0xFEE75C,
        ))
        membre = self.guild.get_member(self.membre_id)
        if membre is None:
            try:
                membre = await self.guild.fetch_member(self.membre_id)
            except (discord.NotFound, discord.HTTPException):
                membre = None
        if membre is None:
            return await interaction.edit_original_response(view=_carte(
                "❌ Vérification impossible", "Vous n'êtes plus membre de ce serveur.", couleur=0xED4245,
            ))
        try:
            resultat, erreur = await web_verif._complete_verification(
                self.bot, self.guild, membre, accept_rules=True, methode="discord+challenge",
            )
        except Exception:
            logger.exception("Vérification Discord en échec guild=%s user=%s", self.guild.id, self.membre_id)
            resultat, erreur = None, None
        if resultat is not None:
            salon = resultat.get("channel_id")
            suite = f"\nRendez-vous dans <#{salon}>." if salon else ""
            texte = (
                "Vous étiez déjà vérifié." if resultat.get("already_verified")
                else f"Bienvenue ! Vous avez maintenant accès au serveur.{suite}"
            )
            return await interaction.edit_original_response(
                view=_carte("✅ Vérifié", texte, couleur=0x57F287)
            )
        return await interaction.edit_original_response(view=_carte(
            "❌ Vérification non terminée",
            message_d_erreur(erreur) if erreur is not None
            else "La vérification n'a pas pu aboutir. Réessayez dans un instant.",
            couleur=0xED4245,
        ))


async def demarrer(interaction: discord.Interaction) -> None:
    """Ouvre le test en privé pour la personne qui a cliqué."""
    guild = interaction.guild
    if guild is None:
        return await interaction.response.send_message(
            "La vérification fonctionne uniquement dans un serveur.", ephemeral=True,
        )
    reglement = False
    try:
        from utils import rules_flow

        reglement = bool(
            await rules_flow.current_rules_record(interaction.client, guild.id)
            and not await rules_flow.has_accepted_current_rules(interaction.client, guild.id, interaction.user.id)
        )
    except Exception:  # noqa: BLE001 — sans règlement lisible, le test reste le même
        logger.debug("Règlement illisible guild=%s", guild.id, exc_info=True)
    test = TestHumain(interaction.client, guild, interaction.user.id, reglement=reglement)
    await interaction.response.send_message(view=test.vue(), ephemeral=True)


async def depuis_le_panneau(interaction: discord.Interaction) -> None:
    """Bouton « Se vérifier » du panneau : passe par le moteur actif (contrôles V71)."""
    moteur = interaction.client.get_cog("HoneypotVerification")
    demarreur = getattr(moteur, "start_human_verification", None)
    if callable(demarreur):
        return await demarreur(interaction)
    return await demarrer(interaction)


__all__ = ["BOUTON_DEMARRER", "CHOIX", "TestHumain", "demarrer", "depuis_le_panneau", "tirer_test"]
