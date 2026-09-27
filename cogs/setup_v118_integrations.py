"""SentriX V118 — intégrations finales du setup guidé.

Expose les nouveaux systèmes sécurité, la réparation du portail de vérification et le
tracker d'invitations directement dans /setup, sans demander une autre commande.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

import sentrix_setup_compact_v113 as v4
import sentrix_setup_guided_v117 as guided
import sentrix_setup_v116 as v116
from utils import log_service

logger = logging.getLogger("bot.setup-v118")
_INSTALLED = False


class InviteTrackerSetupView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int, author_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id

        feed_select = discord.ui.ChannelSelect(
            placeholder="Salon public des invitations",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=0,
        )

        async def feed_cb(interaction: discord.Interaction):
            from cogs import invite_tracker_runtime as tracker

            channel = feed_select.values[0]
            ok, reason = log_service.validate_channel(interaction.guild, channel.id, needs_file=False)
            if not ok:
                return await interaction.response.send_message(
                    f"SentriX ne peut pas écrire dans ce salon : {reason}.", ephemeral=True
                )
            await tracker.set_feed_setting(
                self.bot, self.guild_id, channel_id=channel.id, enabled=True
            )
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)

        feed_select.callback = feed_cb
        self.add_item(feed_select)

        log_select = discord.ui.ChannelSelect(
            placeholder="Salon des logs d'invitations",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=1,
        )

        async def log_cb(interaction: discord.Interaction):
            channel = log_select.values[0]
            ok, reason = log_service.validate_channel(interaction.guild, channel.id, needs_file=False)
            if not ok:
                return await interaction.response.send_message(
                    f"SentriX ne peut pas écrire dans ce salon : {reason}.", ephemeral=True
                )
            await log_service.set_log_config(
                self.bot,
                self.guild_id,
                "invitations",
                channel_id=channel.id,
                enabled=True,
            )
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)

        log_select.callback = log_cb
        self.add_item(log_select)

        toggle_btn = discord.ui.Button(
            label="Basculer l'affichage", style=discord.ButtonStyle.secondary, row=2
        )

        async def toggle_cb(interaction: discord.Interaction):
            from cogs import invite_tracker_runtime as tracker

            current = await tracker.get_feed_setting(self.bot, self.guild_id)
            channel_id = current.get("feed_channel_id")
            if not channel_id:
                return await interaction.response.send_message(
                    "Choisis d'abord le salon public des invitations.", ephemeral=True
                )
            await tracker.set_feed_setting(
                self.bot,
                self.guild_id,
                channel_id=int(channel_id),
                enabled=not bool(current.get("feed_enabled")),
            )
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)

        toggle_btn.callback = toggle_cb
        self.add_item(toggle_btn)

        test_btn = discord.ui.Button(label="Tester", style=discord.ButtonStyle.primary, row=2)

        async def test_cb(interaction: discord.Interaction):
            from cogs import invite_tracker_runtime as tracker

            current = await tracker.get_feed_setting(self.bot, self.guild_id)
            guild = self.bot.get_guild(self.guild_id)
            channel, problem = (
                tracker._channel_ok(guild, current.get("feed_channel_id"))
                if guild
                else (None, "Serveur introuvable")
            )
            if not current.get("feed_enabled") or channel is None or problem:
                return await interaction.response.send_message(
                    "Active d'abord le tracker dans un salon valide.", ephemeral=True
                )
            await channel.send(
                f"{interaction.user.mention} has been invited by {interaction.user.mention} and has now 1 invite.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await interaction.response.send_message("Message de test envoyé.", ephemeral=True)

        test_btn.callback = test_cb
        self.add_item(test_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Ce panneau appartient à la personne qui a lancé /setup.", ephemeral=True
            )
            return False
        return True

    async def build_embed(self) -> discord.Embed:
        from cogs import invite_tracker_runtime as tracker

        guild = self.bot.get_guild(self.guild_id)
        current = await tracker.get_feed_setting(self.bot, self.guild_id)
        feed = (
            guild.get_channel(current.get("feed_channel_id"))
            if guild and current.get("feed_channel_id")
            else None
        )
        logs = await log_service.get_log_setting(self.bot, self.guild_id, "invitations")
        log_channel = (
            guild.get_channel(logs.get("channel_id"))
            if guild and logs.get("channel_id")
            else None
        )
        enabled = bool(current.get("feed_enabled") and feed)
        description = (
            "Configure ici le tracker d'invitations.\n\n"
            f"Salon public : {feed.mention if feed else '**à choisir**'}\n"
            f"Affichage : **{'ACTIF' if enabled else 'INACTIF'}**\n"
            f"Logs techniques : {log_channel.mention if log_channel else '**à choisir**'}\n\n"
            "Arrivée : @membre has been invited by @inviter and has now 10 invites.\n"
            "Départ : pseudo has left the server. They had been invited by @inviter."
        )
        return discord.Embed(
            title="Invitations",
            description=description,
            colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
        )


class VerificationSetupView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int, author_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id

        repair_btn = discord.ui.Button(
            label="Activer / mettre à jour", style=discord.ButtonStyle.success, row=0
        )

        async def repair_cb(interaction: discord.Interaction):
            await self._apply(interaction, "softban")

        repair_btn.callback = repair_cb
        self.add_item(repair_btn)

        kick_btn = discord.ui.Button(label="Mode kick", style=discord.ButtonStyle.secondary, row=0)

        async def kick_cb(interaction: discord.Interaction):
            await self._apply(interaction, "kick")

        kick_btn.callback = kick_cb
        self.add_item(kick_btn)

        disable_btn = discord.ui.Button(label="Désactiver", style=discord.ButtonStyle.danger, row=0)

        async def disable_cb(interaction: discord.Interaction):
            honeypot = self.bot.get_cog("HoneypotVerification")
            if honeypot is None:
                return await interaction.response.send_message(
                    "Module de vérification indisponible.", ephemeral=True
                )
            await interaction.response.defer()
            _ok, message = await honeypot.disable_system(interaction.guild)
            await interaction.edit_original_response(embed=await self.build_embed(), view=self)
            await interaction.followup.send(message, ephemeral=True)

        disable_btn.callback = disable_cb
        self.add_item(disable_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Ce panneau appartient à la personne qui a lancé /setup.", ephemeral=True
            )
            return False
        return True

    async def _apply(self, interaction: discord.Interaction, sanction: str) -> None:
        honeypot = self.bot.get_cog("HoneypotVerification")
        if honeypot is None:
            return await interaction.response.send_message(
                "Module de vérification indisponible.", ephemeral=True
            )
        await interaction.response.defer()
        current = await honeypot.config(interaction.guild.id, enabled_only=False)
        if current and current["enabled"]:
            # Modification d'un système déjà actif : jamais de création de salon.
            # Si un salon a été supprimé, on laisse le serveur tel quel.
            await self.bot.db.execute(
                "UPDATE honeypot_verification SET sanction=? WHERE guild_id=?",
                (sanction, interaction.guild.id),
            )
            result, error = await honeypot.refresh_existing_panels(interaction.guild)
            if error:
                return await interaction.followup.send(error, ephemeral=True)
            message = (
                f"Panel web mis à jour dans {result['verify'].mention}. "
                "Aucun salon ni catégorie n'a été créé."
            )
        else:
            # Activation explicite depuis /setup : création initiale autorisée.
            result, error = await honeypot.create_or_refresh_system(
                interaction.guild, sanction=sanction
            )
            if error:
                return await interaction.followup.send(error, ephemeral=True)
            message = (
                f"Vérification web activée : {result['verify'].mention} · "
                f"Honeypot : {result['trap'].mention}."
            )
        await interaction.edit_original_response(embed=await self.build_embed(), view=self)
        await interaction.followup.send(message, ephemeral=True)

    async def build_embed(self) -> discord.Embed:
        guild = self.bot.get_guild(self.guild_id)
        honeypot = self.bot.get_cog("HoneypotVerification")
        conf = await honeypot.config(self.guild_id, enabled_only=False) if honeypot else None
        active = bool(conf and conf["enabled"])
        verify = (
            guild.get_channel(conf["verify_channel_id"])
            if active and guild and conf["verify_channel_id"]
            else None
        )
        trap = (
            guild.get_channel(conf["trap_channel_id"])
            if active and guild and conf["trap_channel_id"]
            else None
        )
        sanction = str(conf["sanction"] or "softban") if conf else "softban"
        description = (
            f"État : **{'ACTIF' if active else 'INACTIF'}**\n"
            f"Vérification : {verify.mention if verify else '**non publiée**'}\n"
            f"Honeypot : {trap.mention if trap else '**non publié**'}\n"
            f"Sanction du piège : **{sanction}**\n\n"
            "Le membre clique sur le panel Discord puis termine la vérification sur le site SentriX "
            "(OAuth Discord, règlement, ancienneté du compte, CAPTCHA et calcul).\n\n"
            "Si le système est déjà actif, **Mettre à jour** remplace seulement les panels existants. "
            "Un salon supprimé n'est jamais recréé automatiquement. La création de structure n'arrive "
            "que lors d'une nouvelle activation explicite."
        )
        return discord.Embed(
            title="Vérification & Honeypot",
            description=description,
            colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
        )


def _extend_guided_catalogue() -> None:
    keys = list(guided.HOME_MODULE_KEYS)
    for key in ("verification", "roles", "invitations", "rules", "profile"):
        if key not in keys:
            if key == "invitations" and "logs" in keys:
                keys.insert(keys.index("logs") + 1, key)
            else:
                keys.append(key)
    guided.HOME_MODULE_KEYS = tuple(keys)

    guided.GUIDED_SECTIONS["invitations"] = (
        guided._s(
            "tracker",
            "Tracker public",
            "Choisis le salon où SentriX affichera qui a invité chaque nouveau membre.",
            "internal:invitations",
        ),
    )
    guided.GUIDED_SECTIONS["verification"] = (
        guided._s(
            "portal",
            "Portail & Honeypot",
            "Publie ou répare le panneau de vérification et le salon piège anti-bot.",
            "internal:verification",
        ),
        guided._s(
            "role",
            "Rôle vérifié",
            "Choisis le rôle reçu après la validation.",
            "config:verify_role",
        ),
    )

    guided.GUIDED_SECTIONS["rules"] = (
        guided._s(
            "panel",
            "Panneau du règlement",
            "Écris les règles, choisis le salon et publie le panneau d'acceptation.",
            "internal:rules",
        ),
    )

    members = list(guided.GUIDED_SECTIONS.get("members", ()))
    if not any(section.key == "verification_portal" for section in members):
        members.append(
            guided._s(
                "verification_portal",
                "Portail de vérification",
                "Active ou répare verification et stay-muted avec leurs panneaux SentriX.",
                "internal:verification",
            )
        )
        members.append(
            guided._s(
                "rules",
                "Règlement",
                "Configure le texte, le salon et l'acceptation des règles avant la vérification.",
                "internal:rules",
            )
        )
        guided.GUIDED_SECTIONS["members"] = tuple(members)


def _patch_v116_action() -> None:
    current = v116._run_action
    if getattr(current, "_sentrix_v118", False):
        return

    async def run_action_v118(view, interaction: discord.Interaction):
        v116._ensure_state(view)
        module = v116.MODULE_BY_KEY[view._v116_module]
        section = next(s for s in module.sections if s.key == view._v116_section)
        action = section.action
        if action == "internal:invitations":
            subview = InviteTrackerSetupView(view.bot, view.guild_id, interaction.user.id)
            return await interaction.response.send_message(
                embed=await subview.build_embed(), view=subview, ephemeral=True
            )
        if action == "internal:verification":
            subview = VerificationSetupView(view.bot, view.guild_id, interaction.user.id)
            return await interaction.response.send_message(
                embed=await subview.build_embed(), view=subview, ephemeral=True
            )
        if action == "internal:rules":
            from cogs.verify_setup_interactive_v78 import open_setup_interaction
            return await open_setup_interaction(interaction)
        return await current(view, interaction)

    run_action_v118._sentrix_v118 = True
    run_action_v118._sentrix_original = current
    v116._run_action = run_action_v118


def _patch_internal_open() -> None:
    current = guided._open_internal
    if getattr(current, "_sentrix_v118", False):
        return

    async def open_internal_v118(view, interaction: discord.Interaction, name: str):
        if name == "invitations":
            subview = InviteTrackerSetupView(view.bot, view.guild_id, interaction.user.id)
            return await interaction.response.send_message(
                embed=await subview.build_embed(), view=subview, ephemeral=True
            )
        if name == "verification":
            subview = VerificationSetupView(view.bot, view.guild_id, interaction.user.id)
            return await interaction.response.send_message(
                embed=await subview.build_embed(), view=subview, ephemeral=True
            )
        if name == "rules":
            from cogs.verify_setup_interactive_v78 import open_setup_interaction
            return await open_setup_interaction(interaction)
        return await current(view, interaction, name)

    open_internal_v118._sentrix_v118 = True
    open_internal_v118._sentrix_original = current
    guided._open_internal = open_internal_v118


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    _extend_guided_catalogue()
    _patch_internal_open()
    _patch_v116_action()
    _INSTALLED = True
    logger.info(
        "Setup V118 actif : sécurité avancée, vérification réparable et tracker invitations intégrés."
    )


async def setup(bot: commands.Bot) -> None:
    # Le setup V118 dépend du vrai moteur de vérification. L'installation est idempotente
    # et garantit aussi la réparation automatique des anciens salons vides.
    try:
        from cogs.honeypot_verification_v48 import install as install_honeypot
        await install_honeypot(bot)
    except Exception:
        logger.exception("Setup V118 : moteur honeypot/vérification indisponible.")
    install(bot)

    async def on_ready_reapply():
        install(bot)

    if not getattr(bot, "_sentrix_setup_v118_ready_listener", False):
        bot.add_listener(on_ready_reapply, "on_ready")
        bot._sentrix_setup_v118_ready_listener = True


__all__ = ["InviteTrackerSetupView", "VerificationSetupView", "install", "setup"]
