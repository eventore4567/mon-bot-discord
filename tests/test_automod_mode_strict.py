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
    # 22/11/2026 : 4 → 3. _delete_and_timeout ne fait plus son propre contrôle :
    # elle délègue à _delete_and_warn, qui le fait (voir
    # test_une_insulte_confirmee_suit_l_escalade_unique). Aucun chemin n'y échappe.
    assert source.count("await self._admin_exempte(") >= 3
    from cogs.automod import AutoMod
    import inspect
    assert "self._delete_and_warn(" in inspect.getsource(AutoMod._delete_and_timeout)
    assert "and not await self.admins_soumis(" in source
    # Discord refuse tout timeout sur un administrateur : réponse « abus privilégié ».
    # 22/11/2026 : la condition est maintenant écrite sur plusieurs lignes dans
    # _maybe_escalate ; le comportement est vérifié pour de vrai dans
    # tests/test_escalade_contenu.py (test_un_administrateur_...).
    assert "or member.guild_permissions.administrator" in source


def test_seul_le_proprietaire_change_le_mode_et_le_menu_le_propose():
    """Qui peut changer le mode strict : le propriétaire du serveur ou du bot.

    21/11/2026 : la règle était écrite en dur ici, et en dur deux fois de plus
    dans l'écran Sécurité — où elle avait divergé (``guild.owner_id`` seul, donc
    le propriétaire du bot refusé dans l'interface alors que la commande la lui
    donnait). Les trois chemins lisent désormais ``peut_changer_mode_strict``,
    et ce test vérifie la règle elle-même plutôt que sa transcription.
    """
    from types import SimpleNamespace

    import config as config_module
    from cogs.automod import AutoMod

    source = (ROOT / "cogs/automod.py").read_text(encoding="utf-8")
    assert "if not self.peut_changer_mode_strict(ctx.author.id, ctx.guild):" in source

    serveur = SimpleNamespace(id=1, owner_id=999)
    anciens = getattr(config_module, "OWNER_IDS", None)
    config_module.OWNER_IDS = [4242]
    try:
        assert AutoMod.peut_changer_mode_strict(999, serveur) is True   # propriétaire du serveur
        assert AutoMod.peut_changer_mode_strict(4242, serveur) is True  # propriétaire de SentriX
        assert AutoMod.peut_changer_mode_strict(123, serveur) is False  # un admin quelconque
    finally:
        config_module.OWNER_IDS = anciens
    from utils import slash_catalog

    assert any(e.path == "security strict" and e.source == "automod-strict" for e in slash_catalog.CATALOG)
