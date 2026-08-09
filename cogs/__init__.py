"""Initialisation commune des cogs SentriX.

Ce module conserve la compatibilité avec l'architecture historique de SentriX, mais
centralise désormais l'installation des correctifs runtime : chaque installateur est
isolé, journalisé et ne peut plus empêcher les suivants de s'installer s'il rencontre
une erreur. L'ordre des couches critiques de +setup est volontairement conservé.
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
from .command_response_guard import install as install_command_response_guard
from .common_command_names import install as install_common_command_names
from .dashboard_access import install_dashboard_access
from .generated_logs_sync import install as install_generated_logs_sync
from .giveaway_antialt import install as install_giveaway_antialt
from .help_complete import install as install_complete_help
from .help_home_circles import install as install_help_home_circles
from .language_runtime import install as install_language_runtime
from .language_setup_finalizer import install as install_language_setup_finalizer
from .logs_no_ping import install as install_logs_no_ping
from .moderation_logs_fix import install as install_moderation_logs_fix
from .natural_music_intent_guard import install as install_natural_music_intent_guard
from .no_auto_tracker import install as install_no_auto_tracker
from .owner_sanction_immunity import install as install_owner_sanction_immunity
from .poll_ui import install_poll_ui
from .premium_logs import install as install_premium_logs
from .premium_logs_v2 import install as install_premium_logs_v2
from .premium_style_runtime import install as install_premium_style
from .remove_code_command import install as install_remove_code_command
from .reply_reference_fix import install as install_reply_reference_fix
from .rolepanel_display_fix import install as install_rolepanel_display_fix
from .rolepanel_more_notifications import install as install_more_notification_roles
from .rolepanel_notifications import install as install_notification_rolepanel
from .security_runtime_hardening import install as install_security_hardening
from .server_builder_channel_guides import install as install_server_builder_channel_guides
from .server_builder_everyone import install_server_builder_everyone_ping
from .server_builder_existing_bootstrap import install as install_existing_server_bootstrap
from .server_builder_ready_setup import install as install_server_builder_ready_setup
from .server_choice_roles import install as install_server_choice_roles
from .shop_default_prices import install as install_shop_default_prices
from .setup_close_fix import install as install_setup_close_fix
from .setup_create_logs_sync import install as install_setup_create_logs_sync
from .setup_mobile_cleanup import install as install_setup_mobile_cleanup
from .setup_oxyde_style import install as install_setup_oxyde_style
from .stability_runtime import install as install_stability_runtime
from .ticket_claim_security import install as install_ticket_claim_security
from .ticket_ping_role import install_setup_ui as install_ticket_ping_setup
from .ticket_ping_role import install_ticket_runtime as install_ticket_ping_runtime


logger = logging.getLogger("bot.cogs")
_ORIGINAL_LOAD_EXTENSION = commands.Bot.load_extension


def _matches(name: str, extension: str) -> bool:
    return name == extension or name.endswith("." + extension.rsplit(".", 1)[-1])


async def _run_installer(label: str, installer, *args):
    """Exécute un installateur sync ou async sans casser la chaîne de démarrage.

    Les extensions elles-mêmes continuent à lever leurs erreurs normalement. Seules les
    couches runtime optionnelles sont isolées : une erreur de style, dashboard ou panel
    ne doit jamais empêcher une protection sécurité ou le moteur de langue de s'installer.
    """
    try:
        result = installer(*args)
        if inspect.isawaitable(result):
            result = await result
        return result
    except Exception:
        logger.exception("Échec du correctif runtime « %s » ; poursuite du chargement.", label)
        return None


def _install_embed_component_fix(bot: commands.Bot) -> None:
    """Corrige le bouton Annuler de +embed qui envoyait `emoji=○` à Discord."""
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
                        item.emoji = "❌"

            embed_builder.EmbedBuilderView.__init__ = patched_init
            embed_builder.EmbedBuilderView._sentrix_cancel_emoji_fix = True

        bot._sentrix_embed_component_fix = True
        logger.info("Correctif +embed installé : emoji du bouton Annuler remplacé par ❌.")
    except Exception:
        logger.exception("Impossible d'installer le correctif de composant +embed.")


async def _install_configuration_critical_patches(bot: commands.Bot) -> None:
    """Installe les couches essentielles de +setup immédiatement après Configuration."""
    await _run_installer("fermeture setup", install_setup_close_fix, bot)
    await _run_installer("synchronisation logs setup", install_setup_create_logs_sync, bot)
    await _run_installer("style setup", install_setup_oxyde_style, bot)
    await _run_installer("nettoyage mobile setup", install_setup_mobile_cleanup, bot)
    await _run_installer("rôle de ping tickets setup", install_ticket_ping_setup, bot)
    await _run_installer("moteur de langue setup", install_language_runtime, bot)
    await _run_installer("finaliseur de langue setup", install_language_setup_finalizer, bot)
    logger.info("+setup prioritaire installé immédiatement après le Cog Configuration.")


async def _install_common_runtime(bot: commands.Bot) -> None:
    """Couches idempotentes qui peuvent être appelées après chaque extension."""
    await _run_installer("style premium", install_premium_style, bot)
    await _run_installer("réponses sans référence fragile", install_reply_reference_fix)
    await _run_installer("suivi bot", install_bot_tracker, bot)
    await _run_installer("prix boutique par défaut", install_shop_default_prices, bot)
    await _run_installer("rôles de choix serveur", install_server_choice_roles, bot)
    await _run_installer("catalogue rôles notifications", install_more_notification_roles)
    await _run_installer("panel rôles notifications", install_notification_rolepanel, bot)


async def _install_extension_specific(bot: commands.Bot, name: str) -> None:
    """Correctifs qui ne doivent être posés qu'une fois leur cog cible chargé."""
    if _matches(name, "cogs.automod"):
        await _run_installer("renforcement sécurité", install_security_hardening, bot)
        await _run_installer("immunité propriétaire sanctions", install_owner_sanction_immunity, bot)

    if _matches(name, "cogs.moderation"):
        await _run_installer("immunité propriétaire sanctions", install_owner_sanction_immunity, bot)

    if _matches(name, "cogs.ai"):
        await _run_installer("fiabilité IA", install_ai_reliability)
        await _run_installer("garde intention musique", install_natural_music_intent_guard, bot)
        await _run_installer("suppression ancienne commande code", install_remove_code_command, bot)

    if _matches(name, "cogs.utility"):
        await _run_installer("interface sondages", install_poll_ui, bot)
        await _run_installer("aide complète", install_complete_help, bot)
        await _run_installer("accès dashboard depuis aide", install_dashboard_access, bot)
        await _run_installer("style accueil aide", install_help_home_circles, bot)
        await _run_installer("pseudo AFK", install_afk_nickname, bot)
        await _run_installer("signature AFK", install_afk_signature_fix, bot)

    if _matches(name, "cogs.configuration"):
        # Deuxième passage volontaire : ces installateurs sont idempotents et doivent
        # rester compatibles avec les anciennes couches qui peuvent remplacer des vues.
        await _run_installer("fermeture setup (final)", install_setup_close_fix, bot)
        await _run_installer("synchronisation logs setup (final)", install_setup_create_logs_sync, bot)
        await _run_installer("style setup (final)", install_setup_oxyde_style, bot)
        await _run_installer("nettoyage mobile setup (final)", install_setup_mobile_cleanup, bot)
        await _run_installer("rôle de ping tickets setup (final)", install_ticket_ping_setup, bot)

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


async def _install_log_stack(bot: commands.Bot) -> None:
    """Ordre important : routage -> style -> Components V2 -> mentions silencieuses."""
    await _run_installer("routage logs modération", install_moderation_logs_fix, bot)
    await _run_installer("style premium logs", install_premium_logs, bot)
    await _run_installer("Components V2 logs", install_premium_logs_v2, bot)
    await _run_installer("mentions silencieuses logs", install_logs_no_ping)


async def _install_finalizers(bot: commands.Bot, name: str) -> None:
    """Dernières couches, toujours dans le même ordre déterministe."""
    await _run_installer("stabilité transversale", install_stability_runtime, bot, name)
    await _run_installer("aliases techniques", install_common_command_names, bot)
    await _run_installer("moteur de langue", install_language_runtime, bot)
    await _run_installer("finaliseur langue setup", install_language_setup_finalizer, bot)
    await _run_installer("garde de réponse commandes", install_command_response_guard, bot)


async def _load_extension_with_sentrix_patches(
    bot: commands.Bot,
    name: str,
    *,
    package: str | None = None,
):
    """Charge une vraie extension puis applique les couches SentriX de façon déterministe."""
    result = await _ORIGINAL_LOAD_EXTENSION(bot, name, package=package)

    # Configuration est déjà réellement ajoutée à ce point : le setup critique doit être
    # installé AVANT toutes les autres couches, exactement comme dans l'architecture V6/V7.
    if _matches(name, "cogs.configuration"):
        await _install_configuration_critical_patches(bot)

    await _install_common_runtime(bot)
    await _install_extension_specific(bot, name)
    await _install_log_stack(bot)
    await _install_finalizers(bot, name)
    return result


if not getattr(commands.Bot, "_sentrix_extension_loader", False):
    commands.Bot.load_extension = _load_extension_with_sentrix_patches
    commands.Bot._sentrix_extension_loader = True
