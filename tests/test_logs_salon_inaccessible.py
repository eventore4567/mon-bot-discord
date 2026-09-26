"""Un salon de logs devenu inaccessible ne doit plus inonder les journaux.

Relevé en production le 2026-09-26 : deux salons répondaient 403 « Missing
Access » à chaque évènement journalisable, et chaque échec imprimait une trace
de pile complète. Le garde ``log_service.validate_channel`` passe pourtant
avant l'envoi — il lit ``channel.permissions_for(me)``, donc le cache local,
que Discord contredit quand les permissions ont changé.

Un 403 ne se résout pas au message suivant. Ce fichier verrouille le
comportement attendu : une seule ligne lisible, plus d'essais pendant un
moment, et la route coupée si l'échec persiste.
"""
from __future__ import annotations

import logging
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from utils import log_service, wide_logs


class _Refus(discord.HTTPException):
    def __init__(self, status: int, code: int = 50001, text: str = "Missing Access"):
        self.status = status
        self.code = code
        self.text = text


@pytest.fixture(autouse=True)
def _table_propre():
    wide_logs._SALONS_INACCESSIBLES.clear()
    wide_logs._ECHECS_PERMANENTS.clear()
    yield
    wide_logs._SALONS_INACCESSIBLES.clear()
    wide_logs._ECHECS_PERMANENTS.clear()


def test_un_salon_inconnu_n_est_pas_en_quarantaine():
    assert wide_logs.salon_inaccessible(999) is False
    assert wide_logs.salon_inaccessible(None) is False


@pytest.mark.parametrize("status", [403, 404])
def test_403_et_404_mettent_le_salon_en_quarantaine(status):
    """Ni l'un ni l'autre ne se corrige tout seul au prochain évènement."""
    assert wide_logs._est_definitif(_Refus(status)) is True
    wide_logs._mettre_en_quarantaine(42, _Refus(status))
    assert wide_logs.salon_inaccessible(42) is True


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_les_pannes_passageres_ne_mettent_rien_en_quarantaine(status):
    """Une limite de débit ou une panne Discord se rejoue : la garder en
    quarantaine ferait perdre des logs pour rien."""
    assert wide_logs._est_definitif(_Refus(status)) is False


def test_une_seule_ligne_est_journalisee_quels_que_soient_les_echecs(caplog):
    """C'était le défaut : une trace complète par évènement, indéfiniment."""
    with caplog.at_level(logging.ERROR, logger=wide_logs.logger.name):
        for _ in range(5):
            wide_logs._mettre_en_quarantaine(77, _Refus(403))
    lignes = [r for r in caplog.records if "Logs suspendus" in r.getMessage()]
    assert len(lignes) == 1, f"{len(lignes)} lignes au lieu d'une"
    message = lignes[0].getMessage()
    assert "77" in message, "la ligne doit nommer le salon"
    assert "setup" in message, "la ligne doit dire comment réparer"
    assert "Traceback" not in message


def test_les_echecs_sont_comptes_pour_decider_de_couper():
    for attendu in (1, 2, 3):
        wide_logs._mettre_en_quarantaine(55, _Refus(403))
        assert wide_logs.echecs_permanents(55) == attendu


def test_la_quarantaine_expire_d_elle_meme():
    """Si un administrateur rétablit l'accès, les logs repartent sans geste."""
    assert wide_logs.QUARANTAINE_SECONDES > 0
    wide_logs._mettre_en_quarantaine(88, _Refus(403))
    wide_logs._SALONS_INACCESSIBLES[88] = 0.0   # échéance dans le passé
    assert wide_logs.salon_inaccessible(88) is False


def test_reconfigurer_le_salon_leve_la_quarantaine():
    wide_logs._mettre_en_quarantaine(91, _Refus(403))
    wide_logs.oublier_salon(91)
    assert wide_logs.salon_inaccessible(91) is False
    assert wide_logs.echecs_permanents(91) == 0


def test_le_seuil_de_coupure_laisse_place_a_un_incident_isole():
    """Un 403 unique peut venir d'une permission retirée puis remise ; trois
    de suite, non."""
    assert log_service.ECHECS_AVANT_COUPURE >= 2


def test_la_route_saute_un_salon_en_quarantaine_avant_de_construire():
    """Reconstruire la bannière et la vue pour se faire refuser coûte cher."""
    import inspect

    source = inspect.getsource(log_service.send_log)
    position_garde = source.index("salon_inaccessible")
    position_envoi = source.index("send_wide_log(")
    assert position_garde < position_envoi


def test_send_wide_log_sort_avant_tout_travail_si_le_salon_est_puni():
    import inspect

    source = inspect.getsource(wide_logs.send_wide_log)
    debut = source.index("salon_inaccessible")
    assert debut < source.index("log_runtime_capabilities()")
