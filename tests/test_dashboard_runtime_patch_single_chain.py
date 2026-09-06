"""Non-régression : aucune extension tardive ne doit remplacer le loader canonique."""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "x")

from cogs import dashboard_runtime_patch  # noqa: E402
from web import dashboard  # noqa: E402


def test_runtime_patch_ne_recrit_plus_index_html():
    """Le correctif de permissions peut s'installer sans toucher au frontend."""
    original_html = dashboard.INDEX_HTML
    original_flag = getattr(dashboard, "_sentrix_runtime_patch_installed", None)
    original_admin = getattr(dashboard, "ADMINISTRATOR", None)
    original_manager = getattr(dashboard, "_administrator_member", None)

    try:
        if hasattr(dashboard, "_sentrix_runtime_patch_installed"):
            delattr(dashboard, "_sentrix_runtime_patch_installed")
        dashboard_runtime_patch.install()
        assert dashboard.INDEX_HTML == original_html
    finally:
        if original_flag is None:
            if hasattr(dashboard, "_sentrix_runtime_patch_installed"):
                delattr(dashboard, "_sentrix_runtime_patch_installed")
        else:
            dashboard._sentrix_runtime_patch_installed = original_flag
        if original_admin is not None:
            dashboard.ADMINISTRATOR = original_admin
        if original_manager is not None:
            dashboard._administrator_member = original_manager


def test_loader_canonique_survit_au_runtime_patch():
    """Le bug visible en production ne doit jamais réapparaître après install()."""
    original_html = dashboard.INDEX_HTML
    original_flag = getattr(dashboard, "_sentrix_runtime_patch_installed", None)
    original_admin = getattr(dashboard, "ADMINISTRATOR", None)
    original_manager = getattr(dashboard, "_administrator_member", None)

    try:
        if hasattr(dashboard, "_sentrix_runtime_patch_installed"):
            delattr(dashboard, "_sentrix_runtime_patch_installed")
        dashboard_runtime_patch.install()
        html = dashboard.INDEX_HTML
        assert "new AbortController()" in html
        assert "state.guildAbort" in html
        assert "Les données précédentes ont été retirées." not in html
        assert "state.guildLoadToken" not in html
    finally:
        dashboard.INDEX_HTML = original_html
        if original_flag is None:
            if hasattr(dashboard, "_sentrix_runtime_patch_installed"):
                delattr(dashboard, "_sentrix_runtime_patch_installed")
        else:
            dashboard._sentrix_runtime_patch_installed = original_flag
        if original_admin is not None:
            dashboard.ADMINISTRATOR = original_admin
        if original_manager is not None:
            dashboard._administrator_member = original_manager


def test_module_ne_contient_plus_les_anciens_rewriters():
    import inspect

    source = inspect.getsource(dashboard_runtime_patch)
    assert "def _patch_initial_load" not in source
    assert "def _patch_switch_html" not in source
    assert "def _patch_recovery_loader" not in source
