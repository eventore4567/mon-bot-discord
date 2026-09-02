"""Rend +create-server réellement prêt à l'emploi.

Le modèle communauté est allégé, choix-des-rôles devient lecture seule, et le build
configure automatiquement les rôles, la boutique, l'annonce SentriX, le suivi bot
et le profil de sécurité recommandé.
"""
from __future__ import annotations

import logging
import time

import discord

from utils import sentrix_panels as panels
from discord.ext import commands

from .security_runtime_hardening import apply_recommended_security

logger = logging.getLogger("bot.server-builder.ready")
_INSTALLED = False

# Redondants dans le modèle Communauté : on conserve une structure plus courte et utile.
REMOVED_CHANNELS_BY_CATEGORY = {
    "COMMUNAUTÉ": {"discussion-libre", "clips", "hors-sujet"},
    "JEUX": {"actualités-jeux", "équipes", "résultats"},
    "VOCAUX": {"Général 2", "Général 3", "Gaming 2", "Gaming 3"},
    "PARTENAIRES": {"informations-partenariats"},
}
REMOVED_CATEGORIES = {"COMPÉTITION", "ARCHIVES"}
REMOVED_GENERATED_NAMES = {
    "discussion-libre", "clips", "hors-sujet", "actualités-jeux", "équipes", "résultats",
    "général 2", "général 3", "gaming 2", "gaming 3", "informations-partenariats",
    "classement-gaming", "recrutement-équipes", "défis", "matchs", "palmarès",
    "archives-tickets", "archives-sanctions", "archives-événements",
}

SHOP_DEFAULTS = (
    ("VIP", 10_000, "Rôle VIP permanent acheté avec la monnaie du serveur."),
    ("Premium", 25_000, "Rôle Premium permanent avec un statut supérieur au VIP."),
)


def _install_lean_community_template(server_builder) -> int:
    cleaned = []
    removed = 0
    for category in server_builder.COMMUNITY_CATEGORIES:
        name = category["name"]
        if name in REMOVED_CATEGORIES:
            removed += len(category["channels"])
            continue
        excluded = {item.casefold() for item in REMOVED_CHANNELS_BY_CATEGORY.get(name, set())}
        channels = []
        for channel_name, channel_type in category["channels"]:
            if channel_name.casefold() in excluded:
                removed += 1
                continue
            # Le salon reste visible mais aucun membre ne peut y écrire : seuls les boutons
            # et menus SentriX servent à prendre/retirer des rôles.
            if channel_name.casefold() == "choix-des-rôles":
                channel_type = "readonly"
            channels.append((channel_name, channel_type))
        cleaned.append({**category, "channels": channels})

    server_builder.COMMUNITY_CATEGORIES = cleaned
    server_builder.SERVER_TEMPLATES["communaute"]["categories"] = cleaned
    return removed


def _find_text_channel(server_builder, guild: discord.Guild, category_name: str, channel_name: str):
    category = server_builder._find_category(guild, category_name)
    if category is None:
        return None
    channel = server_builder._find_channel(category, channel_name)
    return channel if isinstance(channel, discord.TextChannel) else None


async def _cleanup_old_generated_channels(server_builder, guild: discord.Guild) -> int:
    """Supprime seulement les anciens salons redondants encore vides ou utilisés par SentriX seul."""
    removed = 0
    me = guild.me
    if me is None:
        return 0

    for channel in list(guild.channels):
        if isinstance(channel, discord.CategoryChannel):
            continue
        plain = server_builder._plain_discord_name(channel.name)
        if plain not in REMOVED_GENERATED_NAMES:
            continue
        try:
            if isinstance(channel, discord.VoiceChannel):
                if channel.members:
                    continue
                await channel.delete(reason="Nettoyage des anciens salons redondants de +create-server")
                removed += 1
                continue
            if isinstance(channel, discord.TextChannel):
                messages = [message async for message in channel.history(limit=5)]
                if messages and any(message.author.id != me.id for message in messages):
                    continue
                await channel.delete(reason="Nettoyage des anciens salons redondants de +create-server")
                removed += 1
        except (discord.Forbidden, discord.HTTPException):
            continue

    for category_name in REMOVED_CATEGORIES:
        category = server_builder._find_category(guild, category_name)
        if category is not None and not category.channels:
            try:
                await category.delete(reason="Catégorie devenue inutile après nettoyage +create-server")
            except (discord.Forbidden, discord.HTTPException):
                pass
    return removed


async def _ensure_role_panels(bot: commands.Bot, guild: discord.Guild, channel: discord.TextChannel, creator_id: int) -> str:
    # 1) Jeux/plateformes, langues/régions et couleurs.
    from .server_choice_roles import publish_or_refresh
    await publish_or_refresh(bot, channel)

    # 2) Notifications : panneau séparé compact, avec menus privés Ajouter/Retirer.
    cog = bot.get_cog("NotificationRolePanels")
    if cog is None:
        return "rôles classiques configurés, notifications indisponibles"

    from . import rolepanel_notifications

    roles = await cog._ensure_roles(guild)
    role_ids = [role.id for role in roles]
    row = await bot.db.fetchone(
        "SELECT * FROM notification_role_panels WHERE guild_id = ? AND channel_id = ? ORDER BY created_at DESC LIMIT 1",
        (guild.id, channel.id),
    )
    message = None
    if row:
        try:
            message = await channel.fetch_message(int(row["message_id"]))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            message = None

    view = rolepanel_notifications.NotificationRoleView(guild, role_ids)
    embed = rolepanel_notifications._panel_embed(guild, role_ids)
    if message is None:
        message = await panels.envoyer(channel, panels.avec_composants(panels.depuis_embed(embed), view))
    else:
        await message.edit(embed=embed, view=view)

    await cog._save_panel(message, creator_id, role_ids)
    bot.add_view(rolepanel_notifications.NotificationRoleView(guild, role_ids), message_id=message.id)
    return f"jeux/langues/couleurs + {len(role_ids)} notifications"


async def _ensure_shop(bot: commands.Bot, guild: discord.Guild, channel: discord.TextChannel, creator_id: int) -> str:
    economy = bot.get_cog("Economy")
    if economy is None:
        return "module économie indisponible"

    configured = []
    for role_name, price, description in SHOP_DEFAULTS:
        role = discord.utils.get(guild.roles, name=role_name)
        if role is None:
            continue
        existing = await bot.db.fetchone(
            "SELECT id FROM shop_items WHERE guild_id = ? AND role_id = ?",
            (guild.id, role.id),
        )
        if existing:
            await bot.db.execute(
                "UPDATE shop_items SET name = ?, price = ?, description = ? WHERE id = ?",
                (role.name, price, description, existing["id"]),
            )
        else:
            await bot.db.execute(
                "INSERT INTO shop_items (guild_id, name, price, description, role_id) VALUES (?, ?, ?, ?, ?)",
                (guild.id, role.name, price, description, role.id),
            )
        configured.append(f"{role.name} ({price:,} pièces)".replace(",", " "))

    await economy._refresh_shop_panels(guild)
    from .economy import ShopRoleView

    chunks = await economy._shop_role_options(guild)
    embed = await economy._shop_panel_embed(guild)
    row = await bot.db.fetchone(
        "SELECT * FROM shop_panels WHERE guild_id = ? AND channel_id = ? ORDER BY created_at DESC LIMIT 1",
        (guild.id, channel.id),
    )
    message = None
    if row:
        try:
            message = await channel.fetch_message(int(row["message_id"]))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            message = None
    if message is None:
        message = await panels.envoyer(channel, panels.avec_composants(panels.depuis_embed(embed), ShopRoleView(chunks)))
        await bot.db.execute(
            "INSERT INTO shop_panels (guild_id, channel_id, message_id, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild.id, channel.id, message.id, creator_id, int(time.time())),
        )
    else:
        await message.edit(embed=embed, view=ShopRoleView(chunks))
    return ", ".join(configured) if configured else "aucun rôle VIP/Premium trouvé"


def _bot_ready_embed(guild: discord.Guild) -> discord.Embed:
    e = discord.Embed(
        title="SENTRIX — LE BOT EST PRÊT !",
        description=(
            "SentriX est maintenant disponible sur le serveur pour discuter, jouer, créer des images "
            "et utiliser les outils communautaires."
        ),
        color=0x7C6CFF,
    )
    e.add_field(
        name="Parler avec SentriX",
        value=(
            'Écrivez naturellement **SentriX** suivi de votre demande.\n`SentriX raconte-moi une blague`\n`SentriX donne-moi un défi`\n`SentriX explique-moi quelque chose`\n`SentriX ouvre-moi le help`'
        ),
        inline=False,
    )
    e.add_field(
        name="Jeux et commandes",
        value=(
            "`+guess-number` • `+rps` • `+trivia` • `+tictactoe` • `+hangman`\n"
            "`+math-quiz` • `+blackjack` • `+slots` • `+choose`\n"
            "`+daily` • `+balance` • `+shop`\n\n"
            "Le **Guess Number** accepte autant de participants que nécessaire et n'a pas de limite de temps."
        ),
        inline=False,
    )
    e.add_field(
        name="Génération d'images",
        value=(
            'Exemple : `SentriX fais-moi une image de Goku sous la pluie avec une aura bleue`\nPlus la description est précise, plus le résultat peut suivre votre idée.'
        ),
        inline=False,
    )
    e.add_field(
        name="Découvrir le reste",
        value='Utilisez `+help` pour voir toutes les commandes et tester vos propres demandes.',
        inline=False,
    )
    e.set_footer(text="SentriX • Présentation automatique v1")
    return e


async def _ensure_announcements(bot: commands.Bot, builder_cog, guild: discord.Guild, channel: discord.TextChannel, creator_id: int) -> str:
    await builder_cog._publish_once(
        channel,
        "SentriX • Présentation automatique v1",
        _bot_ready_embed(guild),
    )

    tracker = bot.get_cog("BotTracker")
    if tracker is None:
        return "présentation installée, suivi indisponible"

    row = await bot.db.fetchone("SELECT * FROM bot_tracker_panels WHERE guild_id = ?", (guild.id,))
    message = None
    if row and int(row["channel_id"]) == channel.id:
        try:
            message = await channel.fetch_message(int(row["message_id"]))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            message = None
    if message is None:
        message = await panels.envoyer(channel, panels.depuis_embed(tracker.build_embed(guild)))
    else:
        await message.edit(embed=tracker.build_embed(guild))
    await tracker._save_panel(guild.id, channel.id, message.id, creator_id)
    return "présentation + suivi automatique toutes les minutes"


async def _finish_ready_setup(bot: commands.Bot, builder_cog, guild: discord.Guild, author: discord.Member) -> dict:
    from . import server_builder

    choice_channel = _find_text_channel(server_builder, guild, "ACCUEIL", "choix-des-rôles")
    shop_channel = _find_text_channel(server_builder, guild, "ÉCONOMIE", "boutique")
    announcements = _find_text_channel(server_builder, guild, "ACCUEIL", "annonces")

    role_status = "salon introuvable"
    shop_status = "salon introuvable"
    announce_status = "salon introuvable"
    try:
        if choice_channel:
            role_status = await _ensure_role_panels(bot, guild, choice_channel, author.id)
    except Exception:
        logger.exception("Configuration automatique des panneaux de rôles impossible sur %s", guild.id)
        role_status = "erreur de configuration"
    try:
        if shop_channel:
            shop_status = await _ensure_shop(bot, guild, shop_channel, author.id)
    except Exception:
        logger.exception("Configuration automatique de la boutique impossible sur %s", guild.id)
        shop_status = "erreur de configuration"
    try:
        if announcements:
            announce_status = await _ensure_announcements(bot, builder_cog, guild, announcements, author.id)
    except Exception:
        logger.exception("Publication automatique dans annonces impossible sur %s", guild.id)
        announce_status = "erreur de publication"

    security = await apply_recommended_security(bot, guild)
    cleaned = await _cleanup_old_generated_channels(server_builder, guild)
    return {
        "roles": role_status,
        "shop": shop_status,
        "announcements": announce_status,
        "security_missing": security["missing_permissions"],
        "cleaned": cleaned,
    }


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import server_builder

    template_removed = _install_lean_community_template(server_builder)
    original_build = server_builder.ServerBuilder.build_server

    async def build_server_ready(self, guild: discord.Guild, template_key: str, author: discord.Member):
        result = await original_build(self, guild, template_key, author)
        if result.color and result.color.value == 0xED4245:
            return result
        ready = await _finish_ready_setup(bot, self, guild, author)
        result.add_field(
            name="Prêt à l'emploi",
            value=(
                f"**Choix des rôles :** {ready['roles']}\n"
                f"**Boutique :** {ready['shop']}\n"
                f"**Annonces :** {ready['announcements']}\n"
                f"**Sécurité :** profil renforcé actif"
            ),
            inline=False,
        )
        result.add_field(
            name="Structure allégée",
            value=(
                f"**{template_removed} salons** ont été retirés du modèle Communauté car ils faisaient doublon. "
                f"**{ready['cleaned']} ancien(s) salon(s) généré(s) vide(s)** ont aussi été nettoyés sur cette exécution."
            ),
            inline=False,
        )
        if ready["security_missing"]:
            result.add_field(
                name="Sécurité — permissions manquantes",
                value="● " + "\n● ".join(ready["security_missing"]),
                inline=False,
            )
        return result

    server_builder.ServerBuilder.build_server = build_server_ready
    _INSTALLED = True
    logger.info(
        "+create-server prêt à l'emploi : rôles, boutique, annonces, suivi et sécurité ; %s salons retirés du modèle communauté.",
        template_removed,
    )
