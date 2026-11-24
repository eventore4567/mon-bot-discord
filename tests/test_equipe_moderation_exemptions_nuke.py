"""Équipe modération : admin épargné du mode strict et échecs de l'anti-nuke.

1. Un admin désigné « épargné » en mode strict qui enchaîne des commandes /
   passait l'anti-spam des réponses de bot (_handle_command_spam →
   security_filter_applies_to → _delete_and_warn → _incident_admin) et
   perdait ses rôles au 3e incident : seule l'entrée par message vérifiait
   l'épargne.
2. Anti-nuke : un ban par identifiant refusé était annoncé « Serveur
   protégé » au propriétaire, et une erreur Discord autre que 403 sur le
   ban faisait perdre journal et MP.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
import pytest  # noqa: E402

from cogs import automod as automod_mod  # noqa: E402
from cogs.automod import AutoMod  # noqa: E402

ADMIN = 555


@pytest.fixture
def admin_detecte(monkeypatch):
    monkeypatch.setattr(automod_mod, "_is_discord_administrator", lambda m: getattr(m, "id", 0) == ADMIN)
    monkeypatch.setattr(automod_mod, "_as_member", lambda u, g: u)


def _message_admin():
    guild = SimpleNamespace(id=1, owner_id=999)
    auteur = SimpleNamespace(id=ADMIN, guild=guild, roles=[], bot=False)
    return SimpleNamespace(id=77, guild=guild, author=auteur,
                           channel=SimpleNamespace(id=10, parent_id=None))


def _cog_strict_epargne():
    cog = AutoMod.__new__(AutoMod)
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=2), db=SimpleNamespace())
    cog.admins_soumis = AsyncMock(return_value=True)
    cog.get_immunity_override_cached = AsyncMock(return_value=None)
    cog.get_exempt_roles_cached = AsyncMock(return_value=set())
    cog.epargnes_du_mode_strict = AsyncMock(return_value={ADMIN})
    cog.get_security_filter_policy_cached = AsyncMock(
        return_value={"role_ids": set(), "member_ids": set(), "strict_channel_ids": set()})
    cog.get_ignored_channels_cached = AsyncMock(return_value=set())
    cog._incident_admin = AsyncMock()
    return cog


def test_admin_epargne_hors_anti_spam_des_commandes(admin_detecte):
    cog = _cog_strict_epargne()
    assert asyncio.run(cog.security_filter_applies_to(_message_admin(), "antispam")) is False


def test_admin_epargne_jamais_en_incident_admin(admin_detecte):
    cog = _cog_strict_epargne()
    asyncio.run(cog._delete_and_warn(_message_admin(), "Spam de messages détecté.", "antispam"))
    cog._incident_admin.assert_not_awaited()


def test_admin_non_epargne_reste_soumis_en_strict(admin_detecte):
    cog = _cog_strict_epargne()
    cog.epargnes_du_mode_strict = AsyncMock(return_value=set())
    assert asyncio.run(cog.security_filter_applies_to(_message_admin(), "antispam")) is True


def _cog_nuke():
    cog = AutoMod.__new__(AutoMod)
    cog._journal_securite = AsyncMock()
    return cog


def _http(status):
    return discord.HTTPException(SimpleNamespace(status=status, reason="x"), "refus")


def test_ban_par_id_refuse_est_un_echec(monkeypatch):
    envoye = AsyncMock()
    monkeypatch.setattr(automod_mod, "_mp_vue", envoye)
    guild = SimpleNamespace(
        id=1, name="S", owner=SimpleNamespace(id=999), owner_id=999,
        get_member=lambda _id: None,
        ban=AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason="x"), "non")),
    )
    cog = _cog_nuke()
    asyncio.run(cog._sanctionner_nuker(guild, 4242, "nuke"))
    assert cog._journal_securite.await_args.kwargs["echec"] is True
    vue = envoye.await_args.args[1]
    assert "Serveur protégé" not in repr(vue.to_components())


def test_erreur_discord_sur_le_ban_tente_le_kick_et_journalise(monkeypatch):
    monkeypatch.setattr(automod_mod, "_mp_vue", AsyncMock())
    membre = SimpleNamespace(id=4242, roles=[], kick=AsyncMock(), remove_roles=AsyncMock())
    guild = SimpleNamespace(
        id=1, name="S", owner=SimpleNamespace(id=999), owner_id=999, default_role=object(),
        get_member=lambda _id: membre, ban=AsyncMock(side_effect=_http(500)),
    )
    cog = _cog_nuke()
    asyncio.run(cog._sanctionner_nuker(guild, 4242, "nuke"))
    membre.kick.assert_awaited_once()
    assert cog._journal_securite.await_args.kwargs["echec"] is False
