"""Renforcement défensif du système de sécurité SentriX.

Complète l'AutoMod existant sans remplacer sa logique : pièces jointes exécutables,
mentions massives, flood identique et anti-nuke sur créations/webhooks.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

import discord
from discord.ext import commands

logger = logging.getLogger("bot.security.hardening")
_INSTALLED = False
_COG_NAME = "SecurityHardening"

DANGEROUS_ATTACHMENT_EXTENSIONS = {
    ".exe", ".scr", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".vbe",
    ".js", ".jse", ".wsf", ".wsh", ".msi", ".msp", ".lnk", ".hta",
    ".jar", ".apk", ".dmg", ".pkg", ".iso",
}

RECOMMENDED_AUTOMOD = {
    "antispam": 1,
    "antilink": 1,
    "antiinvite": 1,
    "antimention": 1,
    "anticaps": 1,
    "antiemoji": 1,
    "antiraid": 1,
    "antiscam": 1,
    "antinuke": 1,
    "escalation": 1,
}


async def apply_recommended_security(bot: commands.Bot, guild: discord.Guild) -> dict:
    """Active un profil robuste sans forcer anti-bot/anti-comptes récents."""
    for field, value in RECOMMENDED_AUTOMOD.items():
        await bot.db.set_automod(guild.id, field, value)
    await bot.db.set_guild_config(guild.id, "security_level", "eleve")

    automod = bot.get_cog("Automod")
    if automod is not None:
        automod.automod_cache.pop(guild.id, None)

    me = guild.me
    if me is None:
        return {"missing_permissions": ["Bot absent du cache Discord"]}
    required = {
        "Gérer les messages": me.guild_permissions.manage_messages,
        "Voir les logs d'audit": me.guild_permissions.view_audit_log,
        "Bannir des membres": me.guild_permissions.ban_members,
        "Expulser des membres": me.guild_permissions.kick_members,
        "Modérer les membres": me.guild_permissions.moderate_members,
        "Gérer les rôles": me.guild_permissions.manage_roles,
        "Gérer les salons": me.guild_permissions.manage_channels,
    }
    return {"missing_permissions": [name for name, ok in required.items() if not ok]}


class SecurityHardening(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.duplicate_messages: dict[tuple[int, int, str], list[float]] = defaultdict(list)
        self._handled_messages: set[int] = set()

    def _remember_handled(self, message_id: int):
        self._handled_messages.add(message_id)
        try:
            self.bot.loop.call_later(15, self._handled_messages.discard, message_id)
        except Exception:
            pass

    async def _automod_context(self, message: discord.Message):
        automod = self.bot.get_cog("Automod")
        if automod is None or not message.guild:
            return None, None
        ignored = await automod.get_ignored_channels_cached(message.guild.id)
        if message.channel.id in ignored:
            return automod, None
        if await automod.is_automod_exempt(message.author):
            return automod, None
        conf = await automod.get_automod_cached(message.guild.id)
        return automod, conf or None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or message.id in self._handled_messages:
            return

        automod, conf = await self._automod_context(message)
        if automod is None or not conf:
            return

        # message.mentions ne couvre pas correctement tous les @roles/@everyone.
        if conf.get("antimention"):
            total_targets = len(message.mentions) + len(message.role_mentions)
            if message.mention_everyone or len(message.role_mentions) >= 3 or total_targets >= 5:
                self._remember_handled(message.id)
                return await automod._delete_and_warn(
                    message,
                    "Mention massive, @everyone/@here ou mentions de rôles détectées.",
                    "antimention",
                )

        # Une pièce jointe exécutable échappe à l'anti-lien classique.
        if conf.get("antiscam") and message.attachments:
            dangerous = []
            for attachment in message.attachments:
                lowered = attachment.filename.casefold()
                if any(lowered.endswith(ext) for ext in DANGEROUS_ATTACHMENT_EXTENSIONS):
                    dangerous.append(attachment.filename)
            if dangerous:
                self._remember_handled(message.id)
                return await automod._delete_and_warn(
                    message,
                    "Pièce jointe exécutable potentiellement dangereuse détectée.",
                    "dangerous_attachment",
                )

        # Bloque plus vite un copié-collé répété sans durcir tout l'anti-spam.
        if conf.get("antispam"):
            normalized = " ".join(message.content.casefold().split())
            if len(normalized) >= 3:
                key = (message.guild.id, message.author.id, normalized[:300])
                now = time.time()
                hits = self.duplicate_messages[key]
                hits.append(now)
                hits[:] = [stamp for stamp in hits if now - stamp <= 12]
                if len(hits) >= 3:
                    self.duplicate_messages[key] = []
                    self._remember_handled(message.id)
                    return await automod._delete_and_warn(
                        message,
                        "Flood de messages identiques détecté.",
                        "antispam_duplicate",
                    )

    async def _antinuke_actor(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int | None = None):
        automod = self.bot.get_cog("Automod")
        if automod is None:
            return None, None
        conf = await automod.get_automod_cached(guild.id)
        if not conf or not conf.get("antinuke"):
            return automod, None
        actor = await automod.get_audit_actor(guild, action, target_id)
        if await automod.is_antinuke_exempt(guild, actor):
            return automod, None
        return automod, actor

    async def _record_created_resource(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int, reason: str):
        automod, actor = await self._antinuke_actor(guild, action, target_id)
        if automod is None or actor is None:
            return
        if await automod.record_nuke_action(guild, actor.id):
            await automod.punish_nuker(guild, actor.id, reason)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        await self._record_created_resource(
            channel.guild, discord.AuditLogAction.channel_create, channel.id,
            "Création massive de salons",
        )

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await self._record_created_resource(
            role.guild, discord.AuditLogAction.role_create, role.id,
            "Création massive de rôles",
        )

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        guild = channel.guild
        automod = self.bot.get_cog("Automod")
        if automod is None:
            return
        conf = await automod.get_automod_cached(guild.id)
        if not conf or not conf.get("antinuke"):
            return

        actor = None
        for action in (
            discord.AuditLogAction.webhook_create,
            discord.AuditLogAction.webhook_delete,
            discord.AuditLogAction.webhook_update,
        ):
            actor = await automod.get_audit_actor(guild, action)
            if actor is not None:
                break
        if await automod.is_antinuke_exempt(guild, actor):
            return
        if actor is not None and await automod.record_nuke_action(guild, actor.id):
            await automod.punish_nuker(guild, actor.id, "Modifications massives de webhooks")

    @commands.command(name="security-repair", aliases=["securite-repair", "security-fix"])
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def security_repair(self, ctx: commands.Context):
        result = await apply_recommended_security(self.bot, ctx.guild)
        missing = result["missing_permissions"]
        e = discord.Embed(
            title="Sécurité SentriX réparée",
            description=(
                "Anti-spam, anti-liens, anti-invitations, anti-mentions, anti-caps, "
                "anti-émojis, anti-raid, anti-scam, anti-nuke et escalade automatique sont actifs.\n\n"
                "Anti-bot et anti-comptes récents restent désactivés par défaut pour éviter "
                "les expulsions de membres légitimes."
            ),
            color=0x57F287 if not missing else 0xFEE75C,
        )
        if missing:
            e.add_field(name="Permissions manquantes", value="● " + "\n● ".join(missing), inline=False)
        e.set_footer(text="SentriX • Sécurité défensive")
        await ctx.send(embed=e)


async def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    if bot.get_cog("Automod") is None:
        return
    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(SecurityHardening(bot))
    _INSTALLED = True
    logger.info("Renforcement défensif de la sécurité SentriX activé.")
