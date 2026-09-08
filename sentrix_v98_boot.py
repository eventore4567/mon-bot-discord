"""Point d'entrée Railway SentriX V98/V99.

Python charge ``sitecustomize`` avant ce fichier : V95/V96 sont donc déjà installées.
V99 corrige le transport des options des sous-commandes groupées, puis V98 construit
l'arborescence slash avant de déléguer au bootstrap Railway historique inchangé.
"""
from __future__ import annotations

import runpy

from sentrix_grouped_slash_fix import install as install_grouped_slash_fix
from sentrix_v98_slash import install as install_v98


install_grouped_slash_fix()
install_v98()
runpy.run_module("railway_boot", run_name="__main__")
