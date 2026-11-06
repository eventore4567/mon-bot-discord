"""Mots bloqués AVANT l'envoi, réglés dans /setup → Sécurité (07/11/2026).

Demande : « config le truc avant d'envoyer le message, ça bloque avec un mot-clé
qu'on a configuré dans sécurité, puis le message de pourquoi on veut pas ; ou
plusieurs mots-clés » (capture : « POUR PARLER DE SAB, MERCI D'UTILISER LE SALON
PRÉVU À CET EFFET »).

C'est l'AutoMod natif de Discord : le message n'est jamais publié et l'auteur voit
le message choisi. SentriX crée et lit directement ses règles « SentriX • Mots
bloqués N » — aucune base de données : Discord garde les mots, le message et les
salons autorisés. Discord exempte déjà de l'AutoMod les membres avec Administrateur
ou Gérer le serveur. Discord limite à 6 règles de mots-clés par serveur.
"""
from __future__ import annotations

import logging
import re

import discord

from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.mots-bloques")

PREFIXE = "SentriX • Mots bloqués"
MAX_REGLES = 6
MESSAGE_MAX = 150
MOT_MAX = 60
MOTS_MAX = 1000
RAISON = "SentriX : mots bloqués configurés dans /setup"


def lire_mots(texte: str) -> list[str]:
    """« sab, trade ; vente » -> ['sab', 'trade', 'vente'] (sans doublon, ≤ 60 caractères)."""
    vus: list[str] = []
    for brut in re.split(r"[,;\n]+", str(texte or "")):
        mot = brut.strip().casefold()[:MOT_MAX]
        if mot and mot not in vus:
            vus.append(mot)
    return vus[:MOTS_MAX]


def _numero(nom: str) -> int:
    try:
        return int(str(nom).rsplit(" ", 1)[-1])
    except ValueError:
        return 0


async def lister(guild: discord.Guild) -> list[discord.AutoModRule]:
    me = getattr(guild, "me", None)
    regles = await guild.fetch_automod_rules()
    return sorted(
        (
            r for r in regles
            if str(r.name).startswith(PREFIXE)
            and (me is None or int(getattr(r, "creator_id", 0) or 0) == me.id)
        ),
        key=lambda r: _numero(r.name),
    )


def mots_de(regle) -> list[str]:
    return list(getattr(getattr(regle, "trigger", None), "keyword_filter", None) or [])


def message_de(regle) -> str:
    for action in getattr(regle, "actions", None) or ():
        texte = getattr(action, "custom_message", None)
        if texte:
            return str(texte)
    return ""


async def creer(guild: discord.Guild, mots: list[str], message: str) -> discord.AutoModRule:
    existantes = await lister(guild)
    if len(existantes) >= MAX_REGLES:
        raise ValueError(f"Discord limite à {MAX_REGLES} règles de mots bloqués.")
    pris = {_numero(r.name) for r in existantes}
    numero = next(n for n in range(1, MAX_REGLES + 1) if n not in pris)
    return await guild.create_automod_rule(
        name=f"{PREFIXE} {numero}",
        event_type=discord.AutoModRuleEventType.message_send,
        trigger=discord.AutoModTrigger(keyword_filter=mots),
        actions=[discord.AutoModRuleAction(custom_message=message[:MESSAGE_MAX] or None)],
        enabled=True,
        reason=RAISON,
    )


class AjoutModal(discord.ui.Modal, title="Mots bloqués — nouvelle règle"):
    mots = discord.ui.TextInput(
        label="Mots-clés (séparés par des virgules)",
        placeholder="sab, trade, vente de compte",
        style=discord.TextStyle.paragraph,
        max_length=2000,
    )
    message = discord.ui.TextInput(
        label="Message affiché à la personne",
        placeholder="Pour parler de SAB, merci d'utiliser le salon prévu à cet effet.",
        max_length=MESSAGE_MAX,
        required=False,
    )

    def __init__(self, owner: "MotsBloquesView"):
        super().__init__()
        self.owner = owner

    async def on_submit(self, interaction: discord.Interaction):
        mots = lire_mots(self.mots.value)
        if not mots:
            return await interaction.response.send_message("Écrivez au moins un mot-clé.", ephemeral=True)
        try:
            await creer(self.owner.guild, mots, str(self.message.value or "").strip())
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Il me faut la permission **Gérer le serveur** pour créer la règle.", ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Règle de mots bloqués refusée guild=%s : %s", self.owner.guild.id, exc)
            return await interaction.response.send_message(
                "Discord a refusé la règle (limite de règles atteinte ou mot invalide).", ephemeral=True,
            )
        await self.owner.rafraichir(interaction)


class MotsBloquesView(discord.ui.View):
    """Panneau privé : ajouter, choisir, autoriser dans des salons, supprimer."""

    def __init__(self, guild: discord.Guild, author_id: int, regles: list):
        super().__init__(timeout=600)
        self.guild = guild
        self.author_id = int(author_id)
        self.regles = list(regles)
        self.choisie: int | None = None
        self._construire()

    def _regle(self):
        return next((r for r in self.regles if r.id == self.choisie), None)

    def _construire(self) -> None:
        self.clear_items()
        ajouter = discord.ui.Button(label="Ajouter une règle", style=discord.ButtonStyle.success, row=0)
        ajouter.callback = self._ajouter
        ajouter.disabled = len(self.regles) >= MAX_REGLES
        self.add_item(ajouter)
        if self.regles:
            choix = discord.ui.Select(
                placeholder="Choisir une règle à modifier",
                options=[
                    discord.SelectOption(
                        label=f"Règle {_numero(r.name)} : {', '.join(mots_de(r))}"[:100],
                        value=str(r.id), default=r.id == self.choisie,
                    )
                    for r in self.regles
                ],
                row=1,
            )
            choix.callback = self._choisir
            self.add_item(choix)
        regle = self._regle()
        if regle is not None:
            salons = discord.ui.ChannelSelect(
                placeholder="Salons où ces mots restent autorisés",
                channel_types=[discord.ChannelType.text, discord.ChannelType.news],
                min_values=0, max_values=25, row=2,
            )
            salons.callback = self._salons
            self.add_item(salons)
            supprimer = discord.ui.Button(label="Supprimer la règle", style=discord.ButtonStyle.danger, row=3)
            supprimer.callback = self._supprimer
            self.add_item(supprimer)

    def embed(self) -> discord.Embed:
        e = discord.Embed(
            title="Mots bloqués avant l'envoi",
            description=(
                "Un message qui contient un de ces mots n'est **jamais publié** : la personne "
                "voit seulement votre message. Les administrateurs ne sont pas bloqués.\n"
                "-# Astuce : `*sab*` bloque aussi « sabotage » ; `sab` seul ne bloque que le mot."
            ),
            colour=discord.Colour.blurple(),
        )
        if not self.regles:
            e.add_field(name="Règles", value="Aucune règle pour l'instant.", inline=False)
        for r in self.regles:
            salons = ", ".join(f"<#{c}>" for c in getattr(r, "exempt_channel_ids", ()) or ()) or "aucun"
            e.add_field(
                name=f"Règle {_numero(r.name)}",
                value=(
                    f"**Mots :** {', '.join(mots_de(r))[:700]}\n"
                    f"**Message :** {message_de(r) or '(message Discord par défaut)'}\n"
                    f"**Autorisés dans :** {salons}"
                )[:1024],
                inline=False,
            )
        return e

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce panneau ne vous appartient pas.", ephemeral=True)
            return False
        return True

    async def rafraichir(self, interaction: discord.Interaction) -> None:
        try:
            self.regles = await lister(self.guild)
        except (discord.Forbidden, discord.HTTPException):
            pass
        self._construire()
        await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(self.embed()), self))

    async def _ajouter(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AjoutModal(self))

    async def _choisir(self, interaction: discord.Interaction):
        self.choisie = int(interaction.data["values"][0])
        self._construire()
        await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(self.embed()), self))

    async def _salons(self, interaction: discord.Interaction):
        regle = self._regle()
        if regle is None:
            return await interaction.response.defer()
        ids = [int(v) for v in interaction.data.get("values", [])]
        try:
            await regle.edit(exempt_channels=[discord.Object(id=i) for i in ids], reason=RAISON)
        except (discord.Forbidden, discord.HTTPException):
            return await interaction.response.send_message("Discord a refusé la modification.", ephemeral=True)
        await self.rafraichir(interaction)

    async def _supprimer(self, interaction: discord.Interaction):
        regle = self._regle()
        if regle is None:
            return await interaction.response.defer()
        try:
            await regle.delete(reason=RAISON)
        except (discord.Forbidden, discord.HTTPException):
            return await interaction.response.send_message("Discord a refusé la suppression.", ephemeral=True)
        self.choisie = None
        await self.rafraichir(interaction)


async def ouvrir(interaction: discord.Interaction, guild: discord.Guild) -> None:
    """Ouvre le panneau privé depuis /setup."""
    try:
        regles = await lister(guild)
    except discord.Forbidden:
        return await panels.envoyer(
            interaction.response,
            panels.depuis_embed(embeds.error("Il me faut la permission **Gérer le serveur**.")),
            ephemere=True,
        )
    except discord.HTTPException:
        regles = []
    vue = MotsBloquesView(guild, interaction.user.id, regles)
    await panels.envoyer(
        interaction.response, panels.avec_composants(panels.depuis_embed(vue.embed()), vue), ephemere=True,
    )


__all__ = ["PREFIXE", "MAX_REGLES", "lire_mots", "lister", "creer", "MotsBloquesView", "ouvrir"]
