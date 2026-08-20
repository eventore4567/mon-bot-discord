"""Compatibilité historique pour l'ancien import ``minigames``.

L'implémentation active et maintenue vit uniquement dans :mod:`cogs.minigames`.
Charger cet ancien module racine charge donc exactement le même code que SentriX.
"""

from cogs.minigames import *  # noqa: F401,F403
