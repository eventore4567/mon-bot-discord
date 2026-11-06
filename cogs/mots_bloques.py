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
#: 07/11/2026 : « la possibilité aussi dans mots interdits pour les liens ».
#: Une règle de liens bloque toute adresse web et toute invitation Discord avant
#: l'envoi ; les sites listés restent autorisés (liste d'autorisation Discord).
MOTIFS_LIENS = [
    r"(?i)\bhttps?://\S+",
    r"(?i)\b(?:www\.)\S+",
    r"(?i)\bdiscord(?:app)?\.(?:gg|com/invite)/\S+",
]
SITES_MAX = 100
#: 07/11/2026 : « choisir si on veut mute ou pas » — sans choix, aucun mute.
DUREES_MUTE = (("Aucune (bloquer seulement)", 0), ("Mute 1 minute", 60), ("Mute 5 minutes", 300),
               ("Mute 10 minutes", 600), ("Mute 1 heure", 3600), ("Mute 1 jour", 86400))


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


def est_regle_liens(regle) -> bool:
    return bool(getattr(getattr(regle, "trigger", None), "regex_patterns", None))


def sites_de(regle) -> list[str]:
    return list(getattr(getattr(regle, "trigger", None), "allow_list", None) or [])


def lire_sites(texte: str) -> list[str]:
    """« youtube.com, tenor.com » -> ['*youtube.com*', '*tenor.com*'] (forme Discord)."""
    sites = []
    for mot in lire_mots(texte):
        mot = re.sub(r"^https?://", "", mot).strip("*/ ")
        if mot and f"*{mot}*" not in sites:
            sites.append(f"*{mot}*")
    return sites[:SITES_MAX]


def resume(regle) -> str:
    if est_regle_liens(regle):
        sites = ", ".join(s.strip("*") for s in sites_de(regle))
        return f"Liens bloqués (autorisés : {sites or 'aucun site'})"
    return ", ".join(mots_de(regle))


def declencheur(mots: list[str] | None = None, *, liens: bool = False, sites: list[str] | None = None):
    if liens:
        return discord.AutoModTrigger(regex_patterns=list(MOTIFS_LIENS), allow_list=list(sites or []))
    return discord.AutoModTrigger(keyword_filter=list(mots or []))


def mute_de(regle) -> int:
    """Durée du mute ajouté par la règle (0 = aucun)."""
    for action in getattr(regle, "actions", None) or ():
        duree = getattr(action, "duration", None)
        if duree:
            return int(duree.total_seconds())
    return 0


def actions(message: str, mute: int = 0) -> list:
    liste = [discord.AutoModRuleAction(custom_message=message[:MESSAGE_MAX] or None)]
    if mute:
        from datetime import timedelta

        liste.append(discord.AutoModRuleAction(duration=timedelta(seconds=int(mute))))
    return liste


def message_de(regle) -> str:
    for action in getattr(regle, "actions", None) or ():
        texte = getattr(action, "custom_message", None)
        if texte:
            return str(texte)
    return ""


async def creer(
    guild: discord.Guild, mots: list[str], message: str, *, liens: bool = False,
    sites: list[str] | None = None,
) -> discord.AutoModRule:
    existantes = await lister(guild)
    if len(existantes) >= MAX_REGLES:
        raise ValueError(f"Discord limite à {MAX_REGLES} règles de mots bloqués.")
    pris = {_numero(r.name) for r in existantes}
    numero = next(n for n in range(1, MAX_REGLES + 1) if n not in pris)
    return await guild.create_automod_rule(
        name=f"{PREFIXE} {numero}",
        event_type=discord.AutoModRuleEventType.message_send,
        trigger=declencheur(mots, liens=liens, sites=sites),
        actions=actions(message),
        enabled=True,
        reason=RAISON,
    )


async def modifier(regle, *, mots: list[str] | None = None, message: str = "",
                   sites: list[str] | None = None):
    """Remplace les mots (ou les sites autorisés d'une règle de liens) et le message."""
    liens = est_regle_liens(regle)
    return await regle.edit(
        trigger=declencheur(mots, liens=liens, sites=sites),
        actions=actions(message, mute_de(regle)),
        reason=RAISON,
    )


async def changer_mute(regle, secondes: int):
    """Garde mots et message, change seulement la sanction (0 = pas de mute)."""
    return await regle.edit(actions=actions(message_de(regle), secondes), reason=RAISON)


async def _repondre_erreur(interaction: discord.Interaction, exc: Exception, guild_id: int) -> None:
    if isinstance(exc, ValueError):
        texte = str(exc)
    elif isinstance(exc, discord.Forbidden):
        texte = "Il me faut la permission **Gérer le serveur** pour modifier les règles."
    else:
        logger.warning("Règle de mots bloqués refusée guild=%s : %s", guild_id, exc)
        texte = "Discord a refusé la règle (limite de règles atteinte ou mot invalide)."
    await interaction.response.send_message(texte, ephemeral=True)


class LiensModal(discord.ui.Modal, title="Bloquer les liens"):
    sites = discord.ui.TextInput(
        label="Sites autorisés (facultatif, séparés par ,)",
        placeholder="youtube.com, tenor.com, twitch.tv",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=False,
    )
    message = discord.ui.TextInput(
        label="Message affiché à la personne",
        placeholder="Les liens sont interdits ici, merci d'utiliser le salon #pub.",
        max_length=MESSAGE_MAX,
        required=False,
    )

    def __init__(self, owner: "MotsBloquesView", regle=None):
        super().__init__(title="Modifier le blocage des liens" if regle is not None else "Bloquer les liens")
        self.owner = owner
        self.regle = regle
        if regle is not None:
            self.sites.default = ", ".join(s.strip("*") for s in sites_de(regle))[:2000]
            self.message.default = message_de(regle)[:MESSAGE_MAX]

    async def on_submit(self, interaction: discord.Interaction):
        sites = lire_sites(self.sites.value)
        message = str(self.message.value or "").strip()
        try:
            if self.regle is not None:
                await modifier(self.regle, message=message, sites=sites)
            else:
                await creer(self.owner.guild, [], message, liens=True, sites=sites)
        except (ValueError, discord.HTTPException) as exc:
            return await _repondre_erreur(interaction, exc, self.owner.guild.id)
        await self.owner.rafraichir(interaction)


class ModifierModal(discord.ui.Modal, title="Modifier la règle"):
    """Mots pré-remplis : on en ajoute, on en retire, on change le message."""

    mots = discord.ui.TextInput(
        label="Mots-clés (retirez ou ajoutez, séparés par ,)",
        style=discord.TextStyle.paragraph,
        max_length=4000,
    )
    message = discord.ui.TextInput(
        label="Message affiché à la personne",
        max_length=MESSAGE_MAX,
        required=False,
    )

    def __init__(self, owner: "MotsBloquesView", regle):
        super().__init__()
        self.owner = owner
        self.regle = regle
        self.mots.default = ", ".join(mots_de(regle))[:4000]
        self.message.default = message_de(regle)[:MESSAGE_MAX]

    async def on_submit(self, interaction: discord.Interaction):
        mots = lire_mots(self.mots.value)
        if not mots:
            return await interaction.response.send_message(
                "Gardez au moins un mot-clé, ou supprimez la règle.", ephemeral=True,
            )
        try:
            await modifier(self.regle, mots=mots, message=str(self.message.value or "").strip())
        except (ValueError, discord.HTTPException) as exc:
            return await _repondre_erreur(interaction, exc, self.owner.guild.id)
        await self.owner.rafraichir(interaction)


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
        except (ValueError, discord.HTTPException) as exc:
            return await _repondre_erreur(interaction, exc, self.owner.guild.id)
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
        liens = discord.ui.Button(label="Bloquer les liens", style=discord.ButtonStyle.primary, row=0)
        liens.callback = self._liens
        liens.disabled = len(self.regles) >= MAX_REGLES or any(est_regle_liens(r) for r in self.regles)
        self.add_item(liens)
        if self.regles:
            choix = discord.ui.Select(
                placeholder="Choisir une règle à modifier",
                options=[
                    discord.SelectOption(
                        label=f"Règle {_numero(r.name)} : {resume(r)}"[:100],
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
            actuel = mute_de(regle)
            sanction = discord.ui.Select(
                placeholder="Sanction en plus du blocage",
                options=[
                    discord.SelectOption(label=nom, value=str(sec), default=sec == actuel)
                    for nom, sec in DUREES_MUTE
                ],
                row=3,
            )
            sanction.callback = self._sanction
            self.add_item(sanction)
            changer = discord.ui.Button(
                label="Modifier les sites autorisés" if est_regle_liens(regle) else "Modifier les mots",
                style=discord.ButtonStyle.primary, row=4,
            )
            changer.callback = self._modifier
            self.add_item(changer)
            supprimer = discord.ui.Button(label="Supprimer la règle", style=discord.ButtonStyle.danger, row=4)
            supprimer.callback = self._supprimer
            self.add_item(supprimer)

    def embed(self) -> discord.Embed:
        e = discord.Embed(
            title="Mots bloqués avant l'envoi",
            description=(
                "Un message qui contient un de ces mots n'est **jamais publié** : la personne "
                "voit seulement votre message. Les administrateurs ne sont pas bloqués.\n"
                "-# Astuce : `*sab*` bloque aussi « sabotage » ; `sab` seul ne bloque que le mot.\n"
                "-# **Bloquer les liens** : toute adresse web ou invitation, sauf les sites autorisés."
            ),
            colour=discord.Colour.blurple(),
        )
        if not self.regles:
            e.add_field(name="Règles", value="Aucune règle pour l'instant.", inline=False)
        for r in self.regles:
            salons = ", ".join(f"<#{c}>" for c in getattr(r, "exempt_channel_ids", ()) or ()) or "aucun"
            contenu = (
                f"**Liens bloqués** · sites autorisés : "
                f"{', '.join(s.strip('*') for s in sites_de(r))[:600] or 'aucun'}"
                if est_regle_liens(r) else f"**Mots :** {', '.join(mots_de(r))[:700]}"
            )
            e.add_field(
                name=f"Règle {_numero(r.name)}",
                value=(
                    f"{contenu}\n"
                    f"**Sanction :** {dict((s, n) for n, s in DUREES_MUTE).get(mute_de(r), f'mute {mute_de(r)} s')}\n"
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

    async def _sanction(self, interaction: discord.Interaction):
        regle = self._regle()
        if regle is None:
            return await interaction.response.defer()
        try:
            await changer_mute(regle, int(interaction.data["values"][0]))
        except (discord.Forbidden, discord.HTTPException):
            return await interaction.response.send_message(
                "Discord a refusé : il me faut **Modérer les membres** pour muter.", ephemeral=True,
            )
        await self.rafraichir(interaction)

    async def _liens(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LiensModal(self))

    async def _modifier(self, interaction: discord.Interaction):
        regle = self._regle()
        if regle is None:
            return await interaction.response.defer()
        if est_regle_liens(regle):
            return await interaction.response.send_modal(LiensModal(self, regle))
        await interaction.response.send_modal(ModifierModal(self, regle))

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


__all__ = [
    "PREFIXE", "MAX_REGLES", "MOTIFS_LIENS", "lire_mots", "lire_sites", "lister", "creer", "modifier",
    "est_regle_liens", "MotsBloquesView", "ouvrir",
]
