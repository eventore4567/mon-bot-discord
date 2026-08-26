"""Utilitaires partagés de SentriX.

Ordre final :
1. renderer historique compatible ;
2. runtime unifié ;
3. +ping final ;
4. nettoyage visuel ;
5. logs compacts finaux.

Toutes les couches utilisent exactement la même grande ligne de séparation.
"""

from . import wide_compact_v6 as _wide_compact_v6

_wide_compact_v6.install()

from . import sentrix_runtime as _sentrix_runtime

_sentrix_runtime.install()

from . import ping_final_style as _ping_final_style

_ping_final_style.install()

from . import sentrix_visual_cleanup as _sentrix_visual_cleanup

_sentrix_visual_cleanup.install()

# Synchronise les anciennes couches avec la ligne sûre de 42 caractères.
from . import embeds as _embeds

_SENTRIX_PANEL_BAR = _wide_compact_v6.LONG_BAR
_sentrix_visual_cleanup.PANEL_BAR = _SENTRIX_PANEL_BAR
_sentrix_runtime.BAR = _SENTRIX_PANEL_BAR
_sentrix_runtime.CHANGE_BAR = ""
_embeds.BAR = _SENTRIX_PANEL_BAR
_ping_final_style.command_style_v2.BAR = _SENTRIX_PANEL_BAR

# Toujours en dernier : logs compacts + une seule grande ligne sous le titre.
from . import log_compact_final as _log_compact_final

_log_compact_final.PANEL_BAR = _SENTRIX_PANEL_BAR
_log_compact_final.install()
