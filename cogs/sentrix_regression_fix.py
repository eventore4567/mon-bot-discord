"""Late SentriX regression extension.

The regression layer stays the compatibility base. Product-facing fixes are applied last so
historical cogs cannot re-register ticket setup commands or override the final error policy.
"""
from sentrix_regression_runtime import setup as _regression_setup
from sentrix_product_update import install_runtime


async def setup(bot):
    await _regression_setup(bot)
    await install_runtime(bot)


__all__ = ["setup"]
