"""Le contrôle Administrateur du dashboard ne doit plus coûter un appel REST Discord par
serveur et par requête (mesuré en production : 2 à 3,6 s par appel d'API, 8,2 s pour
/api/guilds, 404 « accès refusé » sporadiques sous rate-limit)."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

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
    def __init__(self, gid, member=None, chunked=True):
        self.id = gid
        self.name = f"g{gid}"
        self.icon = None
        self.owner_id = 0
        self.chunked = chunked
        self._member = member
        self.fetch_calls = 0

    def get_member(self, uid):
        return self._member if self._member and self._member.id == uid else None

    async def fetch_member(self, uid):
        self.fetch_calls += 1
        raise dashboard.discord.NotFound(SimpleNamespace(status=404, reason="nf"), "Unknown Member")


def _bot(guilds):
    return SimpleNamespace(guilds=guilds, get_guild=lambda gid: next((g for g in guilds if g.id == gid), None))


def _request(bot):
    return SimpleNamespace(app={"bot": bot})


def test_administrator_member_never_fetches_when_guild_is_chunked():
    guild = _Guild(1, member=None, chunked=True)
    assert asyncio.run(dashboard._administrator_member(guild, 42)) is None
    assert guild.fetch_calls == 0


def test_administrator_member_still_fetches_when_guild_not_chunked():
    guild = _Guild(1, member=None, chunked=False)
    assert asyncio.run(dashboard._administrator_member(guild, 42)) is None
    assert guild.fetch_calls == 1


def test_refresh_admin_guilds_skips_rest_for_non_member_chunked_guilds():
    me = _Member(42, admin=True)
    mine = _Guild(1, member=me)
    others = [_Guild(i, member=None) for i in range(2, 22)]  # 20 serveurs où je ne suis pas
    bot = _bot([mine, *others])
    session = {"user": {"id": "42"}, "guilds": [{"id": "1", "name": "g1"}]}

    assert asyncio.run(guard._refresh_admin_guilds(_request(bot), dashboard, session)) is True
    assert sum(g.fetch_calls for g in others) == 0
    assert [g["id"] for g in session["guilds"]] == ["1"]
    assert isinstance(session.get(guard._REFRESH_STAMP_KEY), float)


def test_refresh_admin_guilds_reuses_a_recent_verification():
    me = _Member(42, admin=True)
    mine = _Guild(1, member=me)
    bot = _bot([mine])
    session = {"user": {"id": "42"}, "guilds": [{"id": "1", "name": "g1"}]}
    assert asyncio.run(guard._refresh_admin_guilds(_request(bot), dashboard, session)) is True

    # Le membre perd Administrateur : dans la fenêtre, on réutilise le résultat récent…
    mine._member = _Member(42, admin=False)
    assert asyncio.run(guard._refresh_admin_guilds(_request(bot), dashboard, session)) is True

    # …et passé le TTL, la révocation est bien détectée.
    session[guard._REFRESH_STAMP_KEY] = time.time() - guard.ADMIN_REFRESH_TTL_SECONDS - 1
    assert asyncio.run(guard._refresh_admin_guilds(_request(bot), dashboard, session)) is False
    assert session["guilds"] == []


def test_refresh_ttl_matches_live_stream_recheck_cadence():
    assert guard.ADMIN_REFRESH_TTL_SECONDS == 30.0


def test_v18_delegation_lookup_never_fetches_when_guild_is_chunked():
    from web import dashboard_product_v18 as v18
    guild = _Guild(7, member=None, chunked=True)
    assert asyncio.run(v18._member_for_user(guild, 42)) is None
    assert guild.fetch_calls == 0
    not_chunked = _Guild(8, member=None, chunked=False)
    assert asyncio.run(v18._member_for_user(not_chunked, 42)) is None
    assert not_chunked.fetch_calls == 1
