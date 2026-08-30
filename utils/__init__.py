"""Utilitaires partagés de SentriX.

Le renderer officiel des logs reste ``utils.log_service`` -> ``utils.wide_logs``.
Une garde de compatibilité est installée ici afin que les très anciens appelants qui
font encore directement ``TextChannel.send(embed=...)`` dans un salon de logs ne puissent
plus contourner la bannière SentriX.
"""

from utils.log_channel_guard import install as _install_log_channel_guard

_install_log_channel_guard()

del _install_log_channel_guard
