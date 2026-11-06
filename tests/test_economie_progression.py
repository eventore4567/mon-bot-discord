"""07/11/2026 : « le système d'économie est nul » — métiers, promotions, série, intérêts."""
from __future__ import annotations

import os
import random
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import economy_progress as p  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]


def test_la_carriere_monte_avec_les_travaux():
    assert p.metier_pour(0).nom == "Stagiaire"
    assert p.metier_pour(10).nom == "Employé"
    assert p.metier_pour(500).nom == "PDG"
    assert p.prochain_metier(500) is None
    salaires = [m.salaire_max for m in p.METIERS]
    assert salaires == sorted(salaires)                      # chaque promotion paie plus


def test_la_progression_est_lisible():
    assert p.progression_metier(3) == "▰▰▰▱▱▱▱▱▱▱ 3/10 → 💼 Employé"
    assert "Sommet" in p.progression_metier(1000)


def test_le_salaire_reste_dans_la_fourchette_du_metier_hors_evenement():
    alea = random.Random(1)
    for _ in range(200):
        salaire, evenement, metier, tache = p.tirer_salaire(40, alea)
        if evenement is None:
            assert metier.salaire_min <= salaire <= metier.salaire_max
        assert tache in metier.taches


def test_interets_et_serie():
    assert p.interets(0) == 0 and p.interets(10_000) == 100 and p.interets(10**9) == p.INTERET_MAX
    assert p.bonus_serie(1) == 25 and p.bonus_serie(7) == 7 * 25 + 500 and p.bonus_serie(30) == 250


def test_la_serie_s_affiche_dans_le_panneau_du_daily():
    eco = (RACINE / "cogs" / "economy.py").read_text(encoding="utf-8")
    v3 = (RACINE / "cogs" / "community_v3.py").read_text(encoding="utf-8")
    assert "community_v3.register_daily_claim(self.bot, ctx.guild.id, ctx.author.id)" in eco
    assert "Streak quotidien" not in v3                     # plus de second message
    assert "progression.tirer_salaire(travaux)" in eco
