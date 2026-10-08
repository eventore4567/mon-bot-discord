"""Contrats de migration du pack d'emojis d'application SentriX.

Un échec Discord ne doit pas faire supprimer toutes les anciennes icônes,
et un pack partiellement synchronisé ne doit jamais être marqué « terminé ».
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import sentrix_emojis as se


class Old:
    def __init__(self, name: str, log: list[str]):
        self.name = name
        self.log = log
        self.id = 100000000000000000 + len(log)

    def __str__(self):
        return f"<:{self.name}:{self.id}>"

    async def delete(self):
        self.log.append(f"delete:{self.name}")


class App:
    def __init__(self, installed: list[str], *, fail_once=None, marker_fails=False):
        self.log = []
        self.installed = list(installed)
        self.fail_once = fail_once
        self.marker_fails = marker_fails
        self.next_id = 200000000000000000

    async def fetch_application_emojis(self):
        return [Old(n, self.log) for n in self.installed]

    async def create_application_emoji(self, *, name, image):
        self.log.append(f"create:{name}")
        if name == self.fail_once:
            self.fail_once = None
            raise RuntimeError("Discord temporairement indisponible")
        if name == se.TEMOIN and self.marker_fails:
            self.marker_fails = False
            raise RuntimeError("Témoin refusé")
        if name not in self.installed:
            self.installed.append(name)
        self.next_id += 1
        return Old(name, self.log)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    se.reinitialiser()
    monkeypatch.setattr(se, "DELAI_ENTRE_ENVOIS", 0)
    yield
    se.reinitialiser()


@pytest.mark.asyncio
async def test_migration_remplace_chaque_icone_juste_avant_sa_creation(monkeypatch):
    names = se.noms_disponibles()[:3]
    assert len(names) == 3
    app = App(names)
    result = await se.synchroniser(app)
    assert result["echecs"] == 0
    assert result["remplaces"] == 3
    deletes = [i for i, event in enumerate(app.log) if event.startswith("delete:")]
    assert len(deletes) == 3
    for name in names:
        d = app.log.index(f"delete:{name}")
        c = app.log.index(f"create:{name}")
        assert c == d + 1, "Un autre ancien emoji a été supprimé avant sa recréation"
    assert f"create:{se.TEMOIN}" == app.log[-1]
    assert se._SYNCHRONISE is True


@pytest.mark.asyncio
async def test_echec_icone_conserve_les_autres_et_ne_pose_pas_de_temoin():
    names = se.noms_disponibles()[:3]
    app = App(names, fail_once=names[1])
    result = await se.synchroniser(app)
    assert result["echecs"] == 1
    assert f"create:{se.TEMOIN}" not in app.log
    assert se._SYNCHRONISE is False
    assert se.emoji(names[1]) == se.REPLIS.get(names[1], "")
    assert se.emoji(names[2]).startswith("<:"), "Les autres emojis ne doivent pas être cassés"
    assert app.log.index(f"delete:{names[2]}") > app.log.index(f"create:{names[1]}")


@pytest.mark.asyncio
async def test_reprise_apres_televersement_incomplet():
    names = se.noms_disponibles()[:3]
    app = App(names, fail_once=names[1])
    await se.synchroniser(app)
    assert se._SYNCHRONISE is False
    result = await se.synchroniser(app)
    assert result["echecs"] == 0
    assert se.TEMOIN in app.installed
    assert se._SYNCHRONISE is True


@pytest.mark.asyncio
async def test_temoin_refuse_ne_marque_pas_migration_complete():
    app = App([], marker_fails=True)
    first = await se.synchroniser(app)
    assert first["echecs"] == 1
    assert se._SYNCHRONISE is False
    assert se.TEMOIN not in app.installed

    second = await se.synchroniser(app)
    assert second["echecs"] == 0
    assert se._SYNCHRONISE is True
    assert se.TEMOIN in app.installed


@pytest.mark.asyncio
async def test_relance_forcee_relit_les_ids_discord():
    name = se.noms_disponibles()[0]
    app = App([name, se.TEMOIN])
    await se.synchroniser(app)
    se.amorcer({"sentrix_stale": "<:sentrix_stale:111111111111111111>"})
    assert se.emoji("stale")
    await se.synchroniser(app, forcer=True)
    assert se.emoji("stale") == ""
    assert not any(event.startswith("delete:") for event in app.log)
