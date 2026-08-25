"""Initialisation des correctifs runtime SentriX.

La base historique installait plusieurs couches globales après CHAQUE extension Discord.
Cela permettait à un ancien renderer/setup/handler de repasser au-dessus d'une correction
plus récente. Le chargeur ne pose désormais que les correctifs propres au cog qui vient
d'être chargé. Les couches transversales sont finalisées une seule fois, explicitement,
après le chargement complet des extensions via :func:`finalize_runtime`.

Les anciens coordinateurs visuels ``plain_response_policy``, ``setup_mobile_cleanup`` et
``command_no_emoji_runtime`` restent éventuellement présents dans le dépôt pour la
compatibilité historique, mais ils ne font plus partie du chemin runtime actif.
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
from .command_response_guard import install as install_command_response_guard
from .common_command_names import install as install_common_command_names
from .dashboard_access import install_dashboard_access
from .emoji_name_lookup import install as install_emoji_name_lookup
from .final_interaction_policy import install as install_final_interaction_policy
from .final_runtime_polish import install as install_final_runtime_polish
from .generated_logs_sync import install as install_generated_logs_sync
from .giveaway_antialt import install as install_giveaway_antialt
from .help_clean_style import install as install_help_clean_style
from .help_complete import install as install_complete_help
from .help_home_circles import install as install_help_home_circles
from .language_runtime import install as install_language_runtime
from .language_setup_finalizer import install as install_language_setup_finalizer
from .logs_no_ping import install as install_logs_no_ping
from .moderation_logs_fix import install as install_moderation_logs_fix
from .mention_home_runtime import install as install_mention_home
from .natural_music_intent_guard import install as install_natural_music_intent_guard
from .no_auto_tracker import install as install_no_auto_tracker
from .owner_sanction_immunity import install as install_owner_sanction_immunity
from .permission_guard import install as install_permission_guard
from .poll_ui import install_poll_ui
from .premium_logs import install as install_premium_logs
from .premium_logs_v2 import install as install_premium_logs_v2
from .log_rectangle_v25 import install as install_log_rectangle_v25
from .log_reference_layout_v26 import install as install_log_reference_layout_v26
from .premium_style_runtime import install as install_premium_style
from .profile_oxyde_runtime import install as install_profile_oxyde
from .production_ops import install as install_production_ops
from .public_language_choice import install as install_public_language_choice
from .remove_code_command import install as install_remove_code_command
from .reply_reference_fix import install as install_reply_reference_fix
from .rolepanel_display_fix import install as install_rolepanel_display_fix
from .rolepanel_more_notifications import install as install_more_notification_roles
from .rolepanel_notifications import install as install_notification_rolepanel
from .security_command_center import install as install_security_command_center
from .security_runtime_hardening import install as install_security_hardening
from .smart_creation_guard_v47 import install as install_smart_creation_guard_v47
from .server_builder_channel_guides import install as install_server_builder_channel_guides
from .server_builder_everyone import install_server_builder_everyone_ping
from .server_builder_existing_bootstrap import install as install_existing_server_bootstrap
from .server_builder_ready_setup import install as install_server_builder_ready_setup
from .server_choice_roles import install as install_server_choice_roles
from .shop_default_prices import install as install_shop_default_prices
from .setup_close_fix import install as install_setup_close_fix
from .setup_create_logs_sync import install as install_setup_create_logs_sync
from .setup_oxyde_style import install as install_setup_oxyde_style
from .slash_reliability_v7 import install as install_slash_reliability_v7
from .stability_runtime import install as install_stability_runtime
from .ticket_claim_security import install as install_ticket_claim_security
from .ticket_ping_role import install_setup_ui as install_ticket_ping_setup
from .ticket_ping_role import install_ticket_runtime as install_ticket_ping_runtime


logger = logging.getLogger("bot.cogs")
_ORIGINAL_LOAD_EXTENSION = commands.Bot.load_extension


def _matches(name: str, extension: str) -> bool:
    return name == extension or name.endswith("." + extension.rsplit(".", 1)[-1])


def _discord_session_started(bot: commands.Bot) -> bool:
    return bool(getattr(getattr(bot, "http", None), "token", None))


async def _run_installer(label: str, installer, *args):
    """Isole une couche optionnelle sans masquer l'échec de l'extension principale."""
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
    """Une seule chaîne autoritaire pour +setup / /setup."""
    if bot.get_cog("Configuration") is None:
        return
    await _run_installer("fermeture setup", install_setup_close_fix, bot)
    await _run_installer("synchronisation logs setup", install_setup_create_logs_sync, bot)
    await _run_installer("style setup canonique", install_setup_oxyde_style, bot)
    await _run_installer("rôle de ping tickets setup", install_ticket_ping_setup, bot)
    await _run_installer("choix de langue public", install_public_language_choice, bot)
    await _run_installer("moteur de langue setup", install_language_runtime, bot)
    await _run_installer("finaliseur de langue setup", install_language_setup_finalizer, bot)


async def _install_common_runtime(bot: commands.Bot) -> None:
    """Socle transversal installé une seule fois après tous les cogs."""
    await _run_installer("aliases techniques", install_common_command_names, bot)
    await _run_installer("style premium transport", install_premium_style, bot)
    await _run_installer("réponses sans référence fragile", install_reply_reference_fix)
    await _run_installer("suivi bot", install_bot_tracker, bot)
    await _run_installer("prix boutique par défaut", install_shop_default_prices, bot)
    await _run_installer("rôles de choix serveur", install_server_choice_roles, bot)
    await _run_installer("catalogue rôles notifications", install_more_notification_roles)
    await _run_installer("panel rôles notifications", install_notification_rolepanel, bot)


async def _install_extension_specific(bot: commands.Bot, name: str) -> None:
    """Correctifs dépendant réellement du cog qui vient d'être chargé."""
    if _matches(name, "cogs.automod"):
        await _run_installer("renforcement sécurité", install_security_hardening, bot)
        await _run_installer("analyse intelligente créations anti-nuke", install_smart_creation_guard_v47, bot)
        await _run_installer("centre de commandes sécurité", install_security_command_center, bot)
        await _run_installer("immunité propriétaire sanctions", install_owner_sanction_immunity, bot)

    if _matches(name, "cogs.security_tools"):
        await _run_installer("centre de commandes sécurité avancé", install_security_command_center, bot)

    if _matches(name, "cogs.moderation"):
        await _run_installer("immunité propriétaire sanctions", install_owner_sanction_immunity, bot)

    if _matches(name, "cogs.levels"):
        await _run_installer("profil visuel premium", install_profile_oxyde, bot)

    if _matches(name, "cogs.ai"):
        await _run_installer("fiabilité IA", install_ai_reliability)
        await _run_installer("garde intention musique", install_natural_music_intent_guard, bot)
        await _run_installer("suppression ancienne commande code", install_remove_code_command, bot)

    if _matches(name, "cogs.utility"):
        await _run_installer("ajout emoji par nom", install_emoji_name_lookup, bot)
        emoji_command = bot.get_command("addemoji")
        if emoji_command is not None:
            emoji_command.usage = ":nom:"
            emoji_command.description = "Ajouter un emoji en tapant simplement son nom, ex. +addemogi :tete:."
            emoji_command.help = "Tapez seulement le nom entre deux-points, par exemple `+addemogi :tete:`."
        await _run_installer("interface sondages", install_poll_ui, bot)
        await _run_installer("aide complète", install_complete_help, bot)
        await _run_installer("accès dashboard depuis aide", install_dashboard_access, bot)
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

    # Les correctifs de stabilité ciblent des cogs précis (notifications, invites,
    # mini-jeux, IA...). Ils restent donc liés au chargement de l'extension, contrairement
    # aux renderers/style/handlers globaux qui sont désormais finalisés une seule fois.
    await _run_installer("stabilité ciblée", install_stability_runtime, bot, name)


async def _install_log_stack(bot: commands.Bot) -> None:
    """Une seule chaîne logs, dans un ordre déterministe."""
    if _discord_session_started(bot):
        await _run_installer("routage logs modération", install_moderation_logs_fix, bot)
    await _run_installer("style premium logs", install_premium_logs, bot)
    await _run_installer("Components V2 logs", install_premium_logs_v2, bot)
    await _run_installer("mentions silencieuses logs", install_logs_no_ping)

    # Ces deux couches étaient auparavant cachées dans command_no_emoji_runtime.
    try:
        from .log_identity_context_v60 import install as install_log_identity_context_v60
        from .log_consolidation_v61 import install as install_log_consolidation_v61
        await _run_installer("identités logs V60", install_log_identity_context_v60, bot)
        await _run_installer("consolidation logs V61", install_log_consolidation_v61, bot)
    except Exception:
        logger.exception("Impossible de préparer les correctifs logs V60/V61.")

    await _run_installer("anti-doublon logs V25", install_log_rectangle_v25, bot)
    await _run_installer("rendu final logs V26", install_log_reference_layout_v26, bot)


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
            from .official_server_polish import install as install_official_server_polish
            from .official_server_command_fix import install as install_official_server_command_fix
            await _run_installer("serveur officiel", install_official_server, bot)
            await _run_installer("finition serveur officiel", install_official_server_polish, bot)
            await _run_installer("signature serveur officiel", install_official_server_command_fix, bot)
        except Exception:
            logger.exception("Impossible de préparer le constructeur officiel.")


async def _install_help_and_error_stack(bot: commands.Bot) -> None:
    """Un seul propriétaire pour l'aide et un seul pour les erreurs utilisateur."""
    await _run_installer("style aide canonique", install_help_clean_style, bot)
    try:
        from .sentrix_v3_ux import install as install_sentrix_v3_ux
        await _run_installer("UX aide V3", install_sentrix_v3_ux, bot)
        from .help_cooldown_exemption_v3 import install as install_help_cooldown_exemption_v3
        await _run_installer("help sans cooldown global", install_help_cooldown_exemption_v3, bot)
    except Exception:
        logger.exception("Impossible de préparer la couche UX d'aide.")

    await _run_installer("style accueil aide", install_help_home_circles, bot)
    await _run_installer("aide racine et surface commandes", install_final_runtime_polish, bot)
    await _run_installer("accueil compact sur mention", install_mention_home, bot)

    # error_experience_v3 répond ; command_response_guard observe seulement (V3.11).
    try:
        from .error_experience_v3 import install as install_error_experience_v3
        await _run_installer("erreurs utilisateur uniques", install_error_experience_v3, bot)
    except Exception:
        logger.exception("Impossible de préparer le handler d'erreurs utilisateur.")
    await _run_installer("observabilité réponses commandes", install_command_response_guard, bot)


async def finalize_runtime(bot: commands.Bot) -> None:
    """Finalise UNE FOIS le runtime après le chargement de toutes les extensions.

    Cette fonction est l'unique point d'entrée des couches globales. Elle supprime la
    course historique où un vieux renderer se réinstallait après un renderer récent.
    """
    if getattr(bot, "_sentrix_runtime_finalized_clean", False):
        return

    await _install_common_runtime(bot)
    await _install_configuration_critical_patches(bot)
    await _install_log_stack(bot)
    await _install_release_and_official_server(bot)

    # Renderer global canonique. Il n'est plus installé implicitement par GuildArrival.
    try:
        from .sentrix_v3_global_style import install as install_global_style
        await _run_installer("style global SentriX", install_global_style, bot)
    except Exception:
        logger.exception("Impossible de préparer le style global SentriX.")

    await _install_help_and_error_stack(bot)

    # Protection du markup emoji après les renderers visuels, sans coordinateur legacy.
    try:
        from .sentrix_emoji_markup_guard_v361 import install as install_emoji_markup_guard_v361
        await _run_installer("protection markup emojis", install_emoji_markup_guard_v361, bot)
    except Exception:
        logger.exception("Impossible de préparer la protection des emojis.")

    # Sécurité et transports finaux : aucune ancienne couche visuelle n'est installée après.
    await _run_installer("renforcement global commandes V41", install_command_hardening_v41, bot)
    await _run_installer("opérations production", install_production_ops, bot)
    await _run_installer("permissions commandes", install_permission_guard, bot)
    await _run_installer("politique finale interactions", install_final_interaction_policy, bot)
    await _run_installer("libération concurrence slash V41", install_command_error_release_v41, bot)

    bot._sentrix_runtime_finalized_clean = True
    logger.info(
        "Runtime SentriX finalisé une fois : setup/style/help/erreurs/permissions sans réempilement legacy."
    )


async def _load_extension_with_sentrix_patches(
    bot: commands.Bot,
    name: str,
    *,
    package: str | None = None,
):
    """Charge l'extension et seulement les correctifs qui dépendent de cette extension."""
    result = await _ORIGINAL_LOAD_EXTENSION(bot, name, package=package)
    await _install_extension_specific(bot, name)
    return result


if not getattr(commands.Bot, "_sentrix_extension_loader", False):
    commands.Bot.load_extension = _load_extension_with_sentrix_patches
    commands.Bot._sentrix_extension_loader = True


__all__ = ["finalize_runtime"]
