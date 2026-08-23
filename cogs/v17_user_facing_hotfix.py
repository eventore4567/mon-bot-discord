"""Correctifs utilisateur finaux de SentriX.

Cette couche s'installe après les runtimes historiques et reste volontairement
limitée aux correctifs d'interface et de compatibilité.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

logger = logging.getLogger("bot.v17-user-facing-hotfix")

_DISPATCH_PATCHED = False
_MENTION_PATCHED = False
_PLAIN_INSTALL_PATCHED = False
_LANGUAGE_JOIN_PATCHED = False
PRO_TEMPLATE_KEY = "sentrix-official-pro-v4"
PREFIX_ERROR_LIFETIME = 12.0


def _patch_error_dispatch() -> None:
    """Marque le Context avant que les handlers/listeners d'erreur soient planifiés."""
    global _DISPATCH_PATCHED
    if _DISPATCH_PATCHED:
        return

    current_dispatch = commands.Bot.dispatch
    if getattr(current_dispatch, "_sentrix_private_command_errors", False):
        _DISPATCH_PATCHED = True
        return

    def error_dispatch(self: commands.Bot, event_name: str, /, *args: Any, **kwargs: Any):
        if event_name == "command_error" and args:
            ctx = args[0]
            if isinstance(ctx, commands.Context):
                ctx._sentrix_private_error = True
        return current_dispatch(self, event_name, *args, **kwargs)

    error_dispatch._sentrix_private_command_errors = True
    error_dispatch._sentrix_original = current_dispatch
    commands.Bot.dispatch = error_dispatch
    _DISPATCH_PATCHED = True


def _apply_error_context_transport() -> None:
    """Slash = ephemeral. Préfixe = réponse locale temporaire, jamais un DM automatique."""
    current_send = commands.Context.send
    if getattr(current_send, "_sentrix_error_transport_v2", False):
        return

    async def error_send(self: commands.Context, *args, **kwargs):
        if not getattr(self, "_sentrix_private_error", False):
            return await current_send(self, *args, **kwargs)

        interaction = getattr(self, "interaction", None)
        if interaction is not None:
            kwargs["ephemeral"] = True
            return await current_send(self, *args, **kwargs)

        kwargs.pop("ephemeral", None)
        kwargs.setdefault("delete_after", PREFIX_ERROR_LIFETIME)
        kwargs.setdefault("allowed_mentions", discord.AllowedMentions.none())
        message = getattr(self, "message", None)
        if message is not None:
            kwargs.setdefault("reference", message)
            kwargs.setdefault("mention_author", False)
        try:
            result = await current_send(self, *args, **kwargs)
            self._sentrix_response_sent = True
            return result
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            try:
                if message is not None:
                    await message.add_reaction("❌")
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass
            self._sentrix_response_sent = True
            return None

    error_send._sentrix_error_transport_v2 = True
    error_send._sentrix_original = current_send
    commands.Context.send = error_send


def _patch_plain_response_install() -> None:
    """Réapplique le transport d'erreur après chaque réinstallation du rendu final."""
    global _PLAIN_INSTALL_PATCHED
    if _PLAIN_INSTALL_PATCHED:
        return

    from . import plain_response_policy

    current_install = plain_response_policy.install
    if getattr(current_install, "_sentrix_error_install_v2", False):
        _PLAIN_INSTALL_PATCHED = True
        return

    def install_with_error_policy(bot: commands.Bot | None = None) -> None:
        current_install(bot)
        _apply_error_context_transport()

    install_with_error_policy._sentrix_error_install_v2 = True
    install_with_error_policy._sentrix_original = current_install
    plain_response_policy.install = install_with_error_policy
    _PLAIN_INSTALL_PATCHED = True


def _patch_duplicate_mention() -> None:
    """Désactive l'ancienne carte Utilitaires quand le nouvel accueil est disponible."""
    global _MENTION_PATCHED
    if _MENTION_PATCHED:
        return

    from . import common_command_names

    current = common_command_names._mention_help
    if getattr(current, "_sentrix_compact_home_guard", False):
        _MENTION_PATCHED = True
        return

    async def mention_help_without_duplicate(bot: commands.Bot, message: discord.Message):
        if bot.get_cog("Ai") is not None:
            return None
        return await current(bot, message)

    mention_help_without_duplicate._sentrix_compact_home_guard = True
    mention_help_without_duplicate._sentrix_original = current
    common_command_names._mention_help = mention_help_without_duplicate
    _MENTION_PATCHED = True


def _disable_separate_language_join_prompt() -> None:
    """Le choix de langue reste intégré au nouvel accueil, sans second message."""
    global _LANGUAGE_JOIN_PATCHED
    if _LANGUAGE_JOIN_PATCHED:
        return

    from . import language_runtime

    current = getattr(language_runtime, "_send_initial_language_prompt", None)
    if current is None:
        return
    if getattr(current, "_sentrix_join_prompt_disabled", False):
        _LANGUAGE_JOIN_PATCHED = True
        return

    async def no_separate_join_prompt(bot: commands.Bot, guild: discord.Guild):
        del bot, guild
        return None

    no_separate_join_prompt._sentrix_join_prompt_disabled = True
    no_separate_join_prompt._sentrix_original = current
    language_runtime._send_initial_language_prompt = no_separate_join_prompt
    _LANGUAGE_JOIN_PATCHED = True


async def _ensure_create_sentrix(bot: commands.Bot) -> None:
    """Charge le groupe +create sentrix une fois ses dépendances disponibles."""
    if bot.get_command("create sentrix") is not None:
        return
    if bot.get_cog("Tickets") is None or bot.get_cog("Ai") is None:
        return

    existing_group = bot.get_command("create")
    existing_cog = bot.get_cog("CreateSentrix")
    if existing_cog is not None:
        logger.error("CreateSentrix est chargé mais +create sentrix est absent du registre.")
        return
    if existing_group is not None:
        logger.error(
            "Impossible d'enregistrer +create sentrix : +create appartient déjà à %s.",
            getattr(existing_group, "cog_name", "un autre module"),
        )
        return

    from .create_sentrix import CreateSentrix

    try:
        await bot.add_cog(CreateSentrix(bot))
    except commands.CommandRegistrationError:
        logger.exception("Impossible d'enregistrer +create sentrix : collision de commande.")
        return

    if bot.get_command("create sentrix") is None:
        logger.error("Le Cog CreateSentrix a été ajouté mais +create sentrix reste introuvable.")
    else:
        logger.info("Commande +create sentrix enregistrée et disponible.")


async def _grant_support_lead_access(guild: discord.Guild, role: discord.Role) -> None:
    """Donne au Support Lead l'accès aux espaces privés adaptés."""
    for category in guild.categories:
        folded = category.name.casefold()
        if "sentrix" not in folded:
            continue
        if "staff" in folded or "tickets" in folded:
            overwrite = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                manage_threads=True,
            )
        elif "logs" in folded:
            overwrite = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                read_message_history=True,
            )
        else:
            continue

        try:
            await category.set_permissions(
                role,
                overwrite=overwrite,
                reason="Structure professionnelle SentriX",
            )
        except discord.HTTPException:
            continue

        for channel in category.channels:
            try:
                await channel.set_permissions(
                    role,
                    overwrite=overwrite,
                    reason="Structure professionnelle SentriX",
                )
            except discord.HTTPException:
                pass


def _enhance_create_builder(bot: commands.Bot) -> None:
    """Améliore le builder sans remplacer le callback de commande discord.py.

    Important : la commande native garde sa signature (self, ctx). Remplacer
    command.callback dynamiquement a déjà provoqué des erreurs d'invocation et
    l'apparition de <ctx> comme argument utilisateur.
    """
    cog = bot.get_cog("CreateSentrix")
    if cog is None or getattr(cog, "_sentrix_pro_builder_v5", False):
        return

    # La commande native et _mark_installed lisent cette constante au runtime.
    # On aligne donc proprement la version sans toucher à command.callback.
    from . import create_sentrix as create_sentrix_module

    create_sentrix_module.TEMPLATE_KEY = PRO_TEMPLATE_KEY

    original_build = cog._build

    async def professional_build(guild: discord.Guild):
        result = await original_build(guild)

        bot_role, bot_role_new = await cog._role(
            guild,
            "SentriX Bot",
            discord.Color.from_rgb(88, 72, 235),
            discord.Permissions(
                view_audit_log=True,
                manage_roles=True,
                manage_channels=True,
                manage_messages=True,
                manage_threads=True,
                moderate_members=True,
                kick_members=True,
                ban_members=True,
                send_messages=True,
                embed_links=True,
                attach_files=True,
                read_message_history=True,
                add_reactions=True,
            ),
            hoist=True,
        )
        support_lead, support_lead_new = await cog._role(
            guild,
            "Support Lead",
            discord.Color.from_rgb(42, 166, 160),
            discord.Permissions(
                view_audit_log=True,
                moderate_members=True,
                kick_members=True,
                manage_messages=True,
                manage_threads=True,
                manage_nicknames=True,
                move_members=True,
                mute_members=True,
            ),
            hoist=True,
        )

        me = guild.me
        if me is not None and bot_role not in me.roles:
            try:
                await me.add_roles(bot_role, reason="Rôle officiel SentriX")
            except discord.HTTPException:
                logger.warning("Rôle SentriX Bot non attribué automatiquement sur %s", guild.id)

        await _grant_support_lead_access(guild, support_lead)

        result = dict(result or {})
        result["roles_created"] = (
            int(result.get("roles_created", 0))
            + int(bot_role_new)
            + int(support_lead_new)
        )
        result["roles_total"] = 10
        return result

    cog._build = professional_build
    cog._sentrix_pro_builder_v5 = True
    logger.info("Builder professionnel +create sentrix v5 installé avec callback natif.")


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    _patch_error_dispatch()
    _patch_plain_response_install()
    _apply_error_context_transport()
    _patch_duplicate_mention()
    _disable_separate_language_join_prompt()
    await _ensure_create_sentrix(bot)
    _enhance_create_builder(bot)


__all__ = ["install"]
