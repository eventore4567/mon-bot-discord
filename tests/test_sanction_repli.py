"""07/11/2026 : « s'il n'a pas la perm, ça sert à rien, il spamme dans l'AutoMod ;
qu'il trouve une solution à la place »."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs import automod as am  # noqa: E402


def _cog():
    cog = am.AutoMod.__new__(am.AutoMod)
    cog._mark_xp_skip = lambda mid: None
    return cog


def _guild(*, moderer=True, gerer_messages=True, role_bot=10):
    proprietaire = SimpleNamespace(id=1, send=AsyncMock())
    me = SimpleNamespace(
        guild_permissions=SimpleNamespace(moderate_members=moderer, manage_messages=gerer_messages),
        top_role=role_bot,
    )
    return SimpleNamespace(id=5, owner_id=1, owner=proprietaire, me=me, name="Test", get_member=lambda uid: None)


def _vrai_membre(guild, *, role=1):
    return SimpleNamespace(id=7, top_role=role, timed_out_until=None, timeout=AsyncMock(), mention="<@7>")


def test_sans_permission_moderer_sentrix_applique_son_propre_mute():
    cog, guild = _cog(), _guild(moderer=False)
    membre = _vrai_membre(guild)
    resultat = asyncio.run(cog._muter(guild, membre, 600, "spam"))
    assert resultat == "mute_sentrix"
    membre.timeout.assert_not_awaited()
    assert cog._est_mute_sentrix(guild.id, membre.id)
    guild.owner.send.assert_awaited_once()               # le propriétaire est prévenu
    asyncio.run(cog._muter(guild, membre, 600, "spam"))
    guild.owner.send.assert_awaited_once()               # … une seule fois, pas de spam


def test_role_trop_bas_meme_repli():
    cog, guild = _cog(), _guild(role_bot=1)
    membre = _vrai_membre(guild, role=5)
    assert asyncio.run(cog._muter(guild, membre, 60, "x")) == "mute_sentrix"


def test_avec_les_droits_c_est_le_mute_de_discord():
    cog, guild = _cog(), _guild()
    membre = _vrai_membre(guild)
    assert asyncio.run(cog._muter(guild, membre, 60, "x")) == "mute"
    membre.timeout.assert_awaited_once()
    assert not cog._est_mute_sentrix(guild.id, membre.id)


def test_sans_gerer_les_messages_c_est_un_vrai_echec():
    cog, guild = _cog(), _guild(moderer=False, gerer_messages=False)
    assert asyncio.run(cog._muter(guild, _vrai_membre(guild), 60, "x")) == "mute_failed"


def test_les_messages_d_un_membre_mute_par_sentrix_sont_supprimes():
    cog, guild = _cog(), _guild(moderer=False)
    membre = _vrai_membre(guild)
    asyncio.run(cog._muter(guild, membre, 600, "spam"))
    message = SimpleNamespace(id=99, guild=guild, author=SimpleNamespace(id=7, bot=False), delete=AsyncMock(),
                              webhook_id=None)
    asyncio.run(cog.on_message(message))
    message.delete.assert_awaited_once()


def test_le_mute_sentrix_expire():
    cog = _cog()
    cog._mutes_sentrix = {(5, 7): 0.0}
    assert not cog._est_mute_sentrix(5, 7)
