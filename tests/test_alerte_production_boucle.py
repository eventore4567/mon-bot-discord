"""12/11/2026 : l'alerte en MP accusait la base, à chaque déploiement.

Capture de l'utilisateur, deux fois de suite, à vingt minutes d'écart :

    ⚠️ SentriX — alerte production
    Base de données lente : execute (1588 ms).
    Release : 3c0408d10435

PostgreSQL n'y était pour rien. Une attente mesurée autour d'un await compte
aussi le temps pendant lequel la boucle d'événements était bloquée par du code
synchrone. Et ces deux attentes-là venaient du DÉMARRAGE, que la boucle
d'alerte n'avait même pas observé : elle venait de s'armer et lisait la
dernière ligne enregistrée.

Deux défauts, donc, et deux corrections : ne plus accuser la base quand le gel
l'explique, et ne jamais rejouer un démarrage comme s'il était un incident.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import production_ops  # noqa: E402


class _Bot:
    """Un bot réduit à ce que lit _health_alert : son état d'observabilité."""

    def __init__(self, slow_db, armees_a):
        self._sentrix_observability_v26 = {
            "errors": [], "slow_commands": [], "slow_db": slow_db,
        }
        self._sentrix_production_ops = {
            "alertes_armees_a": armees_a, "last_backup_ok": True,
        }


def _attente(ms, *, gel_ms=0.0, age=0):
    return {
        "method": "execute", "ms": ms, "boucle_bloquee_ms": gel_ms,
        "query": "INSERT INTO x", "at": int(time.time()) - age,
    }


def test_une_attente_du_demarrage_n_alerte_pas():
    """Le cas exact de la capture : l'alerte venait de s'armer."""
    armement = int(time.time())
    bot = _Bot([_attente(1588.0, gel_ms=1570.0, age=120)], armement)
    assert production_ops._health_alert(bot) == (None, None)


def test_un_gel_pendant_le_service_accuse_la_boucle_pas_la_base():
    bot = _Bot([_attente(1588.0, gel_ms=1570.0)], int(time.time()) - 600)
    cle, detail = production_ops._health_alert(bot)
    assert cle.startswith("loop-blocked:")
    assert "Boucle d'événements bloquée" in detail
    assert "la base n'est pas en cause" in detail
    assert "Base de données lente" not in detail


def test_une_vraie_lenteur_de_base_alerte_toujours():
    """Sans gel de boucle, l'attente EST imputable à la base : on le dit."""
    bot = _Bot([_attente(1588.0, gel_ms=0.0)], int(time.time()) - 600)
    cle, detail = production_ops._health_alert(bot)
    assert cle == "slow-db:execute"
    assert "Base de données lente" in detail


def test_un_gel_marginal_ne_disculpe_pas_la_base():
    """Un gel de 100 ms n'explique pas une attente de 1,5 s : la base reste en cause."""
    bot = _Bot([_attente(1588.0, gel_ms=100.0)], int(time.time()) - 600)
    cle, _detail = production_ops._health_alert(bot)
    assert cle == "slow-db:execute"


def test_une_attente_sous_le_seuil_n_alerte_pas():
    bot = _Bot([_attente(200.0)], int(time.time()) - 600)
    assert production_ops._health_alert(bot) == (None, None)
