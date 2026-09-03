"""cogs.v17_ai_economy_games et cogs.sentrix_v21 enregistraient CHACUN une commande
+achievements. add_cog() abandonne TOUT le cog des la premiere collision de nom
(CommandRegistrationError), donc SentriXV21 (marche, defis...) et, en cascade
(un seul bloc try/except commun dans _bootstrap_sentrix_v2), SentriXV22 et
SentriXAccessibility echouaient a charger silencieusement a CHAQUE demarrage.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "x")

from cogs import sentrix_v21, v17_ai_economy_games  # noqa: E402


def _hybrid_command_names(module, cls_name: str) -> set[str]:
    cls = getattr(module, cls_name)
    names = set()
    for attr in vars(cls).values():
        name = getattr(attr, "name", None)
        if name and hasattr(attr, "callback"):
            names.add(name)
    return names


def test_sentrix_v21_n_utilise_plus_le_nom_achievements():
    assert "achievements-v21" in sentrix_v21.V21_PUBLIC_COMMANDS
    assert "achievements" not in sentrix_v21.V21_PUBLIC_COMMANDS


def test_aucune_collision_de_nom_entre_v17_et_v21():
    noms_v17 = _hybrid_command_names(v17_ai_economy_games, "V17AIEconomyGames")
    noms_v21 = _hybrid_command_names(sentrix_v21, "SentriXV21")
    assert "achievements" in noms_v17, "le test suppose que v17 garde +achievements"
    collision = noms_v17 & noms_v21
    assert not collision, f"Collision de nom de commande entre v17 et v21 : {collision}"
