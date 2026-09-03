"""La page "Rôles — Règles & CAPTCHA" du setup (cogs/control_center_v3.py) traverse une
douzaine de couches de wrappers avant d'atteindre Discord (setup_v2_ui -> setup_oxyde_v69
-> setup_polish_v70 -> security_verification_v71 -> ... -> control_center_v3_ui_fix). Deux
de ces couches, mesurées en instrumentant discord.Embed.add_field() sur un boot complet,
plafonnent silencieusement le nombre de champs "propres" qu'une page peut ajouter :
setup_polish_v70.py::_add_details (6, avant tri du champ "Module" partagé) ET, PLUS
contraignant, setup_oxyde_v69.py::_build_page -> _copy_matching_fields(limit=4). Une page
qui ajoute un 5e champ ne lève AUCUNE erreur : ce champ disparaît juste, silencieusement,
avant d'atteindre Discord -- c'est exactement ce qui est arrivé une première fois avec le
champ "Vérification technique" pendant le développement du CAPTCHA de vérification.

Ce test ne peut pas rejouer toute la chaîne de wrappers (elle n'existe qu'après un boot
complet des 45+ extensions), mais verrouille la contrainte connue : la page ajoute au plus
4 champs "propres" (hors État/Configuration/Module/Permissions, ajoutés ailleurs et déjà
comptés à part par ces couches partagées)."""
from __future__ import annotations

import ast
import os
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "x")

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "cogs" / "control_center_v3.py").read_text(encoding="utf-8")


def _roles_rules_embed_branch_source() -> str:
    tree = ast.parse(SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_v3_build_embed":
            return ast.get_source_segment(SOURCE, node)
    raise AssertionError("_v3_build_embed introuvable dans control_center_v3.py")


def _embed_fields_branch(function_source: str) -> str:
    """`elif self.category == "roles" and subpage == "rules":` apparaît DEUX fois dans
    _v3_build_embed (une fois pour le titre de page, une fois -- plus loin -- pour les
    champs). On ancre donc la recherche après le premier `panel = embeds.brand(...)`,
    qui n'apparaît qu'une fois, juste après la section titre."""
    anchor = function_source.index("panel = embeds.brand(f\"SentriX — {page_title}\"")
    start = function_source.index('elif self.category == "roles" and subpage == "rules":', anchor)
    end = function_source.index('elif self.category == "roles":', start)
    return function_source[start:end]


def test_roles_rules_page_stays_within_the_shared_four_field_budget():
    branch = _embed_fields_branch(_roles_rules_embed_branch_source())
    count = branch.count(".add_field(")
    assert count <= 4, (
        f"La page Rôles/Règles ajoute {count} champ(s) propres : au-delà de 4, "
        "setup_oxyde_v69.py::_build_page (limit=4) en tronque silencieusement sans erreur. "
        "Fusionnez le contenu dans un champ existant plutôt que d'en ajouter un nouveau."
    )


def test_role_grant_problem_is_merged_into_an_existing_field_not_a_new_one():
    # Confirme que le diagnostic de faisabilité (role_grant_problem) est toujours
    # présent quelque part dans la page, mais fusionné -- pas dans son propre champ,
    # justement pour rester sous la limite de 4.
    branch = _embed_fields_branch(_roles_rules_embed_branch_source())
    assert "role_grant_problem(" in branch
    assert 'name="Vérification technique"' not in branch
