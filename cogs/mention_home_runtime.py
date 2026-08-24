"""Accueil V4 compact affiché lorsqu'un membre mentionne seulement le bot.

Le panneau tient dans un unique embed et une unique rangée de boutons. Il utilise
l'avatar Discord du compte bot comme miniature distante : aucune pièce jointe ne peut
donc se détacher et s'afficher en grand lors d'un clic ou d'une mise à jour du panneau.

Cette couche est installée très tard dans le runtime. Elle porte donc aussi le dernier
verrou anti-doublon des réponses IA passives : les couches V5/V6 remplacent la méthode
``send_sentrix_reply`` après le premier garde-fou de ``ai_reliability``. Sans ce verrou
final, deux services/listeners pouvaient répondre au même message Discord.
"""
from __future__ import annotations

import logging
import time
import types

import discord
from discord.ext import commands

import config
from utils import visual_v5
from utils.instance_identity import brand_label

from . import bot_experience_v5
from .log_rectangle_v25 import _is_primary_process

logger = logging.getLogger("bot.mention-home")
_ACCENT = 0x6C5CE7

# Déduplication locale finale des messages naturels. Le cache est indexé par l'ID Discord
# du message source : deux listeners du même process ne peuvent donc jamais publier deux
# réponses différentes au même message.
_PASSIVE_REPLY_TTL = 30.0
_PASSIVE_REPLY_RECENT: dict[int, float] = {}


def _prefix(bot: commands.Bot, message: discord.Message | None) -> str:
    if message is not None and message.guild is not None:
        cache = getattr(bot, "prefix_cache", {})
        return str(cache.get(message.guild.id, config.DEFAULT_PREFIX))
    return str(config.DEFAULT_PREFIX)


def _avatar_url(bot: commands.Bot) -> str | None:
    user = getattr(bot, "user", None)
    avatar = getattr(user, "display_avatar", None)
    url = getattr(avatar, "url", None)
    return str(url) if url else None


def _tip_embed(bot: commands.Bot, prefix: str, kind: str) -> discord.Embed:
    brand = brand_label()
    if kind == "commands":
        title = "Commandes"
        text = f"Ouvre le centre complet avec **`{prefix}help`**."
    elif kind == "setup":
        title = "Configuration"
        text = f"Configure le serveur depuis un seul panneau avec **`{prefix}setup`**."
    elif kind == "profile":
        title = "Profil"
        text = f"Affiche ta progression avec **`{prefix}profile`**."
    else:
        title = "Statut"
        latency = max(0, round(float(getattr(bot, "latency", 0.0)) * 1000))
        text = f"{brand} est en ligne. Latence Discord : **{latency} ms**."

    embed = discord.Embed(
        title=f"SentriX • {title}",
        description=text,
        color=_ACCENT,
    )
    avatar = _avatar_url(bot)
    if avatar:
        embed.set_author(name=brand, icon_url=avatar)
    else:
        embed.set_author(name=brand)
    return embed


class MentionHomeView(discord.ui.View):
    """Quatre raccourcis lisibles sur une seule ligne."""

    def __init__(self, bot: commands.Bot, prefix: str, owner_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.prefix = prefix
        self.owner_id = int(owner_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "Mentionne directement le bot pour ouvrir ton propre panneau.",
            ephemeral=True,
        )
        return False

    async def _reply(self, interaction: discord.Interaction, kind: str) -> None:
        await interaction.response.send_message(
            embed=_tip_embed(self.bot, self.prefix, kind),
            ephemeral=True,
        )

    @discord.ui.button(label="Commandes", style=discord.ButtonStyle.primary, row=0)
    async def commands_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._reply(interaction, "commands")

    @discord.ui.button(label="Configurer", style=discord.ButtonStyle.secondary, row=0)
    async def setup_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._reply(interaction, "setup")

    @discord.ui.button(label="Profil", style=discord.ButtonStyle.secondary, row=0)
    async def profile_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._reply(interaction, "profile")

    @discord.ui.button(label="Statut", style=discord.ButtonStyle.secondary, row=0)
    async def status_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._reply(interaction, "status")


def _home_embed(bot: commands.Bot, author: discord.abc.User, prefix: str) -> discord.Embed:
    brand = brand_label()
    display_name = getattr(author, "display_name", None) or getattr(author, "name", "membre")
    embed = discord.Embed(
        title="SentriX • Accueil",
        description=(
            f"**{visual_v5.greeting()} {display_name}, je suis {brand}.**\n"
            "Protection, configuration et outils communautaires.\n"
            f"Préfixe `{prefix}` • Commence avec `{prefix}help` ou `{prefix}setup`."
        ),
        color=_ACCENT,
    )
    avatar = _avatar_url(bot)
    if avatar:
        embed.set_author(name=brand, icon_url=avatar)
    else:
        embed.set_author(name=brand)
    embed.set_footer(text=f"{brand} • Accès rapide")
    return embed


async def _send_home(
    bot: commands.Bot,
    destination,
    author: discord.abc.User,
    reply_to: discord.Message | None,
):
    prefix = _prefix(bot, reply_to)
    kwargs = {
        "embed": _home_embed(bot, author, prefix),
        "view": MentionHomeView(bot, prefix, author.id),
        "allowed_mentions": discord.AllowedMentions.none(),
    }
    # Un message unique, sans ping supplémentaire ni deuxième carte.
    return await destination.send(**kwargs)


def _claim_local_passive_reply(message_id: int) -> bool:
    """Réserve localement un message Discord pendant quelques secondes."""
    now = time.monotonic()
    stale = [mid for mid, expires in _PASSIVE_REPLY_RECENT.items() if expires <= now]
    for mid in stale[:1000]:
        _PASSIVE_REPLY_RECENT.pop(mid, None)

    if _PASSIVE_REPLY_RECENT.get(message_id, 0.0) > now:
        return False

    _PASSIVE_REPLY_RECENT[message_id] = now + _PASSIVE_REPLY_TTL
    if len(_PASSIVE_REPLY_RECENT) > 5000:
        for mid in list(_PASSIVE_REPLY_RECENT)[:1000]:
            _PASSIVE_REPLY_RECENT.pop(mid, None)
    return True


async def _claim_passive_reply(bot: commands.Bot, reply_to: discord.Message | None) -> bool:
    """Garantit une seule sortie pour un message naturel, même avec plusieurs runtimes.

    1. seul le service Railway principal est autorisé à publier ;
    2. un cache local bloque les doubles listeners dans le même process ;
    3. si Redis Enterprise est disponible, un lease par ID de message bloque aussi deux
       replicas du même service. Le lease n'est volontairement pas libéré : son TTL est la
       fenêtre anti-doublon.
    """
    if reply_to is None:
        # /sentrix et les autres commandes explicites n'utilisent pas ce verrou : leur cycle
        # de réponse est déjà détenu par discord.py et elles n'ont pas de message passif source.
        return True

    if not _is_primary_process():
        logger.info(
            "Réponse IA passive ignorée sur service Railway secondaire — message=%s",
            getattr(reply_to, "id", "?"),
        )
        return False

    try:
        message_id = int(reply_to.id)
    except (TypeError, ValueError, AttributeError):
        # Sans ID stable, on préfère conserver la réponse plutôt que bloquer un utilisateur.
        return True

    if not _claim_local_passive_reply(message_id):
        logger.info("Réponse IA passive doublon local bloquée — message=%s", message_id)
        return False

    # EnterpriseSuite expose Redis via .infra lorsqu'il est disponible. Le lookup se fait
    # au moment du message (et non à l'installation) pour fonctionner même si le Cog est
    # initialisé plus tard pendant le démarrage.
    service = bot.get_cog("EnterpriseSuite")
    infra = getattr(service, "infra", None) if service is not None else None
    acquire_lease = getattr(infra, "acquire_lease", None)
    if callable(acquire_lease):
        try:
            claimed = await acquire_lease(
                f"ai-passive-reply:{message_id}",
                str(message_id),
                ttl=int(_PASSIVE_REPLY_TTL),
            )
            if not claimed:
                logger.info("Réponse IA passive doublon Redis bloquée — message=%s", message_id)
                return False
        except Exception:
            # Le cache local et le garde Railway restent actifs si Redis tombe momentanément.
            logger.debug("Lease Redis anti-doublon IA indisponible.", exc_info=True)

    return True


def install(bot: commands.Bot) -> None:
    """Pose la version compacte et le dernier verrou anti-doublon au-dessus de V5/V6."""
    ai_cog = bot.get_cog("Ai")
    if ai_cog is None or getattr(ai_cog, "_sentrix_compact_mention_home", False):
        return

    original = ai_cog.send_sentrix_reply

    async def compact_send_sentrix_reply(
        self,
        destination,
        author,
        question: str,
        *,
        reply_to: discord.Message | None = None,
    ):
        if not await _claim_passive_reply(self.bot, reply_to):
            return None

        if bot_experience_v5._is_bare_trigger(self.bot, reply_to):
            return await _send_home(self.bot, destination, author, reply_to)
        return await original(destination, author, question, reply_to=reply_to)

    ai_cog.send_sentrix_reply = types.MethodType(compact_send_sentrix_reply, ai_cog)
    ai_cog._sentrix_compact_mention_home = True
    logger.info("Accueil compact + anti-doublon final IA activés pour %s.", brand_label())
