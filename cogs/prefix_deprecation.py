"""Avertit chaque utilisateur de commandes « + » que le préfixe va disparaître.

28/10/2026 (Jayden) : SentriX passe à 100 % de commandes « / ».
29/10/2026 (Jayden) : l'avis quitte le panneau d'aide. C'est un message Discord
séparé, en gras, sans carte ni embed, qui mentionne la personne concernée — au
plus deux fois par jour et par personne, toutes commandes confondues, compteur
gardé en base pour survivre aux redémarrages. Aucune date : le retrait ne sera
fixé que lorsque toutes les commandes « / » seront disponibles et testées.

Branché sur ``bot.invoke`` (le passage obligé des commandes préfixées ; les
commandes « / » n'y passent pas) plutôt que sur un écouteur de plus : le budget
d'écouteurs est plafonné (tests/test_runtime_hygiene_gates). Couvre +help,
+setup, toutes les commandes « + », et les anciennes commandes supprimées.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time

import discord
from discord.ext import commands

logger = logging.getLogger("bot.prefix-deprecation")

#: Au plus deux rappels par jour (UTC) et par personne, toutes commandes confondues.
MAX_PAR_JOUR = 2
#: Deux commandes « + » d'affilée ne donnent pas deux rappels d'affilée.
ECART_MIN_S = 3600

TABLE = """
CREATE TABLE IF NOT EXISTS sentrix_prefix_notices (
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    last_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
)
"""

_verrous: dict[int, asyncio.Lock] = {}


def actif() -> bool:
    """Coupé par le harnais e2e (SENTRIX_AVIS_PREFIXE=0) : l'avis est un message de
    plus après chaque « + », et les parcours repèrent le panneau du bot comme
    « dernier message ». Lu à l'appel : discord.py recharge l'extension comme un
    nouveau module, un drapeau posé avant le chargement serait perdu.
    tools/prefix_deprecation_e2e.py le teste explicitement, allumé."""
    import os

    return os.environ.get("SENTRIX_AVIS_PREFIXE", "1") != "0"


def prefixe_actif() -> bool:
    """30/10/2026 (Jayden) : « personne n'utilise le +, supprime maintenant ».
    En production, un message « +commande » n'exécute plus rien. Les commandes
    restent chargées : elles sont la source des routes « / ». Le harnais de test
    rallume le « + » (SENTRIX_PREFIXE_ACTIF=1) pour les parcours existants."""
    import os

    return os.environ.get("SENTRIX_PREFIXE_ACTIF", "0") == "1"


def commande_slash(texte: str) -> str | None:
    """« +clear 10 » -> mention cliquable de /clear (catalogue), ou None."""
    from utils import sentrix_panels as panels, slash_ids

    route = panels._route_slash(" ".join(str(texte or "").split()[:3]))
    if route is None:
        return None
    try:
        return slash_ids.mention(route[0])
    except Exception:
        return f"`/{route[0]}`"


def texte_retire(membre: discord.abc.User, slash: str | None = None) -> str:
    conseil = f"Utilise {slash} à la place." if slash else "Tape `/` pour voir la liste des commandes."
    return f"**{membre.mention} Les commandes avec le préfixe `+` ont été supprimées. {conseil}**"


#: « + » retiré : une réponse à CHAQUE essai (sinon rien ne se passe), 10 s
#: d'écart par personne contre le spam, puis suppression rapide du rappel.
PREFIX_REMOVAL_NOTICE_TTL_SECONDS = 8
_dernier_essai: dict[int, float] = {}


async def repondre_retire(ctx: commands.Context) -> None:
    if ctx.guild is None or getattr(ctx.author, "bot", False) or not _concerne(ctx):
        return
    maintenant = time.monotonic()
    if maintenant - _dernier_essai.get(ctx.author.id, -1e9) < 10:
        return
    _dernier_essai[ctx.author.id] = maintenant
    if len(_dernier_essai) > 50_000:
        _dernier_essai.clear()
    from utils import sentrix_panels as panels

    jeton = panels.TEXTE_BRUT.set(True)
    try:
        await ctx.channel.send(
            texte_retire(ctx.author, commande_slash("+" + ctx.message.content[len(ctx.prefix or ""):])),
            delete_after=PREFIX_REMOVAL_NOTICE_TTL_SECONDS,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=[ctx.author],
                                                     replied_user=False),
        )
    except (discord.Forbidden, discord.HTTPException):
        logger.debug("Réponse « + retiré » non envoyée.", exc_info=True)
    finally:
        panels.TEXTE_BRUT.reset(jeton)


def texte_avis(membre: discord.abc.User) -> str:
    return (
        f"**{membre.mention} Les commandes avec le préfixe `+` seront bientôt supprimées. "
        "Nous te conseillons de passer aux commandes `/` dès maintenant.**"
    )


def jour(maintenant: float) -> str:
    return dt.datetime.fromtimestamp(maintenant, dt.timezone.utc).strftime("%Y-%m-%d")


def peut_avertir(compte: int, dernier: int, maintenant: float) -> bool:
    return compte < MAX_PAR_JOUR and maintenant - dernier >= ECART_MIN_S


async def reserver(db, user_id: int, maintenant: float | None = None) -> bool:
    """Réserve un rappel pour ``user_id`` aujourd'hui ; False si la limite est atteinte.

    Le verrou par personne évite deux rappels pour deux commandes simultanées ;
    l'écriture précède l'envoi : un échec d'envoi coûte un rappel, jamais un doublon."""
    maintenant = time.time() if maintenant is None else maintenant
    cle = jour(maintenant)
    verrou = _verrous.setdefault(int(user_id), asyncio.Lock())
    async with verrou:
        row = await db.fetchone(
            "SELECT count, last_at FROM sentrix_prefix_notices WHERE user_id=? AND day=?",
            (int(user_id), cle),
        )
        compte = int(row["count"]) if row else 0
        dernier = int(row["last_at"]) if row else 0
        if not peut_avertir(compte, dernier, maintenant):
            return False
        await db.execute(
            "INSERT INTO sentrix_prefix_notices(user_id, day, count, last_at) VALUES(?,?,1,?) "
            "ON CONFLICT(user_id, day) DO UPDATE SET count=sentrix_prefix_notices.count+1, "
            "last_at=excluded.last_at",
            (int(user_id), cle, int(maintenant)),
        )
    if len(_verrous) > 50_000:
        _verrous.clear()
    return True


def _concerne(ctx: commands.Context) -> bool:
    """Une commande « + » réelle, ou une ancienne commande supprimée tapée en « + »."""
    if ctx.interaction is not None or ctx.guild is None or getattr(ctx.author, "bot", False):
        return False
    if ctx.command is not None:
        return True
    from utils.unused_commands import SUPPRIMEES

    tape = str(ctx.invoked_with or "").casefold()
    return bool(tape) and tape in SUPPRIMEES


async def avertir(bot: commands.Bot, ctx: commands.Context) -> None:
    if not actif() or not _concerne(ctx):
        return
    db = getattr(bot, "db", None)
    if db is None or not await reserver(db, ctx.author.id):
        return
    from utils import sentrix_panels as panels

    # Texte brut, demandé explicitement : sans le signal, la couche des cartes
    # en ferait un panneau titré.
    jeton = panels.TEXTE_BRUT.set(True)
    try:
        await ctx.channel.send(
            texte_avis(ctx.author) if prefixe_actif() else texte_retire(ctx.author),
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=[ctx.author], replied_user=False
            ),
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
        db = getattr(self.bot, "db", None)
        if db is not None:
            await db.execute(TABLE)
        original = self.bot.invoke
        if getattr(original, "_sentrix_avis_prefixe", False):
            return
        bot = self.bot

        async def invoke(ctx: commands.Context, /):
            if ctx.interaction is None and not prefixe_actif():
                # « + » retiré : rien n'est exécuté ; on dit quelle commande « / » utiliser.
                try:
                    await repondre_retire(ctx)
                except Exception:
                    logger.debug("Avis de retrait du préfixe ignoré.", exc_info=True)
                return None
            try:
                return await original(ctx)
            finally:
                if ctx.interaction is None:
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
