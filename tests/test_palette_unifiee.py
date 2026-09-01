"""La palette semantique a UNE seule source.

Mesure a l'origine de ce test : trois fichiers definissaient les memes etats avec des
valeurs differentes. « succes » valait 0x57F287 dans config et sentrix_runtime mais
0x23A559 dans design_system, « avertissement » avait TROIS valeurs. Un membre voyait
donc deux verts distincts selon la commande utilisee.

config.py est la source. design_system et sentrix_runtime la referencent.
"""
import ast
import pathlib

import config
from utils import design_system

ROOT = pathlib.Path(__file__).resolve().parents[1]

# ATTENTION : utils/sentrix_runtime.py appelle install() au niveau MODULE (ligne 466).
# L'importer patche utils/embeds globalement et perturbe les autres tests. On lit donc
# sa source au lieu de l'importer. Cette fragilite est preexistante et documentee ici
# pour qu'elle ne soit pas redecouverte par accident.
_RUNTIME_SOURCE = (ROOT / "utils" / "sentrix_runtime.py").read_text(encoding="utf-8")

ETATS = [
    ("succes", "COLOR_SUCCESS", "success", "COLOR_SUCCESS"),
    ("erreur", "COLOR_ERROR", "danger", "COLOR_DANGER"),
    ("avertissement", "COLOR_WARNING", "warning", "COLOR_WARNING"),
    ("information", "COLOR_INFO", "primary", "COLOR_INFO"),
    ("neutre", "COLOR_NEUTRAL", "neutral", "COLOR_NEUTRAL"),
]


def test_design_system_suit_la_source_unique():
    for label, cfg, ds_attr, _rt in ETATS:
        attendu = getattr(config, cfg)
        obtenu = getattr(design_system.COLORS, ds_attr)
        assert obtenu == attendu, (
            f"{label} : design_system.{ds_attr}={hex(obtenu)} "
            f"mais config.{cfg}={hex(attendu)}"
        )


def test_sentrix_runtime_suit_la_source_unique():
    """Lecture par AST : importer ce module declencherait son install() global."""
    tree = ast.parse(_RUNTIME_SOURCE)
    affectations = {
        node.targets[0].id: ast.unparse(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    for label, cfg, _ds, rt in ETATS:
        valeur = affectations.get(rt)
        assert valeur == f"_config.{cfg}", (
            f"{label} : sentrix_runtime.{rt} = {valeur} au lieu de _config.{cfg}"
        )


def test_sentrix_runtime_installe_au_niveau_module():
    """Constat documente : cet install() a l'import rend l'ordre des tests fragile.

    Ce n'est pas corrige ici — d'autres modules peuvent dependre de cet effet de bord.
    Le test existe pour que le jour ou quelqu'un le corrige, il sache que c'etait su.
    """
    assert "\ninstall()\n" in _RUNTIME_SOURCE


def test_aucun_etat_ne_reste_code_en_dur_dans_design_system():
    """Les etats doivent etre des references, pas des litteraux recopies."""
    source = open(design_system.__file__, encoding="utf-8").read()
    bloc = source.split("class SentriXColors:", 1)[1].split("COLORS =", 1)[0]
    for attribut in ("success", "warning", "danger", "primary", "neutral"):
        ligne = next(l for l in bloc.splitlines() if l.strip().startswith(f"{attribut}:"))
        assert "_config." in ligne, f"{attribut} est recopie en dur : {ligne.strip()}"


def test_les_teintes_de_categorie_restent_propres_a_design_system():
    """economie, moderation, tickets... sont une identite, pas des etats : elles restent."""
    for categorie in ("economy", "moderation", "security", "tickets", "levels", "ai"):
        assert isinstance(getattr(design_system.COLORS, categorie), int)


def test_la_marque_reste_distincte_des_etats():
    assert config.COLOR_BRAND != config.COLOR_INFO
    assert config.COLOR_BRAND == 0x5847EB
