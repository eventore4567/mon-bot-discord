"""Dernière étape déterministe du bootstrap Railway SentriX.

Ce module est chargé en dernier par ``railway_boot.py``. Il ne transforme plus rien en
texte. Il garantit simplement que la finalisation officielle s'exécute même si une
extension optionnelle précédente a échoué, réenregistre l'unique help, débranche les
anciens listeners de logs encore présents dans Configuration, puis répare le routage des
salons historiques.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from . import finalize_runtime
from .help import OfficialHelp
from . import runtime_fix_v1

logger = logging.getLogger("bot.bootstrap-final")

_DUPLICATE_CONFIGURATION_LOG_EVENTS = (
    "on_message_delete",
    "on_message_edit",
    "on_member_join",
    "on_member_remove",
    "on_voice_state_update",
    "on_guild_channel_create",
    "on_guild_channel_delete",
    "on_guild_role_create",
    "on_guild_role_delete",
    "on_member_update",
)


def _disconnect_configuration_log_listeners(bot: commands.Bot) -> int:
    """Débranche les listeners historiques du cog Configuration.

    Le propriétaire unique des événements est ``cogs.logs``. Garder les méthodes dans le
    fichier Configuration préserve la compatibilité du vieux code, mais elles ne sont plus
    enregistrées auprès de discord.py : une action ne produit donc plus deux logs.
    """
    cog = bot.get_cog("Configuration")
    if cog is None:
        return 0
    removed = 0
    for event_name in _DUPLICATE_CONFIGURATION_LOG_EVENTS:
        callback = getattr(cog, event_name, None)
        if callback is None:
            continue
        try:
            bot.remove_listener(callback, event_name)
            removed += 1
        except Exception:
            logger.debug("Listener Configuration %s impossible à retirer.", event_name, exc_info=True)
    return removed


async def _register_official_help(bot: commands.Bot) -> None:
    """Réenregistre l'aide finale sans jamais exposer ``ctx`` à l'utilisateur.

    ``OfficialHelp`` reste le propriétaire de toute l'interface et du slash ``/help``.
    Pour la commande préfixée, on utilise volontairement une petite entrée autonome :
    discord.py sait alors que son premier paramètre est le Context technique et ne peut
    pas le confondre avec un argument utilisateur, même si un ancien cog ``Utility`` ou
    une couche runtime a précédemment manipulé la commande ``help``.
    """
    old = bot.get_command("help")
    if old is not None:
        bot.remove_command("help")

    existing = bot.get_cog("SentriXHelp")
    if existing is not None:
        await bot.remove_cog("SentriXHelp")

    try:
        bot.tree.remove_command("help", type=discord.AppCommandType.chat_input)
    except Exception:
        pass

    # Le Cog fournit les builders, vues, recherche et /help.
    await bot.add_cog(OfficialHelp(bot))

    # Son Command préfixé de classe est retiré du registre racine puis remplacé par une
    # entrée sans Cog. Avec command.cog == None, discord.py retire exactement le premier
    # paramètre (ctx) du parsing et ne garde que ``commande`` comme argument optionnel.
    registered = bot.get_command("help")
    if registered is not None:
        bot.remove_command("help")

    async def prefix_help_entry(ctx: commands.Context, *, commande: str | None = None) -> None:
        help_cog = bot.get_cog("SentriXHelp")
        if not isinstance(help_cog, OfficialHelp):
            logger.error("SentriXHelp absent pendant l'exécution de +help.")
            return
        await help_cog._send_prefix_help(ctx, query=commande)

    prefix_command = commands.Command(
        prefix_help_entry,
        name="help",
        help="Ouvrir l'aide interactive SentriX ou afficher une commande précise.",
        usage="[commande]",
    )
    prefix_command.hidden = False
    prefix_command._sentrix_official_help_owner = True
    prefix_command._sentrix_context_is_internal = True
    bot.add_command(prefix_command)

    # Contrat runtime : l'utilisateur ne doit JAMAIS voir self/ctx/context/interaction.
    exposed = {str(name).casefold() for name in prefix_command.clean_params}
    forbidden = exposed & {"self", "ctx", "context", "interaction", "bot", "cog"}
    if forbidden:
        bot.remove_command("help")
        raise RuntimeError(
            "Signature +help invalide : paramètres techniques exposés : "
            + ", ".join(sorted(forbidden))
        )

    logger.info(
        "Help préfixé officiel enregistré : paramètres utilisateur=%s.",
        ", ".join(prefix_command.clean_params) or "aucun",
    )


async def setup(bot: commands.Bot) -> None:
    # Ne dépend plus du succès de visual_experience_v5 : Railway arrive toujours ici
    # après la boucle complète des extensions.
    await finalize_runtime(bot)

    removed = _disconnect_configuration_log_listeners(bot)
    await _register_official_help(bot)

    # RuntimeFixV1 ne possède pas le renderer/logger : il répare uniquement les routes
    # guild_config -> log_settings et les permissions des salons existants.
    await runtime_fix_v1.setup(bot)

    bot._sentrix_bootstrap_final = True
    logger.info(
        "Bootstrap final : runtime officiel appliqué, help unique, %s listener(s) de logs legacy débranché(s).",
        removed,
    )
