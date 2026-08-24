from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands

from utils import helpers

logger = logging.getLogger("bot.security.honeypot-v49")
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
    """Vérification + salon piège anti-bot, configurable uniquement depuis +setup."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._trap_locks: set[tuple[int, int]] = set()

    async def config(self, guild_id: int, *, enabled_only: bool = True):
        query = "SELECT * FROM honeypot_verification WHERE guild_id = ?"
        if enabled_only:
            query += " AND enabled = 1"
        return await self.bot.db.fetchone(query, (guild_id,))

    async def _log(self, guild: discord.Guild, title: str, description: str, *, danger: bool = False):
        embed = discord.Embed(
            title=title,
            description=description,
            colour=discord.Color.red() if danger else discord.Color.blurple(),
        )
        embed.set_footer(text="SentriX • Vérification & Honeypot")
        try:
            await helpers.send_log(self.bot, guild, "automod", embed)
        except Exception:
            logger.exception("Impossible d'envoyer le log honeypot sur %s.", guild.id)

    def _missing_permissions(self, guild: discord.Guild, sanction: str) -> list[str]:
        me = guild.me
        if me is None:
            return ["SentriX n'est pas disponible dans le cache Discord"]
        checks_map = {
            "Gérer les rôles": me.guild_permissions.manage_roles,
            "Gérer les salons": me.guild_permissions.manage_channels,
            "Gérer les messages": me.guild_permissions.manage_messages,
        }
        if sanction == "softban":
            checks_map["Bannir des membres"] = me.guild_permissions.ban_members
        elif sanction == "kick":
            checks_map["Expulser des membres"] = me.guild_permissions.kick_members
        return [label for label, allowed in checks_map.items() if not allowed]

    async def _find_or_create_role(self, guild: discord.Guild, name: str) -> discord.Role:
        existing = discord.utils.get(guild.roles, name=name)
        if existing is not None and not existing.managed:
            return existing
        return await guild.create_role(
            name=name,
            permissions=discord.Permissions.none(),
            reason="SentriX : configuration vérification/honeypot depuis +setup",
        )

    async def _lock_existing_channels(
        self,
        guild: discord.Guild,
        unverified: discord.Role,
        excluded_ids: set[int],
    ) -> None:
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
            await asyncio.sleep(0.05)

    async def create_or_refresh_system(self, guild: discord.Guild, *, sanction: str = "softban"):
        if sanction not in {"softban", "kick"}:
            sanction = "softban"

        missing = self._missing_permissions(guild, sanction)
        if missing:
            return None, "Permissions manquantes : " + ", ".join(missing)

        unverified = await self._find_or_create_role(guild, "Non vérifié")
        verified = await self._find_or_create_role(guild, "Vérifié")
        me = guild.me
        if me is None:
            return None, "SentriX est introuvable sur ce serveur."

        if unverified >= me.top_role or verified >= me.top_role:
            return None, (
                "Les rôles `Non vérifié` et `Vérifié` doivent être placés sous le rôle SentriX. "
                "Déplace-les puis réessaie depuis +setup."
            )

        old = await self.config(guild.id, enabled_only=False)
        category = guild.get_channel(old["category_id"]) if old and old["category_id"] else None
        if not isinstance(category, discord.CategoryChannel):
            category = await guild.create_category(
                "SentriX • Vérification",
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    unverified: discord.PermissionOverwrite(view_channel=True, read_message_history=True),
                    verified: discord.PermissionOverwrite(view_channel=False),
                    me: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_channels=True,
                        manage_messages=True,
                    ),
                },
                reason="SentriX : vérification + honeypot depuis +setup",
            )

        verify_channel = guild.get_channel(old["verify_channel_id"]) if old and old["verify_channel_id"] else None
        if not isinstance(verify_channel, discord.TextChannel):
            verify_channel = await guild.create_text_channel(
                "verification",
                category=category,
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    unverified: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=False,
                        read_message_history=True,
                    ),
                    verified: discord.PermissionOverwrite(view_channel=False),
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
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    unverified: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        add_reactions=False,
                    ),
                    verified: discord.PermissionOverwrite(view_channel=False),
                    me: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True,
                    ),
                },
                reason="SentriX : salon piège anti-bot",
            )

        await self._lock_existing_channels(
            guild,
            unverified,
            {category.id, verify_channel.id, trap_channel.id},
        )

        try:
            await verify_channel.purge(limit=20, check=lambda message: message.author.id == self.bot.user.id)
        except (discord.Forbidden, discord.HTTPException):
            pass

        verify_embed = discord.Embed(
            title="Vérification SentriX",
            description=(
                "Clique sur **Vérifier mon accès** pour accéder au serveur.\n\n"
                "SentriX retirera le rôle `Non vérifié` et ajoutera le rôle `Vérifié`."
            ),
            colour=discord.Color.blurple(),
        )
        verify_embed.set_footer(text="SentriX • Protection automatique")
        await verify_channel.send(embed=verify_embed, view=HoneypotVerifyView())

        try:
            await trap_channel.purge(limit=20, check=lambda message: message.author.id == self.bot.user.id)
        except (discord.Forbidden, discord.HTTPException):
            pass

        sanction_label = "softban automatique" if sanction == "softban" else "expulsion automatique"
        trap_embed = discord.Embed(
            title="⚠️ NE PAS ENVOYER DE MESSAGE DANS CE SALON",
            description=(
                "Ce salon sert à détecter les **comptes automatisés et spam-bots**.\n"
                f"Tout message envoyé ici peut entraîner un **{sanction_label}**.\n\n"
                f"Pour accéder au serveur, utilise {verify_channel.mention}."
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
            "sanction": sanction,
        }, None

    async def disable_system(self, guild: discord.Guild) -> tuple[bool, str]:
        conf = await self.config(guild.id, enabled_only=False)
        if not conf:
            return True, "Le système était déjà désactivé."

        await self.bot.db.execute(
            "UPDATE honeypot_verification SET enabled = 0 WHERE guild_id = ?",
            (guild.id,),
        )

        unverified = guild.get_role(conf["unverified_role_id"]) if conf["unverified_role_id"] else None
        if unverified is not None:
            # Retire les restrictions posées sur les salons puis libère les membres qui
            # étaient encore en attente. Les salons/rôles sont conservés pour permettre
            # une réactivation propre depuis +setup sans tout recréer.
            for channel in list(guild.channels):
                try:
                    overwrite = channel.overwrites_for(unverified)
                    if not overwrite.is_empty():
                        await channel.set_permissions(
                            unverified,
                            overwrite=None,
                            reason="SentriX : désactivation vérification/honeypot depuis +setup",
                        )
                except (discord.Forbidden, discord.HTTPException):
                    pass
                await asyncio.sleep(0.03)

            for member in list(unverified.members):
                try:
                    await member.remove_roles(
                        unverified,
                        reason="SentriX : vérification/honeypot désactivé",
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass
                await asyncio.sleep(0.03)

        return True, "Vérification + salon piège désactivés. Les salons ont été conservés."

    async def verify_member(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "Cette vérification fonctionne uniquement dans un serveur.",
                ephemeral=True,
            )

        conf = await self.config(interaction.guild.id)
        if not conf:
            return await interaction.response.send_message(
                "Le système de vérification n'est pas activé sur ce serveur.",
                ephemeral=True,
            )

        unverified = interaction.guild.get_role(conf["unverified_role_id"])
        verified = interaction.guild.get_role(conf["verified_role_id"])
        if unverified is None or verified is None:
            return await interaction.response.send_message(
                "La configuration des rôles est incomplète. Préviens un administrateur.",
                ephemeral=True,
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
                "SentriX ne peut pas modifier tes rôles. Vérifie la hiérarchie des rôles.",
                ephemeral=True,
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
            "✅ Vérification réussie. Tu as maintenant accès au serveur.",
            ephemeral=True,
        )
        await self._log(
            interaction.guild,
            "Membre vérifié",
            f"{interaction.user.mention} (`{interaction.user.id}`) a terminé la vérification.",
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # Les bots Discord officiels ne sont jamais placés dans le honeypot. Le système
        # cible les comptes utilisateurs automatisés / selfbots / spam-bots.
        if member.bot:
            return
        conf = await self.config(member.guild.id)
        if not conf:
            return
        unverified = member.guild.get_role(conf["unverified_role_id"])
        if unverified is None:
            return
        try:
            await member.add_roles(
                unverified,
                reason="SentriX : vérification requise à l'arrivée",
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Impossible d'ajouter le rôle Non vérifié à %s sur %s.",
                member.id,
                member.guild.id,
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (
            message.guild is None
            or message.author.bot
            or not isinstance(message.author, discord.Member)
        ):
            return

        conf = await self.config(message.guild.id)
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
                    await member.kick(
                        reason="SentriX honeypot : message envoyé dans le salon piège"
                    )
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
                    "honeypot_kick" if sanction == "kick" else "honeypot_softban",
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
                    "Raison : message envoyé dans le salon piège anti-bot."
                ),
                danger=True,
            )
        finally:
            self._trap_locks.discard(lock_key)


async def _patch_setup_when_available(bot: commands.Bot) -> None:
    """Attend le chargement de Configuration puis injecte le contrôle dans +setup.

    Le module honeypot est chargé avec la pile sécurité, avant cogs.configuration dans
    l'ordre actuel des extensions. On attend donc le Cog Configuration au lieu d'ajouter
    une commande séparée.
    """
    for _ in range(240):  # jusqu'à ~2 minutes, largement au-delà d'un boot normal
        if bot.get_cog("Configuration") is not None:
            break
        await asyncio.sleep(0.5)
    else:
        logger.warning("Configuration non chargée : intégration honeypot +setup reportée.")
        return

    try:
        from cogs import configuration as configuration_module
    except Exception:
        logger.exception("Impossible d'importer cogs.configuration pour le honeypot.")
        return

    setup_cls = getattr(configuration_module, "SetupView", None)
    steps = getattr(configuration_module, "SETUP_STEPS", None)
    if setup_cls is None or not steps:
        logger.warning("SetupView/SETUP_STEPS introuvable pour l'intégration honeypot.")
        return
    if getattr(setup_cls, "_sentrix_honeypot_setup_v49", False):
        return

    original_render_page = setup_cls.render_page
    original_build_embed = setup_cls.build_embed

    def render_page_with_honeypot(self):
        original_render_page(self)
        if self.page == -1:
            return
        try:
            step = configuration_module.SETUP_STEPS[self.page]
        except Exception:
            return
        if step.get("key") != "security":
            return

        menu = discord.ui.Select(
            placeholder="🧩 Vérification + salon piège anti-bot",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Activer — Softban",
                    description="Recommandé : bannit puis débannit le compte piégé.",
                    value="enable_softban",
                ),
                discord.SelectOption(
                    label="Activer — Expulsion",
                    description="Expulse le compte qui écrit dans #stay-muted.",
                    value="enable_kick",
                ),
                discord.SelectOption(
                    label="Désactiver",
                    description="Désactive le piège et libère les membres en attente.",
                    value="disable",
                ),
            ],
            row=3,
        )

        async def callback(interaction: discord.Interaction):
            honeypot = self.bot.get_cog(_COG_NAME)
            if honeypot is None:
                return await interaction.response.send_message(
                    "Le module Vérification + Honeypot n'est pas chargé.",
                    ephemeral=True,
                )
            if not interaction.guild:
                return await interaction.response.send_message(
                    "Cette option fonctionne uniquement dans un serveur.",
                    ephemeral=True,
                )

            value = menu.values[0] if menu.values else ""
            await interaction.response.defer(ephemeral=True, thinking=True)

            if value == "disable":
                _ok, message = await honeypot.disable_system(interaction.guild)
                try:
                    await self.bot.db.log_setup_history(
                        self.guild_id,
                        interaction.user.id,
                        "Sécurité",
                        "vérification + honeypot désactivés",
                        new_value="off",
                    )
                except Exception:
                    pass
                self.render_page()
                await self._refresh_message(interaction)
                return await interaction.followup.send(message, ephemeral=True)

            sanction = "kick" if value == "enable_kick" else "softban"
            result, error = await honeypot.create_or_refresh_system(
                interaction.guild,
                sanction=sanction,
            )
            if error:
                return await interaction.followup.send(
                    f"⚠️ {error}",
                    ephemeral=True,
                )

            try:
                await self.bot.db.log_setup_history(
                    self.guild_id,
                    interaction.user.id,
                    "Sécurité",
                    "vérification + honeypot activés",
                    new_value=sanction,
                )
            except Exception:
                pass

            self.security_touched = True
            self.render_page()
            await self._refresh_message(interaction)
            await interaction.followup.send(
                (
                    "✅ Vérification + salon piège activés.\n"
                    f"Vérification : {result['verify'].mention}\n"
                    f"Piège : {result['trap'].mention}\n"
                    f"Sanction : **{'Softban' if sanction == 'softban' else 'Expulsion'}**"
                ),
                ephemeral=True,
            )

        menu.callback = callback
        try:
            self.add_item(menu)
        except ValueError:
            logger.warning("Impossible d'ajouter le contrôle honeypot à +setup : lignes de composants pleines.")

    async def build_embed_with_honeypot(self):
        embed = await original_build_embed(self)
        if self.page == -1:
            return embed
        try:
            step = configuration_module.SETUP_STEPS[self.page]
        except Exception:
            return embed
        if step.get("key") != "security":
            return embed

        honeypot = self.bot.get_cog(_COG_NAME)
        if honeypot is None:
            return embed
        conf = await honeypot.config(self.guild_id, enabled_only=False)
        if not conf or not conf["enabled"]:
            value = "○ Désactivé"
        else:
            verify = f"<#{conf['verify_channel_id']}>" if conf["verify_channel_id"] else "introuvable"
            trap = f"<#{conf['trap_channel_id']}>" if conf["trap_channel_id"] else "introuvable"
            sanction = "Softban" if str(conf["sanction"]) == "softban" else "Expulsion"
            value = (
                f"● Activé — **{sanction}**\n"
                f"Vérification : {verify}\n"
                f"Salon piège : {trap}"
            )
        embed.add_field(
            name="🧩 Vérification + salon piège anti-bot",
            value=value,
            inline=False,
        )
        return embed

    setup_cls.render_page = render_page_with_honeypot
    setup_cls.build_embed = build_embed_with_honeypot
    setup_cls._sentrix_honeypot_setup_v49 = True
    logger.info("Vérification + Honeypot intégrés directement dans +setup > Sécurité.")


async def install(bot: commands.Bot) -> None:
    """Installe le runtime sans créer aucune nouvelle commande publique."""
    if getattr(bot, "_sentrix_honeypot_verification_v49", False):
        return

    await bot.db.execute(_SCHEMA)

    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(HoneypotVerification(bot))

    if not getattr(bot, "_sentrix_honeypot_verify_view_registered", False):
        bot.add_view(HoneypotVerifyView())
        bot._sentrix_honeypot_verify_view_registered = True

    task = asyncio.create_task(_patch_setup_when_available(bot))
    bot._sentrix_honeypot_setup_task = task
    bot._sentrix_honeypot_verification_v49 = True
    logger.info("Honeypot V49 chargé sans commande publique ; configuration via +setup uniquement.")
