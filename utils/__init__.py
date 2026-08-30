"""Utilitaires partagés de SentriX.

Le pipeline officiel des logs reste ``utils.log_service`` -> ``utils.wide_logs``.
Aucun monkey-patch de ``discord.TextChannel.send`` n'est installé : le vieux fallback
legacy est interdit. Seul le constructeur Components V2 est durci afin qu'une vignette
ou un bouton défectueux ne puisse jamais faire disparaître la bannière.
"""

from .log_v2_hardening import install as _install_log_v2_hardening

_install_log_v2_hardening()
