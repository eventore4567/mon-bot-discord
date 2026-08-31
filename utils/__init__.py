"""Utilitaires partagés de SentriX.

Le package ``utils`` doit rester importable par les tests et les outils statiques même
quand ``discord.py`` n'est pas installé. Les modules visuels Discord sont donc exposés
par des wrappers paresseux et ne sont installés automatiquement que dans le vrai runtime,
où le module ``discord`` est disponible.

Cette séparation évite qu'un simple ``from utils.v22_rules import ...`` ou
``from utils.ai_api_compat import ...`` charge toute la couche Discord pendant les gates
CI, tout en conservant exactement l'installation automatique historique en production.
"""

from __future__ import annotations

import importlib.util


def install_command_visuals():
    from .command_visuals import install_command_visuals as _install

    return _install()


def install_top_command_banners():
    from .top_command_banners import install_top_command_banners as _install

    return _install()


def install_top_banner_guard():
    from .top_banner_guard import install_top_banner_guard as _install

    return _install()


def install_profile_embed_guard():
    from .profile_embed_guard import install_profile_embed_guard as _install

    return _install()


def install_me_single_panel():
    from .me_single_panel import install_me_single_panel as _install

    return _install()


def install_unified_command_panels():
    from .unified_command_panels import install_unified_command_panels as _install

    return _install()


# En production, discord.py est déjà présent avant les imports de ``utils`` : on garde
# les compatibilités historiques puis on installe EN DERNIER l'invariant visuel final.
# Les réponses simples deviennent un seul grand panneau Components V2 ; les anciennes
# vues interactives restent un seul embed classique afin de ne casser aucun bouton.
if importlib.util.find_spec("discord") is not None:
    install_command_visuals()
    install_top_command_banners()
    install_top_banner_guard()
    install_profile_embed_guard()
    install_me_single_panel()
    install_unified_command_panels()


__all__ = [
    "install_command_visuals",
    "install_top_command_banners",
    "install_top_banner_guard",
    "install_profile_embed_guard",
    "install_me_single_panel",
    "install_unified_command_panels",
]
