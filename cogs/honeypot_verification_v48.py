from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import checks, helpers

logger = logging.getLogger("bot.security.honeypot-v48")
_COG_NAME = "HoneypotVerification"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS honeypot_verification (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    category_id INTEGER,
    trap_channel_id INTEGER,
    verify_channel_id INTEGER,
    unverified_role_id INTEGER,
    verified_role_id INTEGER,
    sanction TEXT NOT NULL DEFAULT 'softban',
    created_at INTEGER NOT NULL
)
"""


class HoneypotVerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Vérifier mon accès",
        style=discord.ButtonStyle.success,
        custom_id="sentrix:honeypot:verify",
    )
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog(_COG_NAME)
        if cog is None:
            return await interaction.response.send_message(
                "La vérification SentriX est temporairement indisponible.",
                ephemeral=True,
            )
        await cog.verify_member(interaction)


class HoneypotVerification(commands.Cog, name=_COG_NAME):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._trap_locks: set[tuple[int, int]] = set()

    async def _config(self, guild_id: int):
        return await self.bot.db.fetchone(
            "SELECT * FROM honeypot_verification WHERE guild_id = ? AND enabled = 1",
            (guild_id,),
        )

    async def _log(self, guild: discord.Guild, title: str, description: str, *, danger: bool = False):
        colour = discord.Color.red() if danger else discord.Color.blurple()
        embed = discord.Embed(title=title, description=description, colour=colour)
        embed.set_footer(text="SentriX • Vérification & Honeypot")
        try:
            await helpers.send_log(self.bot, guild, "automod", embed)
        except Exception:
            logger.exception("Impossible d'envoyer le log honeypot sur %s.", guild.id)

    def _setup_missing_permissions(self, guild: discord.Guild) -> list[str]:
        me = guild.me
        if me is None:
            return ["SentriX n'est pas disponible dans le cache Discord"]
        checks_map = {
            "Gérer les rôles": me.guild_permissions.manage_roles,
            "Gérer les salons": me.guild_permissions.manage_channels,
            "Bannir des membres": me.guild_permissions.ban_members,
            "Voir les logs d'audit": me.guild_permissions.view_audit_log,
        }
        return [label for label, allowed in checks_map.items() if not allowed]

    async def _find_or_create_role(self, guild: discord.Guild, name: str) -> discord.Role:
        existing = discord.utils.get(guild.roles, name=name)
        if existing is not None and not existing.managed:
            return existing
        return await guild.create_role(
            name=name,
            permissions=discord.Permissions.none(),
            reason="SentriX : configuration vérification/honeypot",
        )

    async def _lock_existing_channels(self, guild: discord.Guild, unverified: discord.Role, excluded_ids: set[int]):
        overwrite = discord.PermissionOverwrite(
            view_channel=False,
            send_messages=False,
            add_reactions=False,
            create_public_threads=False,
            create_private_threads=False,
            connect=False,
            speak=False,
        )
        for channel in list(guild.channels):
            if channel.id in excluded_ids:
                continue
            try:
                await channel.set_permissions(
                    unverified,
                    overwrite=overwrite,
                    reason="SentriX : accès limité jusqu'à vérification",
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Impossible de verrouiller %s sur %s.", channel.id, guild.id)
            await asyncio.sleep(0.08)

    async def _create_or_refresh_system(self, guild: discord.Guild, *, sanction: str = "softban"):
        missing = self._setup_missing_permissions(guild)
        if missing:
            return None, "Permissions manquantes : " + ", ".join(missing)

        unverified = await self._find_or_create_role(guild, "Non vérifié")
        verified = await self._find_or_create_role(guild, "Vérifié")

        me = guild.me
        if me is None or unverified >= me.top_role or verified >= me.top_role:
            return None, "Place les rôles `Non vérifié` et `Vérifié` sous le rôle SentriX puis relance la commande."

        old = await self.bot.db.fetchone(
            "SELECT * FROM honeypot_verification WHERE guild_id = ?",
            (guild.id,),
        )
        category = guild.get_channel(old["category_id"]) if old and old["category_id"] else None
        if not isinstance(category, discord.CategoryChannel):
            category_overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                unverified: discord.PermissionOverwrite(view_channel=True, read_message_history=True),
                verified: discord.PermissionOverwrite(view_channel=False),
                me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_channels=True,
                    manage_messages=True,
                ),
            }
            category = await guild.create_category(
                "SentriX • Vérification",
                overwrites=category_overwrites,
                reason="SentriX : système vérification/honeypot",
            )

        verify_channel = guild.get_channel(old["verify_channel_id"]) if old and old["verify_channel_id"] else None
        if not isinstance(verify_channel, discord.TextChannel):
            verify_channel = await guild.create_text_channel(
                "verification",
                category=category,
                overwrites={
                    unverified: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=False,
                        read_message_history=True,
                    ),
                    verified: discord.PermissionOverwrite(view_channel=False),
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                },
                reason="SentriX : salon de vérification",
            )

        trap_channel = guild.get_channel(old["trap_channel_id"]) if old and old["trap_channel_id"] else None
        if not isinstance(trap_channel, discord.TextChannel):
            trap_channel = await guild.create_text_channel(
                "stay-muted",
                category=category,
                overwrites={
                    unverified: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        add_reactions=False,
                    ),
                    verified: discord.PermissionOverwrite(view_channel=False),
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True),
                },
                reason="SentriX : salon piège anti-bot",
            )

        await self._lock_existing_channels(
            guild,
            unverified,
            {category.id, verify_channel.id, trap_channel.id},
        )

        try:
            await verify_channel.purge(limit=20, check=lambda m: m.author.id == self.bot.user.id)
        except (discord.Forbidden, discord.HTTPException):
            pass
        verify_embed = discord.Embed(
            title="Vérification SentriX",
            description=(
                "Pour accéder au serveur, clique sur **Vérifier mon accès**.\n\n"
                "Après validation, le rôle `Non vérifié` sera retiré et tu recevras le rôle `Vérifié`."
            ),
            colour=discord.Color.blurple(),
        )
        verify_embed.set_footer(text="SentriX • Protection automatique")
        await verify_channel.send(embed=verify_embed, view=HoneypotVerifyView())

        try:
            await trap_channel.purge(limit=20, check=lambda m: m.author.id == self.bot.user.id)
        except (discord.Forbidden, discord.HTTPException):
            pass
        trap_embed = discord.Embed(
            title="⚠️ NE PAS ENVOYER DE MESSAGE DANS CE SALON",
            description=(
                "Ce salon sert à détecter les **comptes automatisés et spam-bots**.\n"
                "Tout message envoyé ici peut déclencher une **sanction automatique**.\n\n"
                f"Pour accéder au serveur, va dans {verify_channel.mention} et utilise le bouton de vérification."
            ),
            colour=discord.Color.red(),
        )
        trap_embed.set_footer(text="SentriX • Honeypot anti-bot")
        await trap_channel.send(embed=trap_embed)

        await self.bot.db.execute(
            "INSERT INTO honeypot_verification "
            "(guild_id, enabled, category_id, trap_channel_id, verify_channel_id, "
            "unverified_role_id, verified_role_id, sanction, created_at) "
            "VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "enabled=1, category_id=excluded.category_id, trap_channel_id=excluded.trap_channel_id, "
            "verify_channel_id=excluded.verify_channel_id, unverified_role_id=excluded.unverified_role_id, "
            "verified_role_id=excluded.verified_role_id, sanction=excluded.sanction",
            (
                guild.id,
                category.id,
                trap_channel.id,
                verify_channel.id,
                unverified.id,
                verified.id,
                sanction,
                int(time.time()),
            ),
        )
        return {
            "category": category,
            "verify": verify_channel,
            "trap": trap_channel,
            "unverified": unverified,
            "verified": verified,
        }, None

    async def verify_member(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "Cette vérification fonctionne uniquement dans un serveur.", ephemeral=True
            )
        conf = await self._config(interaction.guild.id)
        if not conf:
            return await interaction.response.send_message(
                "Le système de vérification n'est pas activé sur ce serveur.", ephemeral=True
            )

        unverified = interaction.guild.get_role(conf["unverified_role_id"])
        verified = interaction.guild.get_role(conf["verified_role_id"])
        if unverified is None or verified is None:
            return await interaction.response.send_message(
                "La configuration des rôles est incomplète. Préviens un administrateur.", ephemeral=True
            )
        if verified in interaction.user.roles and unverified not in interaction.user.roles:
            return await interaction.response.send_message("Tu es déjà vérifié.", ephemeral=True)

        try:
            if verified not in interaction.user.roles:
                await interaction.user.add_roles(verified, reason="SentriX : vérification réussie")
            if unverified in interaction.user.roles:
                await interaction.user.remove_roles(unverified, reason="SentriX : vérification réussie")
        except (discord.Forbidden, discord.HTTPException):
            return await interaction.response.send_message(
                "SentriX ne peut pas modifier tes rôles. Vérifie la hiérarchie des rôles.", ephemeral=True
            )

        try:
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO verified_users (guild_id, user_id, verified_at) "
                "VALUES (?, ?, strftime('%s','now'))",
                (interaction.guild.id, interaction.user.id),
            )
        except Exception:
            pass
        await interaction.response.send_message(
            "✅ Vérification réussie. Tu as maintenant accès au serveur.", ephemeral=True
        )
        await self._log(
            interaction.guild,
            "Membre vérifié",
            f"{interaction.user.mention} (`{interaction.user.id}`) a terminé la vérification.",
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        conf = await self._config(member.guild.id)
        if not conf:
            return
        unverified = member.guild.get_role(conf["unverified_role_id"])
        if unverified is None:
            return
        try:
            await member.add_roles(unverified, reason="SentriX : vérification requise à l'arrivée")
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Impossible d'ajouter le rôle Non vérifié à %s sur %s.", member.id, member.guild.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or not isinstance(message.author, discord.Member):
            return
        conf = await self._config(message.guild.id)
        if not conf or message.channel.id != conf["trap_channel_id"]:
            return

        member = message.author
        if member.id == message.guild.owner_id or member.guild_permissions.administrator:
            return
        unverified = message.guild.get_role(conf["unverified_role_id"])
        if unverified is None or unverified not in member.roles:
            return

        lock_key = (message.guild.id, member.id)
        if lock_key in self._trap_locks:
            return
        self._trap_locks.add(lock_key)
        try:
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

            sanction = str(conf["sanction"] or "softban")
            action_label = "aucune sanction appliquée"
            if sanction == "kick":
                try:
                    await member.kick(reason="SentriX honeypot : message envoyé dans le salon piège")
                    action_label = "expulsé automatiquement"
                except (discord.Forbidden, discord.HTTPException):
                    action_label = "expulsion impossible (permissions/hiérarchie)"
            else:
                try:
                    await message.guild.ban(
                        member,
                        reason="SentriX honeypot : compte automatisé suspecté",
                        delete_message_seconds=0,
                    )
                    await asyncio.sleep(1.0)
                    await message.guild.unban(
                        discord.Object(id=member.id),
                        reason="SentriX honeypot : fin du softban automatique",
                    )
                    action_label = "softban automatique"
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    action_label = "softban impossible (permissions/hiérarchie)"

            try:
                await self.bot.db.record_sanction(
                    message.guild.id,
                    member.id,
                    self.bot.user.id if self.bot.user else 0,
                    "honeypot_softban" if sanction != "kick" else "honeypot_kick",
                    "Message envoyé dans le salon piège anti-bot SentriX",
                )
            except Exception:
                pass

            await self._log(
                message.guild,
                "Honeypot déclenché",
                (
                    f"Compte : {member.mention} (`{member.id}`)\n"
                    f"Salon : {message.channel.mention}\n"
                    f"Action : **{action_label}**\n"
                    "Raison : message envoyé dans un salon explicitement interdit aux humains."
                ),
                danger=True,
            )
        finally:
            self._trap_locks.discard(lock_key)

    @commands.hybrid_command(
        name="honeypot-setup",
        description="Créer la vérification et le salon piège anti-bot SentriX.",
    )
    @app_commands.choices(
        sanction=[
            app_commands.Choice(name="Softban (recommandé)", value="softban"),
            app_commands.Choice(name="Expulsion", value="kick"),
        ]
    )
    @checks.is_owner_or_admin()
    async def honeypot_setup(self, ctx: commands.Context, sanction: str = "softban"):
        if ctx.guild is None:
            return
        await ctx.defer()
        result, error = await self._create_or_refresh_system(ctx.guild, sanction=sanction)
        if error:
            return await ctx.send(f"❌ {error}")
        await ctx.send(
            "✅ **Protection Vérification + Honeypot activée.**\n"
            f"Vérification : {result['verify'].mention}\n"
            f"Piège anti-bot : {result['trap'].mention}\n"
            f"Rôle bloquant : {result['unverified'].mention}\n"
            f"Rôle vérifié : {result['verified'].mention}\n"
            f"Sanction du piège : **{sanction}**"
        )

    @commands.hybrid_command(
        name="honeypot-status",
        description="Afficher l'état de la protection Vérification + Honeypot.",
    )
    @checks.is_owner_or_admin()
    async def honeypot_status(self, ctx: commands.Context):
        if ctx.guild is None:
            return
        conf = await self._config(ctx.guild.id)
        if not conf:
            return await ctx.send("Le système Vérification + Honeypot est désactivé.")
        verify = ctx.guild.get_channel(conf["verify_channel_id"])
        trap = ctx.guild.get_channel(conf["trap_channel_id"])
        unverified = ctx.guild.get_role(conf["unverified_role_id"])
        verified = ctx.guild.get_role(conf["verified_role_id"])
        await ctx.send(
            "**Vérification + Honeypot SentriX**\n"
            f"État : **ACTIF**\n"
            f"Vérification : {verify.mention if verify else 'introuvable'}\n"
            f"Piège : {trap.mention if trap else 'introuvable'}\n"
            f"Non vérifié : {unverified.mention if unverified else 'introuvable'}\n"
            f"Vérifié : {verified.mention if verified else 'introuvable'}\n"
            f"Sanction : **{conf['sanction']}**"
        )

    @commands.hybrid_command(
        name="honeypot-disable",
        description="Désactiver le honeypot sans supprimer les salons.",
    )
    @checks.is_owner_or_admin()
    async def honeypot_disable(self, ctx: commands.Context):
        if ctx.guild is None:
            return
        await self.bot.db.execute(
            "UPDATE honeypot_verification SET enabled = 0 WHERE guild_id = ?",
            (ctx.guild.id,),
        )
        row = await self.bot.db.fetchone(
            "SELECT unverified_role_id FROM honeypot_verification WHERE guild_id = ?",
            (ctx.guild.id,),
        )
        role = ctx.guild.get_role(row["unverified_role_id"]) if row else None
        if role is not None:
            for member in list(role.members):
                try:
                    await member.remove_roles(role, reason="SentriX : honeypot désactivé")
                except (discord.Forbidden, discord.HTTPException):
                    pass
        await ctx.send("✅ Vérification + Honeypot désactivé. Les membres ne seront plus bloqués à l'arrivée.")


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_honeypot_verification_v48", False):
        return
    await bot.db.execute(_SCHEMA)
    if not getattr(bot, "_sentrix_honeypot_verify_view", False):
        bot.add_view(HoneypotVerifyView())
        bot._sentrix_honeypot_verify_view = True
    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(HoneypotVerification(bot))
    bot._sentrix_honeypot_verification_v48 = True
    logger.info("V48 activé : vérification + salon piège honeypot anti-bot.")
