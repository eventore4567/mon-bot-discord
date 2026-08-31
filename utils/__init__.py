"""Utilitaires partagés de SentriX.

Les modules de logs sont chargés explicitement par leurs consommateurs.
Aucun monkey-patch de transport de logs n'est exécuté à l'import du package ``utils``.
Le transport officiel reste ``utils.log_service`` -> ``utils.wide_logs``.

La présentation des réponses de commandes est centralisée séparément dans
``utils.command_visuals``. Elle ne touche jamais ``TextChannel.send`` ni
``Messageable.send`` et ne peut donc pas intercepter les journaux Components V2.
"""

from .command_visuals import install_command_visuals

install_command_visuals()

__all__ = ["install_command_visuals"]
