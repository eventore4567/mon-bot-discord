"""Désactiver les niveaux doit vraiment tout couper, pas seulement les gains d'XP.

Bug constaté : les gains d'XP étaient bien bloqués, mais +profile, +me/+stats
et +level/+rank continuaient d'afficher niveau et rang — rien ne semblait
désactivé du point de vue de l'utilisateur.
"""
from __future__ import annotations

import ast
import os
import pathlib

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = pathlib.Path(__file__).resolve().parent.parent
SOURCE = (RACINE / "cogs" / "levels.py").read_text(encoding="utf-8")


def _corps(nom: str) -> str:
    for node in ast.walk(ast.parse(SOURCE)):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == nom:
            return ast.unparse(node)
    raise AssertionError(f"{nom} introuvable")


def test_un_seul_point_de_verite_pour_l_etat_des_niveaux():
    """_niveaux_actifs interroge les DEUX interrupteurs existants : celui de
    +level-system et celui du panneau de configuration. Les trois affichages
    doivent s'appuyer dessus plutôt que de réinventer leur propre logique."""
    corps = _corps("_niveaux_actifs")
    assert "system_features" in corps
    assert "is_system_enabled" in corps
    assert "module_enabled" in corps


def test_stats_masque_le_niveau_quand_desactive():
    corps = _corps("build_stats_embed")
    assert "self._niveaux_actifs(guild.id)" in corps
    assert "Désactivés sur ce serveur" in corps


def test_le_panneau_de_niveau_dit_que_c_est_desactive():
    corps = _corps("build_level_panneau")
    assert "self._niveaux_actifs(guild.id)" in corps
    assert "système de niveaux est désactivé" in corps


def test_profile_masque_le_niveau_et_le_rang_quand_desactive():
    corps = _corps("profile")
    assert "self._niveaux_actifs(ctx.guild.id)" in corps
    # Le niveau ne doit apparaître ni dans la description ni comme champ
    # séparé quand le système est coupé.
    assert 'if niveaux_actifs:' in corps
