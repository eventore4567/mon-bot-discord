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
