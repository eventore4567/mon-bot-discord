"""Utilitaires partagés de SentriX.

Le renderer compact historique est chargé en premier pour conserver la compatibilité des
anciens cogs. La couche runtime SentriX est ensuite appliquée une seule fois : elle devient
le point central pour le rendu, les logs et les correctifs transversaux des commandes.
Le nettoyage final retire les séparateurs répétés et espace proprement les journaux.
"""

from . import wide_compact_v6 as _wide_compact_v6

_wide_compact_v6.install()

from . import sentrix_runtime as _sentrix_runtime

_sentrix_runtime.install()

from . import sentrix_visual_cleanup as _sentrix_visual_cleanup

_sentrix_visual_cleanup.install()
