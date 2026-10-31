"""Les administrateurs ne sont plus traités comme des pirates.

L'anti-nuke n'exemptait que le propriétaire du serveur, SentriX et la liste
blanche manuelle : un administrateur qui supprimait trois salons était banni.
Et un auteur de message transmis sans ses permissions (User au lieu de Member)
faisait passer un administrateur pour un membre ordinaire dans les filtres.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs import automod as automod_module  # noqa: E402
from cogs.automod import AutoMod  # noqa: E402

GUILD_OWNER = 1
SENTRIX = 2


def _membre(user_id: int, *, administrateur=False, gerer=False, bot=False, guild=None) -> Mock:
    membre = Mock(spec=discord.Member)
    membre.id = user_id
    membre.bot = bot
    membre.guild = guild
    membre.guild_permissions = SimpleNamespace(
        administrator=administrateur, manage_guild=gerer, manage_channels=gerer,
    )
    return membre


def _contexte(*membres, whitelist=(), fetched=()):
    guild = Mock(spec=discord.Guild)
    guild.id = 10
    guild.owner_id = GUILD_OWNER
    par_id = {m.id: m for m in membres}
    guild.get_member = lambda user_id: par_id.get(user_id)
    fetched_by_id = {m.id: m for m in fetched}
    guild.fetch_member = AsyncMock(side_effect=lambda user_id: fetched_by_id[user_id])
    for m in membres:
        m.guild = guild

    async def fetchone(_sql, params):
        return {"1": 1} if params[1] in whitelist else None

    bot = SimpleNamespace(user=SimpleNamespace(id=SENTRIX), db=SimpleNamespace(fetchone=AsyncMock(side_effect=fetchone)))
    return AutoMod(bot), guild


def _exempt(cog, guild, acteur) -> bool:
    return asyncio.run(cog.is_antinuke_exempt(guild, acteur))


def test_un_administrateur_n_est_pas_sanctionne_par_l_anti_nuke():
    admin = _membre(50, administrateur=True)
    cog, guild = _contexte(admin)
    assert _exempt(cog, guild, admin) is True


def test_un_administrateur_transmis_comme_simple_user_est_reconnu():
    admin = _membre(51, administrateur=True)
    cog, guild = _contexte(admin)
    assert _exempt(cog, guild, SimpleNamespace(id=51)) is True


def test_un_administrateur_absent_du_cache_est_recherche_avant_toute_sanction():
    admin = _membre(56, administrateur=True)
    cog, guild = _contexte(fetched=(admin,))
    assert _exempt(cog, guild, SimpleNamespace(id=56)) is True
    guild.fetch_member.assert_awaited_once_with(56)


def test_un_moderateur_sans_administrateur_reste_surveille():
    moderateur = _membre(52, gerer=True)
    cog, guild = _contexte(moderateur)
    assert _exempt(cog, guild, moderateur) is False


def test_un_bot_administrateur_reste_surveille():
    # Un bot piraté est le scénario de nuke le plus courant.
    robot = _membre(53, administrateur=True, bot=True)
    cog, guild = _contexte(robot)
    assert _exempt(cog, guild, robot) is False


def test_proprietaire_sentrix_et_liste_blanche_restent_exemptes():
    proprio = _membre(GUILD_OWNER)
    confiance = _membre(54)
    inconnu = _membre(55)
    cog, guild = _contexte(proprio, confiance, inconnu, whitelist={54})
    assert _exempt(cog, guild, proprio) is True
    assert _exempt(cog, guild, SimpleNamespace(id=SENTRIX)) is True
    assert _exempt(cog, guild, confiance) is True
    assert _exempt(cog, guild, inconnu) is False


def test_les_filtres_de_messages_reconnaissent_l_admin_transmis_comme_user():
    admin = _membre(60, gerer=True)
    cog, guild = _contexte(admin)
    message = SimpleNamespace(author=SimpleNamespace(id=60, bot=False), guild=guild)
    assert asyncio.run(cog.security_filter_applies_to(message, "antiscam")) is False
    assert automod_module._is_discord_administrator(admin) is True
