"""Corrige la cause structurelle commune à plusieurs bugs slash/préfixe divergents
(dont /unmute, et le dédoublonnage de sanctions qui ne protégeait jamais /ban /kick
/mute /warn) : une fois qu'une HybridCommand/HybridGroup a un app_command construit
(dès la décoration si with_app_command=True, ou plus tard via
cogs/command_hybrid_slash_restore_v3.py), discord.py fige une COPIE de la référence de
fonction dans ``app_command._callback`` (voir discord/ext/commands/hybrid.py,
``HybridAppCommand.__init__`` : ``callback=wrapped.callback`` est un instantané, pas
une liaison vivante).

SentriX applique dédoublonnage/sécurité/logs à des commandes déjà chargées via le
motif ``command.callback = wrapper`` dans une quinzaine de modules (voir
tools/command_callback_integrity_audit.py pour le détail et la preuve empirique). Ce
motif met bien à jour ``Command.callback`` — vu par le chemin préfixe
(``Command.invoke`` relit ``self.callback`` à chaque appel) — mais jamais
``app_command._callback``, vu par le chemin slash. Résultat : `+la commande est
protégée/corrigée, `/la même commande continue d'exécuter l'ANCIEN code, pour
toujours, sans aucune erreur ni log des deux côtés.

Plutôt que de retrouver et corriger individuellement chaque site (~15 modules, et
tout nouveau module futur ferait réapparaître le même bug), ce module fait UNE passe
de resynchronisation après le chargement de toutes les extensions (main.py +
railway_boot.py), juste avant tree.sync() : pour chaque commande hybride dont
l'app_command existe, si son ``_callback`` a divergé de ``command.callback``, il est
réaligné. C'est la même correction que produirait la réécriture de chacun des ~15
sites, appliquée une seule fois, au bon endroit, pour toute commande présente et
future.
"""
from __future__ import annotations

import inspect
import logging

from discord.ext import commands

logger = logging.getLogger("bot.hybrid-callback-resync")


def _walk_hybrid(bot: commands.Bot):
    for command in bot.walk_commands():
        if isinstance(command, (commands.HybridCommand, commands.HybridGroup)):
            yield command


def resync(bot: commands.Bot) -> list[str]:
    """Réaligne app_command._callback sur command.callback partout où ils ont
    divergé. Retourne la liste des noms qualifiés corrigés (pour le log de
    démarrage — voir main.py)."""
    fixed: list[str] = []
    for command in _walk_hybrid(bot):
        app_command = getattr(command, "app_command", None)
        # HybridGroup.app_command vaut discord.utils.MISSING (pas None) tant qu'aucun
        # app_command n'a été construit pour le groupe lui-même (ex: with_app_command=
        # False, ou un groupe dont seules les sous-commandes sont slash) — pas d'objet
        # sur lequel écrire _callback dans ce cas.
        if not app_command or not hasattr(app_command, "_callback"):
            continue
        if command.callback is not getattr(app_command, "_callback", None):
            app_command._callback = command.callback
            fixed.append(command.qualified_name)
    if fixed:
        logger.warning(
            "Callback slash resynchronisé sur le callback préfixe pour %s commande(s) "
            "(la version / exécutait un code différent de +) : %s",
            len(fixed), ", ".join(sorted(fixed)),
        )
    return fixed


# --------------------------------------------------------------------------- garde runtime

# Pour ces commandes précises, le nom de la fonction Python est toujours identique au nom
# de la commande (contrairement à bot-status/system_status, qu'on ne peut pas vérifier
# ainsi sans faux positifs). Appliquer la mauvaise sanction à un membre réel est
# irréversible : on vérifie donc l'identité du code juste avant l'exécution.
SANCTION_COMMANDS = frozenset({"ban", "tempban", "unban", "kick", "mute", "unmute", "warn"})


def _real_function(callback):
    try:
        return inspect.unwrap(callback)
    except (TypeError, ValueError):
        return callback


def _identity_error(command_name: str, callback, path: str) -> str | None:
    """Compare l'identité RÉELLE du code au nom de la commande.

    ``__name__`` seul ne suffit pas : ``functools.wraps`` le recopie depuis la fonction
    enveloppée, donc un wrapper construit autour de ``mute`` se présente comme « mute »
    même s'il est monté sur ``unmute`` — et inversement, un wrapper ``wraps(unmute)``
    autour d'un appel à mute mentirait aussi. ``__code__.co_name`` désigne la fonction
    réellement compilée et ne peut pas être falsifié par wraps.
    """
    if callback is None:
        return f"'{command_name}' n'a aucun callback exécutable ({path})."
    declared = _real_function(callback)
    code = getattr(declared, "__code__", None)
    code_name = str(getattr(code, "co_name", "") or "").casefold()
    if not code_name or code_name == command_name:
        return None
    # Un wrapper légitime garde le nom de la commande dans sa propre fonction interne
    # (ex: V57 monte `mute_with_human_duration` sur +mute) : on n'accepte que si le nom
    # réel CONTIENT le nom de la commande comme mot, et jamais celui d'une autre sanction.
    others = {name for name in SANCTION_COMMANDS if name != command_name}
    if command_name in code_name and not any(
        other in code_name and command_name not in other for other in others
    ):
        return None
    return (
        f"Sécurité : '{command_name}' devait exécuter la fonction '{command_name}' mais le code "
        f"réellement monté est '{code_name}' ({path}, {getattr(code, 'co_filename', '?')}:"
        f"{getattr(code, 'co_firstlineno', '?')}). Commande bloquée plutôt que de risquer "
        f"d'appliquer la mauvaise sanction."
    )


def install_guard(bot: commands.Bot) -> bool:
    """Vérifie l'identité du callback des sanctions AVANT chaque exécution, sur les deux
    chemins (+ et /), et réaligne à la volée un app_command qui aurait divergé après le
    resync de démarrage.

    ``resync()`` ne s'exécute qu'une fois, juste avant le sync Discord. N'importe quel
    module qui refait ``command.callback = wrapper`` ensuite réintroduit silencieusement
    la divergence pour le chemin slash, pour toujours. Ce garde ferme ce trou : il est
    enregistré comme check global (mécanisme additif déjà utilisé par main.py, contrairement
    à before_invoke qui n'a qu'un seul emplacement) et discord.py exécute les checks via
    ``Command.prepare()``, appelé aussi bien par le chemin préfixe que par
    ``HybridAppCommand._invoke_with_namespace``.
    """
    if getattr(bot, "_sentrix_sanction_identity_guard", False):
        return True

    async def sanction_identity_guard(ctx: commands.Context) -> bool:
        command = getattr(ctx, "command", None)
        name = str(getattr(command, "name", "") or "").casefold()
        if name not in SANCTION_COMMANDS:
            return True

        is_slash = getattr(ctx, "interaction", None) is not None
        app_command = getattr(command, "app_command", None)
        if is_slash and app_command is not None and hasattr(app_command, "_callback"):
            if app_command._callback is not command.callback:
                app_command._callback = command.callback
                logger.warning(
                    "Sanction '%s' : callback slash divergent réaligné à l'invocation "
                    "(un module l'a re-patché après le resync de démarrage).", name,
                )

        if is_slash and app_command is not None and hasattr(app_command, "_callback"):
            callback, path = app_command._callback, "slash"
        else:
            callback, path = getattr(command, "callback", None), "préfixe"

        error = _identity_error(name, callback, path)
        if error:
            logger.critical(error)
            raise commands.CheckFailure(error)
        return True

    sanction_identity_guard._sentrix_sanction_identity_guard = True
    bot.add_check(sanction_identity_guard)
    bot._sentrix_sanction_identity_guard = True
    logger.info(
        "Garde d'identité des sanctions actif sur + et / : %s.", ", ".join(sorted(SANCTION_COMMANDS))
    )
    return True
