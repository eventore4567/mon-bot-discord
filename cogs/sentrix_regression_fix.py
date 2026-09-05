"""Late SentriX regression extension.

The implementation lives in ``sentrix_regression_runtime`` so this cog stays a small,
stable bootstrap shim loaded after the historical compatibility layers.
"""
from sentrix_regression_runtime import setup

__all__ = ["setup"]
