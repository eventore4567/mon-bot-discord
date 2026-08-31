"""Utilitaires partagés de SentriX.

Les modules de logs sont chargés explicitement par leurs consommateurs.
Aucun monkey-patch de transport de logs n'est exécuté à l'import du package ``utils``.
Le transport officiel reste ``utils.log_service`` -> ``utils.wide_logs``.

La présentation des réponses de commandes est centralisée séparément dans
``utils.command_visuals``. Elle ne touche jamais ``TextChannel.send`` ni
``Messageable.send`` et ne peut donc pas intercepter les journaux Components V2.
Les panneaux classiques interactifs utilisent en complément ``top_command_banners``
pour garder la bannière SentriX au-dessus du contenu pendant toutes leurs éditions.
"""

from .command_visuals import install_command_visuals
from .top_command_banners import install_top_command_banners

install_command_visuals()
install_top_command_banners()

__all__ = ["install_command_visuals", "install_top_command_banners"]
