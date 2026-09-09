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


def _corps(nom: str, source: str = SOURCE) -> str:
    for node in ast.walk(ast.parse(source)):
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
    """+profile est réellement servie par cogs/profile_oxyde_runtime.py::build_page
    — cogs/levels.py::profile existe encore comme objet Command (aliases,
    description...) mais son corps est remplacé au démarrage, voir
    profile_oxyde_runtime.py::install(). Ce test vérifiait auparavant, à tort,
    le corps mort de cogs/levels.py : il passait sans jamais toucher le code
    qui s'exécute réellement — bug réel trouvé et corrigé pendant Core V2
    Phase 4 (le comportement live n'appliquait aucun garde-fou). Voir aussi
    tests/test_profile_niveaux_actifs.py pour une vérification comportementale,
    pas seulement textuelle."""
    racine = pathlib.Path(__file__).resolve().parent.parent
    source_reel = (racine / "cogs" / "profile_oxyde_runtime.py").read_text(encoding="utf-8")
    corps = _corps("build_page", source=source_reel)
    assert "niveaux_actifs" in corps
    assert 'if niveaux_actifs:' in corps
