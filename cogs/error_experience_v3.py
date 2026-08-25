"""Compatibilité de l'ancien module d'erreurs V3.

La source active est désormais :mod:`cogs.command_error_policy`. Conserver ce petit shim
évite de casser les imports historiques pendant que les anciens tests/branches sont retirés.
"""
from __future__ import annotations

from .command_error_policy import _safe_usage, install, prefix_error_handler, slash_error_handler

__all__ = ["install", "_safe_usage", "prefix_error_handler", "slash_error_handler"]
