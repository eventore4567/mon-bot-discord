"""Late SentriX regression extension.

The regression layer stays the compatibility base. Product-facing fixes are applied last so
historical cogs cannot re-register ticket setup commands or override the final error policy.
V76 is deliberately installed at the end: it guards the live prefix registry immediately
before invocation, after all older wrappers had a chance to touch it. V77 then patches the
already-loaded Invites cog so one-use links deleted by Discord can still be attributed.
"""
from sentrix_regression_runtime import setup as _regression_setup
from sentrix_product_update import install_runtime
from sentrix_final_product_finish import install as install_final_product_finish
from .command_final_guard_v76 import install as install_command_final_guard_v76
from .invite_detection_fix_v77 import install as install_invite_detection_fix_v77


async def setup(bot):
    await _regression_setup(bot)
    await install_runtime(bot)
    await install_final_product_finish(bot)
    install_command_final_guard_v76(bot)
    install_invite_detection_fix_v77(bot)


__all__ = ["setup"]
