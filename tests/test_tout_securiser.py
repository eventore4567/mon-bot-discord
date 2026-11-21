"""Une seule commande pour tout allumer (21/11/2026).

« fait un comende qui active tout au cas ou. »

Allumer les protections une par une demandait dix-huit commandes, ou autant de
clics dans /setup → Sécurité. Quand un raid se prépare, personne n'a le temps.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from cogs import automod as automod_mod  # noqa: E402
from cogs.automod import AutoMod, TOGGLE_FIELDS, TOUT_SECURISER_EXCLUES  # noqa: E402


class _Db:
    def __init__(self, deja=()):
        self.valeurs: dict[str, int] = {cle: 1 for cle in deja}
        self.inserts = 0

    async def execute(self, requete, params=()):
        if "INSERT INTO automod_settings" in requete:
            self.inserts += 1

    async def set_automod(self, guild_id, champ, valeur):
        self.valeurs[champ] = int(valeur)


@pytest.fixture
def envoyes(monkeypatch):
    recus: list[str] = []
    monkeypatch.setattr(automod_mod.panels, "envoyer", AsyncMock())
    monkeypatch.setattr(automod_mod.panels, "depuis_embed", lambda embed: embed)
    monkeypatch.setattr(automod_mod.embeds, "success", lambda texte: recus.append(texte) or texte)
    monkeypatch.setattr(automod_mod.config_journal, "record", AsyncMock())
    return recus


def _cog(db, conf):
    cog = AutoMod.__new__(AutoMod)
    cog.bot = SimpleNamespace(db=db, user=SimpleNamespace(id=2))
    cog.automod_cache = {1: conf}
    cog.get_automod_cached = AsyncMock(return_value=conf)
    return cog


def _ctx():
    return SimpleNamespace(guild=SimpleNamespace(id=1), author=SimpleNamespace(id=7))


@pytest.mark.asyncio
async def test_tout_est_allume_en_une_commande(envoyes):
    db = _Db()
    cog = _cog(db, {cle: 0 for cle in TOGGLE_FIELDS})
    await AutoMod.tout_securiser.callback(cog, _ctx())

    attendu = {cle for cle in TOGGLE_FIELDS if cle not in TOUT_SECURISER_EXCLUES}
    assert {cle for cle, v in db.valeurs.items() if v} == attendu
    assert envoyes and str(len(attendu)) in envoyes[0]


@pytest.mark.asyncio
async def test_le_blocage_total_des_liens_reste_a_part(envoyes):
    """Ce n'est pas une protection, c'est un choix éditorial.

    ``antilink_strict`` coupe aussi les liens légitimes : un lien YouTube, un
    dépôt GitHub, le lien d'aide d'un modérateur. L'allumer « au cas où »
    casserait les conversations du serveur sans arrêter un seul raideur.
    """
    db = _Db()
    cog = _cog(db, {cle: 0 for cle in TOGGLE_FIELDS})
    await AutoMod.tout_securiser.callback(cog, _ctx())

    assert "antilink_strict" in TOUT_SECURISER_EXCLUES
    assert db.valeurs.get("antilink_strict", 0) == 0


@pytest.mark.asyncio
async def test_rien_n_est_jamais_eteint(envoyes):
    """La commande allume ; elle ne doit pas servir d'interrupteur à bascule.

    Si elle éteignait ce qui était allumé, la lancer deux fois de suite
    laisserait le serveur nu — exactement au mauvais moment.
    """
    conf = {cle: 1 for cle in TOGGLE_FIELDS}
    db = _Db(deja=TOGGLE_FIELDS)
    cog = _cog(db, conf)
    await AutoMod.tout_securiser.callback(cog, _ctx())

    assert all(db.valeurs[cle] == 1 for cle in TOGGLE_FIELDS)
    assert "déjà actives" in envoyes[0]


@pytest.mark.asyncio
async def test_seules_les_protections_coupees_sont_journalisees(envoyes, monkeypatch):
    """Le journal de configuration doit rester lisible.

    Journaliser dix-huit lignes « 0 → 1 » alors que seize étaient déjà
    allumées noierait le vrai changement.
    """
    record = AsyncMock()
    monkeypatch.setattr(automod_mod.config_journal, "record", record)
    conf = {cle: 1 for cle in TOGGLE_FIELDS}
    conf["antinuke"] = 0
    conf["antiraid"] = 0
    db = _Db(deja=[cle for cle in TOGGLE_FIELDS if conf[cle]])
    cog = _cog(db, conf)
    await AutoMod.tout_securiser.callback(cog, _ctx())

    cles = {appel.args[2] for appel in record.await_args_list}
    assert cles == {"automod.antinuke", "automod.antiraid"}


@pytest.mark.asyncio
async def test_le_cache_est_vide_pour_que_le_changement_prenne_tout_de_suite(envoyes):
    """Sans ça, les filtres continueraient de lire l'ancienne configuration.

    ``get_automod_cached`` sert chaque message : tant que l'entrée du serveur
    reste en mémoire, les protections fraîchement allumées restent inertes.
    """
    db = _Db()
    conf = {cle: 0 for cle in TOGGLE_FIELDS}
    cog = _cog(db, conf)
    assert 1 in cog.automod_cache
    await AutoMod.tout_securiser.callback(cog, _ctx())
    assert 1 not in cog.automod_cache
