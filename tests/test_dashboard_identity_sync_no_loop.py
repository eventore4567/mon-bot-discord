"""syncDiscordIdentity() dans dashboard_no_decorative_icons.py bouclait à l'infini.

Reproduit et confirmé dans une vraie page (navigateur, pas seulement lecture de
code) : le MutationObserver du module observe #userName/#userAvatar ; avant le
correctif, syncDiscordIdentity() réécrivait toujours userName.textContent après
avoir appelé /api/me, ce qui déclenchait l'observer, qui relançait
syncDiscordIdentity(), indéfiniment. Une page de reproduction isolée (extrait
réel de CLEAN_JS, /api/me simulé) est passée de 164 375 appels en 4 secondes à
5 appels bornés une fois le correctif appliqué. Les journaux Railway confirment
le même client (105.158.237.213) appelant /api/me toutes les 300-900 ms pendant
plus d'une minute continue, alors que chaque réponse ne prenait que 55-70 ms —
la preuve que le client s'auto-relançait, pas qu'il retentait un endpoint lent.

Ce test ne rejoue pas de navigateur : il vérifie que la garde qui casse la
boucle est toujours présente dans le JS embarqué, pour empêcher qu'un futur
« polish » la retire par inadvertance comme l'a fait le commit 3034f5a en
l'introduisant.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "x")

from web.dashboard_no_decorative_icons import CLEAN_JS  # noqa: E402


def test_userName_n_est_reecrit_que_si_la_valeur_change():
    assert 'userName.textContent !== user.username' in CLEAN_JS, (
        "sans cette garde, chaque appel à syncDiscordIdentity() réécrit "
        "userName.textContent même sans changement, ce qui redéclenche le "
        "MutationObserver et relance /api/me à l'infini"
    )


def test_userAvatar_garde_deja_sa_protection_contre_la_reecriture():
    assert 'current.getAttribute("src") !== user.avatar_url' in CLEAN_JS, (
        "l'avatar avait déjà cette garde ; si elle disparaît, la même boucle "
        "infinie réapparaît côté photo de profil"
    )


if __name__ == "__main__":
    import unittest

    unittest.main()
