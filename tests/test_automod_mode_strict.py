"""04/11/2026 : mode strict décidé par le propriétaire — l'AutoMod filtre aussi les admins."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import automod as am  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class _Base:
    def __init__(self):
        self.lignes = {}

    async def execute(self, sql, params=()):
        if sql.lstrip().startswith("INSERT INTO sentrix_automod_strict"):
            self.lignes[int(params[0])] = int(params[1])

    async def fetchone(self, sql, params=()):
        valeur = self.lignes.get(int(params[0]))
        return None if valeur is None else {"admins": valeur}


def _cog():
    cog = am.AutoMod.__new__(am.AutoMod)
    cog.bot = SimpleNamespace(db=_Base())
    return cog


def test_admins_exemptes_par_defaut_puis_filtres_en_mode_strict(monkeypatch):
    monkeypatch.setattr(am, "_is_discord_administrator", lambda member: True)
    cog = _cog()

    async def scenario():
        avant = await cog._admin_exempte(object(), 1)
        await cog.definir_admins_soumis(1, True, 42)
        pendant = await cog._admin_exempte(object(), 1)
        autre_serveur = await cog._admin_exempte(object(), 2)
        await cog.definir_admins_soumis(1, False, 42)
        apres = await cog._admin_exempte(object(), 1)
        return avant, pendant, autre_serveur, apres

    assert asyncio.run(scenario()) == (True, False, True, True)


def test_une_base_illisible_garde_le_comportement_historique():
    cog = am.AutoMod.__new__(am.AutoMod)

    class Panne:
        async def execute(self, *a, **k):
            raise RuntimeError("pool fermé")

    cog.bot = SimpleNamespace(db=Panne())
    assert asyncio.run(cog.admins_soumis(1)) is False


def test_tous_les_filtres_de_messages_passent_par_le_mode_strict():
    source = (ROOT / "cogs/automod.py").read_text(encoding="utf-8")
    # Plus aucun « if _is_discord_administrator(...) : return » en dur sur un message.
    assert "if _is_discord_administrator(message.author):" not in source
    assert source.count("await self._admin_exempte(") >= 4
    assert "and not await self.admins_soumis(" in source
    # Discord refuse tout timeout sur un administrateur : réponse « abus privilégié ».
    assert "or member.guild_permissions.administrator:" in source


def test_seul_le_proprietaire_change_le_mode_et_le_menu_le_propose():
    source = (ROOT / "cogs/automod.py").read_text(encoding="utf-8")
    assert "ctx.author.id != ctx.guild.owner_id and ctx.author.id not in config.OWNER_IDS" in source
    from utils import slash_catalog

    assert any(e.path == "security strict" and e.source == "automod-strict" for e in slash_catalog.CATALOG)
