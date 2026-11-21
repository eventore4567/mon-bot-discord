"""« Il met du temps à mute ou ban et kick dans un raid » (21/11/2026).

Trois retards se cumulaient, tous mesurables :

1. _bot_is_allowlisted faisait un aller-retour en base PAR COMPTE, sans cache ;
2. raid_mode enchaînait ces vérifications EN SÉRIE avant le premier kick, donc
   sur cinquante bots le premier compte ne partait qu'après cinquante requêtes ;
3. cinq expulsions en parallèle seulement, soit dix vagues successives.

Ces tests mesurent le comportement, pas le code : on compte les requêtes et on
vérifie que les vérifications se recouvrent au lieu de s'enchaîner.
"""
from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from cogs import raid_mode  # noqa: E402


class _Db:
    def __init__(self, latence=0.0):
        self.requetes = 0
        self.latence = latence

    async def fetchall(self, requete, params=()):
        self.requetes += 1
        if self.latence:
            await asyncio.sleep(self.latence)
        return []

    async def fetchone(self, requete, params=()):
        self.requetes += 1
        if self.latence:
            await asyncio.sleep(self.latence)
        return None


class _Automod:
    """Le strict nécessaire pour mesurer le chemin d'expulsion."""

    def __init__(self, db):
        self.bot = SimpleNamespace(db=db)

    async def _bot_is_allowlisted(self, guild_id, bot_id):
        from cogs.automod import AutoMod

        return await AutoMod._bot_is_allowlisted(self, guild_id, bot_id)

    async def _bot_allowlist_cached(self, guild_id):
        from cogs.automod import AutoMod

        return await AutoMod._bot_allowlist_cached(self, guild_id)


def _bot_membre(identifiant, guild):
    return SimpleNamespace(
        id=identifiant, bot=True, guild=guild, display_name=f"bot{identifiant}",
        created_at=None, avatar=None, kick=_kick_instantane,
    )


async def _kick_instantane(reason=None):
    await asyncio.sleep(0.01)  # un appel Discord, même rapide, n'est pas gratuit


@pytest.mark.asyncio
async def test_l_allowlist_ne_fait_plus_une_requete_par_compte():
    """Cinquante bots examinés, UNE seule requête au lieu de cinquante."""
    db = _Db()
    automod = _Automod(db)

    for identifiant in range(50):
        await automod._bot_is_allowlisted(1, identifiant)

    assert db.requetes == 1, (
        f"{db.requetes} requêtes pour cinquante comptes — le cache ne sert à rien"
    )


@pytest.mark.asyncio
async def test_modifier_l_allowlist_vide_le_cache():
    """Un cache sans invalidation est un bug : autoriser un bot n'aurait aucun effet."""
    from cogs.automod import AutoMod

    automod = _Automod(_Db())
    await automod._bot_allowlist_cached(1)
    assert 1 in automod._bot_allowlist_cache

    AutoMod._oublier_allowlist_bots(automod, 1)
    assert 1 not in automod._bot_allowlist_cache


@pytest.mark.asyncio
async def test_les_verifications_se_recouvrent_au_lieu_de_s_enchainer():
    """Le vrai correctif : le premier kick n'attend plus les quarante-neuf autres.

    Avec 50 comptes et 20 ms de latence par vérification, la version en série
    coûtait au moins 1 s avant le premier kick. En parallèle, l'ensemble doit
    tenir très en dessous.
    """
    db = _Db(latence=0.02)
    automod = _Automod(db)
    guild = SimpleNamespace(id=1, owner_id=999, me=None)
    membres = [_bot_membre(i, guild) for i in range(50)]
    etat = raid_mode.EtatRaid(debut=0.0, jusqua=0.0, derniere_arrivee=0.0)
    verrou = asyncio.Semaphore(raid_mode.EXPULSIONS_EN_PARALLELE)

    debut = time.monotonic()
    await asyncio.gather(*(
        raid_mode._examiner_et_expulser(automod, etat, m, verrou) for m in membres
    ), return_exceptions=True)
    duree = time.monotonic() - debut

    serie = 50 * 0.02  # ce que coûtait l'ancienne boucle, vérifications seules
    assert duree < serie / 2, (
        f"{duree:.2f}s pour cinquante comptes : les vérifications s'enchaînent encore "
        f"(la version en série coûtait déjà {serie:.2f}s avant le premier kick)"
    )


def test_la_parallelisation_des_expulsions_a_ete_relevee():
    assert raid_mode.EXPULSIONS_EN_PARALLELE >= 10, (
        "cinq expulsions à la fois, c'étaient dix vagues pour cinquante comptes"
    )


def test_la_verification_est_bien_dans_la_tache():
    """Posée avant la boucle, elle resterait séquentielle."""
    import inspect

    source = inspect.getsource(raid_mode.declencher)
    assert "_examiner_et_expulser" in source
    assert "await _intouchable" not in source, (
        "la vérification doit vivre DANS la tâche, pas dans la boucle"
    )


# ------------------------------------------------- « et même pour mute »
def test_l_arbitre_ia_ne_fait_plus_attendre_six_secondes():
    """Six secondes avant toute sanction, pour 1,9 s mesurées en production.

    Les logs du 17/11 donnent 1449 à 1879 ms sur gpt-5.6-luna. Deux secondes
    et demie couvrent le cas normal ; au-delà, on faisait attendre une sanction
    pour un verdict qui n'arrivait pas.
    """
    from cogs import automod

    assert automod.DELAI_ARBITRE_IA <= 3.0, (
        "au-delà de trois secondes, le membre reste libre pendant que l'IA réfléchit"
    )
    assert automod.DELAI_ARBITRE_IA >= 2.0, (
        "en dessous de deux secondes, on couperait des verdicts qui allaient arriver"
    )


def test_un_depassement_de_l_arbitre_ne_perd_pas_la_sanction():
    """Le délai raccourci n'est sûr QUE parce que l'échec retombe sur le local."""
    import inspect

    from cogs import automod

    source = inspect.getsource(automod.AutoMod._insulte_selon_contexte)
    # Sur exception (dont le dépassement de délai), la fonction rend None.
    assert "return None" in source
    assert "l'analyse locale reste l'arbitre" in source


@pytest.mark.asyncio
async def test_le_schema_strict_n_est_cree_qu_une_fois():
    """Ce CREATE TABLE tournait à chaque expiration du cache, soit toutes les 30 s.

    La première sanction de chaque demi-minute payait donc un aller-retour DDL
    avant d'agir.
    """
    from cogs.automod import AutoMod

    class _DbCompteur:
        def __init__(self):
            self.ddl = 0

        async def execute(self, requete, params=()):
            if "CREATE TABLE" in requete.upper():
                self.ddl += 1

        async def fetchone(self, requete, params=()):
            return None

    db = _DbCompteur()
    cog = SimpleNamespace(
        bot=SimpleNamespace(db=db), __dict__={},
        _strict_schema_pret=False,
    )
    # Trois passages séparés par une expiration du cache.
    for _ in range(3):
        cog.__dict__.pop("_strict_cache", None)
        await AutoMod.admins_soumis(cog, 1)

    assert db.ddl == 1, f"{db.ddl} CREATE TABLE pour trois sanctions"
