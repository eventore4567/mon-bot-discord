"""Point d'entrée Railway SentriX V98/V99/V100/V101/V102/V103/V105.

Python charge ``sitecustomize`` avant ce fichier : V95/V96 sont donc déjà installées.
V99 corrige le transport des options des sous-commandes groupées. V100 installe ensuite
les garde-fous d'interaction. V101 assainit les signatures publiques. V102 nettoie enfin
la surface slash et V103 remet ``/setup`` sur son contrôleur natif. V105 devient ensuite
le dernier garde avant chaque sync Discord : il normalise les racines directes et refuse
toute publication de paramètres internes comme ``ctx``, ``args`` ou ``kwargs``.
"""
from __future__ import annotations

import runpy

from sentrix_grouped_slash_fix import install as install_grouped_slash_fix
from sentrix_v100_defer_fix import install as install_v100_defer_fix
from sentrix_v100_runtime_fix import install as install_v100_runtime_fix
from sentrix_v101_command_runtime import install as install_v101_command_runtime
from sentrix_v98_slash import install as install_v98
from sentrix_v102_command_surface import install as install_v102
from sentrix_v103_setup_fix import install as install_v103_setup_fix
from sentrix_v105_slash_schema_guard import install as install_v105_slash_guard


install_grouped_slash_fix()
install_v100_defer_fix()
install_v100_runtime_fix()
install_v101_command_runtime()
install_v98()
install_v102()
install_v103_setup_fix()
install_v105_slash_guard()
runpy.run_module("railway_boot", run_name="__main__")
