"""Utilitaires partagés de SentriX.

Le renderer V6 est chargé ici une seule fois afin que toutes les commandes et tous les
journaux utilisent la même largeur et la même compacité, sans ajouter de nouveau
transport Discord.
"""

from . import wide_compact_v6 as _wide_compact_v6

_wide_compact_v6.install()
