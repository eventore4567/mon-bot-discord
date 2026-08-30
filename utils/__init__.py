"""Utilitaires partagés de SentriX.

``utils.embeds`` reste le renderer canonique et ``utils.log_service`` le transport officiel.
Le thème des journaux est activé uniquement dans les runtimes Discord : les petits outils
CI qui importent ``utils`` sans installer discord.py continuent donc de fonctionner.
"""

try:
    import discord as _discord  # noqa: F401
except ModuleNotFoundError:
    _discord = None

if _discord is not None:
    from .log_banners import install as _install_log_banners
    from .log_banner_assets import install as _install_log_banner_assets
    from .log_wide_guard import install as _install_log_wide_guard

    _install_log_banner_assets()
    _install_log_wide_guard()
    _install_log_banners()

    del _install_log_banner_assets
    del _install_log_wide_guard
    del _install_log_banners

del _discord
