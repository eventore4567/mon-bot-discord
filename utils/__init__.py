"""Utilitaires partagés de SentriX.

``utils.embeds`` reste le renderer canonique et ``utils.log_service`` le transport officiel.
Le transport visuel des journaux est installé ici une seule fois afin que tous les cogs,
y compris les anciens appelants, utilisent les mêmes bannières SentriX 1024 px.
"""

from .log_banners import install as _install_log_banners
from .log_banner_assets import install as _install_log_banner_assets
from .log_wide_guard import install as _install_log_wide_guard

_install_log_banner_assets()
_install_log_wide_guard()
_install_log_banners()

del _install_log_banner_assets
del _install_log_wide_guard
del _install_log_banners
