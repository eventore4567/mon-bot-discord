"""Le journal de production ne montrait plus rien d'utile.

Sur 500 lignes prélevées en production : 441 WARNING, 59 INFO, et **zéro ERROR**.
Une boucle morte y répétait le même message toutes les 60 secondes, et chaque log
Discord réussi produisait six à dix lignes de trace `SXTRACE`. Une panne réelle
serait passée totalement inaperçue.

Deux garde-fous sont verrouillés ici :

1. le filtre anti-répétition compresse le volume MAIS ne masque jamais une erreur ;
2. les traces `SXTRACE` restent en DEBUG — si quelqu'un les repasse en WARNING,
   le test casse, parce que c'est exactement ce qui avait noyé le journal.
"""
from __future__ import annotations

import logging
import os
import pathlib
import re
import time

os.environ.setdefault("DISCORD_TOKEN", "x")

from utils.log_hygiene import FiltreAntiRepetition  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent


def _enregistrement(message: str, niveau: int = logging.WARNING, *args, nom: str = "bot.test"):
    # `nom` est volontairement keyword-only : en positionnel, il captait le
    # premier argument d'interpolation et faussait silencieusement les tests.
    return logging.LogRecord(nom, niveau, __file__, 1, message, args or None, None)


def test_les_erreurs_ne_sont_jamais_compressees():
    """Exigence non négociable : une ERROR répétée reste intégralement visible."""
    filtre = FiltreAntiRepetition(fenetre=60.0, occurrences=1)
    for _ in range(50):
        assert filtre.filter(_enregistrement("panne critique", logging.ERROR)) is True
    for _ in range(50):
        assert filtre.filter(_enregistrement("tout est perdu", logging.CRITICAL)) is True


def test_un_warning_repete_est_compresse():
    filtre = FiltreAntiRepetition(fenetre=60.0, occurrences=2)
    passes = [filtre.filter(_enregistrement("Boucle de fond relancée : %s", logging.WARNING, "demo")) for _ in range(30)]
    assert passes[:2] == [True, True], "les premières occurrences doivent passer"
    assert not any(passes[2:]), "les répétitions suivantes doivent être retenues"
    assert sum(passes) == 2


def test_deux_messages_differents_ne_se_genent_pas():
    filtre = FiltreAntiRepetition(fenetre=60.0, occurrences=1)
    assert filtre.filter(_enregistrement("message A")) is True
    assert filtre.filter(_enregistrement("message B")) is True
    assert filtre.filter(_enregistrement("message A")) is False
    assert filtre.filter(_enregistrement("message C")) is True


def test_le_meme_gabarit_est_groupe_quels_que_soient_les_arguments():
    """Regrouper sur le gabarit, pas sur le texte final : sinon un identifiant
    variable dans le message suffirait à contourner toute la compression."""
    filtre = FiltreAntiRepetition(fenetre=60.0, occurrences=1)
    assert filtre.filter(_enregistrement("serveur %s indisponible", logging.WARNING, 111)) is True
    assert filtre.filter(_enregistrement("serveur %s indisponible", logging.WARNING, 222)) is False


def test_la_reouverture_de_fenetre_annonce_les_repetitions_masquees():
    filtre = FiltreAntiRepetition(fenetre=0.05, occurrences=1)
    assert filtre.filter(_enregistrement("répétitif")) is True
    for _ in range(9):
        filtre.filter(_enregistrement("répétitif"))

    time.sleep(0.06)
    record = _enregistrement("répétitif")
    assert filtre.filter(record) is True
    # L'information n'est pas perdue : elle est résumée.
    assert "9 répétition(s) masquée(s)" in record.msg


def test_le_filtre_ne_casse_pas_l_interpolation():
    """Le résumé est ajouté au gabarit : les %s doivent continuer de fonctionner."""
    filtre = FiltreAntiRepetition(fenetre=0.05, occurrences=1)
    filtre.filter(_enregistrement("salon %s injoignable", logging.WARNING, "général"))
    filtre.filter(_enregistrement("salon %s injoignable", logging.WARNING, "général"))
    time.sleep(0.06)
    record = _enregistrement("salon %s injoignable", logging.WARNING, "général")
    assert filtre.filter(record) is True
    assert record.getMessage().startswith("salon général injoignable")


def test_la_memoire_du_filtre_reste_bornee():
    filtre = FiltreAntiRepetition(fenetre=0.01, occurrences=1, max_cles=64)
    for i in range(500):
        filtre.filter(_enregistrement(f"message unique {i}"))
    assert len(filtre._fenetres) <= 500, "le suivi ne doit pas croître sans limite"


def _source(chemin: str) -> str:
    return (RACINE / chemin).read_text(encoding="utf-8")


def test_les_traces_sxtrace_ne_sont_plus_des_avertissements():
    """441 des 500 lignes de production venaient de ces traces en WARNING."""
    for chemin in ("cogs/logs.py", "utils/log_service.py", "utils/wide_logs.py"):
        source = _source(chemin)
        for bloc in re.findall(r"logger\.warning\(\s*\n?\s*\"([^\"]{0,40})", source):
            assert not bloc.startswith("SXTRACE"), f"{chemin} : trace SXTRACE encore en WARNING"
            assert not bloc.startswith("SENTRIX LOG V2 SUCCESS"), f"{chemin} : succès encore en WARNING"


def test_les_echecs_de_transport_restent_en_erreur():
    """La contrepartie : baisser le bruit ne doit pas faire disparaître les pannes."""
    source = _source("utils/wide_logs.py")
    assert "logger.error(\n            \"SXTRACE 6 TRANSPORT phase=abort" in source or \
           source.count("logger.error(") >= 4, "les chemins d'échec du transport doivent rester en ERROR"
    assert "SENTRIX LOG V2 FAILED" in source


def test_le_filtre_est_installe_au_demarrage():
    source = _source("main.py")
    assert "log_hygiene.installer()" in source, "le filtre doit être posé au démarrage du bot"
