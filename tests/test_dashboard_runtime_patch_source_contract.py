"""Contrat source minimal pour éviter le retour du loader legacy tardif."""
from __future__ import annotations

import inspect

from cogs import dashboard_runtime_patch


def test_runtime_patch_est_permissions_only():
    source = inspect.getsource(dashboard_runtime_patch)
    assert "def _patch_initial_load" not in source
    assert "def _patch_switch_html" not in source
    assert "def _patch_recovery_loader" not in source
    assert "dashboard.INDEX_HTML =" not in source
