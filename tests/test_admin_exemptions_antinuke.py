"""Qui l'anti-nuke surveille.

05/11/2026 : un administrateur reste exempté PAR DÉFAUT. Le propriétaire peut
l'inclure avec « Sanctionner aussi les admins » (/setup → Sécurité, même
interrupteur que +automod-strict). Tant que c'est coupé, une rafale destructrice
d'un admin est signalée au propriétaire en MP.

Les FILTRES de messages, eux, continuent de reconnaître l'administrateur, y
compris quand l'auteur est transmis comme simple User.
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


def test_un_administrateur_est_exempte_par_defaut():
    admin = _membre(50, administrateur=True)
    cog, guild = _contexte(admin)
    assert _exempt(cog, guild, admin) is True


def test_un_administrateur_transmis_comme_simple_user_est_reconnu():
    admin = _membre(51, administrateur=True)
    cog, guild = _contexte(admin)
    assert _exempt(cog, guild, SimpleNamespace(id=51)) is True


def test_sanctionner_aussi_les_admins_les_surveille():
    admin = _membre(56, administrateur=True)
    cog, guild = _contexte(admin)
    cog.admins_soumis = AsyncMock(return_value=True)
    assert _exempt(cog, guild, admin) is False


def test_une_rafale_d_un_admin_exempte_previent_le_proprietaire():
    admin = _membre(57, administrateur=True)
    cog, guild = _contexte(admin)
    cog.admins_soumis = AsyncMock(return_value=False)
    proprietaire = Mock(spec=discord.Member)
    proprietaire.send = AsyncMock()
    guild.owner = proprietaire
    guild.name = "Mon serveur"

    async def scenario():
        for _ in range(3):
            await cog._noter_action_destructrice_admin(guild, admin)
        # Une seule alerte, même si la rafale continue.
        for _ in range(3):
            await cog._noter_action_destructrice_admin(guild, admin)

    asyncio.run(scenario())
    proprietaire.send.assert_awaited_once()


def test_un_moderateur_sans_administrateur_reste_surveille():
    moderateur = _membre(52, gerer=True)
    cog, guild = _contexte(moderateur)
    assert _exempt(cog, guild, moderateur) is False


def test_un_bot_administrateur_n_est_pas_sanctionne_par_defaut():
    robot = _membre(53, administrateur=True, bot=True)
    cog, guild = _contexte(robot)
    assert _exempt(cog, guild, robot) is True


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


def test_un_admin_avec_un_role_exempte_reste_protege_meme_en_mode_strict():
    # 05/11/2026 : « les bypass doivent marcher aussi pour les admins ».
    admin = _membre(58, administrateur=True)
    admin.roles = [SimpleNamespace(id=700)]
    autre = _membre(59, administrateur=True)
    autre.roles = [SimpleNamespace(id=701)]
    cog, guild = _contexte(admin, autre)
    cog.admins_soumis = AsyncMock(return_value=True)
    cog.get_exempt_roles_cached = AsyncMock(return_value={700})
    assert _exempt(cog, guild, admin) is True
    assert _exempt(cog, guild, autre) is False


def test_everyone_d_un_admin_une_fois_rien_trois_fois_sanction():
    # 06/11/2026 : « un admin @everyone une seule fois, fait rien ; s'il ping 3 fois, sanctionne ».
    admin = _membre(60, administrateur=True)
    cog, guild = _contexte(admin)
    cog._repondre_abus_privilegie = AsyncMock(return_value="derank")
    supprimes = []

    def message(n):
        async def delete():
            supprimes.append(n)
        return SimpleNamespace(id=n, guild=guild, author=admin, delete=delete)

    async def scenario():
        for n in (1, 2):
            await cog._everyone_d_un_admin(message(n))
        assert supprimes == [] and cog._repondre_abus_privilegie.await_count == 0
        await cog._everyone_d_un_admin(message(3))

    asyncio.run(scenario())
    assert supprimes == [3]
    args = cog._repondre_abus_privilegie.await_args.args
    assert args[1] is admin and args[3] == automod_module.ABUS_PRIVILEGIE_SEUIL


def test_everyone_d_un_admin_passe_par_le_garde_dedie():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "cogs" / "automod.py").read_text(encoding="utf-8")
    assert "return await self._everyone_d_un_admin(message)" in source
    assert automod_module.ADMIN_EVERYONE_SEUIL == 3


def test_les_admins_ont_plus_de_marge_que_les_membres(monkeypatch):
    # 06/11/2026 : même avec « Sanctionner aussi les admins », seuls spam, @everyone
    # répété et arnaque les visent ; jamais de sanction pour le spam d'un admin.
    admin = _membre(61, administrateur=True)
    cog, guild = _contexte(admin)
    cog.admins_soumis = AsyncMock(return_value=True)
    monkeypatch.setattr(automod_module, "_is_discord_administrator", lambda m: m is admin)
    monkeypatch.setattr(automod_module, "_as_member", lambda m, g: m)
    cog.get_security_filter_policy_cached = AsyncMock(
        return_value={"strict_channel_ids": set(), "role_ids": set(), "member_ids": set()}
    )
    cog.get_immunity_override_cached = AsyncMock(return_value=None)
    cog.get_exempt_roles_cached = AsyncMock(return_value=set())
    cog.get_ignored_channels_cached = AsyncMock(return_value=set())
    message = SimpleNamespace(author=admin, guild=guild, channel=SimpleNamespace(id=3, parent_id=None))

    for filtre in ("anticaps", "antiemoji", "antilink", "antiinvite", "antiinsult"):
        assert asyncio.run(cog.security_filter_applies_to(message, filtre)) is False, filtre

    action = asyncio.run(cog._spam_progressive_action(guild, admin, "spam"))
    assert action == ("warning_ping", 0, None, "⚠️ doucement sur le spam.")
