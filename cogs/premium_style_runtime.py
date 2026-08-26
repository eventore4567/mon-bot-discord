"""Installation non destructive de l'identite visuelle globale SentriX."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import discord
from discord.ext import commands

from utils import premium_style

logger = logging.getLogger("bot.premium-style")
_INSTALLED = False
_BRANDING_INSTALLED = False
_ORIGINALS: dict[str, Any] = {}


def _railway_service_name() -> str:
    return (os.getenv("RAILWAY_SERVICE_NAME") or "").strip()


def _is_odboug_instance() -> bool:
    explicit = (os.getenv("BOT_BRAND_LABEL") or "").strip().casefold()
    if explicit:
        return explicit == "odboug"
    return "odboug" in _railway_service_name().casefold()


def _instance_brand() -> str:
    """Nom affiche dans les embeds pour cette instance uniquement.

    Une variable BOT_BRAND_LABEL explicite reste prioritaire. Sur Railway, le service
    Bot'Odboug est aussi reconnu automatiquement via RAILWAY_SERVICE_NAME. Le service
    principal mon-bot-discord ne correspond pas et conserve donc strictement SentriX.
    """
    explicit = (os.getenv("BOT_BRAND_LABEL") or "").strip()
    if explicit:
        return explicit[:48]
    if _is_odboug_instance():
        return "Odboug"
    return "SentriX"


def _instance_display_name() -> str:
    """Pseudo serveur optionnel du compte bot, sans toucher au bot SentriX principal."""
    explicit = (os.getenv("BOT_DISPLAY_NAME") or "").strip()
    if explicit:
        return explicit[:32]
    if _is_odboug_instance():
        return "[+] Bot'Odboug |"
    return ""


def _configure_instance_branding() -> None:
    """Rend le moteur premium multi-instance sans dupliquer le code du bot.

    Bot'Odboug peut etre configure explicitement avec :
      BOT_BRAND_LABEL=Odboug
      BOT_DISPLAY_NAME=[+] Bot'Odboug |

    Sur Railway ces deux valeurs sont aussi deduites automatiquement lorsque le nom du
    service contient "Odboug". Le service SentriX principal reste donc inchange.
    """
    global _BRANDING_INSTALLED
    if _BRANDING_INSTALLED:
        return

    brand = _instance_brand()
    _BRANDING_INSTALLED = True
    if brand.casefold() == "sentrix":
        return

    original_style_embed = premium_style.style_embed
    premium_style.SENTRIX_TITLE_RE = re.compile(
        rf"^(?:SENTRIX|{re.escape(brand)})\s*(?:/|•)\s*",
        re.IGNORECASE,
    )
    premium_style.CATEGORY_NAMES["brand"] = brand

    def canonical_title(category: str, *, log_type: str | None = None) -> str:
        label = premium_style.CATEGORY_NAMES.get(category, "Information")
        limit = premium_style.VISUAL_LIMITS["title"]
        if log_type:
            return premium_style.clip(f"{brand} • Journal {label}", limit)
        return premium_style.clip(f"{brand} • {label}", limit)

    def footer_text(*, guild: discord.Guild | None = None, requester: Any = None) -> str:
        del requester
        parts = [brand]
        if guild is not None:
            parts.append(premium_style.clip(getattr(guild, "name", "Serveur"), 60))
        return " • ".join(parts)

    def branded_style_embed(embed: discord.Embed, *args, **kwargs):
        if isinstance(embed, discord.Embed):
            title = str(getattr(embed, "title", "") or "").strip()
            match = re.match(r"^SENTRIX\s*(?:/|•)\s*(.+)$", title, flags=re.IGNORECASE)
            if match:
                embed.title = premium_style.clip(
                    f"{brand} • {match.group(1)}",
                    premium_style.VISUAL_LIMITS["title"],
                )
            elif title.casefold() == "sentrix":
                embed.title = brand
        return original_style_embed(embed, *args, **kwargs)

    premium_style._canonical_title = canonical_title
    premium_style._footer_text = footer_text
    premium_style.style_embed = branded_style_embed
    logger.info("Identite visuelle d'instance active : %s.", brand)


async def _apply_instance_display_name(bot: commands.Bot, guild: discord.Guild | None = None) -> None:
    """Applique un pseudo propre a cette instance sur ses serveurs Discord."""
    display_name = _instance_display_name()
    if not display_name:
        return

    guilds = [guild] if guild is not None else list(bot.guilds)
    for target in guilds:
        member = getattr(target, "me", None)
        if member is None or member.display_name == display_name:
            continue
        try:
            await member.edit(nick=display_name, reason="Identite de cette instance du bot")
        except discord.Forbidden:
            logger.warning(
                "Impossible de definir le pseudo %r sur %s : permission Changer le pseudo manquante.",
                display_name,
                getattr(target, "id", "?"),
            )
        except discord.HTTPException:
            logger.exception(
                "Discord a refuse le changement de pseudo %r sur %s.",
                display_name,
                getattr(target, "id", "?"),
            )


def _install_instance_display_name(bot: commands.Bot) -> None:
    if not _instance_display_name() or getattr(bot, "_sentrix_instance_display_name", False):
        return

    async def instance_branding_ready():
        await _apply_instance_display_name(bot)

    async def instance_branding_guild_join(guild: discord.Guild):
        await _apply_instance_display_name(bot, guild)

    bot.add_listener(instance_branding_ready, "on_ready")
    bot.add_listener(instance_branding_guild_join, "on_guild_join")
    bot._sentrix_instance_display_name = True


def _wake_word_pattern() -> re.Pattern[str]:
    configured = [
        item.strip()
        for item in (os.getenv("BOT_WAKE_WORDS") or "").split(",")
        if item.strip()
    ]
    brand = _instance_brand()
    words = configured or [brand]
    if brand.casefold() == "odboug":
        words.extend(["odboug", "bot odboug", "bot'odboug", "bot’odboug"])
    unique = []
    seen = set()
    for word in words:
        key = word.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(word)
    alternatives = "|".join(re.escape(word).replace(r"\ ", r"\s+") for word in unique)
    return re.compile(rf"^(?:{alternatives})\b", re.IGNORECASE)


def _install_instance_wake_word(bot: commands.Bot) -> None:
    """Permet a une instance marquee Odboug de repondre a "Odboug ..." naturellement.

    SentriX garde son listener historique dans cogs.ai ; cette couche ne s'active que pour
    une marque differente afin d'eviter toute double reponse sur le bot principal.
    """
    if _instance_brand().casefold() == "sentrix":
        return
    if getattr(bot, "_sentrix_instance_wake_word", False):
        return

    pattern = _wake_word_pattern()

    async def instance_wake_word(message: discord.Message):
        if message.author.bot or not message.guild:
            return
        content = (message.content or "").strip()
        if not content:
            return

        prefix = (
            bot.prefix_cache.get(message.guild.id, "+")
            if hasattr(bot, "prefix_cache")
            else "+"
        )
        if content.startswith(prefix):
            return

        match = pattern.match(content)
        if match is None:
            return

        ai_cog = bot.get_cog("Ai")
        if ai_cog is None:
            return

        question = content[match.end():].lstrip(" ,:-").strip()
        if not question:
            question = "Salut, comment tu vas ?"

        invoke_natural = getattr(ai_cog, "_invoke_natural_command", None)
        if callable(invoke_natural):
            try:
                if await invoke_natural(message, question, prefix):
                    return
            except Exception:
                logger.exception("Commande naturelle Odboug impossible.")

        send_reply = getattr(ai_cog, "send_sentrix_reply", None)
        if not callable(send_reply):
            return
        try:
            async with message.channel.typing():
                await send_reply(message.channel, message.author, question, reply_to=message)
        except Exception:
            logger.exception("Reponse naturelle Odboug impossible.")

    bot.add_listener(instance_wake_word, "on_message")
    bot._sentrix_instance_wake_word = True
    logger.info("Mot de reveil naturel actif pour %s.", _instance_brand())


def _bot_user_from_context(ctx: commands.Context):
    return getattr(getattr(ctx, "bot", None), "user", None)


def _guild_from_messageable(messageable: Any):
    return getattr(messageable, "guild", None)


def _patch_context_send() -> None:
    original = commands.Context.send
    _ORIGINALS["context_send"] = original

    async def send(self: commands.Context, *args, **kwargs):
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            command=self.command,
            guild=self.guild,
            requester=self.author,
            bot_user=_bot_user_from_context(self),
            allow_content_wrap=True,
            include_brand_asset=True,
        )
        return await original(self, *args, **kwargs)

    commands.Context.send = send


def _patch_context_reply() -> None:
    original = commands.Context.reply
    _ORIGINALS["context_reply"] = original

    async def reply(self: commands.Context, *args, **kwargs):
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            command=self.command,
            guild=self.guild,
            requester=self.author,
            bot_user=_bot_user_from_context(self),
            allow_content_wrap=True,
            include_brand_asset=True,
        )
        return await original(self, *args, **kwargs)

    commands.Context.reply = reply


def _patch_messageable_send(bot: commands.Bot) -> None:
    original = discord.abc.Messageable.send
    _ORIGINALS["messageable_send"] = original

    async def send(self, *args, **kwargs):
        guild = _guild_from_messageable(self)
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            guild=guild,
            bot_user=bot.user,
            allow_content_wrap=False,
            include_brand_asset=True,
        )
        return await original(self, *args, **kwargs)

    discord.abc.Messageable.send = send


def _patch_message_edit(bot: commands.Bot) -> None:
    original = discord.Message.edit
    _ORIGINALS["message_edit"] = original

    async def edit(self: discord.Message, *args, **kwargs):
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            guild=self.guild,
            bot_user=bot.user,
            allow_content_wrap=False,
        )
        return await original(self, *args, **kwargs)

    discord.Message.edit = edit


def _patch_interaction_response(bot: commands.Bot) -> None:
    original_send = discord.InteractionResponse.send_message
    original_edit = discord.InteractionResponse.edit_message
    _ORIGINALS["interaction_send"] = original_send
    _ORIGINALS["interaction_edit"] = original_edit

    async def send_message(self: discord.InteractionResponse, *args, **kwargs):
        interaction = getattr(self, "_parent", None)
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            command=getattr(interaction, "command", None),
            guild=getattr(interaction, "guild", None),
            requester=getattr(interaction, "user", None),
            bot_user=bot.user,
            allow_content_wrap=True,
            include_brand_asset=True,
        )
        return await original_send(self, *args, **kwargs)

    async def edit_message(self: discord.InteractionResponse, *args, **kwargs):
        interaction = getattr(self, "_parent", None)
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            command=getattr(interaction, "command", None),
            guild=getattr(interaction, "guild", None),
            requester=getattr(interaction, "user", None),
            bot_user=bot.user,
            allow_content_wrap=False,
        )
        return await original_edit(self, *args, **kwargs)

    discord.InteractionResponse.send_message = send_message
    discord.InteractionResponse.edit_message = edit_message


def _patch_interaction_edits(bot: commands.Bot) -> None:
    original_edit_original = discord.Interaction.edit_original_response
    _ORIGINALS["interaction_edit_original"] = original_edit_original

    async def edit_original_response(self: discord.Interaction, *args, **kwargs):
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            command=getattr(self, "command", None),
            guild=self.guild,
            requester=self.user,
            bot_user=bot.user,
            allow_content_wrap=False,
        )
        return await original_edit_original(self, *args, **kwargs)

    discord.Interaction.edit_original_response = edit_original_response


def _patch_webhook_followups(bot: commands.Bot) -> None:
    original = discord.Webhook.send
    _ORIGINALS["webhook_send"] = original

    async def send(self: discord.Webhook, *args, **kwargs):
        if getattr(self, "type", None) == discord.WebhookType.application:
            args, kwargs = premium_style.style_kwargs(
                args,
                kwargs,
                bot_user=bot.user,
                allow_content_wrap=True,
                include_brand_asset=True,
            )
        return await original(self, *args, **kwargs)

    discord.Webhook.send = send


def _patch_design_system() -> None:
    """Construit l'embed brut ; le transport l'habille ensuite une seule fois.

    L'ancien comportement appliquait le style ici sans connaître la commande, puis une
    seconde fois dans Context.send. Cela produisait par exemple « SentriX • Musique »
    suivi de « SentriX • Utilitaires » dans le contenu.
    """
    try:
        from utils import design_system
    except Exception:
        return

    original_create = design_system.create_embed
    _ORIGINALS["design_create_embed"] = original_create

    def create_embed(*, title, description=None, colour=0x5865F2, user=None, thumbnail=None, footer=None):
        embed = discord.Embed(title=title, description=description, colour=discord.Colour(colour))
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        if footer:
            embed.set_footer(text=footer)
        return embed

    design_system.create_embed = create_embed


def _patch_log_service() -> None:
    """Applique une identite audit coherente a toutes les categories de journaux."""
    try:
        from utils import log_service
    except Exception:
        return

    original = log_service.send_log
    _ORIGINALS["log_service_send"] = original
    category_by_type = {
        "moderation": "moderation",
        "tickets": "tickets",
        "automod": "security",
        "security": "security",
        "economy": "economy",
        "levels": "levels",
        "ai": "ai",
        "games": "games",
    }

    async def send_log(bot, guild, log_type, embed, file=None):
        if isinstance(embed, discord.Embed):
            premium_style.style_embed(
                embed,
                guild=guild,
                bot_user=getattr(bot, "user", None),
                category=category_by_type.get(str(log_type), "logs"),
                log_type=str(log_type),
            )
        return await original(bot, guild, log_type, embed, file=file)

    log_service.send_log = send_log


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    _configure_instance_branding()
    _install_instance_display_name(bot)
    _install_instance_wake_word(bot)
    if _INSTALLED:
        return

    patchers = (
        ("commandes texte", _patch_context_send),
        ("reponses texte", _patch_context_reply),
        ("salons et messages prives", lambda: _patch_messageable_send(bot)),
        ("editions de messages", lambda: _patch_message_edit(bot)),
        ("reponses d'interaction", lambda: _patch_interaction_response(bot)),
        ("editions d'interaction", lambda: _patch_interaction_edits(bot)),
        ("follow-ups", lambda: _patch_webhook_followups(bot)),
        ("ancien design system", _patch_design_system),
        ("journaux", _patch_log_service),
    )
    installed = 0
    for label, patcher in patchers:
        try:
            patcher()
            installed += 1
        except Exception:
            logger.exception("Style premium : installation impossible pour %s.", label)

    _INSTALLED = True
    logger.info(
        "Identite premium %s installee : %s/%s couches actives.",
        _instance_brand(),
        installed,
        len(patchers),
    )
