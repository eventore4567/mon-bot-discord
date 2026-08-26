"""Utilitaires partagés de SentriX.

Ordre volontaire :
1. compatibilité historique ;
2. runtime unifié ;
3. correctif +ping qui neutralise command_style_v2 ;
4. nettoyage visuel FINAL, chargé après toutes ces couches.

Ainsi aucune ancienne couche ne peut réinjecter les séparateurs ━━━ ou la barre de
progression de +ping après leur suppression.
"""

from . import wide_compact_v6 as _wide_compact_v6

_wide_compact_v6.install()

from . import sentrix_runtime as _sentrix_runtime

_sentrix_runtime.install()

# Importe volontairement command_style_v2 via ping_final_style AVANT le nettoyage final.
from . import ping_final_style as _ping_final_style

_ping_final_style.install()

# Toujours en dernier : retire les séparateurs restants de toutes les réponses stylées.
from . import sentrix_visual_cleanup as _sentrix_visual_cleanup

_sentrix_visual_cleanup.install()
