"""Discord plafonne TOUT TextInput de modal a 4000 caracteres.

C'est une limite du COMPOSANT, distincte de la limite du champ Discord qu'il
alimente : une description d'embed accepte jusqu'a 4096 caracteres, mais le
TextInput de modal qui la saisit ne peut jamais depasser 4000. Utiliser
MAX_DESCRIPTION (4096) comme max_length du modal faisait planter +embed a
chaque ouverture de "Modifier le texte" : HTTPException 400, error 50035,
« max_length should be less than or equal to 4000 ».
"""
from __future__ import annotations

import ast
import os
import pathlib

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = pathlib.Path(__file__).resolve().parent.parent


def test_max_description_input_respecte_la_limite_discord():
    from cogs.embed_builder import MAX_DESCRIPTION_INPUT

    assert MAX_DESCRIPTION_INPUT <= 4000


def test_aucun_textinput_ne_depasse_4000_caracteres():
    """Balaie tout le dépôt : la même erreur ailleurs planterait le modal
    concerné exactement de la même façon."""
    constantes: dict[str, int] = {}
    trouvailles: list[str] = []

    for chemin in sorted(RACINE.glob("cogs/*.py")) + sorted(RACINE.glob("utils/*.py")):
        try:
            arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for n in ast.walk(arbre):
            if isinstance(n, ast.Assign) and len(n.targets) == 1:
                cible = n.targets[0]
                if isinstance(cible, ast.Name) and isinstance(n.value, ast.Constant):
                    if isinstance(n.value.value, int):
                        constantes[cible.id] = n.value.value

        for n in ast.walk(arbre):
            if not isinstance(n, ast.Call) or not ast.unparse(n.func).endswith("TextInput"):
                continue
            for k in n.keywords:
                if k.arg != "max_length":
                    continue
                valeur = None
                if isinstance(k.value, ast.Constant) and isinstance(k.value.value, int):
                    valeur = k.value.value
                elif isinstance(k.value, ast.Name):
                    valeur = constantes.get(k.value.id)
                if valeur is not None and valeur > 4000:
                    trouvailles.append(
                        f"{chemin}:{n.lineno} max_length={ast.unparse(k.value)} ({valeur})"
                    )

    assert not trouvailles, "\n".join(trouvailles)
