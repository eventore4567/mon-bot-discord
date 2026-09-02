"""Dernière étape déterministe du bootstrap Railway SentriX.

Ce module est chargé en dernier par ``railway_boot.py``. Il ne transforme plus rien en
texte. Il garantit simplement que la finalisation officielle s'exécute même si une
extension optionnelle précédente a échoué, réenregistre l'unique help, débranche les
anciens listeners de logs encore présents dans Configuration, restaure le renderer final
validé et répare le routage des salons historiques.
"""
from __future__ import annotations

import inspect
import logging
import types

import discord

from utils import sentrix_panels as panels
from discord.ext import commands

from . import finalize_runtime
from .help import OfficialHelp
from . import runtime_fix_v1

logger = logging.getLogger("bot.bootstrap-final")

_FRAMEWORK_HELP_PARAMS = frozenset({
    "self", "ctx", "context", "interaction", "bot", "cog",
})

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


def _is_official_help_command(command: commands.Command | None) -> bool:
    if command is None:
        return False
    return bool(
        getattr(command, "_sentrix_official_help_owner", False)
        or getattr(command, "_sentrix_context_is_internal", False)
    )


def _help_signature_is_safe(command: commands.Command | None) -> bool:
    """Vérifie le contrat réel de la commande préfixée officielle.

    Le +help final est volontairement une Command autonome : son premier paramètre
    ``ctx`` est donc consommé par discord.py, et ``clean_params`` ne doit contenir que les
    arguments réellement saisissables par le membre (actuellement ``commande``).
    """
    if not _is_official_help_command(command):
        return False
    exposed = {str(name).casefold() for name in getattr(command, "clean_params", {})}
    return getattr(command, "cog", None) is None and not (exposed & _FRAMEWORK_HELP_PARAMS)


def _install_final_visual_stack(bot: commands.Bot) -> None:
    """Restaure explicitement la pile visuelle validée avant la PR #225.

    La PR finale a volontairement supprimé les imports à effet de bord de ``utils`` pour
    rendre le bootstrap plus déterministe. Le problème est que les cinq couches finales
    n'ont ensuite été réinstallées nulle part : +ping, les erreurs et les logs sont donc
    revenus à leurs renderers historiques. On conserve l'architecture propre en les
    installant ici, après les gardes de sécurité et une fois les cogs métier chargés.
    """
    if getattr(bot, "_sentrix_final_visual_stack", False):
        return

    from utils import embeds as shared_embeds
    from utils import log_compact_final
    from utils import ping_final_style
    from utils import sentrix_runtime
    from utils import sentrix_visual_cleanup
    from utils import wide_compact_v6

    # La version pré-merge donnait la priorité au type sémantique (danger, warning,
    # success...) et n'utilisait la couleur de secours que pour un type inconnu. La PR
    # #225 avait inversé cette priorité, ce qui faisait notamment redevenir les erreurs
    # violettes. On restaure ce contrat sans réintroduire un import global de utils.
    def semantic_colour(kind: str | None = None, fallback: int | None = None) -> int:
        return {
            "info": shared_embeds.COLOR_INFO,
            "success": shared_embeds.COLOR_SUCCESS,
            "warning": shared_embeds.COLOR_WARNING,
            "danger": shared_embeds.COLOR_DANGER,
            "neutral": shared_embeds.COLOR_NEUTRAL,
            "brand": shared_embeds.COLOR_BRAND_UI,
        }.get(str(kind or "").casefold(), int(fallback or shared_embeds.SENTRIX_COLOR))

    shared_embeds._colour = semantic_colour

    # Même ordre que le rendu validé juste avant le merge : base large -> runtime métier
    # -> ping final -> nettoyage visuel -> logs compacts.
    wide_compact_v6.install()
    sentrix_runtime.install()
    ping_final_style.install()
    sentrix_visual_cleanup.install()

    panel_bar = wide_compact_v6.LONG_BAR
    sentrix_visual_cleanup.PANEL_BAR = panel_bar
    sentrix_runtime.BAR = panel_bar
    sentrix_runtime.CHANGE_BAR = ""
    shared_embeds.BAR = panel_bar
    ping_final_style.PANEL_BAR = panel_bar
    ping_final_style.command_style_v2.BAR = panel_bar
    log_compact_final.PANEL_BAR = panel_bar
    log_compact_final.install()

    # sentrix_runtime est maintenant installé après le chargement des cogs. Son hook
    # Bot.add_cog ne peut donc pas rétroactivement toucher les commandes déjà présentes :
    # on applique explicitement les deux patchs qui étaient actifs avant le merge.
    sentrix_runtime._patch_clear(bot)
    sentrix_runtime._patch_ping(bot)

    # Le convertisseur app_commands.Range est parfait côté slash, mais son annotation a
    # déjà produit des BadArgument sur la commande préfixée +clear. Le slash garde sa
    # contrainte 1..100 ; seul le parseur préfixé est ramené à un entier simple, le callback
    # final bornant ensuite la valeur à 1..100.
    clear_command = bot.get_command("clear")
    if clear_command is not None:
        async def clear_signature_probe(ctx: commands.Context, nombre: int):
            return None

        probe = commands.Command(clear_signature_probe, name="_sentrix_clear_signature_probe")
        clear_command.params = probe.params.copy()
        clear_command.usage = "<nombre>"
        clear_command._sentrix_clear_int_contract = True

    bot._sentrix_final_visual_stack = True
    logger.info(
        "Pile visuelle finale restaurée : embeds, erreurs, +ping, +clear et logs compacts actifs."
    )


def _install_clear_error_guard(bot: commands.Bot) -> None:
    """Empêche +clear d'être classé à tort comme une erreur de montant."""
    current = getattr(bot, "on_command_error", None)
    function = getattr(current, "__func__", current)
    if not callable(current) or getattr(function, "_sentrix_clear_error_guard", False):
        return

    async def clear_error_guard(_bot, ctx: commands.Context, error: commands.CommandError):
        command = getattr(ctx, "command", None)
        root = getattr(command, "root_parent", None) or command
        root_name = str(getattr(root, "name", "") or "").casefold()
        base = getattr(error, "original", error)
        conversion_errors = tuple(
            cls for cls in (
                getattr(commands, "BadArgument", None),
                getattr(commands, "BadUnionArgument", None),
                getattr(commands, "ConversionError", None),
            ) if isinstance(cls, type)
        )
        if root_name == "clear" and conversion_errors and isinstance(base, conversion_errors):
            from utils import embeds

            return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning('Le nombre doit être un entier entre **1 et 100**.\n\nUtilisez : `+clear <nombre>`', title='Nombre invalide')))

        result = current(ctx, error)
        if inspect.isawaitable(result):
            return await result
        return result

    clear_error_guard._sentrix_clear_error_guard = True
    clear_error_guard._sentrix_original = function
    bot.on_command_error = types.MethodType(clear_error_guard, bot)


def _disable_legacy_help_mutators(bot: commands.Bot) -> None:
    """Empêche définitivement les anciens moteurs V8/V9 de réécrire le vrai +help.

    Ces modules restent importables parce que d'autres fonctions historiques les
    référencent encore, mais ils ne sont plus propriétaires de la commande ``help``.
    Une fois les marqueurs officiels présents, leurs installateurs deviennent donc des
    no-op pour cette commande au lieu d'attacher un callback de forme ``(cog, ctx)`` à une
    Command autonome.
    """
    try:
        from . import help_clean_style

        current = help_clean_style.install
        if not getattr(current, "_sentrix_official_help_guard", False):
            legacy_install = current

            def guarded_help_clean_style(bot_obj: commands.Bot) -> None:
                if _is_official_help_command(bot_obj.get_command("help")):
                    return None
                return legacy_install(bot_obj)

            guarded_help_clean_style._sentrix_official_help_guard = True
            guarded_help_clean_style._sentrix_legacy_install = legacy_install
            help_clean_style.install = guarded_help_clean_style
    except Exception:
        logger.debug("Impossible de neutraliser help_clean_style legacy.", exc_info=True)

    try:
        from . import language_runtime

        current = language_runtime._install_help_patch
        if not getattr(current, "_sentrix_official_help_guard", False):
            legacy_patch = current

            def guarded_language_help_patch(bot_obj: commands.Bot) -> None:
                if _is_official_help_command(bot_obj.get_command("help")):
                    return None
                return legacy_patch(bot_obj)

            guarded_language_help_patch._sentrix_official_help_guard = True
            guarded_language_help_patch._sentrix_legacy_patch = legacy_patch
            language_runtime._install_help_patch = guarded_language_help_patch
    except Exception:
        logger.debug("Impossible de neutraliser language_runtime help legacy.", exc_info=True)


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


async def _register_official_prefix_help(bot: commands.Bot) -> commands.Command:
    """Enregistre uniquement l'entrée préfixée autonome de l'aide officielle."""
    registered = bot.get_command("help")
    if registered is not None:
        bot.remove_command("help")

    async def prefix_help_entry(ctx: commands.Context, *, commande: str | None = None) -> None:
        help_cog = bot.get_cog("SentriXHelp")
        if not isinstance(help_cog, OfficialHelp):
            logger.error("SentriXHelp absent pendant l'exécution de +help.")
            return
        await help_cog.send_help(ctx, commande)

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

    exposed = {str(name).casefold() for name in prefix_command.clean_params}
    forbidden = exposed & _FRAMEWORK_HELP_PARAMS
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
    return prefix_command


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

    # Son Command préfixé de classe est retiré puis remplacé par une Command autonome.
    await _register_official_prefix_help(bot)


async def _ensure_official_help_on_ready(bot: commands.Bot) -> None:
    """Dernier invariant après tous les bootstrap/tasks différés et les reconnects."""
    _disable_legacy_help_mutators(bot)
    command = bot.get_command("help")
    if _help_signature_is_safe(command):
        return

    exposed = list(getattr(command, "clean_params", {})) if command is not None else []
    logger.warning(
        "Mutation legacy de +help détectée au on_ready (params=%s, callback=%s) ; réparation immédiate.",
        exposed,
        getattr(getattr(command, "callback", None), "__qualname__", "absent"),
    )

    # Le Cog officiel existe normalement déjà. On ne touche pas au slash synchronisé :
    # seule l'entrée préfixée, celle qui peut être corrompue par un vieux callback, est
    # reconstruite.
    help_cog = bot.get_cog("SentriXHelp")
    if isinstance(help_cog, OfficialHelp):
        await _register_official_prefix_help(bot)
    else:
        await _register_official_help(bot)


def _install_help_ready_guard(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_official_help_ready_guard", False):
        return

    async def ready_guard() -> None:
        try:
            await _ensure_official_help_on_ready(bot)
        except Exception:
            logger.exception("Impossible de garantir +help officiel au on_ready.")

    bot.add_listener(ready_guard, "on_ready")
    bot._sentrix_official_help_ready_guard = True


async def setup(bot: commands.Bot) -> None:
    # Ne dépend plus du succès de visual_experience_v5 : Railway arrive toujours ici
    # après la boucle complète des extensions.
    await finalize_runtime(bot)

    # Le renderer est volontairement restauré ICI et non dans utils.__init__ : on garde un
    # seul ordre de bootstrap, mais les réponses validées avant le merge redeviennent la
    # dernière autorité visuelle après toutes les couches métier/sécurité.
    _install_final_visual_stack(bot)
    _install_clear_error_guard(bot)

    # Les deux anciennes implémentations possèdent encore des callbacks de forme
    # ``(cog, ctx)``. Elles restent disponibles pour le vieux code, mais ne peuvent plus
    # toucher à la Command autonome officielle.
    _disable_legacy_help_mutators(bot)

    removed = _disconnect_configuration_log_listeners(bot)
    await _register_official_help(bot)
    _install_help_ready_guard(bot)

    # RuntimeFixV1 ne possède pas le renderer/logger : il répare uniquement les routes
    # guild_config -> log_settings et les permissions des salons existants.
    await runtime_fix_v1.setup(bot)

    # Vérification immédiate en plus du on_ready. Toute mutation synchrone d'un installateur
    # chargé pendant ce setup est ainsi détectée avant même la connexion utilisateur.
    if not _help_signature_is_safe(bot.get_command("help")):
        await _register_official_prefix_help(bot)

    bot._sentrix_bootstrap_final = True
    logger.info(
        "Bootstrap final : runtime + renderer restaurés, help unique protégé, %s listener(s) de logs legacy débranché(s).",
        removed,
    )
