"""11/11/2026 : « requête DB lente » accusait PostgreSQL à tort.

La production signalait des UPSERT d'une seule ligne, sur clé primaire, à 300 ms
voire 1 s. La preuve de l'innocence de la base tenait en deux lignes voisines :

    Requête DB lente : execute 1048.8ms — INSERT INTO message_counts ...
    Requête DB lente : execute 1048.4ms — UPDATE engagement_members ...

Deux requêtes, deux tables, 0,4 ms d'écart : la boucle d'événements était gelée
et elles sont reparties ensemble. Ces tests vérifient qu'on détecte ce gel, et
surtout qu'on NOMME la fonction qui l'a causé — sinon on cherche à l'aveugle.
"""
from __future__ import annotations

import asyncio
import os
import time

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils.boucle_sentinelle import Sentinelle  # noqa: E402


def fonction_qui_bloque_la_boucle(duree: float) -> None:
    """Du code synchrone ordinaire : pendant ce temps, RIEN d'autre n'avance."""
    time.sleep(duree)


@pytest.mark.asyncio
async def test_une_boucle_qui_repond_n_est_jamais_signalee():
    sentinelle = Sentinelle()
    for _ in range(5):
        sentinelle.battre()
        await asyncio.sleep(0.01)
    assert sentinelle.retard() < 0.1
    assert sentinelle.gels == 0


@pytest.mark.asyncio
async def test_un_blocage_est_mesure():
    sentinelle = Sentinelle()
    sentinelle.battre()
    fonction_qui_bloque_la_boucle(0.3)
    # La boucle n'a pas pu battre pendant tout ce temps : le retard le dit.
    assert sentinelle.retard() >= 0.2


def test_le_coupable_est_nomme_et_pas_asyncio():
    """Sans le nom du coupable, on sait qu'il y a un gel mais pas où le corriger."""
    sentinelle = Sentinelle()
    pile = [
        '  File "/usr/lib/python3.13/asyncio/base_events.py", line 1, in run_forever\n',
        '  File "/app/cogs/un_module.py", line 42, in genere_une_image\n',
        '  File "/usr/lib/python3.13/asyncio/events.py", line 9, in _run\n',
        '  File "/usr/lib/python3.13/threading.py", line 3, in wait\n',
    ]
    coupable = sentinelle.coupable_probable(pile)
    assert "un_module.py" in coupable and "genere_une_image" in coupable
    assert "asyncio" not in coupable and "threading" not in coupable


def test_une_pile_sans_code_sentrix_ne_fait_pas_tomber_la_sentinelle():
    sentinelle = Sentinelle()
    assert sentinelle.coupable_probable([]) == "pile indisponible"
    asyncio_seul = ['  File "/usr/lib/python3.13/asyncio/base_events.py", line 1, in run\n']
    assert sentinelle.coupable_probable(asyncio_seul)


def test_un_meme_coupable_ne_remplit_pas_les_journaux(caplog):
    """Un blocage répété doit rester lisible : compté à chaque fois, dit une fois."""
    sentinelle = Sentinelle()
    with caplog.at_level("WARNING", logger="bot.boucle"):
        for _ in range(5):
            sentinelle._signaler(0.5)
    assert sentinelle.gels == 5
    assert len([r for r in caplog.records if "Boucle bloquée" in r.message]) == 1


def test_le_fil_attrape_un_vrai_blocage():
    """Le test qui compte : un vrai gel, un vrai fil, un vrai rapport."""
    sentinelle = Sentinelle()
    sentinelle.demarrer()
    try:
        sentinelle.battre()
        fonction_qui_bloque_la_boucle(0.8)
        sentinelle.battre()
        time.sleep(0.2)  # laisser le fil publier son constat
    finally:
        sentinelle.arreter()

    assert sentinelle.gels >= 1, "un gel de 800 ms doit être vu"
    assert sentinelle.pire_gel >= 0.4
    assert sentinelle.etat()["coupables"], "le coupable doit être nommé"


def test_l_etat_reste_lisible_sans_aucun_gel():
    etat = Sentinelle().etat()
    assert etat["gels"] == 0 and etat["pire_gel_ms"] == 0.0 and etat["coupables"] == []


def test_sans_boucle_a_surveiller_le_retard_reste_nul():
    """Un audit hors ligne n'a pas de boucle : il ne doit pas lire « gelée depuis
    toujours » et faire accuser PostgreSQL à la place du vrai coupable."""
    sentinelle = Sentinelle()
    time.sleep(0.2)
    assert sentinelle.retard() == 0.0

    sentinelle.battre()
    time.sleep(0.2)
    assert sentinelle.retard() > 0.0, "une fois la surveillance commencée, le gel compte"
