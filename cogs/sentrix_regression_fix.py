"""Late SentriX regression extension.

The regression layer stays the compatibility base. Product-facing fixes are applied after all
historical runtime layers. V77 patches invitation attribution, V78 replaces the verification
entry point, then V76 runs absolutely last so every prefix command — including commands added
by V78 — is checked and repaired immediately before invocation.
"""
from __future__ import annotations

import os

import sentrix_regression_runtime as _regression_runtime
from sentrix_product_update import install_runtime
from sentrix_final_product_finish import install as install_final_product_finish
from .command_final_guard_v76 import install as install_command_final_guard_v76
from .invite_detection_fix_v77 import install as install_invite_detection_fix_v77
from .verify_setup_interactive_v78 import install as install_verify_setup_interactive_v78


async def setup(bot):
    # Le gate V95 charge volontairement tous les cogs sans ouvrir de session Discord.
    # Dans ce contexte seulement, wait_until_ready() n'est pas utilisable et la restauration
    # des vues persistantes ne peut de toute façon rien restaurer (aucune guilde connectée).
    # On neutralise donc uniquement cette tâche réseau pendant l'audit hors-ligne. Le chemin
    # Railway normal reste strictement inchangé et exécute la restauration historique.
    original_restore = None
    if os.getenv("SENTRIX_CI_OFFLINE") == "1":
        original_restore = _regression_runtime._restore_dropdown_views

        async def _offline_restore(_bot):
            return None

        _regression_runtime._restore_dropdown_views = _offline_restore

    try:
        await _regression_runtime.setup(bot)
    finally:
        if original_restore is not None:
            _regression_runtime._restore_dropdown_views = original_restore

    await install_runtime(bot)
    await install_final_product_finish(bot)
    install_invite_detection_fix_v77(bot)
    install_verify_setup_interactive_v78(bot)
    install_command_final_guard_v76(bot)


__all__ = ["setup"]
