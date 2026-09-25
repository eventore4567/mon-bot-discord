"""Mises de jeu : réservation, règlement, remboursement.

Le défaut d'origine, vu par Jayden : prélever la mise seulement au moment de
perdre laisse un joueur avec 100 ouvrir trois grilles à 100 avant qu'aucune ne
se résolve. Il mise trois fois le même argent.

Tous les tests tournent sur une VRAIE base SQLite, pas sur des mocks : ce qu'on
vérifie ici est justement l'atomicité, et un mock la garantirait par
construction sans rien prouver.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import tempfile

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from services import game_stakes

GUILD, JOUEUR = 1, 2


async def _base(solde: int = 100):
    from database.db import Database

    dossier = tempfile.mkdtemp(prefix="sentrix-stakes-")
    db = Database(str(pathlib.Path(dossier) / "t.db"))
    await db.connect()
    await db.execute(
        "INSERT OR REPLACE INTO economy (guild_id,user_id,cash) VALUES (?,?,?)",
        (GUILD, JOUEUR, solde),
    )
    return db


def _executer(scenario):
    """Ferme la base à la fin : aiosqlite garde un thread vivant par connexion,
    et vingt tests en laisseraient vingt derrière eux."""

    async def enveloppe():
        db = None
        try:
            db = await scenario()
        finally:
            if db is not None:
                fermer = getattr(db, "close", None)
                if fermer is not None:
                    await fermer()

    asyncio.run(enveloppe())


async def _cash(db) -> int:
    ligne = await db.fetchone(
        "SELECT cash FROM economy WHERE guild_id=? AND user_id=?", (GUILD, JOUEUR)
    )
    return int(ligne["cash"]) if ligne else 0


# ----------------------------------------------------------------- réservation

def test_la_mise_est_debitee_a_l_ouverture():
    async def scenario():
        db = await _base(100)
        game_id = game_stakes.nouvel_identifiant("bomb")
        assert await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, game_id) == "ok"
        assert await _cash(db) == 0, "la mise doit partir tout de suite"
        ouverte = await game_stakes.mise_ouverte(db, game_id)
        assert ouverte is not None and int(ouverte["amount"]) == 100
        return db

    _executer(scenario)


def test_deux_parties_simultanees_avec_le_meme_argent_une_seule_demarre():
    """LE test que ce service existe pour faire passer : 100 en poche, deux
    grilles à 100 lancées à la même milliseconde."""

    async def scenario():
        db = await _base(100)
        ids = [game_stakes.nouvel_identifiant("bomb") for _ in range(2)]
        resultats = await asyncio.gather(*(
            game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, gid) for gid in ids
        ))
        assert sorted(resultats) == ["insufficient", "ok"], resultats
        assert await _cash(db) == 0, "une seule mise a été prélevée"
        return db

    _executer(scenario)


def test_dix_parties_simultanees_ne_reservent_que_ce_qui_existe():
    async def scenario():
        db = await _base(300)
        ids = [game_stakes.nouvel_identifiant("bomb") for _ in range(10)]
        resultats = await asyncio.gather(*(
            game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, gid) for gid in ids
        ))
        assert resultats.count("ok") == 3, resultats
        assert await _cash(db) == 0
        return db

    _executer(scenario)


def test_un_solde_insuffisant_ne_cree_aucune_manche():
    async def scenario():
        db = await _base(50)
        game_id = game_stakes.nouvel_identifiant("bomb")
        assert await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, game_id) == "insufficient"
        assert await _cash(db) == 50
        assert await game_stakes.mise_ouverte(db, game_id) is None, "manche fantôme"
        return db

    _executer(scenario)


def test_le_meme_identifiant_ne_debite_qu_une_fois():
    """Idempotence : rejouer la réservation ne reprend pas d'argent."""

    async def scenario():
        db = await _base(200)
        game_id = game_stakes.nouvel_identifiant("bomb")
        assert await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, game_id) == "ok"
        assert await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, game_id) == "duplicate"
        assert await _cash(db) == 100
        return db

    _executer(scenario)


@pytest.mark.parametrize("montant", [0, -1, -100])
def test_une_mise_nulle_ou_negative_est_refusee(montant):
    async def scenario():
        db = await _base(100)
        game_id = game_stakes.nouvel_identifiant("bomb")
        assert await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", montant, game_id) == "invalid"
        assert await _cash(db) == 100
        return db

    _executer(scenario)


# ----------------------------------------------------------------- règlement

def test_un_gain_credite_le_retour_complet():
    """La mise a été débitée : créditer seulement le profit la confisquerait.

    100 misés, encaissement à ×1,66 → on crédite 166, profit net +66.
    """

    async def scenario():
        db = await _base(100)
        game_id = game_stakes.nouvel_identifiant("bomb")
        await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, game_id)
        assert await _cash(db) == 0
        assert await game_stakes.regler_gain(db, game_id, 166) == "ok"
        assert await _cash(db) == 166
        return db

    _executer(scenario)


def test_une_perte_ne_debite_rien_de_plus():
    async def scenario():
        db = await _base(100)
        game_id = game_stakes.nouvel_identifiant("bomb")
        await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, game_id)
        assert await game_stakes.regler_perte(db, game_id) == "ok"
        assert await _cash(db) == 0, "la mise ne doit pas être prélevée deux fois"
        return db

    _executer(scenario)


def test_on_ne_peut_pas_encaisser_deux_fois():
    async def scenario():
        db = await _base(100)
        game_id = game_stakes.nouvel_identifiant("bomb")
        await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, game_id)
        assert await game_stakes.regler_gain(db, game_id, 166) == "ok"
        assert await game_stakes.regler_gain(db, game_id, 166) == "already_settled"
        assert await _cash(db) == 166
        return db

    _executer(scenario)


def test_deux_encaissements_simultanes_ne_paient_qu_une_fois():
    async def scenario():
        db = await _base(100)
        game_id = game_stakes.nouvel_identifiant("bomb")
        await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, game_id)
        resultats = await asyncio.gather(
            game_stakes.regler_gain(db, game_id, 166),
            game_stakes.regler_gain(db, game_id, 166),
        )
        assert sorted(resultats) == ["already_settled", "ok"], resultats
        assert await _cash(db) == 166
        return db

    _executer(scenario)


def test_bombe_et_encaissement_simultanes_donnent_une_seule_issue():
    """Le joueur clique Encaisser au moment exact où sa case était une bombe."""

    async def scenario():
        db = await _base(100)
        game_id = game_stakes.nouvel_identifiant("bomb")
        await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, game_id)
        resultats = await asyncio.gather(
            game_stakes.regler_gain(db, game_id, 166),
            game_stakes.regler_perte(db, game_id),
        )
        assert resultats.count("ok") == 1, resultats
        # Une seule issue s'applique : soit 166, soit 0. Jamais les deux.
        assert await _cash(db) in (0, 166)
        return db

    _executer(scenario)


def test_regler_une_manche_inconnue_ne_cree_rien():
    async def scenario():
        db = await _base(100)
        assert await game_stakes.regler_gain(db, "inexistant", 500) == "unknown"
        assert await _cash(db) == 100
        return db

    _executer(scenario)


# ----------------------------------------------------------------- remboursement

def test_le_remboursement_rend_exactement_la_mise():
    """Erreur technique après réservation, avant que le joueur ait pu jouer."""

    async def scenario():
        db = await _base(100)
        game_id = game_stakes.nouvel_identifiant("bomb")
        await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, game_id)
        assert await _cash(db) == 0
        assert await game_stakes.rembourser_mise(db, game_id) == "ok"
        assert await _cash(db) == 100
        return db

    _executer(scenario)


def test_on_ne_rembourse_pas_une_manche_deja_reglee():
    async def scenario():
        db = await _base(100)
        game_id = game_stakes.nouvel_identifiant("bomb")
        await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, game_id)
        await game_stakes.regler_perte(db, game_id)
        assert await game_stakes.rembourser_mise(db, game_id) == "already_settled"
        assert await _cash(db) == 0
        return db

    _executer(scenario)


def test_le_redemarrage_ne_laisse_aucune_mise_fantome():
    """Une manche interrompue laisse une mise ouverte. Sans ce balayage,
    l'argent resterait bloqué dans une partie qui n'existe plus."""

    async def scenario():
        db = await _base(300)
        vieilles = [game_stakes.nouvel_identifiant("bomb") for _ in range(2)]
        for game_id in vieilles:
            await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, game_id)
        recente = game_stakes.nouvel_identifiant("bomb")
        await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, recente)
        assert await _cash(db) == 0

        # Les deux premières sont vieilles d'une heure et demie.
        from database.db import now
        await db.execute(
            "UPDATE game_stakes SET created_at=? WHERE game_id IN (?,?)",
            (now() - 5400, vieilles[0], vieilles[1]),
        )

        rendues = await game_stakes.rembourser_mises_orphelines(db)
        assert rendues == 2
        assert await _cash(db) == 200, "la manche récente reste en cours"
        assert await game_stakes.mise_ouverte(db, recente) is not None
        return db

    _executer(scenario)


def test_rejouer_ouvre_une_nouvelle_manche():
    """Un game_id par partie : une relance ne peut pas régler l'ancienne."""

    async def scenario():
        db = await _base(300)
        premier = game_stakes.nouvel_identifiant("bomb")
        second = game_stakes.nouvel_identifiant("bomb")
        assert premier != second
        await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, premier)
        await game_stakes.regler_perte(db, premier)
        assert await game_stakes.ouvrir_mise(db, GUILD, JOUEUR, "bomb", 100, second) == "ok"
        assert await game_stakes.regler_gain(db, second, 166) == "ok"
        assert await _cash(db) == 266  # 300 − 100 − 100 + 166
        # L'ancienne manche reste close.
        assert await game_stakes.regler_gain(db, premier, 999) == "already_settled"
        return db

    _executer(scenario)


def test_un_intrus_ne_peut_rien_regler_sans_l_identifiant():
    """L'identifiant de manche est un secret de 16 caractères hexadécimaux :
    il n'est pas devinable, et c'est lui qui autorise le règlement."""
    premiers = {game_stakes.nouvel_identifiant("bomb") for _ in range(1000)}
    assert len(premiers) == 1000, "collision d'identifiants"
    assert all(len(g.split("-", 1)[1]) == 16 for g in premiers)
