"""Initialisation commune des cogs SentriX."""

from discord.ext import commands

from .afk_nickname import install as install_afk_nickname
from .afk_signature_fix import install as install_afk_signature_fix
from .ai_reliability import install as install_ai_reliability
from .dashboard_access import install_dashboard_access
from .help_complete import install as install_complete_help
from .help_home_circles import install as install_help_home_circles
from .poll_ui import install_poll_ui
from .premium_style_runtime import install as install_premium_style
from .remove_code_command import install as install_remove_code_command
from .reply_reference_fix import install as install_reply_reference_fix
from .rolepanel_more_notifications import install as install_more_notification_roles
from .rolepanel_notifications import install as install_notification_rolepanel
from .server_builder_channel_guides import install as install_server_builder_channel_guides
from .server_builder_everyone import install_server_builder_everyone_ping
from .setup_close_fix import install as install_setup_close_fix
from .ticket_claim_security import install as install_ticket_claim_security


_ORIGINAL_LOAD_EXTENSION = commands.Bot.load_extension


async def _load_extension_with_sentrix_patches(
    bot: commands.Bot,
    name: str,
    *,
    package: str | None = None,
):
    result = await _ORIGINAL_LOAD_EXTENSION(bot, name, package=package)

    # Idempotent : le moteur est installé dès le premier cog chargé. Il couvre donc aussi
    # les futurs cogs et reste actif même si un module optionnel échoue plus tard.
    install_premium_style(bot)
    # Toutes les réponses sont envoyées sans MessageReference. Supprimer le message de
    # commande ne doit donc jamais afficher « Le message original a été supprimé ».
    install_reply_reference_fix()

    # Le catalogue est appliqué avant l'installation du panneau afin que +rolepanel et
    # +rolepanel-refresh utilisent toujours les 25 rôles de notifications disponibles.
    install_more_notification_roles()

    # Vérifié après chaque extension : dès que l'ancien +rolepanel apparaît, il est remplacé
    # par le panneau persistant de rôles de notifications. L'installateur reste inactif tant
    # que la commande d'origine n'est pas encore chargée.
    await install_notification_rolepanel(bot)

    if name == "cogs.ai" or name.endswith(".ai"):
        install_ai_reliability()
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
        install_setup_close_fix(bot)
    if name == "cogs.tickets" or name.endswith(".tickets"):
        install_ticket_claim_security(bot)
    if name == "cogs.server_builder" or name.endswith(".server_builder"):
        await install_server_builder_everyone_ping(bot)
        install_server_builder_channel_guides(bot)
    return result


if not getattr(commands.Bot, "_sentrix_extension_loader", False):
    commands.Bot.load_extension = _load_extension_with_sentrix_patches
    commands.Bot._sentrix_extension_loader = True
