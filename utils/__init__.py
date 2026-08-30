"""Utilitaires partagés de SentriX.

``utils.embeds`` reste le renderer canonique et ``utils.log_service`` le transport officiel.
Le transport visuel des journaux est installé ici une seule fois afin que tous les cogs,
y compris les anciens appelants, utilisent les mêmes bannières SentriX 1024 px.
"""

from .log_banners import install as _install_log_banners

_install_log_banners()

del _install_log_banners
