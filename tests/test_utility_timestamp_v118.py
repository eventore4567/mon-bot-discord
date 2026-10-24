"""Régressions des utilitaires public SentriX."""
import datetime

import pytest

from cogs.utility import Utility, _discord_timestamp


def test_timestamp_formats_fr_iso_et_fuseaux():
    attendu = int(datetime.datetime(2027, 1, 1, 18, 30, tzinfo=datetime.timezone.utc).timestamp())
    assert _discord_timestamp("01/01/2027", "18:30", "UTC") == attendu
    assert _discord_timestamp("2027-01-01 18:30", fuseau="UTC") == attendu
    assert _discord_timestamp("01-01-2027", "19:30", "Europe/Paris") == attendu


def test_timestamp_rejette_heures_impossibles_et_fuseaux_invalides():
    with pytest.raises(ValueError, match="n'existe pas"):
        _discord_timestamp("29/03/2026", "02:30", "Europe/Paris")
    with pytest.raises(ValueError, match="Fuseau invalide"):
        _discord_timestamp("01/01/2027", "18:30", "Monde/Inconnu")
    with pytest.raises(ValueError, match="Format invalide"):
        _discord_timestamp("demain", "10:00", "UTC")


def test_timestamp_maintenant():
    maintenant = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    assert abs(_discord_timestamp("maintenant") - maintenant) <= 2


def test_trois_utilitaires_exposes_sans_doublons():
    assert Utility.translate.name == "translate"
    assert Utility.timestamp.name == "timestamp"
    assert Utility.userinfo.name == "userinfo"
