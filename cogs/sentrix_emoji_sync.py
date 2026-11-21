"""Téléverse la bibliothèque d'icônes SentriX au démarrage, sans bloquer.

Les icônes sont des emojis d'APPLICATION : téléversées une fois sur le compte
du bot, elles s'affichent sur les 28 serveurs sans y occuper le moindre
emplacement. Voir ``utils/sentrix_emojis`` pour le détail de ce choix.

**Ce module ne doit jamais empêcher SentriX de démarrer.** Le premier
démarrage pousse plus de cent fichiers ; si Discord limite, si le réseau
tombe, ou si le jeton n'a pas la portée nécessaire, le bot continue et les
panneaux affichent les replis sobres. Un panneau sans icône reste utilisable ;
un bot qui ne démarre pas ne l'est pas.

La tâche part donc en arrière-plan après ``on_ready``, et toute exception y est
absorbée.
"""
from __future__ import annotations

import asyncio
import logging
import re

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_emojis
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.sentrix-emoji-sync")


class SentriXEmojiSync(commands.Cog):
    """Synchronise le pack d'icônes une fois la session Discord ouverte."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tache: asyncio.Task | None = None

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # on_ready peut se déclencher plusieurs fois (reconnexion de gateway).
        # Sans cette garde, chaque reconnexion relancerait un balayage complet.
        if self._tache is not None and not self._tache.done():
            return
        self._tache = asyncio.create_task(
            self._synchroniser(), name="sentrix-emoji-sync"
        )

    async def _synchroniser(self) -> None:
        try:
            bilan = await sentrix_emojis.synchroniser(self.bot)
        except Exception:
            # Déjà absorbé dans synchroniser(), mais une tâche de fond qui
            # meurt sans trace est un angle mort : on le dit.
            logger.exception("Synchronisation des icônes SentriX interrompue.")
            return
        if bilan.get("echecs"):
            logger.warning(
                "Icônes SentriX : %s échec(s) de téléversement, replis actifs "
                "pour ces icônes.",
                bilan["echecs"],
            )

    async def cog_unload(self) -> None:
        if self._tache is not None and not self._tache.done():
            self._tache.cancel()


#: Longueur maximale d'un message Discord, moins une marge pour l'en-tête.
LIMITE_MESSAGE = 1900
#: Au-delà, le catalogue part en privé : personne ne veut quatre cents icônes
#: déroulées dans son salon.
MAX_EN_SALON = 40


#: Les emojis d'application sont servis par le CDN de Discord à partir de leur
#: seul identifiant. Le lien est donc déductible du marquage, sans aucun appel.
_ID_RE = re.compile(r"<(a?):[A-Za-z0-9_]+:(\d+)>")


def lien(marquage: str) -> str:
    """Lien direct vers l'image de l'icône, ou chaîne vide si illisible.

    C'est ce qui sert vraiment : un lien s'ouvre, se télécharge et se colle
    dans une image d'embed ou sur un autre serveur. Le marquage, lui, ne
    s'affiche que dans un message envoyé par SentriX.
    """
    trouve = _ID_RE.fullmatch(str(marquage or "").strip())
    if not trouve:
        return ""
    anime, identifiant = trouve.groups()
    return f"https://cdn.discordapp.com/emojis/{identifiant}.{'gif' if anime else 'png'}"


def _lignes(catalogue: dict[str, str], *, codes: bool = False) -> list[str]:
    """Une ligne par icône : rendu, nom, puis le lien direct — ou le code.

    Le lien par défaut : c'est lui qui sert vraiment, parce qu'il s'ouvre et se
    réutilise partout. Le code n'a d'usage que dans un texte que SentriX
    affiche lui-même, donc il est derrière un mot-clé.
    """
    if codes:
        return [f"{marquage} `{nom}` `{marquage}`" for nom, marquage in catalogue.items()]
    return [
        f"{marquage} `{nom}` {lien(marquage) or f'`{marquage}`'}"
        for nom, marquage in catalogue.items()
    ]


def _pages(lignes: list[str]) -> list[str]:
    """Découpe en messages qui tiennent dans la limite de Discord.

    Jamais au milieu d'une ligne : un marquage coupé en deux s'afficherait en
    texte brut au lieu de l'icône, dans les deux moitiés.
    """
    pages: list[str] = []
    courante: list[str] = []
    taille = 0
    for ligne in lignes:
        if courante and taille + len(ligne) + 1 > LIMITE_MESSAGE:
            pages.append("\n".join(courante))
            courante, taille = [], 0
        courante.append(ligne)
        taille += len(ligne) + 1
    if courante:
        pages.append("\n".join(courante))
    return pages


class SentriXEmojiCatalogue(commands.Cog):
    """« Donne les emojis de SentriX » (21/11/2026).

    Rien ne permettait de les voir : ils sont posés par le code, nom par nom,
    et aucune commande ne les listait.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        # Pas d'alias « emoji-list » : cogs/utility.py le porte déjà, pour les
        # emojis DU SERVEUR. Un alias en doublon fait refuser le cog entier au
        # chargement, donc toutes les icônes auraient disparu avec lui.
        name="emojis", aliases=["icones", "sentrix-emojis"],
        description="Lister les icônes SentriX, avec leur code à copier.",
        with_app_command=False,
    )
    @discord.app_commands.describe(
        recherche="Un mot à chercher dans les noms, « animes », « fixes », ou « tout »",
    )
    async def emojis(self, ctx: commands.Context, *, recherche: str = "") -> None:
        demande = str(recherche or "").strip()
        # « codes » en dernier mot : on rend les marquages au lieu des liens.
        codes = demande.casefold().endswith("codes")
        if codes:
            demande = demande[: -len("codes")].strip()
        terme = demande.casefold()
        if terme in {"animes", "animés", "anime", "animé", "gif"}:
            catalogue = sentrix_emojis.catalogue(animes=True)
            titre = "Icônes animées"
        elif terme in {"fixes", "fixe", "statiques", "png"}:
            catalogue = sentrix_emojis.catalogue(animes=False)
            titre = "Icônes fixes"
        elif terme in {"", "tout", "all", "toutes"}:
            catalogue = sentrix_emojis.catalogue()
            titre = "Toutes les icônes SentriX"
        else:
            complet = sentrix_emojis.catalogue()
            catalogue = {n: m for n, m in complet.items() if terme in n.casefold()}
            titre = f"Icônes contenant « {demande} »"

        if not catalogue:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(
                "Aucune icône ne correspond." if terme not in {"", "tout", "all", "toutes"}
                else "Les icônes ne sont pas encore téléversées. Réessayez dans une minute."
            )))

        animes = sum(1 for m in catalogue.values() if m.startswith("<a:"))
        entete = (
            f"## {titre}\n**{len(catalogue)} icônes**, dont {animes} animées.\n"
            + ("Chaque ligne donne le code à coller dans un texte que SentriX affiche "
               "lui-même. Collé dans un message personnel, Discord le laisse en texte : "
               "un emoji d'application n'appartient qu'au bot qui le possède."
               if codes else
               "Chaque ligne donne le lien direct de l'image : il s'ouvre, se télécharge "
               "et se réutilise ailleurs.\n"
               f"-# Pour les codes à coller : `{ctx.clean_prefix}emojis codes`.")
        )
        pages = _pages(_lignes(catalogue, codes=codes))

        # En privé on déroule tout ; en salon on s'arrête, pour ne pas noyer la
        # conversation sous quatre cents lignes que personne n'a demandées.
        en_prive = ctx.guild is None
        destination = ctx.author if not en_prive and len(catalogue) > MAX_EN_SALON else ctx
        if destination is not ctx:
            try:
                await destination.send(entete)
                for page in pages:
                    await destination.send(page)
            except discord.Forbidden:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(
                    f"**{len(catalogue)} icônes, c'est trop pour un salon**, et les "
                    "messages privés sont fermés.\n"
                    f"Ouvrez-les, ou filtrez : `{ctx.clean_prefix}emojis bouclier`, "
                    f"`{ctx.clean_prefix}emojis animes`."
                )))
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.success(
                f"**{len(catalogue)} icônes envoyées en privé.**"
            )))

        await ctx.send(entete)
        for page in pages:
            await ctx.send(page)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SentriXEmojiSync(bot))
    await bot.add_cog(SentriXEmojiCatalogue(bot))
