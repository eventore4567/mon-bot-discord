"""Complète +create-server avec des guides par salon et des réglages SentriX prêts à l'emploi."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.server-builder.guides")
_INSTALLED = False

# Ces salons possèdent déjà une fiche dédiée créée par server_builder._publish_welcome_content.
_ALREADY_DOCUMENTED = {
    "règlement",
    "annonces",
    "bienvenue",
    "informations",
    "questions-fréquentes",
    "statut-des-services",
}


def _usage_text(channel_type: str, privacy: str) -> str:
    if privacy == "staff":
        if channel_type == "readonly":
            return "Salon interne en lecture pour les informations officielles de l'équipe."
        return "Salon privé réservé à l'équipe pour organiser et traiter ce sujet."
    if channel_type == "readonly":
        return "Salon d'information : consulte les messages publiés par l'équipe."
    return "Utilise ce salon uniquement pour les échanges correspondant à son sujet."


def _guide_embed(server_builder, channel: discord.TextChannel, base_name: str, category_name: str, privacy: str, channel_type: str, accent: discord.Color) -> discord.Embed:
    topic = server_builder._channel_topic(base_name, category_name, privacy)
    embed = discord.Embed(
        title=f"À propos de #{base_name}",
        description=topic,
        color=accent,
    )
    embed.add_field(name="Utilisation", value=_usage_text(channel_type, privacy), inline=False)
    embed.add_field(
        name="Accès",
        value="Équipe du serveur" if privacy == "staff" else "Membres du serveur",
        inline=True,
    )
    embed.add_field(name="Catégorie", value=category_name.title(), inline=True)
    embed.set_footer(text=f"SentriX • Guide salon automatique v1 • {channel.id}")
    return embed


async def _publish_channel_guides(cog, guild: discord.Guild, template_key: str) -> int:
    from . import server_builder

    data = server_builder.SERVER_TEMPLATES[template_key]
    accent = data["accent"]
    published = 0

    for category_data in data["categories"]:
        category_name = category_data["name"]
        privacy = category_data["privacy"]
        category = server_builder._find_category(guild, category_name)
        if category is None:
            continue
        for base_name, channel_type in category_data["channels"]:
            if channel_type == "voice" or base_name in _ALREADY_DOCUMENTED:
                continue
            channel = server_builder._find_channel(category, base_name)
            if not isinstance(channel, discord.TextChannel):
                continue
            marker = f"SentriX • Guide salon automatique v1 • {channel.id}"
            embed = _guide_embed(server_builder, channel, base_name, category_name, privacy, channel_type, accent)
            try:
                published += await cog._publish_once(channel, marker, embed)
            except discord.HTTPException:
                logger.warning("Impossible de publier le guide du salon %s", channel.id)
    return published


async def _configure_safe_defaults(cog, guild: discord.Guild) -> None:
    """Configure ce qui ne demande aucun choix personnel de l'administrateur."""
    defaults = {
        "welcome_message": "Bienvenue {mention} sur **{server}** ! Lis le règlement et choisis tes rôles pour commencer.",
        "goodbye_message": "{user} a quitté **{server}**. Nous lui souhaitons une bonne continuation.",
        "level_message": "Bravo {mention}, tu viens de passer au niveau **{level}** !",
        "warn_ban_threshold": 3,
        "ticket_delete_delay": 30,
        "ticket_transcript_dm": 1,
        "ticket_rating_enabled": 1,
        "security_level": "moyen",
    }
    for field, value in defaults.items():
        try:
            await cog.bot.db.set_guild_config(guild.id, field, value)
        except Exception:
            logger.exception("Impossible de préconfigurer %s sur %s", field, guild.id)

    # Protection de base activée sans toucher aux modules plus agressifs (anti-nuke/anti-bot)
    # qui peuvent dépendre de la structure exacte du serveur.
    try:
        await cog.bot.db.execute(
            "INSERT INTO automod_settings (guild_id, antispam, antilink, antiinvite, antimention, anticaps, antiemoji, antiscam, escalation) "
            "VALUES (?, 1, 1, 1, 1, 1, 1, 1, 1) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "antispam=1, antilink=1, antiinvite=1, antimention=1, anticaps=1, antiemoji=1, antiscam=1, escalation=1",
            (guild.id,),
        )
    except Exception:
        logger.exception("Impossible de préconfigurer l'AutoMod sur %s", guild.id)


def install(bot: commands.Bot) -> None:
    del bot
    global _INSTALLED
    if _INSTALLED:
        return

    from . import server_builder

    original_publish = server_builder.ServerBuilder._publish_welcome_content
    original_configure = server_builder.ServerBuilder._configure_bot_channels

    async def publish_every_channel(self, guild, channel_map, template_key):
        published = await original_publish(self, guild, channel_map, template_key)
        published += await _publish_channel_guides(self, guild, template_key)
        return published

    async def configure_everything_safe(self, guild, role_map, category_map, channel_map, staff_role_name):
        configured = await original_configure(self, guild, role_map, category_map, channel_map, staff_role_name)
        await _configure_safe_defaults(self, guild)
        return configured

    server_builder.ServerBuilder._publish_welcome_content = publish_every_channel
    server_builder.ServerBuilder._configure_bot_channels = configure_everything_safe
    _INSTALLED = True
    logger.info("+create-server enrichi : guides de salons et réglages SentriX par défaut activés.")
