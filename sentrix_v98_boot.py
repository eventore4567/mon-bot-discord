"""Point d'entrée Railway SentriX V98.

Python charge ``sitecustomize`` avant ce fichier : V95/V96 sont donc déjà installées.
V98 remplace ensuite uniquement le constructeur de la surface slash, puis délègue au
bootstrap Railway historique inchangé.
"""
from __future__ import annotations

import runpy

from sentrix_v98_slash import install


install()
runpy.run_module("railway_boot", run_name="__main__")
