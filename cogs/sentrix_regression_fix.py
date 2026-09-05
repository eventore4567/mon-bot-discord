"""Late SentriX regression extension.

The regression layer stays the compatibility base. Product-facing fixes are applied last so
historical cogs cannot re-register ticket setup commands or override the final error policy.
"""
from sentrix_regression_runtime import setup as _regression_setup
from sentrix_product_update import install_runtime
from sentrix_final_product_finish import install as install_final_product_finish


async def setup(bot):
    await _regression_setup(bot)
    await install_runtime(bot)
    await install_final_product_finish(bot)


__all__ = ["setup"]
