"""Chargeur runtime SentriX.

Les correctifs fonctionnels restent ciblés par cog. L'interface, l'aide et les journaux
ont un propriétaire unique :
- embeds : utils.embeds ;
- setup : cogs.setup_control_center ;
- help : cogs.help ;
- logs : cogs.logs -> utils.log_service.
"""
from __future__ import annotations

import inspect
import logging

import discord
from discord.ext import commands

from .afk_nickname import install as install_afk_nickname
from .afk_signature_fix import install as install_afk_signature_fix
from .ai_reliability import install as install_ai_reliability
from .bot_tracker import install as install_bot_tracker
from .command_error_release_v41 import install as install_command_error_release_v41
from .command_hardening_v41 import install as install_command_hardening_v41
from .command_runtime_hardening_v18 import repair_wrapped_signatures
from .command_response_guard import install as install_command_response_guard
from .common_command_names import install as install_common_command_names
from .emoji_name_lookup import install as install_emoji_name_lookup
from .final_interaction_policy import install as install_final_interaction_policy
from .generated_logs_sync import install as install_generated_logs_sync
from .giveaway_antialt import install as install_giveaway_antialt
from .language_official_bridge import install as install_language_official_bridge
from .language_runtime import install as install_language_runtime
from .language_setup_finalizer import install as install_language_setup_finalizer
from .natural_music_intent_guard import install as install_natural_music_intent_guard
from .no_auto_tracker import install as install_no_auto_tracker
from .owner_sanction_immunity import install as install_owner_sanction_immunity
from .permission_guard import install as install_permission_guard
from .poll_ui import install_poll_ui
from .production_ops import install as install_production_ops
from .public_language_choice import install as install_public_language_choice
from .remove_code_command import install as install_remove_code_command
from .reply_reference_fix import install as install_reply_reference_fix
from .rolepanel_display_fix import install as install_rolepanel_display_fix
from .rolepanel_more_notifications import install as install_more_notification_roles
from .rolepanel_notifications import install as install_notification_rolepanel
from .security_command_center import install as install_security_command_center
from .security_runtime_hardening import install as install_security_hardening
from .server_builder_channel_guides import install as install_server_builder_channel_guides
from .server_builder_everyone import install_server_builder_everyone_ping
from .server_builder_existing_bootstrap import install as install_existing_server_bootstrap
from .server_builder_ready_setup import install as install_server_builder_ready_setup
from .server_choice_roles import install as install_server_choice_roles
from .setup_control_center import install as install_setup_control_center
from .shop_default_prices import install as install_shop_default_prices
from .smart_creation_guard_v47 import install as install_smart_creation_guard_v47
from .slash_reliability_v7 import install as install_slash_reliability_v7
from .slash_command_budget import install as install_slash_command_budget
from .stability_runtime import install as install_stability_runtime
from .ticket_claim_security import install as install_ticket_claim_security
from .ticket_ping_role import install_setup_ui as install_ticket_ping_setup
from .ticket_ping_role import install_ticket_runtime as install_ticket_ping_runtime

logger = logging.getLogger("bot.cogs")
_ORIGINAL_LOAD_EXTENSION = commands.Bot.load_extension
_FINAL_EXTENSION = "cogs.visual_experience_v5"
_OFFICIAL_HELP_EXTENSION = "cogs.help"


def _matches(name: str, extension: str) -> bool:
    return name == extension or name.endswith("." + extension.rsplit(".", 1)[-1])


async def _run_installer(label: str, installer, *args):
    try:
        result = installer(*args)
        if inspect.isawaitable(result):
            result = await result
        return result
    except Exception:
        logger.exception("Échec du correctif runtime « %s » ; poursuite du chargement.", label)
        return None


def _install_embed_component_fix(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_embed_component_fix", False):
        return
    try:
        from . import embed_builder
        if not getattr(embed_builder.EmbedBuilderView, "_sentrix_cancel_emoji_fix", False):
            original_init = embed_builder.EmbedBuilderView.__init__

            def patched_init(self, *args, **kwargs):
                original_init(self, *args, **kwargs)
                for item in self.children:
                    if isinstance(item, discord.ui.Button) and item.label == "Annuler":
                        item.emoji = None

            embed_builder.EmbedBuilderView.__init__ = patched_init
            embed_builder.EmbedBuilderView._sentrix_cancel_emoji_fix = True
        bot._sentrix_embed_component_fix = True
    except Exception:
        logger.exception("Impossible d'installer le correctif de composant +embed.")


async def _install_configuration_critical_patches(bot: commands.Bot) -> None:
    if bot.get_cog("Configuration") is None:
        return
    await _run_installer("rôle de ping tickets setup", install_ticket_ping_setup, bot)
    await _run_installer("choix de langue public", install_public_language_choice, bot)
    await _run_installer("moteur de langue setup", install_language_runtime, bot)
    await _run_installer("finaliseur de langue setup", install_language_setup_finalizer, bot)
    await _run_installer("centre de configuration officiel", install_setup_control_center, bot)
    # Le nouveau +setup est installé APRES les anciens correctifs de langue : on rebranche
    # donc explicitement la langue sur son vrai propriétaire, sans restaurer l'ancienne UI.
    await _run_installer("pont langue setup officiel", install_language_official_bridge, bot)


async def _install_common_runtime(bot: commands.Bot) -> None:
    await _run_installer("aliases techniques", install_common_command_names, bot)
    await _run_installer("réponses sans référence fragile", install_reply_reference_fix)
    await _run_installer("suivi bot", install_bot_tracker, bot)
    await _run_installer("prix boutique par défaut", install_shop_default_prices, bot)
    await _run_installer("rôles de choix serveur", install_server_choice_roles, bot)
    await _run_installer("catalogue rôles notifications", install_more_notification_roles)
    await _run_installer("panel rôles notifications", install_notification_rolepanel, bot)


async def _install_extension_specific(bot: commands.Bot, name: str) -> None:
    if _matches(name, "cogs.automod"):
        await _run_installer("renforcement sécurité", install_security_hardening, bot)
        await _run_installer("analyse créations anti-nuke", install_smart_creation_guard_v47, bot)
        await _run_installer("centre sécurité", install_security_command_center, bot)
        await _run_installer("immunité propriétaire sanctions", install_owner_sanction_immunity, bot)
    if _matches(name, "cogs.security_tools"):
        await _run_installer("centre sécurité avancé", install_security_command_center, bot)
    if _matches(name, "cogs.moderation"):
        await _run_installer("immunité propriétaire sanctions", install_owner_sanction_immunity, bot)
    if _matches(name, "cogs.ai"):
        await _run_installer("fiabilité IA", install_ai_reliability)
        await _run_installer("garde intention musique", install_natural_music_intent_guard, bot)
        await _run_installer("suppression ancienne commande code", install_remove_code_command, bot)
    if _matches(name, "cogs.utility"):
        await _run_installer("ajout emoji par nom", install_emoji_name_lookup, bot)
        await _run_installer("interface sondages", install_poll_ui, bot)
        await _run_installer("pseudo AFK", install_afk_nickname, bot)
        await _run_installer("signature AFK", install_afk_signature_fix, bot)
    if _matches(name, "cogs.configuration"):
        await _install_configuration_critical_patches(bot)
    if _matches(name, "cogs.tickets"):
        await _run_installer("sécurité claim tickets", install_ticket_claim_security, bot)
        await _run_installer("rôle de ping tickets runtime", install_ticket_ping_runtime, bot)
    if _matches(name, "cogs.events"):
        await _run_installer("anti-alt giveaway", install_giveaway_antialt, bot)
    if _matches(name, "cogs.server_builder"):
        await _run_installer("ping everyone server builder", install_server_builder_everyone_ping, bot)
        await _run_installer("guides salons server builder", install_server_builder_channel_guides, bot)
        await _run_installer("ready setup server builder", install_server_builder_ready_setup, bot)
        await _run_installer("désactivation auto tracker", install_no_auto_tracker, bot)
        await _run_installer("synchronisation logs générés", install_generated_logs_sync, bot)
        await _run_installer("affichage rolepanel", install_rolepanel_display_fix, bot)
        await _run_installer("bootstrap serveurs existants", install_existing_server_bootstrap, bot)
    if _matches(name, "cogs.embed_builder"):
        _install_embed_component_fix(bot)
        await _run_installer("fiabilité slash V7", install_slash_reliability_v7, bot)
    await _run_installer("stabilité ciblée", install_stability_runtime, bot, name)


async def _install_release_and_official_server(bot: commands.Bot) -> None:
    try:
        from .release_announcer import install as install_release_announcer
        from .release_ping_policy_v63 import install as install_release_ping_policy_v63
        await _run_installer("annonceur releases", install_release_announcer, bot)
        await _run_installer("politique releases majeures", install_release_ping_policy_v63, bot)
    except Exception:
        logger.exception("Impossible de préparer la politique de release.")
    if bot.get_cog("ServerBuilder") is not None:
        try:
            from .official_server import install as install_official_server
            from .official_server_command_fix import install as install_official_server_command_fix
            await _run_installer("serveur officiel", install_official_server, bot)
            await _run_installer("signature serveur officiel", install_official_server_command_fix, bot)
        except Exception:
            logger.exception("Impossible de préparer le constructeur officiel.")


async def _install_error_stack(bot: commands.Bot) -> None:
    try:
        from .error_experience_v3 import install as install_error_experience_v3
        await _run_installer("erreurs utilisateur", install_error_experience_v3, bot)
    except Exception:
        logger.exception("Impossible d'installer le handler d'erreurs utilisateur.")
    await _run_installer("observabilité réponses commandes", install_command_response_guard, bot)


async def _load_official_help(bot: commands.Bot) -> None:
    if bot.get_cog("SentriXHelp") is not None:
        await _run_installer("pont langue help officiel", install_language_official_bridge, bot)
        return
    if _OFFICIAL_HELP_EXTENSION in bot.extensions:
        await _run_installer("pont langue help officiel", install_language_official_bridge, bot)
        return
    try:
        await _ORIGINAL_LOAD_EXTENSION(bot, _OFFICIAL_HELP_EXTENSION)
        bot._sentrix_help_owner = _OFFICIAL_HELP_EXTENSION
        install_permission_guard(bot)
        # Le help officiel vient d'être chargé après l'ancien moteur de langue. Le pont
        # pose ses marqueurs sur le NOUVEL objet +help au lieu de restaurer son prédécesseur.
        await _run_installer("pont langue help officiel", install_language_official_bridge, bot)
        logger.info("Help officiel SentriX chargé : ancien +help remplacé.")
    except Exception:
        logger.exception("Impossible de charger le help officiel SentriX.")
        raise


async def finalize_runtime(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_finalized_clean", False):
        return
    await _install_common_runtime(bot)
    await _install_configuration_critical_patches(bot)
    await _install_release_and_official_server(bot)
    await _install_error_stack(bot)
    await _run_installer("renforcement commandes V41", install_command_hardening_v41, bot)
    await _run_installer("opérations production", install_production_ops, bot)
    await _run_installer("permissions commandes", install_permission_guard, bot)
    await _run_installer("politique finale interactions", install_final_interaction_policy, bot)
    await _run_installer("libération concurrence slash V41", install_command_error_release_v41, bot)
    await _load_official_help(bot)
    bot._sentrix_runtime_finalized_clean = True
    logger.info("Runtime SentriX finalisé : un setup, un help, un renderer, un logger.")


async def _load_extension_with_sentrix_patches(bot: commands.Bot, name: str, *, package: str | None = None):
    install_slash_command_budget(bot)
    result = await _ORIGINAL_LOAD_EXTENSION(bot, name, package=package)
    await _install_extension_specific(bot, name)
    repair_wrapped_signatures(bot)
    if _matches(name, _FINAL_EXTENSION):
        await finalize_runtime(bot)
    return result


if not getattr(commands.Bot, "_sentrix_extension_loader", False):
    commands.Bot.load_extension = _load_extension_with_sentrix_patches
    commands.Bot._sentrix_extension_loader = True

__all__ = ["finalize_runtime"]