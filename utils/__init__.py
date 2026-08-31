"""Utilitaires partagés de SentriX.

Les modules de logs sont chargés explicitement par leurs consommateurs.
Aucun monkey-patch de transport de logs n'est exécuté à l'import du package ``utils``.
Le transport officiel reste ``utils.log_service`` -> ``utils.wide_logs``.

La présentation des réponses de commandes est centralisée séparément dans
``utils.command_visuals``. Elle ne touche jamais ``TextChannel.send`` ni
``Messageable.send`` et ne peut donc pas intercepter les journaux Components V2.
Les panneaux classiques interactifs utilisent en complément ``top_command_banners``
pour garder la bannière SentriX au-dessus du contenu pendant toutes leurs éditions.
``top_banner_guard`` couvre enfin les réponses d'interactions/followups qui contiennent
déjà une bannière SentriX sans modifier les logs ni les images métier.
``profile_embed_guard`` garde /profile en vrai embed Discord afin que ses statistiques
inline restent compactes et s'affichent sur plusieurs colonnes.
``me_single_panel`` rend +me dans un seul Container Components V2 avec sa bannière,
son contenu et ses quatre boutons de navigation dans le même bloc.
"""

from .command_visuals import install_command_visuals
from .top_command_banners import install_top_command_banners
from .top_banner_guard import install_top_banner_guard
from .profile_embed_guard import install_profile_embed_guard
from .me_single_panel import install_me_single_panel

install_command_visuals()
install_top_command_banners()
install_top_banner_guard()
install_profile_embed_guard()
install_me_single_panel()

__all__ = [
    "install_command_visuals",
    "install_top_command_banners",
    "install_top_banner_guard",
    "install_profile_embed_guard",
    "install_me_single_panel",
]
