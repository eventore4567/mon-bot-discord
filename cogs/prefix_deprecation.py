"""Avertit chaque utilisateur de commandes « + » que le préfixe va disparaître.

28/10/2026 (Jayden) : SentriX passe à 100 % de commandes « / ». Chaque personne
qui lance une commande « + » voit, une fois par jour au plus, une ligne courte
dans le style des avis Discord : la date de retrait, le temps restant (horodatage
relatif Discord) et la commande « / » à utiliser quand elle existe.

Branché sur ``bot.invoke`` (le passage obligé des commandes préfixées ; les
commandes « / » n'y passent pas) plutôt que sur un écouteur de plus : le budget
d'écouteurs est plafonné (tests/test_runtime_hygiene_gates).
"""
from __future__ import annotations

import datetime as dt
import logging
import time

import discord
from discord.ext import commands

logger = logging.getLogger("bot.prefix-deprecation")

#: Date annoncée du retrait des commandes « + » (UTC).
DATE_RETRAIT = dt.datetime(2026, 11, 30, tzinfo=dt.timezone.utc)
DATE_LISIBLE = "30 novembre 2026"
#: Une fois par jour et par personne : un avis, pas un harcèlement.
INTERVALLE_S = 24 * 3600
#: L'avis s'efface seul, comme une notification.
EFFACER_APRES_S = 120

_dernier_avis: dict[tuple[int, int], float] = {}


def actif() -> bool:
    """Coupé par le harnais e2e (SENTRIX_AVIS_PREFIXE=0) : l'avis est un message de
    plus après chaque « + », et les parcours repèrent le panneau du bot comme
    « dernier message ». Lu à l'appel : discord.py recharge l'extension comme un
    nouveau module, un drapeau posé avant le chargement serait perdu.
    tools/prefix_deprecation_e2e.py le teste explicitement, allumé."""
    import os

    return os.environ.get("SENTRIX_AVIS_PREFIXE", "1") != "0"


def equivalent_slash(bot: commands.Bot, commande: commands.Command) -> str | None:
    """La commande « / » à proposer, en mention cliquable si possible."""
    from utils import slash_ids
    from utils.access_matrix import MIRROR_TARGETS

    nom = commande.qualified_name
    # +logsearch → /logs search : la correspondance inverse de MIRROR_TARGETS.
    inverse = {cible: chemin for chemin, cible in MIRROR_TARGETS.items()}
    chemin = inverse.get(nom, nom)
    racine = chemin.split(" ")[0]
    if bot.tree.get_command(racine) is None:
        return None
    return slash_ids.mention(chemin)


def texte_avis(bot: commands.Bot, commande: commands.Command | None) -> str:
    horodatage = int(DATE_RETRAIT.timestamp())
    suite = None
    if commande is not None:
        try:
            suite = equivalent_slash(bot, commande)
        except Exception:
            logger.debug("Équivalent / introuvable pour %s", getattr(commande, "qualified_name", "?"), exc_info=True)
    conseil = f"Utilisez {suite} à la place." if suite else "Utilisez les commandes `/`."
    return (
        f"⚠️ **Les commandes `+` seront retirées le {DATE_LISIBLE}** (<t:{horodatage}:R>). {conseil}"
    )


def doit_avertir(guild_id: int, user_id: int, maintenant: float | None = None) -> bool:
    maintenant = time.time() if maintenant is None else maintenant
    if maintenant >= DATE_RETRAIT.timestamp() + 7 * 86400:
        return False
    cle = (int(guild_id), int(user_id))
    if maintenant - _dernier_avis.get(cle, 0.0) < INTERVALLE_S:
        return False
    _dernier_avis[cle] = maintenant
    if len(_dernier_avis) > 50_000:
        _dernier_avis.clear()
    return True


async def avertir(bot: commands.Bot, ctx: commands.Context) -> None:
    if not actif() or ctx.interaction is not None or ctx.guild is None or ctx.command is None:
        return
    if getattr(ctx.author, "bot", False) or not doit_avertir(ctx.guild.id, ctx.author.id):
        return
    from utils import sentrix_panels as panels

    # Texte brut, comme l'avis Discord de la capture : sans le signal, la couche
    # des cartes en ferait un panneau titré.
    jeton = panels.TEXTE_BRUT.set(True)
    try:
        await ctx.channel.send(
            texte_avis(bot, ctx.command),
            delete_after=EFFACER_APRES_S,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except (discord.Forbidden, discord.HTTPException):
        logger.debug("Avis de retrait du préfixe non envoyé.", exc_info=True)
    finally:
        panels.TEXTE_BRUT.reset(jeton)


class PrefixDeprecation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._original = None

    async def cog_load(self) -> None:
        original = self.bot.invoke
        if getattr(original, "_sentrix_avis_prefixe", False):
            return
        bot = self.bot

        async def invoke(ctx: commands.Context, /):
            try:
                return await original(ctx)
            finally:
                if ctx.command is not None and ctx.interaction is None:
                    try:
                        await avertir(bot, ctx)
                    except Exception:
                        logger.debug("Avis de retrait du préfixe ignoré.", exc_info=True)

        invoke._sentrix_avis_prefixe = True
        self._original = original
        bot.invoke = invoke

    async def cog_unload(self) -> None:
        if self._original is not None:
            self.bot.invoke = self._original


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PrefixDeprecation(bot))
