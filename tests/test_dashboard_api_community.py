"""Routes Communauté du dashboard (Niveaux / Économie / Rôles) : mêmes tables que Discord."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from aiohttp import web

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from web import dashboard  # noqa: E402
from web import dashboard_api_community as community  # noqa: E402


def test_routes_are_registered_once_in_build_app():
    app = web.Application()
    app["bot"] = SimpleNamespace(db=None)
    community.register(app, dashboard)
    paths = {(r.method, r.resource.canonical) for r in app.router.routes()}
    expected = {
        ("GET", "/api/guilds/{guild_id}/levels"), ("PUT", "/api/guilds/{guild_id}/levels"),
        ("POST", "/api/guilds/{guild_id}/levels/roles"), ("DELETE", "/api/guilds/{guild_id}/levels/roles/{level}"),
        ("GET", "/api/guilds/{guild_id}/economy"), ("PUT", "/api/guilds/{guild_id}/economy"),
        ("POST", "/api/guilds/{guild_id}/economy/shop"), ("DELETE", "/api/guilds/{guild_id}/economy/shop/{item_id}"),
        ("GET", "/api/guilds/{guild_id}/economy/games"), ("PUT", "/api/guilds/{guild_id}/economy/games"),
        ("GET", "/api/guilds/{guild_id}/roles"), ("GET", "/api/guilds/{guild_id}/roles/messages"),
        ("POST", "/api/guilds/{guild_id}/roles/panels/reaction"), ("POST", "/api/guilds/{guild_id}/roles/panels/refresh"),
        ("POST", "/api/guilds/{guild_id}/roles/reactions"), ("DELETE", "/api/guilds/{guild_id}/roles/reactions/{message_id}/{emoji_key}"),
    }
    assert expected <= paths


def test_int_validation_messages_are_user_facing():
    assert community._int("12", 1, 20, "niveau") == 12
    with pytest.raises(ValueError, match="doit être un nombre entier"):
        community._int("abc", 1, 20, "niveau")
    with pytest.raises(ValueError, match="compris entre 1 et 20"):
        community._int(99, 1, 20, "niveau")


def test_role_ids_keep_only_existing_roles_once():
    guild = SimpleNamespace(get_role=lambda rid: SimpleNamespace(id=rid) if rid in (1, 2) else None)
    assert community._role_ids(guild, ["1", "2", "2", "3", "x", None]) == [1, 2]


def test_build_app_registers_community_routes():
    """Le dashboard canonique branche ces routes lui-même (pas de couche séparée)."""
    from pathlib import Path
    source = Path(dashboard.__file__).read_text(encoding="utf-8")
    assert "register_community_routes(app, sys.modules[__name__])" in source
