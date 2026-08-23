"""SentriX V32 — catalogue de logs étendu + rendu adaptatif des très longs messages.

Ajoute cinq journaux réellement distincts sans casser les catégories historiques :
- channels -> logs-salons ;
- cases -> logs-dossiers ;
- spam -> logs-protect-spam-logs ;
- raid -> raidprotect-logs ;
- staff -> moderator-only.

Les événements ne sont redirigés vers une nouvelle catégorie que si son salon est activé
et valide. Sinon le journal historique reste utilisé. Les messages courts/moyens gardent
strictement le renderer V30 ; uniquement au-dessus de LONG_MESSAGE_THRESHOLD le bloc
DÉTAILS est autorisé à grandir pour conserver davantage de contenu.
"""
from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from typing import Iterable

import discord
from discord.ext import commands

from utils import log_service
from . import log_premium_v28 as v28
from . import log_preferred_style_v30 as v30
from . import log_rectangle_v25 as v25

logger = logging.getLogger("bot.log-catalog-v32")
_INSTALLED = False
LONG_MESSAGE_THRESHOLD = 1500
LONG_MESSAGE_LIMIT = 3800

NEW_LOG_TYPES = {
    "channels": {
        "label": "Salons et catégories (création, suppression, modification)",
        "category": "Salons détaillés",
        "legacy_column": None,
        "emits": True,
    },
    "cases": {
        "label": "Dossiers de modération (warns et dossiers de sanction)",
        "category": "Dossiers",
        "legacy_column": None,
        "emits": True,
    },
    "spam": {
        "label": "Protection anti-spam (spam, liens, mentions, caps, emojis, arnaques)",
        "category": "Anti-spam",
        "legacy_column": None,
        "emits": True,
    },
    "raid": {
        "label": "Protection anti-raid (raid, anti-nuke, comptes/bots suspects)",
        "category": "Anti-raid",
        "legacy_column": None,
        "emits": True,
    },
    "staff": {
        "label": "Activité modérateur (commandes staff sensibles)",
        "category": "Staff",
        "legacy_column": None,
        "emits": True,
    },
}

CATEGORY_META = {
    "channels": ("SALONS", "⚙️"),
    "cases": ("DOSSIERS", "🛡️"),
    "spam": ("ANTI-SPAM", "🛡️"),
    "raid": ("ANTI-RAID", "🛡️"),
    "staff": ("STAFF", "🛡️"),
}

CHANNEL_ALIASES: dict[str, tuple[str, ...]] = {
    "tickets": ("logs-tickets",),
    "server": ("logs-serveur",),
    "messages": ("logs-messages",),
    "members": ("logs-membre", "logs-membres"),
    "voice": ("logs-vocal", "logs-vocaux"),
    "roles": ("logs-roles", "logs-rôles"),
    "moderation": ("logs-modération", "logs-moderation"),
    "automod": ("automod", "logs-sécurité", "logs-securite"),
    "channels": ("logs-salons",),
    "cases": ("logs-dossiers",),
    "spam": ("logs-protect-spam-logs", "protect-spam-logs"),
    "raid": ("raidprotect-logs", "logs-raidprotect"),
    "staff": ("moderator-only", "logs-moderator-only"),
}

MODERN_CHANNELS = {
    "channels": ("logs-salons", "Création, suppression et modification des salons et catégories."),
    "cases": ("logs-dossiers", "Dossiers de modération, avertissements et sanctions suivies par SentriX."),
    "spam": ("logs-protect-spam-logs", "Détections anti-spam, liens, mentions, caps, emojis et arnaques."),
    "raid": ("raidprotect-logs", "Détections anti-raid, anti-nuke et protections contre les actions massives."),
    "staff": ("moderator-only", "Commandes sensibles exécutées par les modérateurs et administrateurs."),
}

SPAM_MARKERS = (
    "spam", "anti spam", "lien", "invite", "mention", "majusc", "caps", "emoji",
    "scam", "arnaque", "blacklist", "mot interdit", "terme interdit", "multilingue",
)
RAID_MARKERS = (
    "raid", "nuke", "anti nuke", "afflux", "compte recent", "bot non autorise",
    "actions massives", "action massive", "destruct", "protection serveur",
)
CASE_MARKERS = (
    "avertissement", "warn", "dossier", "case", "note staff", "sanction ajoutee",
    "sanction créée", "sanction creee",
)
STAFF_COMMAND_PREFIXES = (
    "ban", "tempban", "unban", "kick", "warn", "mute", "unmute", "clear", "purge",
    "slowmode", "lock", "unlock", "role", "channel", "ticket", "setup", "logsetup",
    "logs", "set", "automod", "anti", "blacklist", "whitelist", "security", "antinuke",
    "create-server", "create server", "wipe-server", "wipe server", "create-logs",
)


def _plain(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _sample(embed: discord.Embed) -> str:
    values = [str(embed.title or ""), str(embed.description or "")]
    values.extend(f"{field.name} {field.value}" for field in embed.fields)
    return _plain(" ".join(values)[:12000])


def _find_channel(guild: discord.Guild, aliases: Iterable[str]):
    lowered = tuple(alias.casefold() for alias in aliases)
    exact = {alias.casefold() for alias in aliases}
    for channel in guild.text_channels:
        name = channel.name.casefold()
        if name in exact:
            return channel
    for channel in guild.text_channels:
        name = channel.name.casefold()
        if any(alias in name for alias in lowered):
            return channel
    return None


async def _setting_ready(bot: commands.Bot, guild: discord.Guild, log_type: str) -> bool:
    try:
        setting = await log_service.get_log_setting(bot, guild.id, log_type)
        if not setting.get("enabled") or not setting.get("channel_id"):
            return False
        ok, _reason = log_service.validate_channel(guild, int(setting["channel_id"]))
        return bool(ok)
    except Exception:
        return False


async def _restore_long_message(bot: commands.Bot, guild: discord.Guild, embed: discord.Embed) -> discord.Embed:
    """Récupère le texte complet depuis le cache SentriX uniquement quand il est vraiment long."""
    message_id = v28._message_id("messages", embed)
    if not message_id:
        return embed
    try:
        row = await bot.db.fetchone(
            "SELECT content FROM message_log_cache WHERE guild_id = ? AND message_id = ?",
            (guild.id, int(message_id)),
        )
    except Exception:
        return embed
    if not row:
        return embed
    try:
        full = str(row["content"] or "")
    except Exception:
        return embed
    if len(full) < LONG_MESSAGE_THRESHOLD:
        return embed

    event = v28._event("messages", embed)
    wanted = "contenu" if event == "message_delete" else "apres" if event == "message_edit" else ""
    if not wanted:
        return embed

    enriched = embed.copy()
    for index, field in enumerate(list(enriched.fields)):
        if wanted not in _plain(field.name):
            continue
        enriched.set_field_at(
            index,
            name=str(field.name),
            value=full[:LONG_MESSAGE_LIMIT],
            inline=bool(field.inline),
        )
        return enriched
    return embed


def _patch_renderer() -> None:
    """Petit/moyen = fonction V30 originale ; très long = même style mais bloc plus haut."""
    v28.CATEGORY_META.update(CATEGORY_META)
    v30.CATEGORY_ICON.update({
        "channels": "⚙️", "cases": "🛡️", "spam": "🛡️", "raid": "🛡️", "staff": "🛡️",
    })
    v25.CATEGORY_LABELS.update({key: label for key, (label, _icon) in CATEGORY_META.items()})

    current_silent = v28._silent_mention_embed
    if not getattr(current_silent, "_sentrix_adaptive_long_v32", False):
        def adaptive_silent(source: discord.Embed) -> discord.Embed:
            result = current_silent(source)
            for index, field in enumerate(list(source.fields)):
                normalized = _plain(field.name)
                raw = str(field.value or "")
                if not any(token in normalized for token in ("contenu", "avant", "apres")):
                    continue
                if len(raw) < LONG_MESSAGE_THRESHOLD:
                    continue
                safe = raw.replace("@everyone", "＠everyone").replace("@here", "＠here")[:LONG_MESSAGE_LIMIT]
                result.set_field_at(index, name=str(field.name)[:256], value=safe, inline=False)
            return result

        adaptive_silent._sentrix_adaptive_long_v32 = True
        adaptive_silent._sentrix_original = current_silent
        v28._silent_mention_embed = adaptive_silent

    current_details = v30._generic_details
    if not getattr(current_details, "_sentrix_adaptive_long_v32", False):
        def adaptive_details(embed: discord.Embed, consumed: set[int]) -> str | None:
            long_found = any(
                len(str(field.value or "")) >= LONG_MESSAGE_THRESHOLD
                and any(token in _plain(field.name) for token in ("contenu", "avant", "apres"))
                for field in embed.fields
            )
            if not long_found:
                return current_details(embed, consumed)

            rows: list[str] = []
            for index, field in enumerate(embed.fields):
                if index in consumed:
                    continue
                name = str(field.name).strip() or "Information"
                normalized = _plain(name)
                if v30._is_id_field(name):
                    continue
                value = str(field.value or "").strip()
                if not value:
                    continue
                clean_name = re.sub(r"^[^\wÀ-ÿ]+\s*", "", name).strip() or "Information"
                if normalized in {"contenu", "avant", "apres"} or any(token in normalized for token in ("contenu", "avant", "apres")):
                    limit = 3200 if len(value) >= LONG_MESSAGE_THRESHOLD else 900
                    quoted = value[:limit].replace("\n", "\n> ")
                    rows.append(f"**{clean_name}**\n> {quoted}")
                else:
                    value = value[:700]
                    if "\n" in value or len(value) > 120:
                        rows.append(f"**{clean_name}**\n> {value.replace(chr(10), chr(10) + '> ')}")
                    else:
                        rows.append(f"**{clean_name}**  {value}")
                if len(rows) >= 6:
                    break
            if not rows:
                return current_details(embed, consumed)
            return ("### DÉTAILS\n" + "\n\n".join(rows))[:3900]

        adaptive_details._sentrix_adaptive_long_v32 = True
        adaptive_details._sentrix_original = current_details
        v30._generic_details = adaptive_details


def _install_catalog() -> None:
    log_service.LOG_TYPES.update(NEW_LOG_TYPES)
    for category in ("Salons détaillés", "Dossiers", "Anti-spam", "Anti-raid", "Staff"):
        if category not in log_service.CATEGORY_ORDER:
            # Les nouvelles familles restent proches des catégories qu'elles détaillent.
            if category == "Salons détaillés" and "Salons" in log_service.CATEGORY_ORDER:
                pos = log_service.CATEGORY_ORDER.index("Salons") + 1
                log_service.CATEGORY_ORDER.insert(pos, category)
            elif category == "Dossiers" and "Modération" in log_service.CATEGORY_ORDER:
                pos = log_service.CATEGORY_ORDER.index("Modération") + 1
                log_service.CATEGORY_ORDER.insert(pos, category)
            else:
                log_service.CATEGORY_ORDER.append(category)


async def _sync_existing_channels(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
        await asyncio.sleep(5)
        for guild in bot.guilds:
            for log_type, aliases in CHANNEL_ALIASES.items():
                channel = _find_channel(guild, aliases)
                if channel is None:
                    continue
                row = await bot.db.fetchone(
                    "SELECT enabled, channel_id FROM log_settings WHERE guild_id = ? AND log_type = ?",
                    (guild.id, log_type),
                )
                if row is None:
                    await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
                    await log_service.set_log_enabled(bot, guild.id, log_type, True)
                    continue
                current_id = row["channel_id"]
                if not current_id or guild.get_channel(int(current_id)) is None:
                    await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
                    # Une ligne sans salon n'était pas réellement configurée : le salon
                    # nommé explicitement comme log devient donc actif automatiquement.
                    await log_service.set_log_enabled(bot, guild.id, log_type, True)
        logger.info("V32 : synchronisation des salons de logs existants terminée.")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("V32 : synchronisation automatique des salons de logs impossible.")


def _patch_create_logs(bot: commands.Bot) -> None:
    try:
        from . import configuration
    except Exception:
        return
    current = configuration.Configuration.create_log_channels
    if getattr(current, "_sentrix_catalog_v32", False):
        return

    async def create_log_channels_v32(self, guild: discord.Guild, author: discord.Member):
        created = list(await current(self, guild, author))

        category = None
        for aliases in CHANNEL_ALIASES.values():
            channel = _find_channel(guild, aliases)
            if channel is not None and channel.category is not None:
                category = channel.category
                break

        if category is None:
            conf = await self.bot.db.get_guild_config(guild.id)
            overwrites: dict[object, discord.PermissionOverwrite] = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
            }
            if guild.me is not None:
                overwrites[guild.me] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True,
                    embed_links=True, attach_files=True, manage_channels=True,
                )
            if conf:
                try:
                    mod_role_id = conf["mod_role"]
                except Exception:
                    mod_role_id = None
                role = guild.get_role(int(mod_role_id)) if mod_role_id else None
                if role is not None:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True,
                    )
            if author.guild_permissions.administrator:
                overwrites[author] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
            category = await guild.create_category(
                "📡 SentriX — Logs", overwrites=overwrites,
                reason=f"Système de logs V32 créé par {author}",
            )

        for log_type, (name, topic) in MODERN_CHANNELS.items():
            channel = _find_channel(guild, CHANNEL_ALIASES[log_type])
            if channel is None:
                channel = await guild.create_text_channel(
                    name,
                    category=category,
                    topic=topic,
                    reason=f"Système de logs V32 créé par {author}",
                )
                created.append(channel)
            await log_service.set_log_channel(self.bot, guild.id, log_type, channel.id)
            await log_service.set_log_enabled(self.bot, guild.id, log_type, True)
        return created

    create_log_channels_v32._sentrix_catalog_v32 = True
    create_log_channels_v32._sentrix_original = current
    configuration.Configuration.create_log_channels = create_log_channels_v32


def _is_staff_member(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return bool(
        perms.administrator or perms.manage_guild or perms.manage_channels or perms.manage_roles
        or perms.moderate_members or perms.kick_members or perms.ban_members or perms.manage_messages
    )


def _is_staff_command(name: str) -> bool:
    plain = _plain(name).replace(" ", "-")
    return any(plain.startswith(_plain(prefix).replace(" ", "-")) for prefix in STAFF_COMMAND_PREFIXES)


def _staff_embed(member: discord.Member, channel, command_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="Commande staff exécutée",
        colour=0x5865F2,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Membre", value=f"{member.mention}\n`{member.id}`", inline=False)
    if channel is not None:
        mention = getattr(channel, "mention", None) or f"`{getattr(channel, 'id', 'inconnu')}`"
        embed.add_field(name="Salon", value=str(mention), inline=False)
    embed.add_field(name="Commande", value=f"`{command_name}`", inline=False)
    embed.set_footer(text=f"Identifiant : {member.id}")
    return embed


def _install_staff_activity(bot: commands.Bot) -> None:
    async def prefix_completion(ctx: commands.Context):
        if ctx.guild is None or not isinstance(ctx.author, discord.Member) or ctx.command is None:
            return
        name = str(ctx.command.qualified_name)
        if not _is_staff_member(ctx.author) or not _is_staff_command(name):
            return
        await log_service.send_log(bot, ctx.guild, "staff", _staff_embed(ctx.author, ctx.channel, name))

    async def slash_completion(interaction: discord.Interaction, command):
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member) or command is None:
            return
        name = str(getattr(command, "qualified_name", None) or getattr(command, "name", ""))
        if not _is_staff_member(member) or not _is_staff_command(name):
            return
        await log_service.send_log(bot, guild, "staff", _staff_embed(member, interaction.channel, name))

    bot.add_listener(prefix_completion, "on_command_completion")
    bot.add_listener(slash_completion, "on_app_command_completion")


def _install_router(bot: commands.Bot) -> None:
    previous = log_service.send_log
    if getattr(previous, "_sentrix_catalog_v32", False):
        return

    async def routed_send(
        inner_bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        file: discord.File | None = None,
    ) -> bool:
        source = str(log_type)
        working = embed
        if source == "messages" and file is None:
            working = await _restore_long_message(inner_bot, guild, embed)

        sample = _sample(working)
        event = v28._event(source, working)
        target = source

        if source == "server" and event in {"channel_create", "channel_delete", "channel_update"}:
            if await _setting_ready(inner_bot, guild, "channels"):
                target = "channels"
        elif source == "moderation" and any(marker in sample for marker in CASE_MARKERS):
            if await _setting_ready(inner_bot, guild, "cases"):
                target = "cases"
        elif source in {"automod", "security"}:
            if any(marker in sample for marker in RAID_MARKERS) and await _setting_ready(inner_bot, guild, "raid"):
                target = "raid"
            elif any(marker in sample for marker in SPAM_MARKERS) and await _setting_ready(inner_bot, guild, "spam"):
                target = "spam"

        return await previous(inner_bot, guild, target, working, file=file)

    routed_send._sentrix_catalog_v32 = True
    routed_send._sentrix_original = previous
    log_service.send_log = routed_send


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    _install_catalog()
    _patch_renderer()
    _patch_create_logs(bot)
    _install_staff_activity(bot)
    _install_router(bot)

    if not getattr(bot, "_sentrix_log_catalog_sync_v32", None):
        bot._sentrix_log_catalog_sync_v32 = bot.loop.create_task(_sync_existing_channels(bot))

    logger.info(
        "V32 actif : salons/dossiers/anti-spam/anti-raid/staff + messages adaptatifs >= %s caractères.",
        LONG_MESSAGE_THRESHOLD,
    )


__all__ = ["install", "NEW_LOG_TYPES", "CHANNEL_ALIASES", "LONG_MESSAGE_THRESHOLD"]
