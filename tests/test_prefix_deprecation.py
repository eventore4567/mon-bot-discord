"""Avis de retrait des commandes « + ».

28/10/2026 : SentriX passe à 100 % « / ». 29/10/2026 : message séparé, en gras,
avec mention, au plus deux fois par jour et par personne, compteur persistant,
sans date fixée.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import prefix_deprecation as avis  # noqa: E402


class _Db:
    """Base SQLite réelle (même SQL qu'en production), interface de bot.db."""

    def __init__(self, path=":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

    async def execute(self, sql, params=()):
        self.conn.execute(sql, params)
        self.conn.commit()

    async def fetchone(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()


def _db(path=":memory:"):
    db = _Db(path)
    asyncio.run(db.execute(avis.TABLE))
    return db


def test_message_demande_en_gras_avec_mention_et_sans_date():
    texte = avis.texte_avis(SimpleNamespace(mention="<@42>"))
    assert texte == ("**<@42> Les commandes avec le préfixe `+` seront bientôt supprimées. "
                     "Nous te conseillons de passer aux commandes `/` dès maintenant.**")
    assert "novembre" not in texte and "<t:" not in texte


def test_deux_rappels_par_jour_au_plus_toutes_commandes_confondues():
    db = _db()
    t = 1_790_000_000.0
    assert asyncio.run(avis.reserver(db, 7, t)) is True
    assert asyncio.run(avis.reserver(db, 7, t + 60)) is False, "écart minimum entre deux rappels"
    assert asyncio.run(avis.reserver(db, 7, t + avis.ECART_MIN_S)) is True
    assert asyncio.run(avis.reserver(db, 7, t + 3 * avis.ECART_MIN_S)) is False, "troisième rappel du jour"
    assert asyncio.run(avis.reserver(db, 8, t + 60)) is True, "une autre personne a son propre compteur"
    assert asyncio.run(avis.reserver(db, 7, t + 86_400)) is True, "nouveau jour"


def test_le_compteur_survit_a_un_redemarrage(tmp_path):
    chemin = str(tmp_path / "avis.db")
    t = 1_790_000_000.0
    db = _db(chemin)
    assert asyncio.run(avis.reserver(db, 7, t)) is True
    assert asyncio.run(avis.reserver(db, 7, t + avis.ECART_MIN_S)) is True
    avis._verrous.clear()
    relance = _Db(chemin)
    assert asyncio.run(avis.reserver(relance, 7, t + 3 * avis.ECART_MIN_S)) is False


def test_deux_commandes_simultanees_ne_donnent_qu_un_rappel():
    db = _db()

    async def deux():
        return await asyncio.gather(avis.reserver(db, 9, 1_790_000_000.0),
                                    avis.reserver(db, 9, 1_790_000_000.0))

    assert sorted(asyncio.run(deux())) == [False, True]
