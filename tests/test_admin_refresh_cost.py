"""Régressions du contrôle Administrateur et du polling de récupération dashboard."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import web
from web import admin_only_dashboard as guard
from web import dashboard


class _Perms:
    def __init__(self, admin):
        self.administrator = admin


class _Member:
    def __init__(self, uid, admin=True):
        self.id = uid
        self.guild_permissions = _Perms(admin)


class _Guild:
    def __init__(self, gid, member=None, fetched_member=None, chunked=True):
        self.id = gid
        self.name = f"g{gid}"
        self.icon = None
        self.owner_id = 0
        self.chunked = chunked
        self._member = member
        self.fetched_member = fetched_member
        self.fetch_calls = 0

    def get_member(self, uid):
        return self._member if self._member and self._member.id == uid else None

    async def fetch_member(self, uid):
        self.fetch_calls += 1
        if self.fetched_member is not None and self.fetched_member.id == uid:
            return self.fetched_member
        raise dashboard.discord.NotFound(SimpleNamespace(status=404, reason="nf"), "Unknown Member")


def _bot(guilds):
    return SimpleNamespace(guilds=guilds, get_guild=lambda gid: next((g for g in guilds if g.id == gid), None))


def _request(bot):
    return SimpleNamespace(app={"bot": bot})


def _dashboard_guard():
    return SimpleNamespace(_administrator_member=guard._administrator_member_cached)


def test_admin_helper_repairs_chunked_cache_miss_once_then_reuses_result():
    guard._ADMIN_MEMBER_CACHE.clear()
    admin = _Member(42, admin=True)
    guild = _Guild(101, member=None, fetched_member=admin, chunked=True)

    assert asyncio.run(guard._administrator_member_cached(guild, 42)) is admin
    assert asyncio.run(guard._administrator_member_cached(guild, 42)) is admin
    assert guild.fetch_calls == 1


def test_refresh_only_fetches_oauth_candidates_not_every_bot_guild():
    guard._ADMIN_MEMBER_CACHE.clear()
    admin = _Member(42, admin=True)
    mine = _Guild(1, member=None, fetched_member=admin)
    others = [_Guild(i, member=None) for i in range(2, 22)]
    bot = _bot([mine, *others])
    session = {"user": {"id": "42"}, "guilds": [{"id": "1", "name": "g1"}]}

    assert asyncio.run(guard._refresh_admin_guilds(_request(bot), _dashboard_guard(), session)) is True
    assert mine.fetch_calls == 1
    assert sum(g.fetch_calls for g in others) == 0
    assert [g["id"] for g in session["guilds"]] == ["1"]
    assert [g["id"] for g in session[guard._OAUTH_GUILDS_KEY]] == ["1"]
    assert isinstance(session.get(guard._REFRESH_STAMP_KEY), float)


def test_refresh_admin_guilds_reuses_a_recent_verification_and_detects_revocation():
    guard._ADMIN_MEMBER_CACHE.clear()
    me = _Member(42, admin=True)
    mine = _Guild(31, member=me)
    bot = _bot([mine])
    session = {"user": {"id": "42"}, "guilds": [{"id": "31", "name": "g31"}]}
    helper = _dashboard_guard()
    assert asyncio.run(guard._refresh_admin_guilds(_request(bot), helper, session)) is True

    # Dans la fenêtre de 30 s, les routes de la même page partagent le verdict récent.
    mine._member = _Member(42, admin=False)
    assert asyncio.run(guard._refresh_admin_guilds(_request(bot), helper, session)) is True

    # Après le TTL, le cache gateway actuel reprend autorité et la révocation est détectée.
    session[guard._REFRESH_STAMP_KEY] = time.time() - guard.ADMIN_REFRESH_TTL_SECONDS - 1
    assert asyncio.run(guard._refresh_admin_guilds(_request(bot), helper, session)) is False
    assert session["guilds"] == []


def test_oauth_candidate_survives_temporary_false_negative_and_can_recover():
    guard._ADMIN_MEMBER_CACHE.clear()
    admin = _Member(42, admin=True)
    mine = _Guild(51, member=None, fetched_member=admin)
    bot = _bot([mine])
    session = {"user": {"id": "42"}, "guilds": [{"id": "51", "name": "g51"}]}
    helper = _dashboard_guard()

    assert asyncio.run(guard._refresh_admin_guilds(_request(bot), helper, session)) is True
    assert [g["id"] for g in session[guard._OAUTH_GUILDS_KEY]] == ["51"]

    # Simule un cache/fetch Discord momentanément vide : la liste live peut être refusée,
    # mais le candidat OAuth d'origine ne doit pas être détruit.
    session[guard._REFRESH_STAMP_KEY] = time.time() - 31
    guard._ADMIN_MEMBER_CACHE.clear()
    mine.fetched_member = None
    assert asyncio.run(guard._refresh_admin_guilds(_request(bot), helper, session)) is False
    assert [g["id"] for g in session[guard._OAUTH_GUILDS_KEY]] == ["51"]

    # Au prochain contrôle, le serveur peut donc être récupéré sans nouvelle connexion OAuth.
    session[guard._REFRESH_STAMP_KEY] = time.time() - 31
    guard._ADMIN_MEMBER_CACHE.clear()
    mine.fetched_member = admin
    assert asyncio.run(guard._refresh_admin_guilds(_request(bot), helper, session)) is True
    assert [g["id"] for g in session["guilds"]] == ["51"]


def test_core_recovery_stops_as_soon_as_runtime_is_healthy():
    script = web._CORE_RECOVERY_JS
    assert "data.online && data.oauth_ready && attempts >= 6" not in script
    assert "if (data.online && data.oauth_ready) { arreter(); return; }" in script
    assert "await refreshRuntime();\n      if (arrete) return;" in script


def test_refresh_ttl_stays_bounded():
    assert guard.ADMIN_REFRESH_TTL_SECONDS == 30.0
    assert guard.ADMIN_MEMBER_NEGATIVE_TTL_SECONDS <= 5.0


def test_v18_delegation_lookup_never_fetches_when_guild_is_chunked():
    from web import dashboard_product_v18 as v18
    guild = _Guild(7, member=None, chunked=True)
    assert asyncio.run(v18._member_for_user(guild, 42)) is None
    assert guild.fetch_calls == 0
    not_chunked = _Guild(8, member=None, chunked=False)
    assert asyncio.run(v18._member_for_user(not_chunked, 42)) is None
    assert not_chunked.fetch_calls == 1
