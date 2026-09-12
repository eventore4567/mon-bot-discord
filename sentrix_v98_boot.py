"""Point d'entrée Railway SentriX V98/V99/V100/V101/V102.

Python charge ``sitecustomize`` avant ce fichier : V95/V96 sont donc déjà installées.
V99 corrige le transport des options des sous-commandes groupées. V100 installe ensuite
les garde-fous d'interaction. V101 assainit les signatures publiques. V102 nettoie enfin
la surface slash, simplifie les noms visibles et fiabilise les playlists avant que V98
construise l'arborescence finale, puis le bootstrap Railway historique prend le relais.
"""
from __future__ import annotations

import runpy

from sentrix_grouped_slash_fix import install as install_grouped_slash_fix
from sentrix_v100_defer_fix import install as install_v100_defer_fix
from sentrix_v100_runtime_fix import install as install_v100_runtime_fix
from sentrix_v101_command_runtime import install as install_v101_command_runtime
from sentrix_v98_slash import install as install_v98
from sentrix_v102_command_surface import install as install_v102


install_grouped_slash_fix()
install_v100_defer_fix()
install_v100_runtime_fix()
install_v101_command_runtime()
install_v98()
install_v102()
runpy.run_module("railway_boot", run_name="__main__")
