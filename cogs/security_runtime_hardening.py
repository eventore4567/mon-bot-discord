"""Renforcement défensif du système de sécurité SentriX.

Cette couche complète AutoMod sans dupliquer son moteur :
- détection des pièces jointes exécutables et du flood identique ;
- anti-nuke étendu aux créations de salons/rôles et aux webhooks ;
- compteur anti-nuke persistant en SQLite pour survivre aux redémarrages ;
- verrou propriétaire sur les réglages de sécurité capables de neutraliser la protection ;
- mode d'urgence +panic avec snapshot/restauration exacte de l'écriture @everyone.

Aucune adresse IP ni donnée réseau privée n'est collectée.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict

import discord

from utils import embeds
from discord import app_commands
from discord.ext import commands

import config
from database.db import PRIMARY_CREATOR_ID
from utils import checks, helpers

logger = logging.getLogger("bot.security.hardening")
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

# Ces commandes permettent de rendre une protection aveugle ou d'exempter un compte.
# Elles sont donc volontairement plus strictes que les réglages AutoMod ordinaires.
CRITICAL_SECURITY_COMMANDS = frozenset({
    "antinuke",
    "antinuke-whitelist-add",
    "antinuke-whitelist-remove",
    "automod-exempt-role-add",
    "automod-exempt-role-remove",
})

NUKE_ACTION_WINDOW = 30
NUKE_ACTION_THRESHOLD = 3


async def _ensure_security_tables(bot: commands.Bot) -> None:
    """Crée uniquement les tables runtime ajoutées par cette couche.

    Elles sont créées ici plutôt que d'attendre une migration manuelle : le module est
    chargé après la connexion SQLite, donc un ancien déploiement est mis à niveau sans
    perte de données au premier démarrage.
    """
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS antinuke_events (
            guild_id INTEGER NOT NULL,
            actor_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    await bot.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_antinuke_events_actor "
        "ON antinuke_events (guild_id, actor_id, created_at)"
    )
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS panic_snapshots (
            guild_id INTEGER PRIMARY KEY,
            created_by INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            state_json TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            actor_id INTEGER,
            event_type TEXT NOT NULL,
            detail TEXT,
            created_at INTEGER NOT NULL
        )
        """
    )


async def _is_bot_owner_id(bot: commands.Bot, user_id: int) -> bool:
    if user_id == PRIMARY_CREATOR_ID or user_id in config.OWNER_IDS:
        return True
    try:
        return bool(await bot.db.is_bot_creator(user_id))
    except Exception:
        return False


async def _critical_owner_ctx(ctx: commands.Context) -> bool:
    if ctx.guild is not None and ctx.author.id == ctx.guild.owner_id:
        return True
    if await _is_bot_owner_id(ctx.bot, ctx.author.id):
        return True
    raise checks.BotPermissionError(
        "Ce réglage de sécurité est critique. Seul le propriétaire du serveur ou du bot peut le modifier."
    )


def critical_security_owner_only():
    return commands.check(_critical_owner_ctx)


async def _critical_owner_interaction(bot: commands.Bot, interaction: discord.Interaction) -> bool:
    if interaction.guild is not None and interaction.user.id == interaction.guild.owner_id:
        return True
    if await _is_bot_owner_id(bot, interaction.user.id):
        return True
    raise app_commands.CheckFailure(
        "Ce réglage de sécurité est réservé au propriétaire du serveur ou du bot."
    )


def _install_critical_command_guards(bot: commands.Bot) -> None:
    """Ajoute le verrou propriétaire aux commandes Hybrid déjà enregistrées.

    On protège les checks texte ET slash. Le marqueur sur l'objet commande rend
    l'installation idempotente lors d'un reload d'extension.
    """
    for name in CRITICAL_SECURITY_COMMANDS:
        command = bot.get_command(name)
        if command is None or getattr(command, "_sentrix_critical_security_guard", False):
            continue

        command.add_check(_critical_owner_ctx)
        app_command = getattr(command, "app_command", None)
        if app_command is not None and hasattr(app_command, "add_check"):
            async def app_check(interaction: discord.Interaction, _bot=bot):
                return await _critical_owner_interaction(_bot, interaction)
            app_command.add_check(app_check)

        command._sentrix_critical_security_guard = True
        logger.info("Verrou propriétaire installé sur %s.", name)


def _install_persistent_antinuke(bot: commands.Bot) -> None:
    """Remplace seulement le compteur volatile d'AutoMod par un compteur SQLite.

    Toute la détection d'acteur et toute la sanction restent celles du Cog AutoMod.
    En cas d'erreur SQLite, on retombe sur son ancien compteur mémoire pour ne jamais
    désactiver la protection à cause d'une panne de stockage.
    """
    automod = bot.get_cog("Automod")
    if automod is None or getattr(automod, "_sentrix_persistent_antinuke", False):
        return

    original_record = automod.record_nuke_action
    lock = asyncio.Lock()

    async def persistent_record_nuke_action(guild: discord.Guild, actor_id: int) -> bool:
        now_ts = int(time.time())
        cutoff = now_ts - NUKE_ACTION_WINDOW
        try:
            async with lock:
                await bot.db.execute(
                    "DELETE FROM antinuke_events WHERE created_at < ?",
                    (cutoff,),
                )
                await bot.db.execute(
                    "INSERT INTO antinuke_events (guild_id, actor_id, created_at) VALUES (?, ?, ?)",
                    (guild.id, actor_id, now_ts),
                )
                row = await bot.db.fetchone(
                    "SELECT COUNT(*) AS n FROM antinuke_events "
                    "WHERE guild_id = ? AND actor_id = ? AND created_at >= ?",
                    (guild.id, actor_id, cutoff),
                )
                count = int(row["n"] if row else 0)
                triggered = count >= NUKE_ACTION_THRESHOLD
                if triggered:
                    # Une même rafale ne doit pas déclencher dix sanctions/logs identiques.
                    await bot.db.execute(
                        "DELETE FROM antinuke_events WHERE guild_id = ? AND actor_id = ?",
                        (guild.id, actor_id),
                    )
                    await bot.db.execute(
                        "INSERT INTO security_events "
                        "(guild_id, actor_id, event_type, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                        (
                            guild.id,
                            actor_id,
                            "antinuke_trigger",
                            f"Seuil atteint: {count} action(s) en {NUKE_ACTION_WINDOW}s",
                            now_ts,
                        ),
                    )
                return triggered
        except Exception:
            logger.exception(
                "Compteur anti-nuke persistant indisponible sur %s; fallback mémoire.",
                guild.id,
            )
            return await original_record(guild, actor_id)

    automod.record_nuke_action = persistent_record_nuke_action
    automod._sentrix_persistent_antinuke = True
    logger.info("Anti-nuke persistant SQLite activé.")


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



def _panneau(titre: str, description: str = "", *, kind: str = "brand") -> discord.Embed:
    """Panneau de securite au format canonique.

    Ce module construisait ses embeds a la main avec des couleurs en dur : ni pied
    de page, ni barre d'identite, et des teintes qui ne suivaient pas la palette.
    """
    return embeds._base(titre, description or None, kind=kind)


class SecurityHardening(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.duplicate_messages: dict[tuple[int, int, str], list[float]] = defaultdict(list)
        self._handled_messages: set[int] = set()
        self._panic_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _remember_handled(self, message_id: int):
        self._handled_messages.add(message_id)
        try:
            self.bot.loop.call_later(15, self._handled_messages.discard, message_id)
        except Exception:
            pass

    async def _security_event(
        self,
        guild_id: int,
        event_type: str,
        *,
        actor_id: int | None = None,
        detail: str = "",
    ) -> None:
        try:
            await self.bot.db.execute(
                "INSERT INTO security_events "
                "(guild_id, actor_id, event_type, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                (guild_id, actor_id, event_type, detail[:1500], int(time.time())),
            )
        except Exception:
            logger.exception("Impossible d'enregistrer l'événement sécurité %s.", event_type)

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
                lowered = attachment.filename.casefold().strip()
                if any(lowered.endswith(ext) for ext in DANGEROUS_ATTACHMENT_EXTENSIONS):
                    dangerous.append(attachment.filename)
            if dangerous:
                self._remember_handled(message.id)
                await self._security_event(
                    message.guild.id,
                    "dangerous_attachment",
                    actor_id=message.author.id,
                    detail=", ".join(dangerous),
                )
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
                now_ts = time.time()
                hits = self.duplicate_messages[key]
                hits.append(now_ts)
                hits[:] = [stamp for stamp in hits if now_ts - stamp <= 12]
                if len(hits) >= 3:
                    self.duplicate_messages[key] = []
                    self._remember_handled(message.id)
                    return await automod._delete_and_warn(
                        message,
                        "Flood de messages identiques détecté.",
                        "antispam_duplicate",
                    )

    async def _antinuke_actor(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int | None = None,
    ):
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

    async def _record_created_resource(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
        reason: str,
    ):
        automod, actor = await self._antinuke_actor(guild, action, target_id)
        if automod is None or actor is None:
            return
        if await automod.record_nuke_action(guild, actor.id):
            await automod.punish_nuker(guild, actor.id, reason)

    async def _panic_row(self, guild_id: int):
        return await self.bot.db.fetchone(
            "SELECT * FROM panic_snapshots WHERE guild_id = ? AND active = 1",
            (guild_id,),
        )

    async def _add_channel_to_panic_snapshot(self, channel: discord.TextChannel, row) -> None:
        """Un salon créé pendant +panic doit être verrouillé puis restaurable lui aussi."""
        try:
            state = json.loads(row["state_json"] or "{}")
        except (TypeError, ValueError):
            state = {}
        key = str(channel.id)
        if key in state:
            return
        overwrite = channel.overwrites_for(channel.guild.default_role)
        state[key] = overwrite.send_messages
        await self.bot.db.execute(
            "UPDATE panic_snapshots SET state_json = ? WHERE guild_id = ? AND active = 1",
            (json.dumps(state, separators=(",", ":")), channel.guild.id),
        )

    async def _lock_text_channel(self, channel: discord.TextChannel, reason: str) -> bool:
        overwrite = channel.overwrites_for(channel.guild.default_role)
        if overwrite.send_messages is False:
            return True
        overwrite.send_messages = False
        try:
            await channel.set_permissions(channel.guild.default_role, overwrite=overwrite, reason=reason)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        await self._record_created_resource(
            channel.guild,
            discord.AuditLogAction.channel_create,
            channel.id,
            "Création massive de salons",
        )

        if isinstance(channel, discord.TextChannel):
            row = await self._panic_row(channel.guild.id)
            if row:
                await self._add_channel_to_panic_snapshot(channel, row)
                await self._lock_text_channel(channel, "Mode PANIC SentriX actif")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await self._record_created_resource(
            role.guild,
            discord.AuditLogAction.role_create,
            role.id,
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

    async def _activate_panic(self, ctx: commands.Context) -> None:
        guild = ctx.guild
        lock = self._panic_locks[guild.id]
        async with lock:
            if await self._panic_row(guild.id):
                return await ctx.send(
                    embed=_panneau('PANIC déjà actif', 'Le serveur est déjà verrouillé. Utilisez `+panic status` ou `+panic off`.', kind="warning")
                )

            state = {}
            for channel in guild.text_channels:
                overwrite = channel.overwrites_for(guild.default_role)
                state[str(channel.id)] = overwrite.send_messages

            # Le snapshot est enregistré AVANT toute modification Discord : même si le bot
            # redémarre au milieu du verrouillage, +panic off sait toujours quoi restaurer.
            now_ts = int(time.time())
            await self.bot.db.execute(
                """
                INSERT INTO panic_snapshots (guild_id, created_by, created_at, state_json, active)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(guild_id) DO UPDATE SET
                    created_by = excluded.created_by,
                    created_at = excluded.created_at,
                    state_json = excluded.state_json,
                    active = 1
                """,
                (guild.id, ctx.author.id, now_ts, json.dumps(state, separators=(",", ":"))),
            )

            result = await apply_recommended_security(self.bot, guild)
            locked = 0
            failed = []
            for channel in guild.text_channels:
                if await self._lock_text_channel(channel, f"Mode PANIC activé par {ctx.author}"):
                    locked += 1
                else:
                    failed.append(channel.mention)

            await self._security_event(
                guild.id,
                "panic_on",
                actor_id=ctx.author.id,
                detail=f"{locked} salon(s) verrouillé(s); {len(failed)} échec(s)",
            )

            embed = _panneau('PANIC ACTIVÉ', "Le serveur est placé en mode d'urgence. Les protections recommandées sont actives et l'écriture @everyone a été verrouillée dans les salons textuels.", kind="danger")
            embed.add_field(name="Salons verrouillés", value=str(locked), inline=True)
            embed.add_field(name="Échecs", value=str(len(failed)), inline=True)
            missing = result.get("missing_permissions", [])
            if missing:
                embed.add_field(
                    name="Permissions bot manquantes",
                    value="\n".join(f"- {item}" for item in missing)[:1024],
                    inline=False,
                )
            if failed:
                embed.add_field(name="Salons non verrouillés", value=" ".join(failed)[:1024], inline=False)
            embed.set_footer(text="SentriX • +panic off pour restaurer exactement les anciens overwrites")
            await ctx.send(embed=embed)

    async def _deactivate_panic(self, ctx: commands.Context) -> None:
        guild = ctx.guild
        lock = self._panic_locks[guild.id]
        async with lock:
            row = await self._panic_row(guild.id)
            if not row:
                return await ctx.send(
                    embed=_panneau('PANIC inactif', "Aucun snapshot d'urgence actif n'a besoin d'être restauré.", kind="brand")
                )

            try:
                state = json.loads(row["state_json"] or "{}")
            except (TypeError, ValueError):
                logger.exception("Snapshot PANIC illisible sur %s.", guild.id)
                return await ctx.send(
                    embed=_panneau('Restauration impossible', "Le snapshot PANIC est illisible. Aucune permission n'a été modifiée.", kind="danger")
                )

            restored = 0
            failed = []
            for channel_id, previous in state.items():
                try:
                    channel = guild.get_channel(int(channel_id))
                except (TypeError, ValueError):
                    channel = None
                if channel is None or not isinstance(channel, discord.TextChannel):
                    continue

                overwrite = channel.overwrites_for(guild.default_role)
                overwrite.send_messages = previous if previous in (True, False, None) else None
                try:
                    await channel.set_permissions(
                        guild.default_role,
                        overwrite=overwrite,
                        reason=f"Fin du mode PANIC par {ctx.author}",
                    )
                    restored += 1
                except (discord.Forbidden, discord.HTTPException):
                    failed.append(channel.mention)

            # Si Discord refuse encore certains salons, on garde le snapshot actif pour
            # permettre un second +panic off après correction de la hiérarchie/permissions.
            if not failed:
                await self.bot.db.execute(
                    "UPDATE panic_snapshots SET active = 0 WHERE guild_id = ?",
                    (guild.id,),
                )

            await self._security_event(
                guild.id,
                "panic_off" if not failed else "panic_restore_partial",
                actor_id=ctx.author.id,
                detail=f"{restored} restauré(s); {len(failed)} échec(s)",
            )

            embed = _panneau(
                "PANIC RESTAURÉ" if not failed else "PANIC PARTIELLEMENT RESTAURÉ",
                (
                    "Les valeurs d'écriture @everyone précédentes ont été remises exactement."
                    if not failed
                    else "Certains salons n'ont pas pu être restaurés. Corrigez les permissions du bot puis relancez `+panic off`."
                ),
                kind="success" if not failed else "warning",
            )
            embed.timestamp = discord.utils.utcnow()
            embed.add_field(name="Salons restaurés", value=str(restored), inline=True)
            embed.add_field(name="Échecs", value=str(len(failed)), inline=True)
            if failed:
                embed.add_field(name="À réessayer", value=" ".join(failed)[:1024], inline=False)
            embed.set_footer(text="SentriX • Les protections AutoMod renforcées restent actives")
            await ctx.send(embed=embed)

    @commands.group(name="panic", invoke_without_command=True)
    @commands.guild_only()
    @critical_security_owner_only()
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def panic(self, ctx: commands.Context):
        """Verrouillage d'urgence du serveur avec snapshot restaurable."""
        await self._activate_panic(ctx)

    @panic.command(name="off", aliases=["stop", "restore", "restaurer"])
    @critical_security_owner_only()
    async def panic_off(self, ctx: commands.Context):
        """Restaure exactement les permissions d'écriture précédant +panic."""
        await self._deactivate_panic(ctx)

    @panic.command(name="status", aliases=["etat", "state"])
    @critical_security_owner_only()
    async def panic_status(self, ctx: commands.Context):
        row = await self._panic_row(ctx.guild.id)
        if not row:
            return await ctx.send(
                embed=_panneau('PANIC inactif', "Le serveur n'est pas en mode d'urgence.", kind="success")
            )
        embed = _panneau('PANIC actif', f"Activé <t:{row['created_at']}:R> par <@{row['created_by']}>.\nUtilisez `+panic off` pour restaurer le snapshot.", kind="danger")
        await ctx.send(embed=embed)

    @commands.command(name="security-repair", aliases=["securite-repair", "security-fix"])
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def security_repair(self, ctx: commands.Context):
        result = await apply_recommended_security(self.bot, ctx.guild)
        missing = result["missing_permissions"]
        e = _panneau(
            "Sécurité SentriX réparée",
            (
                "Anti-spam, anti-liens, anti-invitations, anti-mentions, anti-caps, "
                "anti-émojis, anti-raid, anti-scam, anti-nuke et escalade automatique sont actifs.\n\n"
                "Anti-bot et anti-comptes récents restent désactivés par défaut pour éviter "
                "les expulsions de membres légitimes."
            ),
            kind="success" if not missing else "warning",
        )
        if missing:
            e.add_field(name="Permissions manquantes", value="- " + "\n- ".join(missing), inline=False)
        e.set_footer(text="SentriX • Sécurité défensive")
        await ctx.send(embed=e)


async def install(bot: commands.Bot) -> None:
    """Installation idempotente par instance de bot, compatible reload/tests."""
    if getattr(bot, "_sentrix_security_hardening_installed", False):
        return
    if bot.get_cog("Automod") is None:
        return

    await _ensure_security_tables(bot)
    _install_persistent_antinuke(bot)
    _install_critical_command_guards(bot)

    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(SecurityHardening(bot))

    bot._sentrix_security_hardening_installed = True
    logger.info(
        "Renforcement sécurité SentriX activé : anti-nuke persistant, verrou propriétaire et +panic."
    )
