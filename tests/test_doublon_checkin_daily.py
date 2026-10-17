"""+checkin faisait doublon avec +daily, et payait deux fois.

Relevé le 2026-10-17 :

- ``+daily`` verse ``DAILY_AMOUNT`` (200) via ``claim_timed_reward`` sur la
  clé ``last_daily`` ;
- ``+checkin`` versait 50 à 150 via une table séparée ``v2_daily_claims``,
  avec son propre cooldown.

Deux tables, deux cooldowns, deux commandes dont les descriptions se
lisaient à l'identique : « Récupérer votre récompense quotidienne » et
« Récupérer votre récompense de présence quotidienne ». Un membre au
courant encaissait 250 à 350 pièces par jour, les autres 200.

Les journaux d'usage de la production tranchent : ``checkin`` figure dans
« USAGE JAMAIS DEPUIS LE DÉBUT » sur les 29 serveurs, ``daily`` non.

La commande part, la fonctionnalité reste : ``claim_checkin`` est appelée
par le bouton du panneau V2, et la série alimente toujours ``+progress``
et ``+profilecard``.
"""
from __future__ import annotations

import inspect
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import sentrix_v2


def test_la_commande_checkin_n_existe_plus():
    assert not hasattr(sentrix_v2.SentriXV2, "checkin"), (
        "+checkin est de retour : vérifier qu'elle ne refait pas doublon avec +daily"
    )
    assert 'name="checkin"' not in inspect.getsource(sentrix_v2)


def test_la_fonctionnalite_de_serie_est_conservee():
    """Retirer la commande ne doit pas retirer le système de présence."""
    assert hasattr(sentrix_v2.SentriXV2, "claim_checkin")
    assert hasattr(sentrix_v2.SentriXV2, "checkin_row")


def test_le_bouton_du_panneau_appelle_toujours_la_serie():
    src = inspect.getsource(sentrix_v2)
    assert "claim_checkin(view.guild, view.member)" in src, (
        "le bouton était le seul usage réel : il doit survivre au retrait de la commande"
    )


def test_le_profil_lit_toujours_la_serie():
    from cogs import sentrix_v21

    src = inspect.getsource(sentrix_v21)
    assert "v2_daily_checkins" in src
    assert "checkin_row" in src


def test_checkin_ne_traine_plus_dans_les_catalogues():
    """Une commande retirée qui reste annoncée produit un nom mort dans l'aide."""
    from utils import access_matrix, slash_catalog

    assert '"checkin"' not in inspect.getsource(slash_catalog)
    assert '"checkin"' not in inspect.getsource(access_matrix)


def test_il_ne_reste_qu_une_recompense_quotidienne():
    from cogs import economy

    src = inspect.getsource(economy)
    assert 'name="daily"' in src, "+daily doit rester la seule récompense quotidienne"
