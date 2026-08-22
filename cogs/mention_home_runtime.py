"""Accueil V4 compact affiché lorsqu'un membre mentionne seulement le bot.

Le panneau tient dans un unique embed et une unique rangée de boutons. Il utilise
l'avatar Discord du compte bot comme miniature distante : aucune pièce jointe ne peut
donc se détacher et s'afficher en grand lors d'un clic ou d'une mise à jour du panneau.
"""
from __future__ import annotations

import logging
import types

import discord
from discord.ext import commands

import config
from utils import visual_v5
from utils.instance_identity import brand_label

from . import bot_experience_v5

logger = logging.getLogger("bot.mention-home")
_ACCENT = 0x6C5CE7


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


def install(bot: commands.Bot) -> None:
    """Pose la version compacte au-dessus du pipeline d'accueil V6 existant."""
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
        if bot_experience_v5._is_bare_trigger(self.bot, reply_to):
            return await _send_home(self.bot, destination, author, reply_to)
        return await original(destination, author, question, reply_to=reply_to)

    ai_cog.send_sentrix_reply = types.MethodType(compact_send_sentrix_reply, ai_cog)
    ai_cog._sentrix_compact_mention_home = True
    logger.info("Accueil compact sur mention activé pour %s.", brand_label())
