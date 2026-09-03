"""_install_command_surface() ne doit jamais referencer un module supprime.

Le commit 2a130d7 ("supprime le groupe mort des correctifs de logs") a retire
cogs/command_access_policy_v2.py, cogs/command_centers_v2.py et
cogs/command_direct_aliases_v2.py en les croyant morts : son detecteur ne voit
pas un `from . import (...)` DIFFERE (a l'interieur d'un corps de fonction),
donc invisible a une analyse statique du graphe d'imports au niveau module.
_install_command_surface() les importait toujours, dans le meme `from . import`
que command_catalog_cleanup/command_hybrid_slash_restore_v3/slash_command_budget
(bien vivants) : l'ImportError sur le premier nom manquant empechait ces trois
survivants de tourner, a CHAQUE demarrage, silencieusement avale par le
try/except de help_v8_final_guard.install().
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "x")

from cogs import final_runtime_polish  # noqa: E402


def test_install_command_surface_n_importe_que_des_modules_existants():
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(final_runtime_polish._install_command_surface))
    tree = ast.parse(source)
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    for nom_supprime in (
        "command_access_policy_v2",
        "command_centers_v2",
        "command_direct_aliases_v2",
    ):
        assert nom_supprime not in imported_names, (
            f"_install_command_surface importe encore {nom_supprime}, "
            "supprime du depot (commit 2a130d7) : ImportError garantie au demarrage."
        )


def test_install_command_surface_importe_reellement_sans_lever():
    # Execute le meme `from . import (...)` que _install_command_surface : si un des
    # trois modules restants disparaissait a son tour sans que cette fonction soit mise
    # a jour, ce test le detecterait immediatement (au lieu d'un log d'erreur avale).
    from cogs import (  # noqa: F401
        command_catalog_cleanup,
        command_hybrid_slash_restore_v3,
        slash_command_budget,
    )
