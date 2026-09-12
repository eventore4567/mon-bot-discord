"""Milestone 2 (Configuration Platform), priorité P1 #7 : le chemin d'écriture
le plus emprunté du dashboard (réglages généraux, AutoMod, IA) n'écrivait dans
aucune table d'audit — confirmé par une lecture complète de web/dashboard.py et
web/operations_center.py, et par le fait que cogs/operations_center.py
(propriétaire d'origine de la table dashboard_audit_log) n'est chargé nulle
part dans le boot réel (ni main.EXTENSIONS, ni railway_boot.py), donc la table
qu'il crée n'a jamais existé en production : le wrapper d'audit générique déjà
présent (web/operations_center.py::_wrap_existing_writes) échouait donc
silencieusement à CHAQUE tentative d'écriture, avalé par son propre
try/except.

Deux correctifs indépendants, testés séparément ici :
1. dashboard_audit_log déplacée dans database/db.py::SCHEMA (source unique
   déjà réconciliée par database/migrations.py) : la table existe désormais
   qu'importe si cogs/operations_center.py charge ou non.
2. web/dashboard.py::handle_update_guild calcule maintenant le détail champ par
   champ (ancienne valeur -> nouvelle valeur) et le dépose sur
   request["dashboard_audit_changes"] ; le wrapper existant dans
   web/operations_center.py le lit et l'inclut dans la ligne d'audit qu'il
   écrivait déjà — plutôt que d'ajouter un second système d'audit parallèle.
"""
from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DISCORD_TOKEN", "x")

from database.db import SCHEMA  # noqa: E402
from web import dashboard  # noqa: E402


# ---------------------------------------------------------------- unitaire --

def test_diff_changed_fields_ignores_unchanged_values():
    old_row = {"prefix": "+", "welcome_channel": 123}
    changes = dashboard._diff_changed_fields(old_row, {"prefix": "+", "welcome_channel": 456})
    assert changes == {"welcome_channel": {"old": 123, "new": 456}}


def test_diff_changed_fields_treats_missing_old_row_as_all_new():
    changes = dashboard._diff_changed_fields(None, {"prefix": "!"})
    assert changes == {"prefix": {"old": None, "new": "!"}}


def test_diff_changed_fields_empty_when_nothing_sent():
    assert dashboard._diff_changed_fields({"prefix": "+"}, {}) == {}


# ------------------------------------------------------ schéma unique de vérité --

def test_dashboard_audit_log_is_now_owned_by_the_core_schema():
    """La table ne doit plus dépendre du chargement de cogs/operations_center.py
    pour exister : elle est réconciliée à chaque Database.connect() via SCHEMA."""
    assert "CREATE TABLE IF NOT EXISTS dashboard_audit_log" in SCHEMA


# --------------------------------------------------- handle_update_guild bout en bout --

class _FakeRequest(dict):
    """dict pour supporter request[...] = ... comme le vrai aiohttp.web.Request."""

    def __init__(self, *, bot, guild_id: int, payload: dict, user_id: str = "1"):
        super().__init__()
        self.app = {"bot": bot, "write_limits": {}}
        self.match_info = {"guild_id": str(guild_id)}
        self.cookies = {}
        self.path = f"/api/guilds/{guild_id}/settings"
        self._payload = payload
        self.json = AsyncMock(return_value=payload)


def _db_with_current(guild_row: dict | None, automod_row: dict | None = None) -> Mock:
    db = Mock()
    db.get_guild_config = AsyncMock(return_value=guild_row)
    db.get_automod = AsyncMock(return_value=automod_row)
    db.fetchone = AsyncMock(return_value=None)
    db.set_guild_config = AsyncMock(return_value=None)
    db.set_automod = AsyncMock(return_value=None)
    db.execute = AsyncMock(return_value=None)
    return db


async def _call_handle_update_guild(guild_row, payload):
    guild = Mock()
    guild.id = 42

    async def manageable(_request, _guild_id):
        return {"user": {"id": "7", "username": "testeur"}}, guild, None

    db = _db_with_current(guild_row)
    bot = Mock()
    bot.db = db
    request = _FakeRequest(bot=bot, guild_id=42, payload=payload)

    with patch.object(dashboard, "_manageable_guild", side_effect=manageable), \
         patch.object(dashboard, "_require_csrf", return_value=None), \
         patch.object(dashboard, "_validate_settings", return_value=(payload.get("settings", {}), None)):
        response = await dashboard.handle_update_guild(request)
    return request, response, db


def test_handle_update_guild_records_field_level_diff_on_the_request():
    async def run():
        request, response, _db = await _call_handle_update_guild(
            {"prefix": "+"}, {"settings": {"prefix": "!"}}
        )
        assert response.status == 200
        assert request["dashboard_audit_changes"] == {"prefix": {"old": "+", "new": "!"}}

    asyncio.run(run())


def test_handle_update_guild_records_no_diff_when_value_is_unchanged():
    async def run():
        request, response, _db = await _call_handle_update_guild(
            {"prefix": "+"}, {"settings": {"prefix": "+"}}
        )
        assert response.status == 200
        assert request["dashboard_audit_changes"] == {}

    asyncio.run(run())


# ------------------------------------------------- wrapper d'audit générique --

def test_ops_wrapper_forwards_the_diff_into_the_audit_row():
    """web/operations_center.py::_wrap_existing_writes lit request["dashboard_
    audit_changes"] et l'inclut désormais dans la ligne dashboard_audit_log,
    au lieu d'écrire une ligne vide de tout détail comme avant ce correctif."""
    from web import operations_center as ops

    recorded = {}

    async def fake_audit(request, guild_id, user_id, action, target="", details=None):
        recorded["guild_id"] = guild_id
        recorded["action"] = action
        recorded["details"] = details

    async def fake_original(request):
        request["dashboard_audit_changes"] = {"prefix": {"old": "+", "new": "!"}}
        return Mock(status=200)

    fake_dashboard = Mock()
    fake_dashboard._session = Mock(return_value={"user": {"id": "7"}})
    fake_dashboard.handle_update_guild = fake_original

    with patch.object(ops, "_audit", side_effect=fake_audit):
        ops._wrap_existing_writes(fake_dashboard)
        request = _FakeRequest(bot=Mock(), guild_id=42, payload={})
        asyncio.run(fake_dashboard.handle_update_guild(request))

    assert recorded["guild_id"] == 42
    assert recorded["action"] == "settings_update"
    assert recorded["details"] == {"changes": {"prefix": {"old": "+", "new": "!"}}}


def test_ops_wrapper_omits_details_when_nothing_changed():
    from web import operations_center as ops

    recorded = {}

    async def fake_audit(request, guild_id, user_id, action, target="", details=None):
        recorded["details"] = details

    async def fake_original(request):
        request["dashboard_audit_changes"] = {}
        return Mock(status=200)

    fake_dashboard = Mock()
    fake_dashboard._session = Mock(return_value={"user": {"id": "7"}})
    fake_dashboard.handle_update_guild = fake_original

    with patch.object(ops, "_audit", side_effect=fake_audit):
        ops._wrap_existing_writes(fake_dashboard)
        request = _FakeRequest(bot=Mock(), guild_id=42, payload={})
        asyncio.run(fake_dashboard.handle_update_guild(request))

    assert recorded["details"] is None
