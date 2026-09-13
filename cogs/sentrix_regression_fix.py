"""Late SentriX regression extension.

The regression layer stays the compatibility base. Product-facing fixes are applied after all
historical runtime layers. V77 patches invitation attribution, V78 replaces the verification
entry point, then V76 runs absolutely last so every prefix command — including commands added
by V78 — is checked and repaired immediately before invocation.
"""
from sentrix_regression_runtime import setup as _regression_setup
from sentrix_product_update import install_runtime
from sentrix_final_product_finish import install as install_final_product_finish
from .command_final_guard_v76 import install as install_command_final_guard_v76
from .invite_detection_fix_v77 import install as install_invite_detection_fix_v77
from .verify_setup_interactive_v78 import install as install_verify_setup_interactive_v78
from .slash_command_budget import finalize as finalize_slash_budget


async def setup(bot):
    await _regression_setup(bot)
    await install_runtime(bot)
    await install_final_product_finish(bot)
    install_invite_detection_fix_v77(bot)
    install_verify_setup_interactive_v78(bot)
    install_command_final_guard_v76(bot)

    # railway_boot charge ce cog en dernier. C'est donc le dernier endroit sûr avant le
    # tree.sync() de main.py pour récupérer une commande slash utile qui aurait été mise
    # en attente pendant le chargement, après suppression des anciens alias/duplicats.
    finalize_slash_budget(bot)


__all__ = ["setup"]