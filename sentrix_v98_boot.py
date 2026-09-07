"""Point d'entrée Railway SentriX V98/V99.

Ce fichier est l'entrée réellement utilisée par le Procfile et le Dockerfile. Il ne
repose plus sur l'import implicite de ``sitecustomize`` pour les couches critiques :
V95 est branchée explicitement, puis le bootstrap Railway est importé (ce qui installe
la vraie classe AutoShardedBot), ensuite V97/V98 et la vérification V96 sont réaffirmées
avant la création du bot et avant tout ``CommandTree.sync``.
"""
from __future__ import annotations

import asyncio
import logging

from discord import app_commands

from sentrix_v95_bootstrap import install as install_v95


logger = logging.getLogger("bot.v98-boot")

# V95 doit exister avant l'import du bootstrap Railway afin que CommandTree.sync soit
# intercepté même si Python n'a pas chargé sitecustomize (l'appel est idempotent).
install_v95()
if not getattr(app_commands.CommandTree.sync, "_sentrix_v95", False):
    raise RuntimeError("V95 slash n'est pas branchée sur CommandTree.sync.")

# railway_boot remplace commands.Bot par la classe AutoSharded de production puis importe
# main. Il ne démarre rien tant que run() n'est pas appelé.
import railway_boot as runtime_boot  # noqa: E402

from sentrix_v97_reliability import install as install_v97  # noqa: E402
from sentrix_v98_slash import install as install_v98  # noqa: E402
from sentrix_verification_v96 import install as install_v96  # noqa: E402
from sentrix_verification_v96_finalizer import install as install_v96_finalizer  # noqa: E402
import sentrix_v95_runtime as v95  # noqa: E402

# Même ordre que le bootstrap HA produit : V97 fiabilise Interaction -> Context et /setup,
# V98 construit l'arborescence sémantique finale, puis V96 est réinstallée sur la vraie
# classe Bot de production et réaffirmée juste avant la préparation slash.
install_v97(runtime_boot.dashboard_web)
install_v98()
install_v96()
install_v96_finalizer()

if not getattr(v95, "_sentrix_v97_reliability", False):
    raise RuntimeError("V97 fiabilité slash absente du bootstrap Railway.")
if not getattr(v95, "_sentrix_v98_grouped_slash", False):
    raise RuntimeError("V98 arborescence slash absente du bootstrap Railway.")

logger.warning("Bootstrap V99 prêt : V95 + V97 + V98 + V96 confirmés avant Discord.")


if __name__ == "__main__":
    try:
        asyncio.run(runtime_boot.run())
    except KeyboardInterrupt:
        logger.info("Arrêt de SentriX V99.")
