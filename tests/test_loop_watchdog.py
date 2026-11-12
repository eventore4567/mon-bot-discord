"""utils/loop_watchdog : un blocage de la boucle est signalé AVEC le code fautif."""
from __future__ import annotations

import asyncio
import logging
import os
import time

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from pathlib import Path  # noqa: E402

from utils import loop_watchdog  # noqa: E402


def _calcul_bloquant():
    time.sleep(1.6)  # du code synchrone dans une coroutine : la boucle est figée


def test_un_blocage_est_signale_avec_la_fonction_fautive(caplog):
    async def scenario():
        loop_watchdog.demarrer(asyncio.get_running_loop())
        await asyncio.sleep(0.6)
        _calcul_bloquant()
        await asyncio.sleep(0.3)
        loop_watchdog.arreter()

    with caplog.at_level(logging.WARNING, logger="bot.loop-watchdog"):
        asyncio.run(scenario())
    messages = [r.getMessage() for r in caplog.records if r.name == "bot.loop-watchdog"]
    assert any("Boucle bloquée" in m and "_calcul_bloquant" in m for m in messages), messages


def test_une_boucle_fluide_ne_signale_rien(caplog):
    async def scenario():
        loop_watchdog.demarrer(asyncio.get_running_loop())
        for _ in range(8):
            await asyncio.sleep(0.2)
        loop_watchdog.arreter()

    with caplog.at_level(logging.WARNING, logger="bot.loop-watchdog"):
        asyncio.run(scenario())
    assert not [r for r in caplog.records if r.name == "bot.loop-watchdog" and r.levelno >= logging.WARNING]


def test_ancien_thread_ignore_une_nouvelle_generation(caplog):
    """Une vieille surveillance n'a pas le droit d'alerter au cycle suivant."""
    import threading

    saved = dict(loop_watchdog._etat)
    try:
        previous_generation = int(saved["generation"])
        loop_watchdog._etat.update({
            "generation": previous_generation + 1,
            "actif": True,
            "dernier": time.monotonic() - 10,
        })
        with caplog.at_level(logging.WARNING, logger="bot.loop-watchdog"):
            loop_watchdog._surveiller(threading.get_ident(), previous_generation)
        assert not [record for record in caplog.records if record.name == "bot.loop-watchdog"]
    finally:
        loop_watchdog._etat.update(saved)


def test_ancien_battement_ne_modifie_pas_l_etat_d_un_nouveau_cycle():
    saved = dict(loop_watchdog._etat)
    try:
        previous_generation = int(saved["generation"])
        loop_watchdog._etat.update({
            "generation": previous_generation + 1,
            "actif": True,
            "dernier": 123.0,
        })
        asyncio.run(loop_watchdog._battre(previous_generation))
        assert loop_watchdog._etat["dernier"] == 123.0
    finally:
        loop_watchdog._etat.update(saved)


# ---------------------------------------------------------------------------
# 11/11/2026 : le détecteur existait, mais son seuil d'une seconde laissait
# passer les gels de 400 à 900 ms — qui ressortaient alors en « requête DB
# lente » et faisaient accuser PostgreSQL, innocent. Preuve en production :
# deux requêtes sur deux tables différentes à 1048.8 ms et 1048.4 ms, reparties
# ensemble parce que la boucle, elle, était bloquée.
# ---------------------------------------------------------------------------
def test_le_seuil_attrape_les_gels_de_moins_d_une_seconde():
    assert loop_watchdog.SEUIL_S <= 0.5, (
        "un gel de 400 ms est déjà un gel : pendant ce temps aucune commande, "
        "aucune règle AutoMod, aucun battement n'avance"
    )


def test_sans_detecteur_actif_le_retard_est_nul():
    """Un audit hors ligne n'a pas de boucle : il doit lire « aucun gel »,
    pas « gelée depuis toujours », sinon l'observabilité accuse un innocent."""
    loop_watchdog.arreter()
    assert loop_watchdog.retard_de_la_boucle() == 0.0


def test_le_retard_grandit_quand_la_boucle_ne_bat_plus():
    import time as _time

    loop_watchdog._etat["actif"] = True
    loop_watchdog._etat["dernier"] = _time.monotonic() - 1.0
    try:
        assert loop_watchdog.retard_de_la_boucle() > 0.5
    finally:
        loop_watchdog.arreter()


# ---------------------------------------------------------------------------
# 12/11/2026 : le détecteur démarrait trop tard pour voir ce qui compte.
# Il attendait que le bot soit prêt PLUS 30 secondes, alors que les plus gros
# gels sont ceux du démarrage. Mesuré le 11/11 en production : un gel de 1,28 s
# à 23:40:38, détecteur actif seulement à 23:41:08. Il est passé inaperçu, et
# l'observabilité, lisant un retard nul, l'a imputé à PostgreSQL.
# ---------------------------------------------------------------------------
def test_le_detecteur_demarre_des_le_chargement_du_cog():
    import inspect

    from cogs.loop_watchdog_cog import LoopWatchdog

    source = inspect.getsource(LoopWatchdog.cog_load)
    assert "demarrer" in source, "cog_load doit démarrer le détecteur lui-même"
    assert "is_ready" not in source, "attendre d'être prêt laisse passer les gels du démarrage"
    assert "sleep" not in source, "une marge après le démarrage rate exactement ce qu'on cherche"


def test_un_meme_gel_ne_produit_qu_une_ligne():
    """Démarrer tôt n'a de sens que si un démarrage chargé ne noie pas le journal."""
    import inspect

    source = inspect.getsource(loop_watchdog._surveiller)
    assert "signale" in source, "le détecteur doit se taire tant que le même gel dure"


# ---------------------------------------------------------------------------
# 12/11/2026 : le détecteur tournait, et PostgreSQL était ENCORE accusé.
#
#   17:36:57  Détecteur de blocage de boucle actif dès le chargement
#   17:39:50  Requête DB lente : fetchall 1411.8ms — feature_suite_items
#   17:39:50  Requête DB lente : fetchall 1411.6ms — platform_role_menus
#
# La signature jumelle d'un gel, trois minutes APRÈS le démarrage du détecteur.
# La faute était dans la mesure : interroger le retard une fois la boucle
# repartie renvoie toujours zéro, puisque le battement vient d'être rafraîchi.
# Il fallait demander « y a-t-il eu un gel pendant cette attente ? ».
# ---------------------------------------------------------------------------
def test_un_gel_termine_reste_imputable_apres_coup():
    import time as _time

    loop_watchdog._etat["actif"] = True
    try:
        debut = _time.monotonic()
        loop_watchdog._etat["dernier_gel_fin"] = debut + 0.1
        loop_watchdog._etat["dernier_gel_duree"] = 1.4

        # La boucle est repartie : le retard instantané ne dit plus rien...
        loop_watchdog._etat["dernier"] = _time.monotonic()
        assert loop_watchdog.retard_de_la_boucle() < 0.1
        # ...mais le gel qui a chevauché l'attente reste imputable.
        assert loop_watchdog.gel_pendant(debut) == 1.4
    finally:
        loop_watchdog.arreter()


def test_un_gel_anterieur_n_est_pas_impute_a_une_attente_posterieure():
    import time as _time

    loop_watchdog._etat["actif"] = True
    try:
        loop_watchdog._etat["dernier_gel_fin"] = _time.monotonic() - 10.0
        loop_watchdog._etat["dernier_gel_duree"] = 2.0
        assert loop_watchdog.gel_pendant(_time.monotonic()) == 0.0
    finally:
        loop_watchdog.arreter()


def test_sans_detecteur_aucun_gel_n_est_impute():
    loop_watchdog.arreter()
    assert loop_watchdog.gel_pendant(0.0) == 0.0


def test_la_generation_des_emojis_ne_bloque_plus_la_boucle():
    """Le détecteur l'a nommée au premier démarrage qu'il surveillait vraiment :

        Boucle bloquée depuis 0.5 s — tools/generer_emojis_application_v2.py:96
          generer ← utils/sentrix_emojis.py:460 synchroniser

    Le générateur de variantes colorées, juste en dessous, passait déjà par un
    fil : la leçon avait été tirée pour l'un et oubliée pour l'autre.
    """
    source = (Path(__file__).resolve().parents[1] / "utils" / "sentrix_emojis.py").read_text(encoding="utf-8")
    assert "await asyncio.to_thread(generer, DOSSIER)" in source
    assert "resultat = generer(DOSSIER)" not in source
