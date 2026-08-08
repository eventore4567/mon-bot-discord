"""Initialisation commune des cogs SentriX."""

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


def _install_embed_component_fix(bot: commands.Bot) -> None:
    """Corrige le bouton Annuler de +embed qui envoyait `emoji=○` à Discord.

    `○` est un symbole Unicode valide dans un label, mais ce n'est pas un emoji de
    composant accepté par l'API Discord. Le serveur répond alors 400 / 50035 et refuse
    tout le panneau. On remplace uniquement l'emoji du bouton par un vrai emoji.
    """
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
    """Installe les couches essentielles de +setup dès que Configuration existe.

    Ces correctifs ne doivent pas dépendre des autres installateurs globaux : en production,
    un échec dans un module non lié pouvait laisser le Cog Configuration chargé tout en
    sautant la refonte de +setup. On isole donc chaque étape pour garantir le menu final.
    """
    steps = (
        ("fermeture setup", lambda: install_setup_close_fix(bot)),
        ("synchronisation logs setup", lambda: install_setup_create_logs_sync(bot)),
        ("style setup", lambda: install_setup_oxyde_style(bot)),
        ("nettoyage mobile setup", lambda: install_setup_mobile_cleanup(bot)),
        ("rôle de ping tickets setup", lambda: install_ticket_ping_setup(bot)),
    )
    for label, installer in steps:
        try:
            installer()
        except Exception:
            logger.exception("Échec du correctif %s ; poursuite du chargement de +setup.", label)

    try:
        await install_language_runtime(bot)
    except Exception:
        logger.exception("Échec du moteur de langue pendant le chargement prioritaire de +setup.")

    try:
        install_language_setup_finalizer(bot)
    except Exception:
        logger.exception("Échec du finaliseur de langue pendant le chargement prioritaire de +setup.")

    logger.info("+setup prioritaire installé immédiatement après le Cog Configuration.")


async def _load_extension_with_sentrix_patches(
    bot: commands.Bot,
    name: str,
    *,
    package: str | None = None,
):
    result = await _ORIGINAL_LOAD_EXTENSION(bot, name, package=package)

    # IMPORTANT : Configuration est déjà réellement ajoutée au bot à ce point. On installe
    # immédiatement le nouveau +setup avant tout autre correctif global. Ainsi, même si un
    # autre module rencontre ensuite un problème avec les données réelles du serveur, le
    # panneau Catégories et sa langue ne peuvent plus rester sur l'ancien renderer.
    if name == "cogs.configuration" or name.endswith(".configuration"):
        await _install_configuration_critical_patches(bot)

    # Idempotent : le moteur est installé dès le premier cog chargé. Il couvre donc aussi
    # les futurs cogs et reste actif même si un module optionnel échoue plus tard.
    install_premium_style(bot)
    # Toutes les réponses sont envoyées sans MessageReference. Supprimer le message de
    # commande ne doit donc jamais afficher « Le message original a été supprimé ».
    install_reply_reference_fix()
    # Le cog de suivi reste chargé pour conserver +suivi-bot, mais aucun panneau n'est
    # désormais publié automatiquement par +create-server ou ses migrations.
    await install_bot_tracker(bot)
    # Prix boutique par défaut : VIP 500 pièces, Premium 2 000 pièces.
    await install_shop_default_prices(bot)
    # Boutons persistants pour les rôles jeux/langues/couleurs créés par +create-server.
    await install_server_choice_roles(bot)

    # Le catalogue est appliqué avant l'installation du panneau afin que +rolepanel et
    # +rolepanel-refresh utilisent toujours les 25 rôles de notifications disponibles.
    install_more_notification_roles()

    # Vérifié après chaque extension : dès que l'ancien +rolepanel apparaît, il est remplacé
    # par le panneau persistant de rôles de notifications. L'installateur reste inactif tant
    # que la commande d'origine n'est pas encore chargée.
    await install_notification_rolepanel(bot)

    if name == "cogs.automod" or name.endswith(".automod"):
        await install_security_hardening(bot)
        install_owner_sanction_immunity(bot)
    if name == "cogs.moderation" or name.endswith(".moderation"):
        install_owner_sanction_immunity(bot)
    if name == "cogs.ai" or name.endswith(".ai"):
        install_ai_reliability()
        install_natural_music_intent_guard(bot)
        install_remove_code_command(bot)
    if name == "cogs.utility" or name.endswith(".utility"):
        await install_poll_ui(bot)
        # L'aide complète doit être installée avant l'ajout du bouton dashboard afin que
        # celui-ci enveloppe bien la nouvelle page d'accueil dynamique.
        install_complete_help(bot)
        await install_dashboard_access(bot)
        # Le style sobre passe en dernier pour nettoyer aussi le champ et le bouton du
        # dashboard sans modifier leur fonctionnement.
        install_help_home_circles(bot)
        await install_afk_nickname(bot)
        install_afk_signature_fix(bot)
    if name == "cogs.configuration" or name.endswith(".configuration"):
        # Deuxième passage volontaire et idempotent : il garde la compatibilité avec les
        # anciennes couches tout en garantissant que le passage prioritaire ci-dessus a déjà
        # installé le vrai menu avant les modules globaux.
        install_setup_close_fix(bot)
        install_setup_create_logs_sync(bot)
        install_setup_oxyde_style(bot)
        install_setup_mobile_cleanup(bot)
        install_ticket_ping_setup(bot)
    if name == "cogs.tickets" or name.endswith(".tickets"):
        install_ticket_claim_security(bot)
        # Le rôle de ping est indépendant du rôle staff qui gère les permissions du salon.
        install_ticket_ping_runtime(bot)
    if name == "cogs.events" or name.endswith(".events"):
        # Les participations giveaway passent par une vérification réseau à empreinte HMAC :
        # une connexion ne peut valider qu'un compte par giveaway, sans stocker l'IP brute.
        await install_giveaway_antialt(bot)
    if name == "cogs.server_builder" or name.endswith(".server_builder"):
        await install_server_builder_everyone_ping(bot)
        install_server_builder_channel_guides(bot)
        install_server_builder_ready_setup(bot)
        # Ne plus recréer le suivi du bot dans annonces à chaque redéploiement.
        install_no_auto_tracker(bot)
        # Les salons logs-* générés deviennent la source de vérité du moteur log_settings.
        install_generated_logs_sync(bot)
        # Important : répare la détection des panneaux AVANT la migration des serveurs
        # existants, sinon le style global peut provoquer un doublon au redémarrage.
        install_rolepanel_display_fix(bot)
        install_existing_server_bootstrap(bot)
    if name == "cogs.embed_builder" or name.endswith(".embed_builder"):
        # Discord rejetait entièrement +embed car le bouton Annuler utilisait le symbole ○
        # dans le champ emoji. Le patch s'applique après le chargement réel du cog.
        _install_embed_component_fix(bot)

    # Répare le routage des logs et supprime les doublons générés par les événements
    # Discord quand SentriX a déjà produit une fiche de sanction détaillée.
    # Appelé après chaque extension : le patch attend simplement que le cog Logs existe.
    install_moderation_logs_fix(bot)

    # Style premium appliqué EN DERNIER sur le moteur de logs : les infos d'Audit Log
    # (staff/autre bot), la déduplication et l'auto-réparation ont donc déjà été faites.
    install_premium_logs(bot)
    # Sur discord.py >= 2.6, transforme les embeds en cartes Components V2 avec vraie
    # barre d'accent, sections, séparateurs, thumbnail et boutons intégrés. Un fallback
    # conserve automatiquement l'embed premium si Discord refuse la carte.
    install_premium_logs_v2(bot)
    # Les mentions restent visibles dans les cartes, mais ne notifient jamais les membres,
    # rôles, @everyone ou @here. Le reste du bot garde ses vrais pings normalement.
    install_logs_no_ping()

    # Correctifs transversaux issus de la passe de stabilité : reprise des notifications
    # sociales, sérialisation du cache d'invitations et limite de récompenses de jeux.
    install_stability_runtime(bot, name)

    # Les aliases techniques historiques sont posés d'abord ; le moteur de langue retire
    # ensuite les anciens alias FR globaux et relie FR/EN aux mêmes objets commandes.
    install_common_command_names(bot)
    await install_language_runtime(bot)
    # +setup possède plusieurs couches visuelles qui peuvent remplacer render_page/build_embed.
    # Ce finaliseur enveloppe toujours la version réellement active en dernier.
    install_language_setup_finalizer(bot)

    # Dernier filet de sécurité : après toutes les couches de rendu/réponse, une commande
    # valide ne peut plus se terminer silencieusement. Les réponses normales restent intactes.
    install_command_response_guard(bot)
    return result


if not getattr(commands.Bot, "_sentrix_extension_loader", False):
    commands.Bot.load_extension = _load_extension_with_sentrix_patches
    commands.Bot._sentrix_extension_loader = True
