"""+sysinfo ne doit pas afficher « None ms » à un membre.

Mesuré par tools/command_sweep.py le 2026-10-14 — seule réponse du
balayage, sur 807 commandes, à laisser fuir un terme technique :

    ## SentriX V2.1 — État UNAVAILABLE
    **Discord** · Indisponible · None ms

``.get(cle, defaut)`` ne sert le défaut que si la clé est ABSENTE. Ici
elle existe avec la valeur None dès que le bot n'est pas prêt, puisque
``helpers.latence_ms`` renvoie None — pendant un démarrage, et en
permanence sur l'instance qui ne détient pas le bail HA.

Même famille que le « 0 commandes » de /commands : afficher une valeur
vide de sens plutôt que dire qu'on ne sait pas.
"""
from __future__ import annotations

import inspect
import os
import re

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import sentrix_v21


def _source_systemstatus() -> str:
    commande = sentrix_v21.SentriXV21.systemstatus
    return inspect.getsource(getattr(commande, "callback", commande))


def test_une_latence_inconnue_est_nommee_et_pas_rendue_brute():
    src = _source_systemstatus()
    assert "latence inconnue" in src
    assert "get('latency_ms', '?')" not in src
    assert 'get("latency_ms", "?")' not in src


def test_une_latence_de_zero_reste_affichee_comme_une_mesure():
    """0 ms est une latence valide : tester None, pas la vérité de la valeur."""
    src = _source_systemstatus()
    assert 'get("latency_ms") is None' in src, (
        "un test de vérité transformerait 0 ms en « inconnue »"
    )


def test_aucune_autre_valeur_optionnelle_n_est_rendue_avec_un_defaut_trompeur():
    """Garde de famille : `.get(cle, defaut)` ne rattrape jamais un None.

    Le défaut d'un ``.get`` ne sert que pour une clé absente. L'utiliser
    pour couvrir une valeur qui peut légitimement valoir None affiche
    « None » au membre, comme ici.
    """
    src = _source_systemstatus()
    fautifs = re.findall(r"\.get\(\s*['\"](\w*latency\w*|\w*latence\w*)['\"]\s*,", src)
    assert not fautifs, f"défaut trompeur sur : {fautifs}"
