"""Utilitaires partagés de SentriX.

Ordre volontaire :
1. compatibilité historique ;
2. runtime unifié ;
3. correctif +ping ;
4. nettoyage visuel final des commandes ;
5. rendu compact final des logs avec une seule grande ligne.
"""

from . import wide_compact_v6 as _wide_compact_v6

_wide_compact_v6.install()

from . import sentrix_runtime as _sentrix_runtime

_sentrix_runtime.install()

from . import ping_final_style as _ping_final_style

_ping_final_style.install()

from . import sentrix_visual_cleanup as _sentrix_visual_cleanup

_sentrix_visual_cleanup.install()

# Dernière couche, limitée aux logs : une seule grande ligne, sans agrandir le reste.
from . import log_compact_final as _log_compact_final

_log_compact_final.install()
